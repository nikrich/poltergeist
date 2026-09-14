import CoreGraphics
import Foundation

/// One on-screen window, front-to-back order preserved by the caller.
public struct WindowDescriptor: Equatable, Sendable {
    public var windowID: UInt32
    public var ownerPID: Int32
    public var ownerBundleID: String?
    public var ownerName: String
    public var title: String?
    public var layer: Int
    public var isOnScreen: Bool
    /// Global screen coordinates (CoreGraphics, origin top-left of main display).
    public var frame: CGRect

    public init(windowID: UInt32, ownerPID: Int32, ownerBundleID: String?, ownerName: String, title: String?, layer: Int, isOnScreen: Bool, frame: CGRect) {
        self.windowID = windowID
        self.ownerPID = ownerPID
        self.ownerBundleID = ownerBundleID
        self.ownerName = ownerName
        self.title = title
        self.layer = layer
        self.isOnScreen = isOnScreen
        self.frame = frame
    }

    /// Bundle id when known, else the owner's process name.
    public var appLabel: String { ownerBundleID ?? ownerName }
}

/// Pure ranking of meeting windows. Input order is front-to-back.
public enum TargetResolver {
    public static let minWidth: CGFloat = 400
    public static let minHeight: CGFloat = 300

    public static let nativeMeetingApps: Set<String> = [
        "com.microsoft.teams2",
        "com.microsoft.teams",
        "us.zoom.xos",
        "Cisco-Systems.Spark",
        "com.webex.meetingmanager",
        "com.tinyspeck.slackmacgap",
    ]

    public static let browsers: Set<String> = [
        "com.google.Chrome",
        "com.google.Chrome.beta",
        "com.google.Chrome.canary",
        "com.apple.Safari",
        "com.apple.SafariTechnologyPreview",
        "org.mozilla.firefox",
        "com.microsoft.edgemac",
        "com.brave.Browser",
        "company.thebrowser.Browser", // Arc
    ]

    static let browserMeetingRegex = try! NSRegularExpression(
        pattern: #"Meet – |Google Meet|meet\.google\.com|Webex|Zoom Meeting|Microsoft Teams"#,
        options: []
    )
    // Meeting apps keep non-meeting windows open all day (Teams chat, Zoom
    // home, Slack workspace). Only a title that positively looks like a live
    // meeting / call / huddle counts — otherwise the recorder would never ask
    // the "no meeting window" question while Teams is merely running.
    static let teamsMeetingRegex = try! NSRegularExpression(pattern: #"Meeting|Call|Webinar|Town hall"#, options: [.caseInsensitive])
    /// Teams app sections. Their windows are titled "<Section> | <org> | <email> | Microsoft Teams".
    static let teamsSections: Set<String> = [
        "chat", "calendar", "activity", "teams", "calls", "files", "onedrive", "apps",
        "copilot", "communities", "settings", "notifications", "help", "just me", "meeting compact view",
    ]
    static let teamsCompactPrefix = "Meeting compact view | "
    static let teamsBundles: Set<String> = ["com.microsoft.teams2", "com.microsoft.teams"]
    static let zoomMeetingRegex = try! NSRegularExpression(pattern: #"Meeting|Webinar"#, options: [.caseInsensitive])
    static let slackHuddleRegex = try! NSRegularExpression(pattern: #"Huddle"#, options: [.caseInsensitive])
    static let webexHomeRegex = try! NSRegularExpression(pattern: #"^(Cisco )?Webex( Meetings)?$"#)

    /// First " | "-separated segment of a Teams window title, lower-cased.
    static func teamsFirstSegment(_ title: String) -> String {
        let seg = title.components(separatedBy: " | ").first ?? title
        return seg.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    /// Subjects of meetings Teams is currently showing a "Meeting compact view"
    /// for. That floating monitor appears whenever the meeting window is not
    /// frontmost and is titled "Meeting compact view | <subject> | …", which
    /// tells us exactly which subject-titled window is the live meeting.
    public static func teamsCompactSubjects(_ windows: [WindowDescriptor]) -> Set<String> {
        var out = Set<String>()
        for w in windows {
            guard let b = w.ownerBundleID, teamsBundles.contains(b), let t = w.title, t.hasPrefix(teamsCompactPrefix) else { continue }
            let rest = String(t.dropFirst(teamsCompactPrefix.count))
            if let subject = rest.components(separatedBy: " | ").first?.trimmingCharacters(in: .whitespacesAndNewlines), !subject.isEmpty {
                out.insert(subject.lowercased())
            }
        }
        return out
    }

    /// 0 = a window whose title positively identifies a live meeting / call /
    /// huddle (or a browser tab on a meeting page); 1 = a lower-confidence
    /// meeting window (a subject-titled Teams window, a Webex window that is
    /// not the app's home window). nil = not a meeting window (Teams app
    /// sections such as Chat / Calendar, Zoom home, Slack workspace windows).
    public static func tier(for w: WindowDescriptor, compactSubjects: Set<String> = []) -> Int? {
        guard w.layer == 0, w.isOnScreen else { return nil }
        guard w.frame.width >= minWidth, w.frame.height >= minHeight else { return nil }
        guard let title = w.title?.trimmingCharacters(in: .whitespacesAndNewlines), !title.isEmpty else { return nil }
        guard let bundle = w.ownerBundleID else { return nil }

        if nativeMeetingApps.contains(bundle) {
            switch bundle {
            case "com.microsoft.teams2", "com.microsoft.teams":
                // Teams titles its meeting window with the meeting *subject*:
                // "[Core Platform] Daily stand-up | <org> | <email> | Microsoft Teams".
                // Only app sections ("Chat | …", "Calendar | …") are reliably
                // non-meetings, so: sections → nil; explicit Meeting/Call or a
                // subject confirmed by a compact view → 0; any other
                // subject-titled window → 1 (a popped-out chat can land here;
                // the user can re-target from the desktop).
                let first = teamsFirstSegment(title)
                if teamsSections.contains(first) { return nil }
                if matches(teamsMeetingRegex, title) || compactSubjects.contains(first) { return 0 }
                return title.components(separatedBy: " | ").count >= 3 ? 1 : nil
            case "us.zoom.xos":
                return matches(zoomMeetingRegex, title) ? 0 : nil
            case "com.tinyspeck.slackmacgap":
                return matches(slackHuddleRegex, title) ? 0 : nil
            default: // Webex
                return matches(webexHomeRegex, title) ? nil : 1
            }
        }
        if browsers.contains(bundle) {
            return matches(browserMeetingRegex, title) ? 0 : nil
        }
        return nil
    }

    /// Frontmost meeting app wins; within that app the best tier, then the
    /// largest window.
    public static func resolve(_ windows: [WindowDescriptor]) -> WindowDescriptor? {
        let compact = teamsCompactSubjects(windows)
        let candidates: [(Int, WindowDescriptor)] = windows.compactMap { w in
            guard let t = tier(for: w, compactSubjects: compact) else { return nil }
            return (t, w)
        }
        guard let front = candidates.first else { return nil }
        let sameApp = candidates.filter { $0.1.ownerPID == front.1.ownerPID }
        let bestTier = sameApp.map(\.0).min() ?? front.0
        let pool = sameApp.filter { $0.0 == bestTier }.map(\.1)
        return pool.max { a, b in area(a) < area(b) }
    }

    private static func area(_ w: WindowDescriptor) -> CGFloat { w.frame.width * w.frame.height }

    private static func matches(_ re: NSRegularExpression, _ s: String) -> Bool {
        re.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) != nil
    }
}
