import XCTest
@testable import GhostbrainCaptureCore

final class SlideDetectorTests: XCTestCase {
    private let A = Thumbnail(fill: 0.1)
    private let B = Thumbnail(fill: 0.6)
    private let C = Thumbnail(fill: 0.9)

    func testMeanAbsDiff() {
        XCTAssertEqual(FrameDiff.meanAbsDiff(A, A), 0)
        XCTAssertEqual(FrameDiff.meanAbsDiff(A, B), 0.5, accuracy: 1e-6)
    }

    func testThumbnailFromBGRA() {
        // 8x4 frame: left half white, right half black.
        let w = 8, h = 4
        var px = [UInt8](repeating: 0, count: w * h * 4)
        for y in 0..<h { for x in 0..<(w / 2) { let p = (y * w + x) * 4; px[p] = 255; px[p+1] = 255; px[p+2] = 255; px[p+3] = 255 } }
        let t = px.withUnsafeBytes { Thumbnail.fromBGRA($0.baseAddress!, width: w, height: h, bytesPerRow: w * 4) }
        XCTAssertEqual(t.pixels[0], 1.0, accuracy: 1e-5)
        XCTAssertEqual(t.pixels[Thumbnail.width - 1], 0.0, accuracy: 1e-5)
        XCTAssertEqual(t.pixels[Thumbnail.width * (Thumbnail.height - 1)], 1.0, accuracy: 1e-5)
        let lit = t.pixels.filter { $0 > 0.5 }.count
        XCTAssertEqual(lit, Thumbnail.width * Thumbnail.height / 2)
    }

    func testFirstFrameNeedsSettleThenKept() {
        var d = SlideDetector()
        XCTAssertEqual(d.observe(A, offsetMs: 0), .skip(.settling))
        XCTAssertEqual(d.observe(A, offsetMs: 1000), .keep(diff: 1.0))
        XCTAssertEqual(d.keptCount, 1)
        XCTAssertEqual(d.observe(A, offsetMs: 2000), .skip(.unchanged))
    }

    func testChangeMustSettleAndRespectMinInterval() {
        var d = SlideDetector(minIntervalMs: 3000)
        _ = d.observe(A, offsetMs: 0)
        _ = d.observe(A, offsetMs: 1000) // kept @1000
        XCTAssertEqual(d.observe(B, offsetMs: 2000), .skip(.settling))
        XCTAssertEqual(d.observe(B, offsetMs: 3000), .skip(.debounced), "settled but only 2 s since last kept")
        if case .keep(let diff) = d.observe(B, offsetMs: 4000) {
            XCTAssertEqual(diff, 0.5, accuracy: 1e-6)
        } else {
            XCTFail("expected keep at 4000")
        }
        XCTAssertEqual(d.lastKeptOffsetMs, 4000)
    }

    func testABOscillationNeverSettles() {
        var d = SlideDetector()
        _ = d.observe(A, offsetMs: 0)
        _ = d.observe(A, offsetMs: 1000)
        var t = 2000
        for _ in 0..<20 {
            XCTAssertEqual(d.observe(B, offsetMs: t), .skip(.settling)); t += 1000
            XCTAssertEqual(d.observe(A, offsetMs: t), .skip(.unchanged)); t += 1000
        }
        XCTAssertEqual(d.keptCount, 1)
        // A slow fade: B → C → C settles on C.
        XCTAssertEqual(d.observe(B, offsetMs: t), .skip(.settling)); t += 1000
        XCTAssertEqual(d.observe(C, offsetMs: t), .skip(.settling)); t += 1000
        if case .keep(let diff) = d.observe(C, offsetMs: t) {
            XCTAssertEqual(diff, 0.8, accuracy: 1e-5)
        } else {
            XCTFail("expected C to settle and be kept")
        }
    }

    func testSmallNoiseBelowThresholdIsUnchanged() {
        var d = SlideDetector(changeThreshold: 0.04)
        _ = d.observe(A, offsetMs: 0)
        _ = d.observe(A, offsetMs: 1000)
        let noisy = Thumbnail(fill: 0.1 + 0.03)
        XCTAssertEqual(d.observe(noisy, offsetMs: 2000), .skip(.unchanged))
    }

    func testMaxSlides() {
        var d = SlideDetector(settleFrames: 1, minIntervalMs: 0, maxSlides: 2)
        XCTAssertEqual(d.observe(A, offsetMs: 0), .keep(diff: 1.0))
        XCTAssertEqual(d.observe(B, offsetMs: 1), .keep(diff: 0.5))
        XCTAssertEqual(d.observe(C, offsetMs: 2), .skip(.maxSlides))
    }
}
