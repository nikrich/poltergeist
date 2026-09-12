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
    static let teamsChatRegex = try! NSRegularExpression(pattern: #"^Chat \|"#)
    static let zoomMeetingRegex = try! NSRegularExpression(pattern: #"Meeting|Webinar"#, options: [.caseInsensitive])
    static let slackHuddleRegex = try! NSRegularExpression(pattern: #"Huddle"#, options: [.caseInsensitive])
    static let webexHomeRegex = try! NSRegularExpression(pattern: #"^(Cisco )?Webex( Meetings)?$"#)

    /// 0 = a window whose title positively identifies a live meeting / call /
    /// huddle (or a browser tab on a meeting page); 1 = a Webex window that is
    /// not the app's home window. nil = not a meeting window (this includes
    /// Teams chat, Zoom home and Slack workspace windows).
    public static func tier(for w: WindowDescriptor) -> Int? {
        guard w.layer == 0, w.isOnScreen else { return nil }
        guard w.frame.width >= minWidth, w.frame.height >= minHeight else { return nil }
        guard let title = w.title?.trimmingCharacters(in: .whitespacesAndNewlines), !title.isEmpty else { return nil }
        guard let bundle = w.ownerBundleID else { return nil }

        if nativeMeetingApps.contains(bundle) {
            switch bundle {
            case "com.microsoft.teams2", "com.microsoft.teams":
                if matches(teamsChatRegex, title) { return nil }
                return matches(teamsMeetingRegex, title) ? 0 : nil
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
        let candidates: [(Int, WindowDescriptor)] = windows.compactMap { w in
            guard let t = tier(for: w) else { return nil }
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
