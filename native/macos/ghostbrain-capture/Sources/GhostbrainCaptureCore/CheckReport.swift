import Foundation

public enum MicStatus: String, Sendable {
    case granted, denied, restricted, notDetermined = "not_determined"
}

public struct OSVersion: Equatable, Sendable {
    public var major: Int, minor: Int, patch: Int
    public init(_ major: Int, _ minor: Int, _ patch: Int) {
        self.major = major; self.minor = minor; self.patch = patch
    }
    public var string: String { "\(major).\(minor).\(patch)" }
    public var supported: Bool { major >= 15 }
}

/// Output of `check` / `request-permissions`. Encodes to the JSON the Python
/// probe consumes. `code` is the exit code `run` would fail with right now.
public struct CheckReport: Encodable, Equatable, Sendable {
    public var ok: Bool
    public var code: Int32
    public var macos: String
    public var macosSupported: Bool
    public var screenRecording: String
    public var microphone: String
    public var audioOnly: Bool
    public var issues: [String]
    public var version: String

    enum CodingKeys: String, CodingKey {
        case ok, code, macos
        case macosSupported = "macos_supported"
        case screenRecording = "screen_recording"
        case microphone
        case audioOnly = "audio_only"
        case issues, version
    }

    /// Note: with the ScreenCaptureKit backend, system audio itself needs
    /// Screen Recording, so it stays fatal even for `--audio-only`; the flag
    /// only tunes the wording. (An audio-only CoreAudio-tap path would relax
    /// this — see README.)
    public static func build(os: OSVersion, screenRecordingGranted: Bool, microphone: MicStatus, audioOnly: Bool) -> CheckReport {
        var issues: [String] = []
        var code = ExitCode.ok
        if !os.supported {
            issues.append("macOS 15 or newer is required for native capture (found \(os.string)); set recorder.capture_backend: blackhole")
            code = .unsupportedOS
        }
        if !screenRecordingGranted {
            issues.append(audioOnly
                ? "Screen Recording permission not granted (ScreenCaptureKit needs it even for system audio); run 'ghostbrain-capture request-permissions' and enable it in System Settings > Privacy & Security > Screen & System Audio Recording"
                : "Screen Recording permission not granted; run 'ghostbrain-capture request-permissions' and enable it in System Settings > Privacy & Security > Screen & System Audio Recording")
            if code == .ok { code = .screenRecordingDenied }
        }
        switch microphone {
        case .granted: break
        case .denied, .restricted:
            issues.append("Microphone permission \(microphone.rawValue); enable it in System Settings > Privacy & Security > Microphone")
            if code == .ok { code = .microphoneDenied }
        case .notDetermined:
            issues.append("Microphone permission not determined yet; run 'ghostbrain-capture request-permissions'")
            if code == .ok { code = .microphoneDenied }
        }
        return CheckReport(
            ok: code == .ok,
            code: code.rawValue,
            macos: os.string,
            macosSupported: os.supported,
            screenRecording: screenRecordingGranted ? "granted" : "denied",
            microphone: microphone.rawValue,
            audioOnly: audioOnly,
            issues: issues,
            version: ghostbrainCaptureVersion
        )
    }

    public func jsonString() -> String {
        let enc = JSONEncoder()
        enc.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        guard let data = try? enc.encode(self), let s = String(data: data, encoding: .utf8) else {
            return "{\"ok\":false,\"code\":1,\"issues\":[\"failed to encode report\"]}"
        }
        return s
    }

    public func textLines() -> [String] {
        var lines = [
            "ok: \(ok)",
            "macos: \(macos) (supported: \(macosSupported))",
            "screen_recording: \(screenRecording)",
            "microphone: \(microphone)",
        ]
        for i in issues { lines.append("issue: \(i)") }
        return lines
    }
}
