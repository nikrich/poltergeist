import Foundation

/// Encoder for the stdout protocol: one `KEY k=v k2="quoted v"` line per event.
/// Values are left bare when they are a single token; anything with
/// whitespace, quotes, `=` or an empty string is double-quoted with
/// backslash escapes so a shlex-style parser round-trips it.
public enum ProtocolLine {
    public static func format(_ key: String, _ fields: [(String, String)] = []) -> String {
        var parts = [key]
        for (k, v) in fields {
            parts.append("\(k)=\(quoteIfNeeded(v))")
        }
        return parts.joined(separator: " ")
    }

    public static func quoteIfNeeded(_ value: String) -> String {
        let needsQuote = value.isEmpty || value.contains { ch in
            ch == " " || ch == "\t" || ch == "\n" || ch == "\"" || ch == "=" || ch == "\\"
        }
        guard needsQuote else { return value }
        var out = "\""
        for ch in value {
            switch ch {
            case "\\": out += "\\\\"
            case "\"": out += "\\\""
            case "\n": out += "\\n"
            case "\t": out += "\\t"
            default: out.append(ch)
            }
        }
        out += "\""
        return out
    }
}

/// stdout writer. Errors (EPIPE when the parent closed the pipe) are swallowed;
/// SIGPIPE is ignored by the executable at startup.
public final class StdoutEmitter: @unchecked Sendable {
    public static let shared = StdoutEmitter()
    private let lock = NSLock()

    public init() {}

    public func emit(_ key: String, _ fields: [(String, String)] = []) {
        write(ProtocolLine.format(key, fields))
    }

    public func write(_ line: String) {
        lock.lock()
        defer { lock.unlock() }
        var text = line
        if !text.hasSuffix("\n") { text += "\n" }
        _ = fputs(text, stdout)
        _ = fflush(stdout)
        clearerr(stdout)
    }
}

/// stderr logger: `[ghostbrain-capture] LEVEL msg`.
public final class Logger: @unchecked Sendable {
    public enum Level: Int, Comparable, Sendable {
        case debug = 0, info, warn, error
        public static func < (a: Level, b: Level) -> Bool { a.rawValue < b.rawValue }
        var label: String {
            switch self {
            case .debug: return "DEBUG"
            case .info: return "INFO"
            case .warn: return "WARN"
            case .error: return "ERROR"
            }
        }
    }

    public let minimum: Level
    private let lock = NSLock()
    private let sink: @Sendable (String) -> Void

    public init(verbose: Bool = false, sink: (@Sendable (String) -> Void)? = nil) {
        minimum = verbose ? .debug : .info
        self.sink = sink ?? { line in
            _ = fputs(line + "\n", stderr)
        }
    }

    public func log(_ level: Level, _ message: String) {
        guard level >= minimum else { return }
        lock.lock()
        defer { lock.unlock() }
        sink("[ghostbrain-capture] \(level.label) \(message)")
    }

    public func debug(_ m: String) { log(.debug, m) }
    public func info(_ m: String) { log(.info, m) }
    public func warn(_ m: String) { log(.warn, m) }
    public func error(_ m: String) { log(.error, m) }
}
