@preconcurrency import AVFoundation
import Foundation

/// Per-lane converter: any PCM layout SCStream hands us → Float32 mono 16 kHz.
///
/// Downmix is an explicit per-frame mean of the channels (mirrors
/// `to_mono_16k` in wasapi_io.py); sample-rate conversion goes through
/// `AVAudioConverter` so we get a proper anti-aliasing filter instead of the
/// Python path's linear interpolation.
public final class PCMConverter: @unchecked Sendable {
    public static let outputRate: Double = 16000

    public let inputFormat: AVAudioFormat
    private let monoInput: AVAudioFormat
    private let monoOutput: AVAudioFormat
    private let converter: AVAudioConverter?

    public init?(inputFormat: AVAudioFormat) {
        self.inputFormat = inputFormat
        guard let mi = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: inputFormat.sampleRate, channels: 1, interleaved: false),
              let mo = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: Self.outputRate, channels: 1, interleaved: false)
        else { return nil }
        monoInput = mi
        monoOutput = mo
        if inputFormat.sampleRate == Self.outputRate {
            converter = nil
        } else {
            guard let c = AVAudioConverter(from: mi, to: mo) else { return nil }
            c.sampleRateConverterQuality = AVAudioQuality.high.rawValue
            converter = c
        }
    }

    /// Convenience for tests / callers that already have interleaved floats.
    public convenience init?(sampleRate: Double, channels: Int) {
        guard let f = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: sampleRate, channels: AVAudioChannelCount(channels), interleaved: true) else { return nil }
        self.init(inputFormat: f)
    }

    public func convert(_ buffer: AVAudioPCMBuffer) -> [Float] {
        resample(Self.downmix(buffer))
    }

    /// Interleaved frames at the input rate → mono → 16 kHz.
    public func convert(interleaved: [Float], channels: Int) -> [Float] {
        resample(Self.downmix(interleaved: interleaved, channels: channels))
    }

    /// Mean of all channels per frame. Handles Float32 / Int16 / Int32,
    /// interleaved or planar. Torn frames are truncated like the Python code.
    public static func downmix(_ buffer: AVAudioPCMBuffer) -> [Float] {
        let frames = Int(buffer.frameLength)
        let channels = Int(buffer.format.channelCount)
        guard frames > 0, channels > 0 else { return [] }
        var out = [Float](repeating: 0, count: frames)
        let stride = buffer.stride
        let interleaved = buffer.format.isInterleaved
        let scale = 1.0 / Float(channels)

        func accumulate<T>(_ planes: UnsafePointer<UnsafeMutablePointer<T>>, _ toFloat: (T) -> Float) {
            if interleaved {
                let p = planes[0]
                for f in 0..<frames {
                    var acc: Float = 0
                    for c in 0..<channels { acc += toFloat(p[f * stride + c]) }
                    out[f] = acc * scale
                }
            } else {
                for c in 0..<channels {
                    let p = planes[c]
                    for f in 0..<frames { out[f] += toFloat(p[f * stride]) }
                }
                if channels > 1 { for f in 0..<frames { out[f] *= scale } }
            }
        }

        if let fl = buffer.floatChannelData {
            accumulate(fl) { $0 }
        } else if let i16 = buffer.int16ChannelData {
            accumulate(i16) { Float($0) / 32768.0 }
        } else if let i32 = buffer.int32ChannelData {
            accumulate(i32) { Float($0) / 2147483648.0 }
        } else {
            return []
        }
        return out
    }

    public static func downmix(interleaved: [Float], channels: Int) -> [Float] {
        guard channels > 0 else { return [] }
        if channels == 1 { return interleaved }
        let frames = interleaved.count / channels
        var out = [Float](repeating: 0, count: frames)
        let scale = 1.0 / Float(channels)
        for f in 0..<frames {
            var acc: Float = 0
            let base = f * channels
            for c in 0..<channels { acc += interleaved[base + c] }
            out[f] = acc * scale
        }
        return out
    }

    private func resample(_ mono: [Float]) -> [Float] {
        guard !mono.isEmpty else { return [] }
        guard let converter else { return mono }
        guard let inBuf = AVAudioPCMBuffer(pcmFormat: monoInput, frameCapacity: AVAudioFrameCount(mono.count)) else { return [] }
        inBuf.frameLength = AVAudioFrameCount(mono.count)
        mono.withUnsafeBufferPointer { src in
            inBuf.floatChannelData![0].update(from: src.baseAddress!, count: mono.count)
        }
        let ratio = Self.outputRate / monoInput.sampleRate
        let capacity = AVAudioFrameCount((Double(mono.count) * ratio).rounded(.up)) + 64
        guard let outBuf = AVAudioPCMBuffer(pcmFormat: monoOutput, frameCapacity: capacity) else { return [] }

        final class Once: @unchecked Sendable { var consumed = false }
        let once = Once()
        var error: NSError?
        let status = converter.convert(to: outBuf, error: &error) { _, outStatus in
            if once.consumed {
                outStatus.pointee = .noDataNow
                return nil
            }
            once.consumed = true
            outStatus.pointee = .haveData
            return inBuf
        }
        guard status != .error, error == nil else { return [] }
        let n = Int(outBuf.frameLength)
        guard n > 0, let p = outBuf.floatChannelData?[0] else { return [] }
        return Array(UnsafeBufferPointer(start: p, count: n))
    }
}
