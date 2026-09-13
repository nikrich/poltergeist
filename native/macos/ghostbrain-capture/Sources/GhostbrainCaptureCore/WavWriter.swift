import Foundation

public enum WavWriterError: Error, CustomStringConvertible {
    case io(String)
    public var description: String {
        switch self { case .io(let m): return m }
    }
}

/// Port of `IncrementalWavWriter` (ghostbrain/recorder/audio/wasapi_io.py):
/// canonical 44-byte header, PCM16 mono 16 kHz, data written unbuffered on
/// every append, header sizes rewritten roughly every second and on close so
/// a SIGKILL leaves a file whose header is stale by at most ~1 s.
public final class WavWriter: @unchecked Sendable {
    public static let headerLength = 44
    public static let sampleRate: UInt32 = 16000
    public static let channels: UInt16 = 1
    public static let bitsPerSample: UInt16 = 16

    public let path: URL
    public private(set) var dataBytes: UInt64 = 0
    public private(set) var isClosed = false

    private let fd: Int32
    private let headerRewriteInterval: TimeInterval
    private var lastHeaderWrite: TimeInterval
    private let lock = NSLock()

    public init(path: URL, headerRewriteInterval: TimeInterval = 1.0) throws {
        self.path = path
        self.headerRewriteInterval = headerRewriteInterval
        let dir = path.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let fd = open(path.path, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0o644)
        guard fd >= 0 else {
            throw WavWriterError.io("open(\(path.path)) failed: \(String(cString: strerror(errno)))")
        }
        self.fd = fd
        self.lastHeaderWrite = ProcessInfo.processInfo.systemUptime
        try writeHeaderLocked()
    }

    /// Byte-identical to the Python `struct.pack` layout:
    /// RIFF <I 36+data> WAVE fmt  <I 16><H 1><H 1><I 16000><I 32000><H 2><H 16> data <I data>
    public static func header(dataBytes: UInt32) -> [UInt8] {
        var out: [UInt8] = []
        out.reserveCapacity(headerLength)
        func u32(_ v: UInt32) { withUnsafeBytes(of: v.littleEndian) { out.append(contentsOf: $0) } }
        func u16(_ v: UInt16) { withUnsafeBytes(of: v.littleEndian) { out.append(contentsOf: $0) } }
        out.append(contentsOf: Array("RIFF".utf8))
        u32(36 &+ dataBytes)
        out.append(contentsOf: Array("WAVE".utf8))
        out.append(contentsOf: Array("fmt ".utf8))
        u32(16)
        u16(1)                                       // PCM
        u16(channels)
        u32(sampleRate)
        u32(sampleRate * UInt32(channels) * UInt32(bitsPerSample / 8)) // byte rate 32000
        u16(channels * (bitsPerSample / 8))          // block align 2
        u16(bitsPerSample)
        out.append(contentsOf: Array("data".utf8))
        u32(dataBytes)
        return out
    }

    public func append(_ samples: [Int16]) throws {
        lock.lock()
        defer { lock.unlock() }
        guard !isClosed else { throw WavWriterError.io("append after close") }
        guard !samples.isEmpty else { return }
        var bytes = [UInt8]()
        bytes.reserveCapacity(samples.count * 2)
        for s in samples {
            let le = UInt16(bitPattern: s).littleEndian
            bytes.append(UInt8(le & 0xff))
            bytes.append(UInt8(le >> 8))
        }
        try pwriteAll(bytes, offset: off_t(Self.headerLength) + off_t(dataBytes))
        dataBytes += UInt64(bytes.count)
        let now = ProcessInfo.processInfo.systemUptime
        if now - lastHeaderWrite >= headerRewriteInterval {
            try writeHeaderLocked()
        }
    }

    /// Rewrite the size fields now (used by tests and before risky operations).
    public func flushHeader() throws {
        lock.lock()
        defer { lock.unlock() }
        guard !isClosed else { return }
        try writeHeaderLocked()
    }

    public func close() throws {
        lock.lock()
        defer { lock.unlock() }
        guard !isClosed else { return }
        isClosed = true
        defer { _ = Foundation.close(fd) }
        try writeHeaderLocked()
    }

    /// Total bytes on disk (header + data).
    public var fileBytes: UInt64 { UInt64(Self.headerLength) + dataBytes }

    private func writeHeaderLocked() throws {
        let clamped = UInt32(min(dataBytes, UInt64(UInt32.max) - 36))
        try pwriteAll(Self.header(dataBytes: clamped), offset: 0)
        lastHeaderWrite = ProcessInfo.processInfo.systemUptime
    }

    private func pwriteAll(_ bytes: [UInt8], offset: off_t) throws {
        var written = 0
        while written < bytes.count {
            let n = bytes.withUnsafeBytes { raw -> Int in
                pwrite(fd, raw.baseAddress!.advanced(by: written), bytes.count - written, offset + off_t(written))
            }
            if n < 0 {
                if errno == EINTR { continue }
                throw WavWriterError.io("write(\(path.path)) failed: \(String(cString: strerror(errno)))")
            }
            written += n
        }
    }
}
