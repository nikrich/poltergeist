import Foundation
import GhostbrainCaptureCore

// The parent (Python) may close our stdout early; never die on EPIPE.
signal(SIGPIPE, SIG_IGN)
setvbuf(stdout, nil, _IOLBF, 0)

let emitter = StdoutEmitter.shared

func fail(usage message: String) -> Never {
    FileHandle.standardError.write(Data("[ghostbrain-capture] ERROR \(message)\n\n\(CLIOptions.usage)\n".utf8))
    exit(ExitCode.usage.rawValue)
}

func requireMacOS15(_ log: Logger) {
    let v = Permissions.osVersion
    guard v.supported else {
        log.error("macOS 15 or newer is required for native capture (found \(v.string)); set recorder.capture_backend: blackhole")
        exit(ExitCode.unsupportedOS.rawValue)
    }
}

let command: Command
do {
    command = try CLIOptions.parse(Array(CommandLine.arguments.dropFirst()))
} catch let e as CLIError {
    fail(usage: e.message)
} catch {
    fail(usage: "\(error)")
}

switch command {
case .version:
    emitter.write(ghostbrainCaptureVersion)
    exit(ExitCode.ok.rawValue)

case .help:
    emitter.write(CLIOptions.usage)
    exit(ExitCode.ok.rawValue)

case .check(let json, let audioOnly):
    let report = Permissions.check(audioOnly: audioOnly)
    if json { emitter.write(report.jsonString()) } else { report.textLines().forEach { emitter.write($0) } }
    exit(report.code)

case .requestPermissions(let json):
    Task { @MainActor in
        let report = await Permissions.request()
        if json { emitter.write(report.jsonString()) } else { report.textLines().forEach { emitter.write($0) } }
        exit(report.code)
    }
    dispatchMain()

case .listDevices(let json):
    let log = Logger()
    requireMacOS15(log)
    if #available(macOS 14, *) {
        let devices = Devices.listInputs()
        if json {
            emitter.write(Devices.json(devices))
        } else {
            for d in devices { emitter.write("\(d.id)\t\(d.name)\(d.isDefault ? "\t(default)" : "")") }
        }
    }
    exit(ExitCode.ok.rawValue)

case .run(let options):
    let log = Logger(verbose: options.verbose)
    requireMacOS15(log)
    guard #available(macOS 15, *) else { exit(ExitCode.unsupportedOS.rawValue) }
    let session = CaptureSession(options: options, log: log)
    Task { @MainActor in
        await session.start()
    }
    dispatchMain()
}
