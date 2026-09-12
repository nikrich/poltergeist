import CoreGraphics
import Foundation
import GhostbrainCaptureCore
import ScreenCaptureKit

@available(macOS 15, *)
struct Shareable {
    let displays: [SCDisplay]
    /// Front-to-back, already filtered to what ScreenCaptureKit can see.
    let windows: [WindowDescriptor]
    /// The SCWindow behind each descriptor, needed to build a window filter.
    let scWindows: [UInt32: SCWindow]
}

@available(macOS 15, *)
enum ShareableContent {
    static func fetch() async throws -> Shareable {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        var byID: [UInt32: SCWindow] = [:]
        for w in content.windows { byID[w.windowID] = w }
        return Shareable(displays: content.displays, windows: descriptors(from: content.windows), scWindows: byID)
    }

    /// `CGWindowListCopyWindowInfo` gives z-order; SCWindow gives the bundle id
    /// and title. Join by window number. Windows SC does not report are dropped.
    static func descriptors(from scWindows: [SCWindow]) -> [WindowDescriptor] {
        var byID: [UInt32: SCWindow] = [:]
        for w in scWindows { byID[w.windowID] = w }

        var ordered: [WindowDescriptor] = []
        var seen = Set<UInt32>()
        let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
        if let infos = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] {
            for info in infos {
                guard let num = info[kCGWindowNumber as String] as? UInt32 ?? (info[kCGWindowNumber as String] as? Int).map(UInt32.init) else { continue }
                guard let sc = byID[num] else { continue }
                seen.insert(num)
                ordered.append(descriptor(sc, cgLayer: info[kCGWindowLayer as String] as? Int))
            }
        }
        // Anything SC knows but CG did not list (rare): append at the back.
        for w in scWindows where !seen.contains(w.windowID) {
            ordered.append(descriptor(w, cgLayer: nil))
        }
        return ordered
    }

    private static func descriptor(_ w: SCWindow, cgLayer: Int?) -> WindowDescriptor {
        WindowDescriptor(
            windowID: w.windowID,
            ownerPID: w.owningApplication?.processID ?? 0,
            ownerBundleID: w.owningApplication?.bundleIdentifier.isEmpty == false ? w.owningApplication?.bundleIdentifier : nil,
            ownerName: w.owningApplication?.applicationName ?? "",
            title: w.title,
            layer: cgLayer ?? w.windowLayer,
            isOnScreen: w.isOnScreen,
            frame: w.frame
        )
    }

    /// Display whose frame contains the window centre; else main display; else first.
    static func display(for window: WindowDescriptor?, in displays: [SCDisplay]) -> SCDisplay? {
        if let w = window {
            let c = CGPoint(x: w.frame.midX, y: w.frame.midY)
            if let d = displays.first(where: { $0.frame.contains(c) }) { return d }
        }
        let mainID = CGMainDisplayID()
        return displays.first(where: { $0.displayID == mainID }) ?? displays.first
    }

    /// Backing scale (pixels per point) for a display.
    static func pixelScale(of display: SCDisplay) -> CGFloat {
        guard let mode = CGDisplayCopyDisplayMode(display.displayID), display.width > 0 else { return 2 }
        return CGFloat(mode.pixelWidth) / CGFloat(display.width)
    }
}
