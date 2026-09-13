import XCTest
@testable import GhostbrainCaptureCore

final class ProtocolAndCheckTests: XCTestCase {
    func testProtocolLineFormatting() {
        XCTAssertEqual(ProtocolLine.format("READY", [("wav", "/tmp/a.wav"), ("fps", "1")]), "READY wav=/tmp/a.wav fps=1")
        XCTAssertEqual(ProtocolLine.format("TARGET", [("kind", "none"), ("awaiting_choice", "true")]), "TARGET kind=none awaiting_choice=true")
        XCTAssertEqual(ProtocolLine.format("TARGET", [("title", "Weekly sync | Meeting")]), "TARGET title=\"Weekly sync | Meeting\"")
        XCTAssertEqual(ProtocolLine.format("X", [("t", "a\"b")]), "X t=\"a\\\"b\"")
        XCTAssertEqual(ProtocolLine.format("X", [("t", "")]), "X t=\"\"")
        XCTAssertEqual(ProtocolLine.format("X", [("t", "k=v")]), "X t=\"k=v\"")
        XCTAssertEqual(ProtocolLine.format("X", [("t", "line1\nline2")]), "X t=\"line1\\nline2\"")
        XCTAssertEqual(ProtocolLine.format("DONE"), "DONE")
    }

    func testLoggerFormatAndLevels() {
        final class Box: @unchecked Sendable { var lines: [String] = [] }
        let box = Box()
        let log = Logger(verbose: false, sink: { box.lines.append($0) })
        log.debug("hidden")
        log.info("hello")
        log.warn("careful")
        log.error("boom")
        XCTAssertEqual(box.lines, ["[ghostbrain-capture] INFO hello", "[ghostbrain-capture] WARN careful", "[ghostbrain-capture] ERROR boom"])
        let verbose = Logger(verbose: true, sink: { box.lines.append($0) })
        verbose.debug("shown")
        XCTAssertEqual(box.lines.last, "[ghostbrain-capture] DEBUG shown")
    }

    func testCheckReportOK() throws {
        let r = CheckReport.build(os: OSVersion(15, 1, 0), screenRecordingGranted: true, microphone: .granted, audioOnly: false)
        XCTAssertTrue(r.ok)
        XCTAssertEqual(r.code, 0)
        XCTAssertTrue(r.issues.isEmpty)
        let obj = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(r.jsonString().utf8)) as? [String: Any])
        XCTAssertEqual(obj["ok"] as? Bool, true)
        XCTAssertEqual(obj["macos"] as? String, "15.1.0")
        XCTAssertEqual(obj["macos_supported"] as? Bool, true)
        XCTAssertEqual(obj["screen_recording"] as? String, "granted")
        XCTAssertEqual(obj["microphone"] as? String, "granted")
        XCTAssertEqual(obj["version"] as? String, ghostbrainCaptureVersion)
        XCTAssertEqual((obj["issues"] as? [String])?.count, 0)
    }

    func testCheckReportCodesInPriorityOrder() {
        XCTAssertEqual(CheckReport.build(os: OSVersion(14, 7, 1), screenRecordingGranted: false, microphone: .denied, audioOnly: false).code, 3)
        XCTAssertEqual(CheckReport.build(os: OSVersion(15, 0, 0), screenRecordingGranted: false, microphone: .denied, audioOnly: false).code, 4)
        XCTAssertEqual(CheckReport.build(os: OSVersion(15, 0, 0), screenRecordingGranted: true, microphone: .denied, audioOnly: false).code, 5)
        XCTAssertEqual(CheckReport.build(os: OSVersion(15, 0, 0), screenRecordingGranted: true, microphone: .notDetermined, audioOnly: false).code, 5)
        XCTAssertEqual(CheckReport.build(os: OSVersion(26, 0, 0), screenRecordingGranted: true, microphone: .restricted, audioOnly: false).code, 5)
        // Screen recording stays fatal for audio-only with the SCStream backend.
        let r = CheckReport.build(os: OSVersion(15, 0, 0), screenRecordingGranted: false, microphone: .granted, audioOnly: true)
        XCTAssertEqual(r.code, 4)
        XCTAssertTrue(r.audioOnly)
        XCTAssertEqual(r.issues.count, 1)
        XCTAssertTrue(r.issues[0].contains("system audio"))
    }
}
