import Foundation

public struct SlideTarget: Codable, Equatable, Sendable {
    public var kind: String   // window | display | none
    public var app: String?
    public var title: String?
    public init(kind: String, app: String? = nil, title: String? = nil) {
        self.kind = kind; self.app = app; self.title = title
    }
}

public struct SlideRecord: Codable, Equatable, Sendable {
    public var index: Int
    public var offsetMs: Int
    public var image: String
    public var width: Int
    public var height: Int
    public var text: String
    public var ocr: String          // accurate | skipped | failed
    public var confidence: Double
    public var diff: Double

    enum CodingKeys: String, CodingKey {
        case index
        case offsetMs = "offset_ms"
        case image, width, height, text, ocr, confidence, diff
    }

    public init(index: Int, offsetMs: Int, image: String, width: Int, height: Int, text: String, ocr: String, confidence: Double, diff: Double) {
        self.index = index; self.offsetMs = offsetMs; self.image = image; self.width = width; self.height = height
        self.text = text; self.ocr = ocr; self.confidence = confidence; self.diff = diff
    }
}

public struct SlideManifest: Codable, Equatable, Sendable {
    public var version: Int = 1
    public var wav: String
    public var startedAt: String
    public var durationMs: Int
    public var fps: Int
    public var target: SlideTarget
    public var slides: [SlideRecord]

    enum CodingKeys: String, CodingKey {
        case version, wav
        case startedAt = "started_at"
        case durationMs = "duration_ms"
        case fps, target, slides
    }
}

public enum SlideLogError: Error, CustomStringConvertible {
    case io(String)
    public var description: String { switch self { case .io(let m): return m } }
}

/// Owns `<frames-dir>/slides.jsonl` (append per slide, crash-safe) and
/// `<frames-dir>/slides.json` (atomic rewrite via temp file + rename).
/// Not thread-safe: callers serialise on their own queue.
public final class SlideLog: @unchecked Sendable {
    public static let jsonlName = "slides.jsonl"
    public static let jsonName = "slides.json"

    public let directory: URL
    public let wavName: String
    public let startedAt: Date
    public let fps: Int
    public var target: SlideTarget
    public private(set) var records: [SlideRecord] = []

    private let jsonlHandle: FileHandle
    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return e
    }()

    /// `2026-09-12T10:00:00Z` (UTC, second precision).
    public static func iso8601(_ date: Date) -> String {
        date.formatted(.iso8601.year().month().day().dateSeparator(.dash)
            .dateTimeSeparator(.standard).time(includingFractionalSeconds: false).timeZone(separator: .omitted))
    }

    public init(directory: URL, wavName: String, startedAt: Date, fps: Int, target: SlideTarget) throws {
        self.directory = directory
        self.wavName = wavName
        self.startedAt = startedAt
        self.fps = fps
        self.target = target
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        } catch {
            throw SlideLogError.io("mkdir \(directory.path): \(error.localizedDescription)")
        }
        let jsonl = directory.appendingPathComponent(Self.jsonlName)
        if !FileManager.default.fileExists(atPath: jsonl.path) {
            guard FileManager.default.createFile(atPath: jsonl.path, contents: nil) else {
                throw SlideLogError.io("create \(jsonl.path) failed")
            }
        }
        guard let h = FileHandle(forWritingAtPath: jsonl.path) else {
            throw SlideLogError.io("open \(jsonl.path) for append failed")
        }
        h.seekToEndOfFile()
        jsonlHandle = h
    }

    /// `slide-0001-00004200.jpg` — 1-based index, offset in ms since READY.
    public static func imageName(index: Int, offsetMs: Int) -> String {
        String(format: "slide-%04d-%08d.jpg", index, max(0, offsetMs))
    }

    public func append(_ record: SlideRecord) throws {
        records.append(record)
        do {
            var line = try encoder.encode(record)
            line.append(0x0a)
            try jsonlHandle.write(contentsOf: line)
            try jsonlHandle.synchronize()
        } catch {
            throw SlideLogError.io("append \(Self.jsonlName): \(error.localizedDescription)")
        }
    }

    public func manifest(durationMs: Int) -> SlideManifest {
        SlideManifest(
            wav: wavName,
            startedAt: Self.iso8601(startedAt),
            durationMs: durationMs,
            fps: fps,
            target: target,
            slides: records.sorted { $0.index < $1.index }
        )
    }

    public func writeManifest(durationMs: Int) throws {
        let final = directory.appendingPathComponent(Self.jsonName)
        let tmp = directory.appendingPathComponent(".\(Self.jsonName).tmp-\(getpid())")
        do {
            let data = try encoder.encode(manifest(durationMs: durationMs))
            try data.write(to: tmp, options: [])
            _ = try FileManager.default.replaceItemAt(final, withItemAt: tmp)
        } catch {
            try? FileManager.default.removeItem(at: tmp)
            throw SlideLogError.io("write \(Self.jsonName): \(error.localizedDescription)")
        }
    }

    public func close() {
        try? jsonlHandle.close()
    }
}
