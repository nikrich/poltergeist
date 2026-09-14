import XCTest
@testable import GhostbrainCaptureCore

final class MixerTests: XCTestCase {
    func testDrainZeroPadsShorterLane_durationLongest() {
        let m = Mixer()
        m.push([Float](repeating: 0.5, count: 1600), lane: .system)
        m.push([Float](repeating: 0.25, count: 800), lane: .mic)
        let out = m.drain(elapsedSeconds: 0.1) // 1600 samples
        XCTAssertEqual(out.count, 1600)
        XCTAssertEqual(out[0], Int16((0.75 * 32767).rounded()))
        XCTAssertEqual(out[799], Int16((0.75 * 32767).rounded()))
        XCTAssertEqual(out[800], Int16((0.5 * 32767).rounded()), "mic lane padded with zeros")
        XCTAssertEqual(m.written, 1600)
        XCTAssertEqual(m.backlog(.system), 0)
    }

    func testBothLanesEmptyStillOutputsSilenceForWallClock() {
        let m = Mixer()
        let out = m.drain(elapsedSeconds: 0.2)
        XCTAssertEqual(out.count, 3200)
        XCTAssertTrue(out.allSatisfy { $0 == 0 })
        // A second drain at the same elapsed time yields nothing more.
        XCTAssertEqual(m.drain(elapsedSeconds: 0.2).count, 0)
        XCTAssertEqual(m.drain(elapsedSeconds: 0.25).count, 800)
    }

    func testClipping() {
        let m = Mixer()
        m.push([0.9, -0.9, 0.1], lane: .system)
        m.push([0.9, -0.9, 0.1], lane: .mic)
        let out = m.drain(count: 3)
        XCTAssertEqual(out, [32767, -32767, Int16((0.2 * 32767).rounded())])
    }

    func testBacklogTrimWarnsAndBounds() {
        final class Box: @unchecked Sendable { var warnings: [String] = [] }
        let box = Box()
        let m = Mixer(maxBacklogMs: 500, warn: { box.warnings.append($0) })
        // 1 s of system audio arrives but the wall clock only advanced 100 ms.
        m.push([Float](repeating: 0.1, count: 16000), lane: .system)
        _ = m.drain(elapsedSeconds: 0.1)
        XCTAssertEqual(m.backlog(.system), 8000, "trimmed to 500 ms")
        XCTAssertEqual(box.warnings.count, 1)
        XCTAssertTrue(box.warnings[0].contains("system lane backlog"))
        XCTAssertEqual(m.trimmedSamples[.system], 16000 - 1600 - 8000)
        // Mic lane untouched.
        XCTAssertEqual(m.backlog(.mic), 0)
    }

    func testNoTrimBelowThreshold() {
        final class Box: @unchecked Sendable { var warnings: [String] = [] }
        let box = Box()
        let m = Mixer(warn: { box.warnings.append($0) })
        m.push([Float](repeating: 0.1, count: 1600 + 7000), lane: .mic)
        _ = m.drain(elapsedSeconds: 0.1)
        XCTAssertEqual(m.backlog(.mic), 7000)
        XCTAssertTrue(box.warnings.isEmpty)
    }

    func testDrainRemainingFlushesLongestLane() {
        let m = Mixer()
        m.push([Float](repeating: 0.5, count: 300), lane: .system)
        m.push([Float](repeating: 0.5, count: 100), lane: .mic)
        let out = m.drainRemaining()
        XCTAssertEqual(out.count, 300)
        XCTAssertEqual(out[0], 32767)
        XCTAssertEqual(out[299], Int16((0.5 * 32767).rounded()))
        XCTAssertEqual(m.drainRemaining().count, 0)
    }

    func testFifoOrderAcrossManyDrains() {
        let m = Mixer()
        let ramp = (0..<4000).map { Float($0) / 4000.0 }
        m.push(ramp, lane: .system)
        var got: [Int16] = []
        for i in 1...4 { got += m.drain(elapsedSeconds: Double(i) * 1000.0 / 16000.0) }
        XCTAssertEqual(got.count, 4000)
        XCTAssertEqual(got, Mixer.toInt16(ramp))
    }
}
