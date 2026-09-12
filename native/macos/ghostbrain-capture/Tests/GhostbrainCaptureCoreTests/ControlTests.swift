import CoreGraphics
import XCTest
@testable import GhostbrainCaptureCore

final class ControlTests: XCTestCase {
    func testParseCommands() {
        XCTAssertEqual(ControlCommand.parse(Data(#"{"target":"display"}"#.utf8)), .display)
        XCTAssertEqual(ControlCommand.parse(Data(#"{"target":"screen"}"#.utf8)), .display)
        XCTAssertEqual(ControlCommand.parse(Data(#"{"target":"audio"}"#.utf8)), .audio)
        XCTAssertEqual(ControlCommand.parse(Data(#"{"target":"window","window_id":8812}"#.utf8)), .window(8812))
        XCTAssertEqual(ControlCommand.parse(Data(#"{"target":"window","window_id":"42"}"#.utf8)), .window(42))
        XCTAssertNil(ControlCommand.parse(Data(#"{"target":"window"}"#.utf8)))
        XCTAssertNil(ControlCommand.parse(Data(#"{"target":"bogus"}"#.utf8)))
        XCTAssertNil(ControlCommand.parse(Data("not json".utf8)))
    }

    private func win(_ id: UInt32, _ bundle: String?, _ title: String?, layer: Int = 0, onScreen: Bool = true,
                     size: CGSize = CGSize(width: 1280, height: 800)) -> WindowDescriptor {
        WindowDescriptor(windowID: id, ownerPID: Int32(id), ownerBundleID: bundle, ownerName: bundle ?? "App", title: title,
                         layer: layer, isOnScreen: onScreen, frame: CGRect(origin: .zero, size: size))
    }

    func testCatalogFiltersAndFlagsCandidates() {
        let windows = [
            win(1, "us.zoom.xos", "Zoom Meeting"),
            win(2, "com.microsoft.teams2", "Chat | Jane | Microsoft Teams"),
            win(3, "com.apple.finder", "Downloads", size: CGSize(width: 300, height: 200)),
            win(4, "com.apple.dt.Xcode", "CaptureSession.swift"),
            win(5, "tech.codeship.ghostbrain", "Poltergeist"),
            win(6, "com.apple.Notes", ""),
            win(7, "com.apple.Music", "Music", layer: 25),
            win(1, "us.zoom.xos", "Zoom Meeting"), // duplicate id
        ]
        let entries = WindowCatalog.entries(from: windows, excludingBundleIDs: ["tech.codeship.ghostbrain"])
        XCTAssertEqual(entries.map(\.windowID), [1, 2, 4])
        XCTAssertEqual(entries.map(\.candidate), [true, false, false])
        XCTAssertEqual(entries[1].appName, "com.microsoft.teams2")
    }

    func testEncodeIsStableAndFingerprintIgnoresTime() {
        let entries = WindowCatalog.entries(from: [win(9, "com.google.Chrome", "Google Meet")])
        let a = WindowCatalog.encode(entries, generatedAt: Date(timeIntervalSince1970: 0))
        let b = WindowCatalog.encode(entries, generatedAt: Date(timeIntervalSince1970: 0))
        XCTAssertEqual(a, b)
        let obj = try! JSONSerialization.jsonObject(with: a) as! [String: Any]
        let list = obj["windows"] as! [[String: Any]]
        XCTAssertEqual(list.count, 1)
        XCTAssertEqual(list[0]["window_id"] as? Int, 9)
        XCTAssertEqual(list[0]["candidate"] as? Bool, true)
        XCTAssertEqual(WindowCatalog.fingerprint(entries), "9:Google Meet:true")
    }
}
