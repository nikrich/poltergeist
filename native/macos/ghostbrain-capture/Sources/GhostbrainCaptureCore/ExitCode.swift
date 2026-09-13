import Foundation

/// Process exit codes. Canonical table lives in the package README and is
/// mirrored by `ghostbrain/recorder/audio/darwin_native.py`.
public enum ExitCode: Int32, Sendable {
    case ok = 0
    case internalError = 1
    case usage = 2
    case unsupportedOS = 3
    case screenRecordingDenied = 4
    case microphoneDenied = 5
    case streamStartFailed = 6
    case outputIO = 7
    case noDisplay = 8
    case streamStopped = 9
}

public let ghostbrainCaptureVersion = "0.1.0"
