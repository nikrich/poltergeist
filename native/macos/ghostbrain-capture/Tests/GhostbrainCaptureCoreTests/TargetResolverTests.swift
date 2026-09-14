import CoreGraphics
import XCTest
@testable import GhostbrainCaptureCore

final class TargetResolverTests: XCTestCase {
    private var nextID: UInt32 = 1

    private func win(_ bundle: String?, _ title: String?, pid: Int32 = 100, layer: Int = 0, onScreen: Bool = true,
                     size: CGSize = CGSize(width: 1280, height: 800), origin: CGPoint = .zero) -> WindowDescriptor {
        defer { nextID += 1 }
        return WindowDescriptor(windowID: nextID, ownerPID: pid, ownerBundleID: bundle, ownerName: bundle ?? "?", title: title,
                                layer: layer, isOnScreen: onScreen, frame: CGRect(origin: origin, size: size))
    }

    func testNoWindows() {
        XCTAssertNil(TargetResolver.resolve([]))
        XCTAssertNil(TargetResolver.resolve([win("com.apple.finder", "Downloads")]))
    }

    func testDropsLayerOffscreenSmallUntitled() {
        XCTAssertNil(TargetResolver.resolve([win("us.zoom.xos", "Zoom Meeting", layer: 25)]))
        XCTAssertNil(TargetResolver.resolve([win("us.zoom.xos", "Zoom Meeting", onScreen: false)]))
        XCTAssertNil(TargetResolver.resolve([win("us.zoom.xos", "Zoom Meeting", size: CGSize(width: 399, height: 800))]))
        XCTAssertNil(TargetResolver.resolve([win("us.zoom.xos", "Zoom Meeting", size: CGSize(width: 800, height: 299))]))
        XCTAssertNil(TargetResolver.resolve([win("us.zoom.xos", "")]))
        XCTAssertNil(TargetResolver.resolve([win("us.zoom.xos", nil)]))
        XCTAssertNil(TargetResolver.resolve([win(nil, "Zoom Meeting")]))
        XCTAssertNotNil(TargetResolver.resolve([win("us.zoom.xos", "Zoom Meeting", size: CGSize(width: 400, height: 300))]))
    }

    func testNativeAppsNeedMeetingLikeTitles() {
        for b in ["com.microsoft.teams2", "com.microsoft.teams", "us.zoom.xos"] {
            XCTAssertNotNil(TargetResolver.resolve([win(b, "Some meeting window")]), b)
            XCTAssertNil(TargetResolver.resolve([win(b, "Some other window")]), b)
        }
        XCTAssertNotNil(TargetResolver.resolve([win("com.tinyspeck.slackmacgap", "Huddle: design-sync - Slack")]))
        XCTAssertNil(TargetResolver.resolve([win("com.tinyspeck.slackmacgap", "general - Acme - Slack")]))
        XCTAssertNotNil(TargetResolver.resolve([win("Cisco-Systems.Spark", "Team standup")]))
        XCTAssertNil(TargetResolver.resolve([win("Cisco-Systems.Spark", "Webex")]))
        XCTAssertNil(TargetResolver.resolve([win("com.webex.meetingmanager", "Cisco Webex Meetings")]))
    }

    func testZoomHomeIsNotAMeeting() {
        let home = win("us.zoom.xos", "Zoom Workplace", size: CGSize(width: 1600, height: 1000))
        let meeting = win("us.zoom.xos", "Zoom Meeting", size: CGSize(width: 900, height: 600))
        XCTAssertEqual(TargetResolver.resolve([home, meeting])?.windowID, meeting.windowID)
        XCTAssertNil(TargetResolver.tier(for: home))
        XCTAssertEqual(TargetResolver.tier(for: meeting), 0)
        XCTAssertNil(TargetResolver.resolve([home]))
    }

    func testTeamsSubjectTitledWindowIsAMeeting() {
        // Real-world title: Teams names the meeting window after the meeting subject.
        let standup = win("com.microsoft.teams2",
                          "[Core Platform & Partner Channel - Digisure] Daily stand-up | Sanlam Life Insurance Limited | me@example.com | Microsoft Teams")
        XCTAssertEqual(TargetResolver.tier(for: standup), 1)
        XCTAssertEqual(TargetResolver.resolve([standup])?.windowID, standup.windowID)
        // App sections are never meetings.
        for section in ["Chat", "Calendar", "Activity", "Teams", "Calls", "Files", "OneDrive", "Apps", "Copilot", "Just me"] {
            XCTAssertNil(TargetResolver.tier(for: win("com.microsoft.teams2", "\(section) | Acme | me@example.com | Microsoft Teams")), section)
        }
        // A bare two-segment title is not enough.
        XCTAssertNil(TargetResolver.tier(for: win("com.microsoft.teams2", "Something | Microsoft Teams")))
    }

    func testTeamsCompactViewPromotesSubjectWindow() {
        let compact = win("com.microsoft.teams2",
                          "Meeting compact view | [Core] Daily stand-up | Acme | me@example.com | Microsoft Teams",
                          size: CGSize(width: 320, height: 180))  // too small to capture, still a signal
        let meeting = win("com.microsoft.teams2", "[Core] Daily stand-up | Acme | me@example.com | Microsoft Teams",
                          size: CGSize(width: 900, height: 600))
        let popped = win("com.microsoft.teams2", "Jane Doe | Acme | me@example.com | Microsoft Teams",
                         size: CGSize(width: 1600, height: 1000))
        XCTAssertEqual(TargetResolver.teamsCompactSubjects([compact, meeting]), ["[core] daily stand-up"])
        XCTAssertNil(TargetResolver.tier(for: compact))
        // Without the compact view both are tier 1 and the larger popped chat would win…
        XCTAssertEqual(TargetResolver.resolve([popped, meeting])?.windowID, popped.windowID)
        // …with it, the confirmed subject wins regardless of size.
        XCTAssertEqual(TargetResolver.resolve([compact, popped, meeting])?.windowID, meeting.windowID)
    }

    func testTeamsChatIsNotAMeeting() {
        let chat = win("com.microsoft.teams2", "Chat | Jane Doe | Microsoft Teams", size: CGSize(width: 1800, height: 1100))
        let poppedOutChat = win("com.microsoft.teams2", "Chat | Jane Doe (Group Office) | Acme | Microsoft Teams")
        let meeting = win("com.microsoft.teams2", "Weekly sync | Meeting | Microsoft Teams", size: CGSize(width: 1000, height: 700))
        XCTAssertEqual(TargetResolver.resolve([chat, meeting])?.windowID, meeting.windowID)
        let call = win("com.microsoft.teams2", "Call with Bob")
        XCTAssertEqual(TargetResolver.tier(for: call), 0)
        XCTAssertNil(TargetResolver.tier(for: chat))
        XCTAssertNil(TargetResolver.tier(for: poppedOutChat))
        // Chat windows alone must NOT count, or the "no meeting window" prompt
        // never fires while Teams is merely running in the background.
        XCTAssertNil(TargetResolver.resolve([chat, poppedOutChat]))
    }

    func testBrowsersNeedMeetingTitle() {
        XCTAssertNil(TargetResolver.resolve([win("com.google.Chrome", "GitHub - Pull requests")]))
        for title in ["Meet – abc-defg-hij", "Google Meet", "meet.google.com/abc", "Webex | Team standup", "Zoom Meeting", "Microsoft Teams"] {
            XCTAssertNotNil(TargetResolver.resolve([win("com.google.Chrome", title)]), title)
        }
        for b in ["com.apple.Safari", "org.mozilla.firefox", "com.microsoft.edgemac", "com.brave.Browser", "company.thebrowser.Browser"] {
            XCTAssertNotNil(TargetResolver.resolve([win(b, "Google Meet")]), b)
        }
    }

    func testFrontmostAppWinsThenLargestWithinApp() {
        let front = win("com.google.Chrome", "Google Meet", pid: 1, size: CGSize(width: 800, height: 600))
        let backBig = win("us.zoom.xos", "Zoom Meeting", pid: 2, size: CGSize(width: 2000, height: 1200))
        XCTAssertEqual(TargetResolver.resolve([front, backBig])?.windowID, front.windowID, "frontmost app wins even if smaller")

        let small = win("us.zoom.xos", "Zoom Meeting", pid: 3, size: CGSize(width: 600, height: 400))
        let big = win("us.zoom.xos", "Zoom Meeting", pid: 3, size: CGSize(width: 1600, height: 900))
        XCTAssertEqual(TargetResolver.resolve([small, big])?.windowID, big.windowID, "largest within the frontmost app")
    }

    func testNonMeetingFrontWindowIsSkipped() {
        let finder = win("com.apple.finder", "Downloads", pid: 9)
        let teams = win("com.microsoft.teams2", "Standup | Meeting | Microsoft Teams", pid: 10)
        XCTAssertEqual(TargetResolver.resolve([finder, teams])?.windowID, teams.windowID)
        XCTAssertEqual(teams.appLabel, "com.microsoft.teams2")
    }
}
