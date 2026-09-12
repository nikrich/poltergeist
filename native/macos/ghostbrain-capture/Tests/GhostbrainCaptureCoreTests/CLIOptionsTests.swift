import XCTest
@testable import GhostbrainCaptureCore

final class CLIOptionsTests: XCTestCase {
    func testVersionAndHelp() throws {
        XCTAssertEqual(try CLIOptions.parse(["--version"]), .version)
        XCTAssertEqual(try CLIOptions.parse(["--help"]), .help)
        XCTAssertEqual(try CLIOptions.parse(["-h"]), .help)
    }

    func testCheckFlags() throws {
        XCTAssertEqual(try CLIOptions.parse(["check"]), .check(json: false, audioOnly: false))
        XCTAssertEqual(try CLIOptions.parse(["check", "--json", "--audio-only"]), .check(json: true, audioOnly: true))
        XCTAssertThrowsError(try CLIOptions.parse(["check", "--wav", "x"]))
        XCTAssertEqual(try CLIOptions.parse(["request-permissions"]), .requestPermissions(json: false))
        XCTAssertEqual(try CLIOptions.parse(["list-devices", "--json"]), .listDevices(json: true))
    }

    func testRunDefaults() throws {
        guard case .run(let o) = try CLIOptions.parse(["run", "--wav", "/tmp/a.wav"]) else { return XCTFail() }
        XCTAssertEqual(o.wav, "/tmp/a.wav")
        XCTAssertNil(o.framesDir)
        XCTAssertNil(o.controlFile)
        XCTAssertFalse(o.wantsVideo)
        XCTAssertEqual(o.fps, 1)
        XCTAssertEqual(o.target, .auto)
        XCTAssertEqual(o.noWindowPolicy, .ask)
        XCTAssertEqual(o.micDevice, .systemDefault)
        XCTAssertEqual(o.ocrLangs, ["en-US"])
        XCTAssertEqual(o.slideThreshold, 0.04)
        XCTAssertEqual(o.maxFrames, 600)
        XCTAssertEqual(o.maxDurationS, 21600)
        XCTAssertFalse(o.verbose)
    }

    func testRunAllOptions() throws {
        let argv = ["run", "--wav", "o.wav", "--frames-dir", "o.frames", "--control-file", "o.control.json", "--fps", "2", "--target", "window",
                    "--no-window-policy", "audio", "--mic-device", "AppleUSBAudioEngine:1", "--ocr-langs", "en-US, de-DE",
                    "--slide-threshold", "0.1", "--max-frames", "50", "--max-duration-s", "600", "--verbose"]
        guard case .run(let o) = try CLIOptions.parse(argv) else { return XCTFail() }
        XCTAssertEqual(o.framesDir, "o.frames")
        XCTAssertEqual(o.controlFile, "o.control.json")
        XCTAssertTrue(o.wantsVideo)
        XCTAssertEqual(o.fps, 2)
        XCTAssertEqual(o.target, .window)
        XCTAssertEqual(o.noWindowPolicy, .audio)
        XCTAssertEqual(o.micDevice, .id("AppleUSBAudioEngine:1"))
        XCTAssertEqual(o.ocrLangs, ["en-US", "de-DE"])
        XCTAssertEqual(o.slideThreshold, 0.1)
        XCTAssertEqual(o.maxFrames, 50)
        XCTAssertEqual(o.maxDurationS, 600)
        XCTAssertTrue(o.verbose)
    }

    func testMicNone() throws {
        guard case .run(let o) = try CLIOptions.parse(["run", "--wav", "a", "--mic-device", "none"]) else { return XCTFail() }
        XCTAssertEqual(o.micDevice, .none)
    }

    func testUsageErrors() {
        XCTAssertThrowsError(try CLIOptions.parse([]))
        XCTAssertThrowsError(try CLIOptions.parse(["bogus"]))
        XCTAssertThrowsError(try CLIOptions.parse(["run"]))
        XCTAssertThrowsError(try CLIOptions.parse(["run", "--wav"]))
        XCTAssertThrowsError(try CLIOptions.parse(["run", "--wav", "a", "--fps", "0"]))
        XCTAssertThrowsError(try CLIOptions.parse(["run", "--wav", "a", "--fps", "x"]))
        XCTAssertThrowsError(try CLIOptions.parse(["run", "--wav", "a", "--target", "screen"]))
        XCTAssertThrowsError(try CLIOptions.parse(["run", "--wav", "a", "--no-window-policy", "maybe"]))
        XCTAssertThrowsError(try CLIOptions.parse(["run", "--wav", "a", "--slide-threshold", "2"]))
        XCTAssertThrowsError(try CLIOptions.parse(["run", "--wav", "a", "--bogus"]))
    }
}
