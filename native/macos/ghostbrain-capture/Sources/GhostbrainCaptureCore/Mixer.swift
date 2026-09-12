import Foundation

/// Two FIFO lanes (system audio, microphone) of Float32 mono 16 kHz samples.
///
/// Every tick the caller drains `target = elapsed_wall * rate - written`
/// samples from each lane, shortfalls are zero-padded, lanes summed, clipped
/// and converted to Int16 — i.e. ffmpeg `amix duration=longest` semantics
/// driven by the wall clock so the WAV length tracks real time even when a
/// lane goes silent (SCStream stops delivering system audio when nothing is
/// playing). Drift is bounded by trimming any lane whose backlog exceeds
/// `maxBacklogMs` after a drain (oldest samples dropped, WARN logged).
public final class Mixer: @unchecked Sendable {
    public enum Lane: Int, CaseIterable, Sendable {
        case system = 0
        case mic = 1
        public var name: String { self == .system ? "system" : "mic" }
    }

    public let sampleRate: Int
    public let maxBacklogSamples: Int
    public private(set) var written: Int = 0
    public private(set) var trimmedSamples: [Lane: Int] = [:]

    private var lanes: [[Float]]
    private var heads: [Int]
    private let lock = NSLock()
    private let warn: @Sendable (String) -> Void

    public init(sampleRate: Int = 16000, maxBacklogMs: Int = 500, warn: @escaping @Sendable (String) -> Void = { _ in }) {
        self.sampleRate = sampleRate
        self.maxBacklogSamples = sampleRate * maxBacklogMs / 1000
        self.warn = warn
        lanes = Lane.allCases.map { _ in [] }
        heads = Lane.allCases.map { _ in 0 }
    }

    public func push(_ samples: [Float], lane: Lane) {
        guard !samples.isEmpty else { return }
        lock.lock()
        lanes[lane.rawValue].append(contentsOf: samples)
        lock.unlock()
    }

    public func backlog(_ lane: Lane) -> Int {
        lock.lock()
        defer { lock.unlock() }
        return lanes[lane.rawValue].count - heads[lane.rawValue]
    }

    /// Drain for a wall-clock position. Returns exactly the number of samples
    /// needed to bring `written` up to `elapsedSeconds * sampleRate`.
    public func drain(elapsedSeconds: Double) -> [Int16] {
        let goal = Int((elapsedSeconds * Double(sampleRate)).rounded(.down))
        lock.lock()
        let target = max(0, goal - written)
        lock.unlock()
        return drain(count: target)
    }

    /// Drain exactly `count` samples (zero-padding lanes that fall short).
    public func drain(count: Int) -> [Int16] {
        guard count > 0 else { return [] }
        lock.lock()
        defer { lock.unlock() }
        var mix = [Float](repeating: 0, count: count)
        for lane in Lane.allCases {
            let li = lane.rawValue
            let available = lanes[li].count - heads[li]
            let n = min(available, count)
            if n > 0 {
                let base = heads[li]
                lanes[li].withUnsafeBufferPointer { buf in
                    for i in 0..<n { mix[i] += buf[base + i] }
                }
                heads[li] += n
            }
            compactLocked(li)
            let remaining = lanes[li].count - heads[li]
            if remaining > maxBacklogSamples {
                let drop = remaining - maxBacklogSamples
                heads[li] += drop
                trimmedSamples[lane, default: 0] += drop
                compactLocked(li, force: true)
                warn("mixer: \(lane.name) lane backlog \(remaining * 1000 / sampleRate) ms > \(maxBacklogSamples * 1000 / sampleRate) ms, dropped \(drop * 1000 / sampleRate) ms")
            }
        }
        written += count
        return Self.toInt16(mix)
    }

    /// Final drain: flush whatever is left, longest lane wins (`duration=longest`).
    public func drainRemaining() -> [Int16] {
        lock.lock()
        let longest = Lane.allCases.map { lanes[$0.rawValue].count - heads[$0.rawValue] }.max() ?? 0
        lock.unlock()
        return drain(count: longest)
    }

    public static func toInt16(_ samples: [Float]) -> [Int16] {
        samples.map { s in
            let clipped = min(max(s, -1.0), 1.0)
            return Int16((clipped * 32767.0).rounded())
        }
    }

    private func compactLocked(_ li: Int, force: Bool = false) {
        let head = heads[li]
        guard head > 0, force || head >= sampleRate else { return } // compact ~1 s at a time
        lanes[li].removeFirst(head)
        heads[li] = 0
    }
}
