import Foundation

public struct CLIError: Error, CustomStringConvertible, Sendable {
    public let message: String
    public init(_ message: String) { self.message = message }
    public var description: String { message }
}

public enum TargetMode: String, Sendable { case auto, display, window }
public enum NoWindowPolicy: String, Sendable { case ask, display, audio }

public enum MicDevice: Equatable, Sendable {
    case systemDefault
    case none
    case id(String)
}

public struct RunOptions: Equatable, Sendable {
    public var wav: String
    public var framesDir: String?
    /// JSON file polled once a second for runtime target changes (see `ControlCommand`).
    public var controlFile: String?
    public var fps: Int = 1
    public var target: TargetMode = .auto
    public var noWindowPolicy: NoWindowPolicy = .ask
    public var micDevice: MicDevice = .systemDefault
    public var ocrLangs: [String] = ["en-US"]
    public var slideThreshold: Double = 0.04
    public var maxFrames: Int = 600
    public var maxDurationS: Int = 21600
    public var verbose: Bool = false

    public init(wav: String, framesDir: String? = nil) {
        self.wav = wav
        self.framesDir = framesDir
    }

    /// Video is only ever captured when a frames directory was given.
    public var wantsVideo: Bool { framesDir != nil }
}

public enum Command: Equatable, Sendable {
    case run(RunOptions)
    case check(json: Bool, audioOnly: Bool)
    case requestPermissions(json: Bool)
    case listDevices(json: Bool)
    case version
    case help
}

public enum CLIOptions {
    public static let usage = """
    ghostbrain-capture \(ghostbrainCaptureVersion) — native macOS meeting capture (ScreenCaptureKit)

    USAGE
      ghostbrain-capture run --wav <path> [--frames-dir <dir>] [--control-file <path>] [--fps 1]
                             [--target auto|display|window]
                             [--no-window-policy ask|display|audio] [--mic-device <uid>|none]
                             [--ocr-langs en-US[,de-DE]] [--slide-threshold 0.04] [--max-frames 600]
                             [--max-duration-s 21600] [--verbose]
      ghostbrain-capture check [--json] [--audio-only]
      ghostbrain-capture request-permissions [--json]
      ghostbrain-capture list-devices [--json]
      ghostbrain-capture --version | --help

    EXIT CODES
      0 ok  1 internal  2 usage  3 macOS < 15  4 Screen Recording denied  5 Microphone denied
      6 SCStream failed to start  7 output I/O  8 no display  9 stream stopped unexpectedly (WAV finalised)

    SIGNALS (run)
      SIGINT/SIGTERM stop and finalise; SIGUSR1 enable full-display video; SIGUSR2 audio only, stop asking.

    CONTROL FILE (run, --control-file)
      Polled every second. JSON {"target":"display"} | {"target":"audio"} | {"target":"window","window_id":N}.
      With --frames-dir the helper also writes <frames-dir>/windows.json listing pickable windows.

    See native/macos/ghostbrain-capture/README.md for the full stdout protocol.
    """

    public static func parse(_ argv: [String]) throws -> Command {
        guard let first = argv.first else { throw CLIError("missing subcommand") }
        switch first {
        case "--version", "-V", "version":
            return .version
        case "--help", "-h", "help":
            return .help
        case "run":
            return .run(try parseRun(Array(argv.dropFirst())))
        case "check":
            let flags = try parseFlags(Array(argv.dropFirst()), allowed: ["--json", "--audio-only"])
            return .check(json: flags.contains("--json"), audioOnly: flags.contains("--audio-only"))
        case "request-permissions":
            let flags = try parseFlags(Array(argv.dropFirst()), allowed: ["--json"])
            return .requestPermissions(json: flags.contains("--json"))
        case "list-devices":
            let flags = try parseFlags(Array(argv.dropFirst()), allowed: ["--json"])
            return .listDevices(json: flags.contains("--json"))
        default:
            throw CLIError("unknown subcommand '\(first)'")
        }
    }

    private static func parseFlags(_ args: [String], allowed: Set<String>) throws -> Set<String> {
        var seen = Set<String>()
        for a in args {
            guard allowed.contains(a) else { throw CLIError("unexpected argument '\(a)'") }
            seen.insert(a)
        }
        return seen
    }

    private static func parseRun(_ args: [String]) throws -> RunOptions {
        var wav: String?
        var opts = RunOptions(wav: "")
        var i = 0
        func value(_ flag: String) throws -> String {
            i += 1
            guard i < args.count else { throw CLIError("\(flag) requires a value") }
            return args[i]
        }
        func intValue(_ flag: String, min: Int, max: Int) throws -> Int {
            let raw = try value(flag)
            guard let n = Int(raw), n >= min, n <= max else {
                throw CLIError("\(flag) must be an integer in \(min)...\(max), got '\(raw)'")
            }
            return n
        }
        while i < args.count {
            let a = args[i]
            switch a {
            case "--wav": wav = try value(a)
            case "--frames-dir": opts.framesDir = try value(a)
            case "--control-file": opts.controlFile = try value(a)
            case "--fps": opts.fps = try intValue(a, min: 1, max: 10)
            case "--target":
                let raw = try value(a)
                guard let t = TargetMode(rawValue: raw) else { throw CLIError("--target must be auto|display|window") }
                opts.target = t
            case "--no-window-policy":
                let raw = try value(a)
                guard let p = NoWindowPolicy(rawValue: raw) else { throw CLIError("--no-window-policy must be ask|display|audio") }
                opts.noWindowPolicy = p
            case "--mic-device":
                let raw = try value(a)
                opts.micDevice = raw == "none" ? .none : (raw.isEmpty || raw == "default" ? .systemDefault : .id(raw))
            case "--ocr-langs":
                let raw = try value(a)
                let langs = raw.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
                guard !langs.isEmpty else { throw CLIError("--ocr-langs requires at least one language") }
                opts.ocrLangs = langs
            case "--slide-threshold":
                let raw = try value(a)
                guard let d = Double(raw), d > 0, d <= 1 else { throw CLIError("--slide-threshold must be in (0, 1]") }
                opts.slideThreshold = d
            case "--max-frames": opts.maxFrames = try intValue(a, min: 1, max: 100_000)
            case "--max-duration-s": opts.maxDurationS = try intValue(a, min: 1, max: 86_400 * 7)
            case "--verbose", "-v": opts.verbose = true
            default:
                throw CLIError("unexpected argument '\(a)'")
            }
            i += 1
        }
        guard let w = wav, !w.isEmpty else { throw CLIError("run requires --wav <path>") }
        opts.wav = w
        return opts
    }
}
