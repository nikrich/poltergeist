import AVFoundation
import XCTest
@testable import GhostbrainCaptureCore

final class PCMConvertTests: XCTestCase {
    private func sine(freq: Double, rate: Double, seconds: Double, phase: Double = 0) -> [Float] {
        let n = Int(rate * seconds)
        return (0..<n).map { Float(sin(2 * .pi * freq * Double($0) / rate + phase)) }
    }

    private func zeroCrossings(_ x: [Float]) -> Int {
        var c = 0
        for i in 1..<x.count where (x[i - 1] < 0) != (x[i] < 0) { c += 1 }
        return c
    }

    func testDownmixIsMeanOfChannels() {
        let stereo: [Float] = [1, 0, 0.5, -0.5, -1, -1]
        XCTAssertEqual(PCMConverter.downmix(interleaved: stereo, channels: 2), [0.5, 0, -1])
        XCTAssertEqual(PCMConverter.downmix(interleaved: [0.3, 0.6], channels: 1), [0.3, 0.6])
        // torn frame is truncated
        XCTAssertEqual(PCMConverter.downmix(interleaved: [1, 1, 1], channels: 2), [1])
    }

    func test48kStereoSineTo16kMono() throws {
        let conv = try XCTUnwrap(PCMConverter(sampleRate: 48000, channels: 2))
        let mono = sine(freq: 440, rate: 48000, seconds: 1.0)
        var stereo = [Float](); stereo.reserveCapacity(mono.count * 2)
        for s in mono { stereo.append(s); stereo.append(s) }
        let out = conv.convert(interleaved: stereo, channels: 2)
        // ≈ 16000 samples (converter priming may shave a handful)
        XCTAssertGreaterThan(out.count, 15800)
        XCTAssertLessThanOrEqual(out.count, 16064)
        // Still a 440 Hz tone: ~880 zero crossings per second.
        let zc = zeroCrossings(out)
        XCTAssertTrue((840...920).contains(zc), "zero crossings \(zc)")
        let peak = out.map { abs($0) }.max() ?? 0
        XCTAssertGreaterThan(peak, 0.9)
        XCTAssertLessThan(peak, 1.05)
    }

    func testAntiPhaseStereoCancelsToSilence() throws {
        let conv = try XCTUnwrap(PCMConverter(sampleRate: 48000, channels: 2))
        let l = sine(freq: 1000, rate: 48000, seconds: 0.2)
        var stereo = [Float]()
        for s in l { stereo.append(s); stereo.append(-s) }
        let out = conv.convert(interleaved: stereo, channels: 2)
        XCTAssertFalse(out.isEmpty)
        XCTAssertLessThan(out.map { abs($0) }.max() ?? 1, 1e-4)
    }

    func testStreamingChunksKeepTotalLength() throws {
        let conv = try XCTUnwrap(PCMConverter(sampleRate: 48000, channels: 1))
        let mono = sine(freq: 300, rate: 48000, seconds: 1.0)
        var total = 0
        var i = 0
        while i < mono.count {
            let chunk = Array(mono[i..<min(i + 480, mono.count)]) // 10 ms like SCStream
            total += conv.convert(interleaved: chunk, channels: 1).count
            i += 480
        }
        XCTAssertGreaterThan(total, 15800)
        XCTAssertLessThanOrEqual(total, 16100)
    }

    func testSameRatePassThrough() throws {
        let conv = try XCTUnwrap(PCMConverter(sampleRate: 16000, channels: 1))
        XCTAssertEqual(conv.convert(interleaved: [0.1, 0.2], channels: 1), [0.1, 0.2])
    }

    func testAVAudioPCMBufferPlanarFloatDownmix() throws {
        let fmt = try XCTUnwrap(AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 2, interleaved: false))
        let buf = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: 4))
        buf.frameLength = 4
        buf.floatChannelData![0].update(from: [1, 1, 0, -1], count: 4)
        buf.floatChannelData![1].update(from: [0, 1, 0, -1], count: 4)
        let conv = try XCTUnwrap(PCMConverter(inputFormat: fmt))
        XCTAssertEqual(conv.convert(buf), [0.5, 1, 0, -1])
    }

    func testAVAudioPCMBufferInt16Interleaved() throws {
        let fmt = try XCTUnwrap(AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 2, interleaved: true))
        let buf = try XCTUnwrap(AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: 2))
        buf.frameLength = 2
        buf.int16ChannelData![0].update(from: [16384, 16384, -32768, 0], count: 4)
        let out = PCMConverter.downmix(buf)
        XCTAssertEqual(out.count, 2)
        XCTAssertEqual(out[0], 0.5, accuracy: 1e-6)
        XCTAssertEqual(out[1], -0.5, accuracy: 1e-6)
    }
}
