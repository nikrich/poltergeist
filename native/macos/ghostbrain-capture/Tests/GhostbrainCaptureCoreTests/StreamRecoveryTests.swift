import XCTest
@testable import GhostbrainCaptureCore

final class StreamRecoveryTests: XCTestCase {
    func testBacksOffThenHoldsAtLastDelay() {
        var r = StreamRecovery(delays: [0.5, 1, 2], maxDowntime: 60)
        XCTAssertEqual(r.nextDelay(now: 0), 0.5)
        XCTAssertEqual(r.nextDelay(now: 1), 1)
        XCTAssertEqual(r.nextDelay(now: 2), 2)
        XCTAssertEqual(r.nextDelay(now: 5), 2)
    }

    func testGivesUpAfterMaxDowntime() {
        var r = StreamRecovery(delays: [1], maxDowntime: 10)
        XCTAssertNotNil(r.nextDelay(now: 100))
        XCTAssertNotNil(r.nextDelay(now: 109.9))
        XCTAssertNil(r.nextDelay(now: 110))
    }

    func testRecoveryResetsScheduleAndDowntime() {
        var r = StreamRecovery(delays: [0.5, 1], maxDowntime: 10)
        _ = r.nextDelay(now: 0)
        _ = r.nextDelay(now: 9)
        r.recovered()
        XCTAssertEqual(r.restarts, 1)
        // A later outage gets the full window and the short first delay again.
        XCTAssertEqual(r.nextDelay(now: 500), 0.5)
        XCTAssertNotNil(r.nextDelay(now: 509))
    }

    func testRepeatedOutagesAreEachRecoverable() {
        var r = StreamRecovery(delays: [1], maxDowntime: 5)
        for i in 0..<20 {
            let t = Double(i) * 100
            XCTAssertNotNil(r.nextDelay(now: t))
            r.recovered()
        }
        XCTAssertEqual(r.restarts, 20)
    }
}
