import CoreGraphics
import Foundation

/// A runtime instruction written by the controlling process (Python) to the
/// `--control-file`. Signals can only carry "display" / "audio"; picking a
/// specific window needs a payload, hence the file.
///
/// ```json
/// {"target": "display"}
/// {"target": "audio"}
/// {"target": "window", "window_id": 8812}
/// ```
public enum ControlCommand: Equatable, Sendable {
    case display
    case audio
    case window(UInt32)

    public static func parse(_ data: Data) -> ControlCommand? {
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        guard let target = obj["target"] as? String else { return nil }
        switch target.lowercased() {
        case "display", "screen": return .display
        case "audio", "none": return .audio
        case "window":
            if let n = obj["window_id"] as? Int, n > 0 { return .window(UInt32(n)) }
            if let s = obj["window_id"] as? String, let n = UInt32(s) { return .window(n) }
            return nil
        default: return nil
        }
    }
}

/// The on-screen windows a user could pick as the slide source, serialised to
/// `<frames-dir>/windows.json` so the desktop app can render a picker while
/// the helper is waiting for a choice.
public enum WindowCatalog {
    public struct Entry: Equatable, Sendable {
        public var windowID: UInt32
        public var app: String
        public var appName: String
        public var title: String
        public var width: Int
        public var height: Int
        /// True when `TargetResolver` would have picked it as a meeting window.
        public var candidate: Bool
    }

    /// Windows worth offering: normal layer, on screen, big enough, titled, and
    /// not belonging to `excludingPID` (the desktop app itself, if known).
    public static func entries(from windows: [WindowDescriptor], excludingBundleIDs: Set<String> = []) -> [Entry] {
        var out: [Entry] = []
        var seen = Set<UInt32>()
        for w in windows {
            guard w.layer == 0, w.isOnScreen else { continue }
            guard w.frame.width >= TargetResolver.minWidth, w.frame.height >= TargetResolver.minHeight else { continue }
            guard let title = w.title?.trimmingCharacters(in: .whitespacesAndNewlines), !title.isEmpty else { continue }
            if let b = w.ownerBundleID, excludingBundleIDs.contains(b) { continue }
            guard !seen.contains(w.windowID) else { continue }
            seen.insert(w.windowID)
            out.append(Entry(
                windowID: w.windowID,
                app: w.appLabel,
                appName: w.ownerName.isEmpty ? w.appLabel : w.ownerName,
                title: title,
                width: Int(w.frame.width.rounded()),
                height: Int(w.frame.height.rounded()),
                candidate: TargetResolver.tier(for: w) != nil
            ))
        }
        return out
    }

    /// Stable JSON (sorted keys, front-to-back order preserved) so callers can
    /// compare encodings to detect "the list changed".
    public static func encode(_ entries: [Entry], generatedAt: Date = Date()) -> Data {
        let iso = ISO8601DateFormatter()
        let payload: [String: Any] = [
            "version": 1,
            "generated_at": iso.string(from: generatedAt),
            "windows": entries.map { e -> [String: Any] in
                [
                    "window_id": Int(e.windowID),
                    "app": e.app,
                    "app_name": e.appName,
                    "title": e.title,
                    "width": e.width,
                    "height": e.height,
                    "candidate": e.candidate,
                ]
            },
        ]
        return (try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])) ?? Data()
    }

    /// Fingerprint of what matters for the picker (ignores timestamps).
    public static func fingerprint(_ entries: [Entry]) -> String {
        entries.map { "\($0.windowID):\($0.title):\($0.candidate)" }.joined(separator: "|")
    }
}
