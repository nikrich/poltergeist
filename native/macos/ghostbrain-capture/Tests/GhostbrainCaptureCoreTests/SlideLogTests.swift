import XCTest
@testable import GhostbrainCaptureCore

final class SlideLogTests: XCTestCase {
    private var dir: URL!

    override func setUpWithError() throws {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent("gbc-slides-\(UUID().uuidString)")
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: dir)
    }

    func testImageName() {
        XCTAssertEqual(SlideLog.imageName(index: 1, offsetMs: 4200), "slide-0001-00004200.jpg")
        XCTAssertEqual(SlideLog.imageName(index: 600, offsetMs: 21_600_000), "slide-0600-21600000.jpg")
        XCTAssertEqual(SlideLog.imageName(index: 12, offsetMs: -5), "slide-0012-00000000.jpg")
    }

    func testAppendJsonlAndAtomicManifest() throws {
        let started = Date(timeIntervalSince1970: 1_800_000_000) // 2027-01-15T08:00:00Z
        let log = try SlideLog(directory: dir, wavName: "out.wav", startedAt: started, fps: 1,
                               target: SlideTarget(kind: "window", app: "com.microsoft.teams2", title: "Meeting | Teams"))
        let r2 = SlideRecord(index: 2, offsetMs: 9000, image: "slide-0002-00009000.jpg", width: 1600, height: 900,
                             text: "Second", ocr: "accurate", confidence: 0.8, diff: 0.2)
        let r1 = SlideRecord(index: 1, offsetMs: 4200, image: "slide-0001-00004200.jpg", width: 1600, height: 900,
                             text: "Q3 Roadmap\n- item \"quoted\"", ocr: "accurate", confidence: 0.91, diff: 0.31)
        try log.append(r2) // OCR completion order can differ from index order
        try log.append(r1)

        let jsonl = try String(contentsOf: dir.appendingPathComponent("slides.jsonl"), encoding: .utf8)
        let lines = jsonl.split(separator: "\n")
        XCTAssertEqual(lines.count, 2)
        let dec = JSONDecoder()
        XCTAssertEqual(try dec.decode(SlideRecord.self, from: Data(lines[0].utf8)), r2)
        XCTAssertEqual(try dec.decode(SlideRecord.self, from: Data(lines[1].utf8)), r1)
        XCTAssertTrue(lines[1].contains("\"offset_ms\":4200"))

        try log.writeManifest(durationMs: 3_612_000)
        let manifestURL = dir.appendingPathComponent("slides.json")
        let obj = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: manifestURL)) as? [String: Any])
        XCTAssertEqual(obj["version"] as? Int, 1)
        XCTAssertEqual(obj["wav"] as? String, "out.wav")
        XCTAssertEqual(obj["started_at"] as? String, "2027-01-15T08:00:00Z")
        XCTAssertEqual(obj["duration_ms"] as? Int, 3_612_000)
        XCTAssertEqual(obj["fps"] as? Int, 1)
        let target = try XCTUnwrap(obj["target"] as? [String: Any])
        XCTAssertEqual(target["kind"] as? String, "window")
        XCTAssertEqual(target["app"] as? String, "com.microsoft.teams2")
        let slides = try XCTUnwrap(obj["slides"] as? [[String: Any]])
        XCTAssertEqual(slides.map { $0["index"] as? Int }, [1, 2], "manifest sorted by index")
        XCTAssertEqual(slides[0]["image"] as? String, "slide-0001-00004200.jpg")
        XCTAssertEqual(slides[0]["text"] as? String, "Q3 Roadmap\n- item \"quoted\"")
        XCTAssertEqual(slides[0]["ocr"] as? String, "accurate")

        // No temp files left behind; rewrite replaces in place.
        log.target = SlideTarget(kind: "display")
        try log.writeManifest(durationMs: 4_000_000)
        let names = try FileManager.default.contentsOfDirectory(atPath: dir.path).sorted()
        XCTAssertEqual(names, ["slides.json", "slides.jsonl"])
        let obj2 = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: manifestURL)) as? [String: Any])
        XCTAssertEqual((obj2["target"] as? [String: Any])?["kind"] as? String, "display")
        XCTAssertEqual(obj2["duration_ms"] as? Int, 4_000_000)
        log.close()
    }

    func testEmptyManifestWritesEmptySlidesArray() throws {
        let log = try SlideLog(directory: dir, wavName: "a.wav", startedAt: Date(), fps: 2, target: SlideTarget(kind: "none"))
        try log.writeManifest(durationMs: 10)
        let obj = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: dir.appendingPathComponent("slides.json"))) as? [String: Any])
        XCTAssertEqual((obj["slides"] as? [Any])?.count, 0)
        XCTAssertNil((obj["target"] as? [String: Any])?["app"])
        log.close()
    }
}
