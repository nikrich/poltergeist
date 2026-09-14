import AVFoundation
import CoreGraphics
import Foundation
import GhostbrainCaptureCore

enum Permissions {
    static var osVersion: OSVersion {
        let v = ProcessInfo.processInfo.operatingSystemVersion
        return OSVersion(v.majorVersion, v.minorVersion, v.patchVersion)
    }

    /// Non-prompting TCC query. Reflects the *responsible* process
    /// (Poltergeist.app when launched from the sidecar, Terminal when run by hand).
    static func screenRecordingGranted() -> Bool {
        CGPreflightScreenCaptureAccess()
    }

    static func microphoneStatus() -> MicStatus {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: return .granted
        case .denied: return .denied
        case .restricted: return .restricted
        case .notDetermined: return .notDetermined
        @unknown default: return .denied
        }
    }

    static func check(audioOnly: Bool) -> CheckReport {
        CheckReport.build(
            os: osVersion,
            screenRecordingGranted: screenRecordingGranted(),
            microphone: microphoneStatus(),
            audioOnly: audioOnly
        )
    }

    /// Triggers the TCC prompts. Screen Recording's prompt is asynchronous
    /// (macOS shows it and returns immediately), the mic one can be awaited.
    static func request() async -> CheckReport {
        if !screenRecordingGranted() {
            _ = CGRequestScreenCaptureAccess()
        }
        if AVCaptureDevice.authorizationStatus(for: .audio) == .notDetermined {
            _ = await AVCaptureDevice.requestAccess(for: .audio)
        }
        return check(audioOnly: false)
    }
}
