import XCTest
@testable import GhostbrainCaptureCore

final class WavWriterTests: XCTestCase {
    private func tmpURL(_ name: String) -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("gbc-\(UUID().uuidString)-\(name)")
    }

    /// Python: b"RIFF" + <I 36+n> + b"WAVEfmt " + <IHHIIHH 16,1,1,16000,32000,2,16> + b"data" + <I n>
    private func pythonHeader(dataBytes: UInt32) -> [UInt8] {
        func le32(_ v: UInt32) -> [UInt8] { [UInt8(v & 0xff), UInt8((v >> 8) & 0xff), UInt8((v >> 16) & 0xff), UInt8(v >> 24)] }
        func le16(_ v: UInt16) -> [UInt8] { [UInt8(v & 0xff), UInt8(v >> 8)] }
        return Array("RIFF".utf8) + le32(36 + dataBytes) + Array("WAVEfmt ".utf8)
            + le32(16) + le16(1) + le16(1) + le32(16000) + le32(32000) + le16(2) + le16(16)
            + Array("data".utf8) + le32(dataBytes)
    }

    func testHeaderBytesMatchPythonLayout() {
        XCTAssertEqual(WavWriter.header(dataBytes: 0), pythonHeader(dataBytes: 0))
        XCTAssertEqual(WavWriter.header(dataBytes: 6400), pythonHeader(dataBytes: 6400))
        XCTAssertEqual(WavWriter.header(dataBytes: 0x01020304), pythonHeader(dataBytes: 0x01020304))
        XCTAssertEqual(WavWriter.header(dataBytes: 0).count, 44)
    }

    func testAppendAndCloseProducesValidFile() throws {
        let url = tmpURL("a.wav")
        defer { try? FileManager.default.removeItem(at: url) }
        let w = try WavWriter(path: url)
        let samples: [Int16] = [0, 1, -1, 32767, -32768, 256]
        try w.append(samples)
        try w.append([7])
        try w.close()
        let data = try Data(contentsOf: url)
        XCTAssertEqual(data.count, 44 + 14)
        XCTAssertEqual(Array(data.prefix(44)), pythonHeader(dataBytes: 14))
        // little-endian payload
        XCTAssertEqual(Array(data[44..<58]), [0,0, 1,0, 0xff,0xff, 0xff,0x7f, 0x00,0x80, 0x00,0x01, 7,0])
        XCTAssertEqual(w.fileBytes, 58)
    }

    func testHeaderIsRewrittenOnIntervalWithoutClose() throws {
        let url = tmpURL("b.wav")
        defer { try? FileManager.default.removeItem(at: url) }
        let w = try WavWriter(path: url, headerRewriteInterval: 0) // rewrite on every append
        try w.append([Int16](repeating: 1, count: 1600))
        // Not closed: header must already declare 3200 data bytes (crash contract).
        let data = try Data(contentsOf: url)
        XCTAssertEqual(Array(data.prefix(44)), pythonHeader(dataBytes: 3200))
        try w.close()
    }

    func testStaleHeaderBeforeIntervalThenFixedOnClose() throws {
        let url = tmpURL("c.wav")
        defer { try? FileManager.default.removeItem(at: url) }
        let w = try WavWriter(path: url, headerRewriteInterval: 3600)
        try w.append([1, 2, 3])
        var data = try Data(contentsOf: url)
        XCTAssertEqual(Array(data.prefix(44)), pythonHeader(dataBytes: 0), "header not yet rewritten")
        try w.close()
        data = try Data(contentsOf: url)
        XCTAssertEqual(Array(data.prefix(44)), pythonHeader(dataBytes: 6))
    }

    func testOpenFailureThrows() {
        XCTAssertThrowsError(try WavWriter(path: URL(fileURLWithPath: "/nonexistent-root-dir-\(UUID())/x/y.wav")))
    }
}
