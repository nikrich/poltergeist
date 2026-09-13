import AVFoundation
import CoreMedia
import Foundation
import GhostbrainCaptureCore
import ScreenCaptureKit

/// Orchestrates one recording: permissions → shareable content → SCStream(s) →
/// READY → (re-resolve target every 3 s, drain mixer every 100 ms) → stop.
///
/// Two streams: the *audio* stream always uses a display content filter
/// (ScreenCaptureKit scopes system audio to the filter, so a display filter
/// = everything the user hears) and never attaches a screen output. The
/// *video* stream is created on demand with either a window filter — which
/// renders that window alone, even when other windows overlap it — or a
/// display filter for whole-screen capture. Cropping a display stream to the
/// window's rectangle was tried first and captured whatever was in front.
/// Everything here runs on the main actor; SCStream callbacks land in
/// `StreamOutput` on their own queues and only touch thread-safe objects.
@available(macOS 15, *)
@MainActor
final class CaptureSession {
    enum VideoMode: Equatable {
        case off
        case window(WindowDescriptor)
        case display
    }

    static let resolveInterval: TimeInterval = 3
    static let drainInterval: TimeInterval = 0.1
    static let stopWatchdog: TimeInterval = 3
    static let ocrFinishTimeout: TimeInterval = 3

    let options: RunOptions
    let log: Logger
    let emitter = StdoutEmitter.shared

    private var stream: SCStream?            // audio (+ mic)
    private var videoStream: SCStream?
    private var videoStreamMode: VideoMode = .off
    private var videoDelegate: VideoStreamDelegate?
    private var lastShareable: Shareable?
    private var output: StreamOutput?
    private let mixer: Mixer
    private var wav: WavWriter?
    private var sampler: FrameSampler?
    private var displays: [SCDisplay] = []
    private var currentDisplay: SCDisplay?
    private var videoMode: VideoMode = .off
    private var awaitingChoice = false
    private var userChoseDisplay = false
    private var declinedVideo = false
    /// Window the user picked explicitly (control file). While set, automatic
    /// re-targeting is suspended; cleared when that window disappears.
    private var pinnedWindowID: UInt32?
    private var controlTimer: DispatchSourceTimer?
    private var controlMTime: Date?
    private var lastCatalogFingerprint: String?
    private var stopping = false
    private var exitCodeOnStop: ExitCode = .ok
    private var startedAt = Date()
    private var startUptime: TimeInterval = 0
    private let mixerQueue = DispatchQueue(label: "ghostbrain-capture.mixer", qos: .userInitiated)
    private var drainTimer: DispatchSourceTimer?
    private var resolveTimer: DispatchSourceTimer?
    private var maxDurationTimer: DispatchSourceTimer?
    private var signalSources: [DispatchSourceSignal] = []
    private var wavFailed = false

    init(options: RunOptions, log: Logger) {
        self.options = options
        self.log = log
        let l = log
        mixer = Mixer(warn: { l.warn($0) })
    }

    private var elapsedMs: Int {
        Int((ProcessInfo.processInfo.systemUptime - startUptime) * 1000)
    }

    // MARK: Start

    func start() async {
        emitter.emit("STARTING", [("version", ghostbrainCaptureVersion), ("pid", String(getpid()))])
        installSignalHandlers()

        // Permissions first; never prompt here.
        guard Permissions.screenRecordingGranted() else {
            log.error("Screen Recording permission not granted (ScreenCaptureKit needs it for system audio too); run 'ghostbrain-capture request-permissions'")
            exit(ExitCode.screenRecordingDenied.rawValue)
        }
        if options.micDevice != .none {
            let mic = Permissions.microphoneStatus()
            guard mic == .granted else {
                log.error("Microphone permission \(mic.rawValue); run 'ghostbrain-capture request-permissions' or pass --mic-device none")
                exit(ExitCode.microphoneDenied.rawValue)
            }
        }

        // Shareable content + display.
        let shareable: Shareable
        do {
            shareable = try await ShareableContent.fetch()
        } catch {
            let ns = error as NSError
            if ns.domain == SCStreamErrorDomain, ns.code == SCStreamError.Code.userDeclined.rawValue {
                log.error("Screen Recording declined: \(ns.localizedDescription)")
                exit(ExitCode.screenRecordingDenied.rawValue)
            }
            log.error("SCShareableContent failed: \(ns.localizedDescription) (domain=\(ns.domain) code=\(ns.code))")
            exit(ExitCode.streamStartFailed.rawValue)
        }
        displays = shareable.displays
        lastShareable = shareable
        guard !displays.isEmpty else {
            log.error("no display available to capture")
            exit(ExitCode.noDisplay.rawValue)
        }

        // Output files.
        let wavURL = URL(fileURLWithPath: options.wav)
        do {
            wav = try WavWriter(path: wavURL)
        } catch {
            log.error("\(error)")
            exit(ExitCode.outputIO.rawValue)
        }
        startedAt = Date()
        startUptime = ProcessInfo.processInfo.systemUptime

        // Initial target.
        let initialWindow = options.wantsVideo && options.target != .display ? TargetResolver.resolve(shareable.windows) : nil
        if options.wantsVideo {
            // Diagnostics: which meeting-app windows were considered. Chat /
            // home windows are listed but rejected (title not meeting-like).
            let seen = shareable.windows.compactMap { w -> String? in
                guard let b = w.ownerBundleID,
                      TargetResolver.nativeMeetingApps.contains(b) || TargetResolver.browsers.contains(b),
                      let t = w.title, !t.isEmpty else { return nil }
                let verdict = TargetResolver.tier(for: w) == nil ? "rejected" : "candidate"
                return "\(b) \"\(t.prefix(60))\" → \(verdict)"
            }
            log.info("meeting-window scan: \(seen.isEmpty ? "none" : seen.joined(separator: "; "))")
            writeWindowCatalog(shareable.windows)
        }
        currentDisplay = ShareableContent.display(for: initialWindow, in: displays)
        decideInitialVideo(window: initialWindow)

        if let framesDir = options.framesDir {
            do {
                sampler = try FrameSampler(
                    framesDir: URL(fileURLWithPath: framesDir),
                    wavName: wavURL.lastPathComponent,
                    startedAt: startedAt,
                    options: options,
                    target: slideTarget(),
                    log: log,
                    emitter: emitter,
                    durationProvider: { [startUptime] in Int((ProcessInfo.processInfo.systemUptime - startUptime) * 1000) }
                )
            } catch {
                log.error("\(error)")
                exit(ExitCode.outputIO.rawValue)
            }
        }

        // Stream.
        let out = StreamOutput(
            mixer: mixer, sampler: sampler, log: log,
            offsetProvider: { [startUptime] in Int((ProcessInfo.processInfo.systemUptime - startUptime) * 1000) },
            onStop: { error in
                Task { @MainActor in
                    // Deliberately not weak: the session lives until exit().
                    CaptureSession.active?.streamDidStop(error)
                }
            }
        )
        output = out
        out.videoEnabled = videoMode != .off
        Self.active = self

        guard let display = currentDisplay else {
            exit(ExitCode.noDisplay.rawValue)
        }
        let filter = SCContentFilter(display: display, excludingWindows: [])
        let config = makeAudioConfiguration()
        let stream = SCStream(filter: filter, configuration: config, delegate: out)
        do {
            try stream.addStreamOutput(out, type: .audio, sampleHandlerQueue: out.audioQueue)
            if options.micDevice != .none {
                try stream.addStreamOutput(out, type: .microphone, sampleHandlerQueue: out.micQueue)
            }
            try await stream.startCapture()
        } catch {
            let ns = error as NSError
            log.error("SCStream failed to start: \(ns.localizedDescription) (domain=\(ns.domain) code=\(ns.code))")
            try? wav?.close()
            exit(ExitCode.streamStartFailed.rawValue)
        }
        self.stream = stream
        // Re-anchor the clock on the moment audio can actually arrive.
        startedAt = Date()
        startUptime = ProcessInfo.processInfo.systemUptime

        await reconcileVideo()
        startTimers()
        emitTarget()
        var readyFields: [(String, String)] = [("wav", options.wav)]
        if let fd = options.framesDir { readyFields.append(("frames_dir", fd)) }
        readyFields.append(("fps", String(options.fps)))
        readyFields.append(("mic", options.micDevice == .none ? "off" : "on"))
        emitter.emit("READY", readyFields)
        log.info("capturing: display=\(display.displayID) video=\(videoModeLabel) mic=\(options.micDevice != .none)")
    }

    // Static handle so the non-Sendable delegate callback can reach us.
    nonisolated(unsafe) static var active: CaptureSession?

    private func decideInitialVideo(window: WindowDescriptor?) {
        guard options.wantsVideo else { videoMode = .off; return }
        if options.target == .display { videoMode = .display; return }
        if let w = window { videoMode = .window(w); return }
        if options.target == .window { videoMode = .off; return }
        switch options.noWindowPolicy {
        case .display: videoMode = .display
        case .audio: videoMode = .off
        case .ask:
            videoMode = .off
            awaitingChoice = true
        }
    }

    private var videoModeLabel: String {
        switch videoMode {
        case .off: return "off"
        case .display: return "display"
        case .window(let w): return "window(\(w.appLabel))"
        }
    }

    private func slideTarget() -> SlideTarget {
        switch videoMode {
        case .off: return SlideTarget(kind: "none")
        case .display: return SlideTarget(kind: "display")
        case .window(let w): return SlideTarget(kind: "window", app: w.appLabel, title: w.title)
        }
    }

    private func emitTarget(reason: String? = nil) {
        var fields: [(String, String)] = []
        switch videoMode {
        case .off:
            fields.append(("kind", "none"))
            if awaitingChoice { fields.append(("awaiting_choice", "true")) }
        case .display:
            fields.append(("kind", "display"))
            if let d = currentDisplay { fields.append(("display", String(d.displayID))) }
        case .window(let w):
            fields.append(("kind", "window"))
            fields.append(("app", w.appLabel))
            fields.append(("title", w.title ?? ""))
            fields.append(("window_id", String(w.windowID)))
        }
        if let r = reason { fields.append(("reason", r)) }
        emitter.emit("TARGET", fields)
        sampler?.updateTarget(slideTarget())
    }

    // MARK: Configuration

    /// Audio-only stream: system audio (display filter) + optional mic. No
    /// screen output is attached, so the frame size is just a placeholder.
    private func makeAudioConfiguration() -> SCStreamConfiguration {
        let c = SCStreamConfiguration()
        c.capturesAudio = true
        c.sampleRate = 48000
        c.channelCount = 2
        c.excludesCurrentProcessAudio = true
        switch options.micDevice {
        case .none:
            c.captureMicrophone = false
        case .systemDefault:
            c.captureMicrophone = true
        case .id(let uid):
            c.captureMicrophone = true
            c.microphoneCaptureDeviceID = uid
        }
        c.width = 64
        c.height = 36
        c.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        c.queueDepth = 1
        c.showsCursor = false
        return c
    }

    /// Video stream: frames only, output size = source size in pixels with the
    /// long edge capped at `FrameSampler.maxLongEdge`.
    private func makeVideoConfiguration(sourceSize: CGSize, scale: CGFloat) -> SCStreamConfiguration {
        let c = SCStreamConfiguration()
        c.capturesAudio = false
        c.captureMicrophone = false
        c.minimumFrameInterval = CMTime(value: 1, timescale: CMTimeScale(options.fps))
        c.pixelFormat = kCVPixelFormatType_32BGRA
        c.queueDepth = 3
        c.showsCursor = false
        var pw = max(1, sourceSize.width) * scale, ph = max(1, sourceSize.height) * scale
        let longEdge = max(pw, ph)
        if longEdge > CGFloat(FrameSampler.maxLongEdge) {
            let s = CGFloat(FrameSampler.maxLongEdge) / longEdge
            pw *= s; ph *= s
        }
        c.width = max(2, Int(pw.rounded()) & ~1)
        c.height = max(2, Int(ph.rounded()) & ~1)
        return c
    }

    private func videoDisplay(for mode: VideoMode) -> SCDisplay? {
        switch mode {
        case .window(let w): return ShareableContent.display(for: w, in: displays)
        default: return ShareableContent.display(for: nil, in: displays)
        }
    }

    /// Make the video stream match `videoMode`: tear down / rebuild when the
    /// target kind or window changes, just resize when the same window moved.
    private func reconcileVideo() async {
        guard options.wantsVideo, let out = output else { return }
        defer { out.videoEnabled = videoMode != .off && videoStream != nil }

        if videoMode == .off {
            await stopVideoStream()
            return
        }

        // Same target already streaming → maybe resize only.
        if let vs = videoStream {
            switch (videoStreamMode, videoMode) {
            case (.display, .display):
                return
            case (.window(let a), .window(let b)) where a.windowID == b.windowID:
                if a.frame.size != b.frame.size, let d = videoDisplay(for: videoMode) {
                    do {
                        try await vs.updateConfiguration(makeVideoConfiguration(
                            sourceSize: b.frame.size, scale: ShareableContent.pixelScale(of: d)))
                    } catch {
                        log.warn("video updateConfiguration failed: \(error.localizedDescription)")
                    }
                    videoStreamMode = videoMode
                }
                return
            default:
                await stopVideoStream()
            }
        }

        // Build a new one.
        guard let display = videoDisplay(for: videoMode) else { return }
        let scale = ShareableContent.pixelScale(of: display)
        let filter: SCContentFilter
        let sourceSize: CGSize
        switch videoMode {
        case .window(let w):
            var sc = lastShareable?.scWindows[w.windowID]
            if sc == nil, let fresh = try? await ShareableContent.fetch() {
                lastShareable = fresh
                displays = fresh.displays
                sc = fresh.scWindows[w.windowID]
            }
            guard let scWindow = sc else {
                log.warn("video: window \(w.windowID) vanished before capture could start")
                return
            }
            filter = SCContentFilter(desktopIndependentWindow: scWindow)
            sourceSize = w.frame.size
        case .display:
            filter = SCContentFilter(display: display, excludingWindows: [])
            sourceSize = CGSize(width: display.width, height: display.height)
        case .off:
            return
        }
        let delegate = VideoStreamDelegate { [weak self] error in
            Task { @MainActor in self?.videoStreamDidStop(error) }
        }
        let vs = SCStream(filter: filter, configuration: makeVideoConfiguration(sourceSize: sourceSize, scale: scale), delegate: delegate)
        do {
            try vs.addStreamOutput(out, type: .screen, sampleHandlerQueue: out.videoQueue)
            try await vs.startCapture()
        } catch {
            let ns = error as NSError
            log.warn("video stream failed to start: \(ns.localizedDescription) (domain=\(ns.domain) code=\(ns.code))")
            return
        }
        videoStream = vs
        videoDelegate = delegate
        videoStreamMode = videoMode
        log.info("video stream: \(videoModeLabel)")
    }

    private func stopVideoStream() async {
        guard let vs = videoStream else { return }
        videoStream = nil
        videoDelegate = nil
        videoStreamMode = .off
        struct StreamBox: @unchecked Sendable { let stream: SCStream }
        let box = StreamBox(stream: vs)
        _ = await withTaskGroup(of: Bool.self) { group -> Bool in
            group.addTask {
                do { try await box.stream.stopCapture() } catch {}
                return true
            }
            group.addTask {
                try? await Task.sleep(for: .seconds(Self.stopWatchdog))
                return false
            }
            let first = await group.next() ?? false
            group.cancelAll()
            return first
        }
    }

    func videoStreamDidStop(_ error: Error?) {
        guard !stopping, videoStream != nil else { return }
        // Window closed or display went away: drop the stream; the next
        // resolve tick re-targets per policy and rebuilds.
        log.warn("video stream stopped: \(error?.localizedDescription ?? "unknown"); re-resolving")
        videoStream = nil
        videoDelegate = nil
        videoStreamMode = .off
        output?.videoEnabled = false
        Task { @MainActor in await self.resolveTick() }
    }

    // MARK: Timers

    private func startTimers() {
        let drain = DispatchSource.makeTimerSource(queue: mixerQueue)
        drain.schedule(deadline: .now() + Self.drainInterval, repeating: Self.drainInterval, leeway: .milliseconds(10))
        let mixer = self.mixer
        let startUptime = self.startUptime
        let wav = self.wav
        let log = self.log
        drain.setEventHandler { @Sendable in
            let elapsed = ProcessInfo.processInfo.systemUptime - startUptime
            let samples = mixer.drain(elapsedSeconds: elapsed)
            do {
                try wav?.append(samples)
            } catch {
                log.error("\(error)")
                Task { @MainActor in CaptureSession.active?.wavWriteFailed() }
            }
        }
        drain.resume()
        drainTimer = drain

        if options.wantsVideo && options.target != .display {
            let t = DispatchSource.makeTimerSource(queue: .main)
            t.schedule(deadline: .now() + Self.resolveInterval, repeating: Self.resolveInterval, leeway: .milliseconds(250))
            t.setEventHandler { @Sendable in Task { @MainActor in await CaptureSession.active?.resolveTick() } }
            t.resume()
            resolveTimer = t
        }

        if options.controlFile != nil, options.wantsVideo {
            let c = DispatchSource.makeTimerSource(queue: .main)
            c.schedule(deadline: .now() + 1, repeating: 1, leeway: .milliseconds(200))
            c.setEventHandler { @Sendable in Task { @MainActor in await CaptureSession.active?.controlTick() } }
            c.resume()
            controlTimer = c
        }

        let m = DispatchSource.makeTimerSource(queue: .main)
        m.schedule(deadline: .now() + .seconds(options.maxDurationS))
        m.setEventHandler { @Sendable in Task { @MainActor in await CaptureSession.active?.stop(reason: "max_duration") } }
        m.resume()
        maxDurationTimer = m
    }

    private var resolving = false

    func resolveTick() async {
        guard !stopping, !resolving, options.wantsVideo, options.target != .display else { return }
        resolving = true
        defer { resolving = false }
        let shareable: Shareable
        do {
            shareable = try await ShareableContent.fetch()
        } catch {
            log.debug("re-resolve: SCShareableContent failed: \(error.localizedDescription)")
            return
        }
        guard !stopping else { return }
        displays = shareable.displays
        lastShareable = shareable
        writeWindowCatalog(shareable.windows)

        if let pinned = pinnedWindowID {
            // User picked a window: follow it (moves/resizes), and only fall
            // back when it is gone. Never auto-switch away from it.
            if let w = shareable.windows.first(where: { $0.windowID == pinned }) {
                if case .window(let cur) = videoMode, cur.frame == w.frame, cur.title == w.title, videoStream != nil { return }
                videoMode = .window(w)
                await reconcileVideo()
                return
            }
            pinnedWindowID = nil
            fallbackAfterWindowGone()
            await reconcileVideo()
            emitTarget(reason: "window_gone")
            return
        }

        let found = TargetResolver.resolve(shareable.windows)

        switch (videoMode, found) {
        case (.window(let cur), .some(let w)):
            if cur.windowID != w.windowID {
                videoMode = .window(w)
                await reconcileVideo()
                emitTarget(reason: "window_changed")
            } else if cur.frame != w.frame || videoStream == nil {
                videoMode = .window(w)
                await reconcileVideo()
            }
        case (.window, .none):
            fallbackAfterWindowGone()
            await reconcileVideo()
            emitTarget(reason: "window_gone")
        case (.off, .some(let w)), (.display, .some(let w)):
            guard !declinedVideo else { return }
            videoMode = .window(w)
            awaitingChoice = false
            await reconcileVideo()
            emitTarget(reason: "window_found")
        case (.display, .none):
            if videoStream == nil { await reconcileVideo() }  // rebuild after an unexpected stop
        case (.off, .none):
            break
        }
    }

    private func fallbackAfterWindowGone() {
        if declinedVideo || options.target == .window || options.noWindowPolicy == .audio {
            videoMode = .off
            return
        }
        if userChoseDisplay || options.noWindowPolicy == .display {
            videoMode = .display
            return
        }
        // ask
        videoMode = .off
        awaitingChoice = true
    }

    // MARK: Control file + window catalog

    private func writeWindowCatalog(_ windows: [WindowDescriptor]) {
        guard let framesDir = options.framesDir else { return }
        let entries = WindowCatalog.entries(from: windows, excludingBundleIDs: ["tech.codeship.ghostbrain"])
        let fp = WindowCatalog.fingerprint(entries)
        guard fp != lastCatalogFingerprint else { return }
        lastCatalogFingerprint = fp
        let url = URL(fileURLWithPath: framesDir).appendingPathComponent("windows.json")
        let tmp = url.appendingPathExtension("tmp")
        do {
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try WindowCatalog.encode(entries).write(to: tmp, options: .atomic)
            _ = try FileManager.default.replaceItemAt(url, withItemAt: tmp)
        } catch {
            log.warn("could not write windows.json: \(error.localizedDescription)")
        }
    }

    func controlTick() async {
        guard !stopping, let path = options.controlFile else { return }
        let url = URL(fileURLWithPath: path)
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: url.path),
              let mtime = attrs[.modificationDate] as? Date else { return }
        guard mtime != controlMTime else { return }
        controlMTime = mtime
        guard let data = try? Data(contentsOf: url), !data.isEmpty else { return }
        guard let cmd = ControlCommand.parse(data) else {
            log.warn("control file: unrecognised command \(String(decoding: data.prefix(120), as: UTF8.self))")
            return
        }
        await applyControl(cmd)
    }

    func applyControl(_ cmd: ControlCommand) async {
        guard options.wantsVideo else { log.info("control ignored: no --frames-dir"); return }
        switch cmd {
        case .display:
            pinnedWindowID = nil
            userChoseDisplay = true
            declinedVideo = false
            awaitingChoice = false
            videoMode = .display
            await reconcileVideo()
            emitTarget(reason: "user_choice")
            log.info("control: full-display video enabled")
        case .audio:
            pinnedWindowID = nil
            declinedVideo = true
            userChoseDisplay = false
            awaitingChoice = false
            videoMode = .off
            await reconcileVideo()
            emitTarget(reason: "user_choice")
            log.info("control: audio only, no further prompts")
        case .window(let id):
            let shareable: Shareable
            do { shareable = try await ShareableContent.fetch() } catch {
                log.warn("control: SCShareableContent failed: \(error.localizedDescription)")
                return
            }
            displays = shareable.displays
            lastShareable = shareable
            guard let w = shareable.windows.first(where: { $0.windowID == id }) else {
                log.warn("control: window \(id) not on screen; ignoring")
                return
            }
            pinnedWindowID = id
            declinedVideo = false
            userChoseDisplay = false
            awaitingChoice = false
            videoMode = .window(w)
            await reconcileVideo()
            emitTarget(reason: "user_choice")
            log.info("control: pinned window \(id) (\(w.appLabel) \"\(w.title ?? "")\")")
        }
    }

    // MARK: Signals

    private func installSignalHandlers() {
        for sig in [SIGINT, SIGTERM, SIGUSR1, SIGUSR2] {
            signal(sig, SIG_IGN)
            let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
            src.setEventHandler { @Sendable in
                Task { @MainActor in await CaptureSession.active?.handleSignal(sig) }
            }
            src.resume()
            signalSources.append(src)
        }
    }

    func handleSignal(_ sig: Int32) async {
        switch sig {
        case SIGINT, SIGTERM:
            if stopping {
                log.warn("second stop signal; exiting immediately")
                exit(exitCodeOnStop.rawValue)
            }
            await stop(reason: sig == SIGINT ? "sigint" : "sigterm")
        case SIGUSR1:
            guard !stopping else { return }
            guard videoMode == .off else { log.info("SIGUSR1 ignored: video already \(videoModeLabel)"); return }
            await applyControl(.display)
        case SIGUSR2:
            guard !stopping else { return }
            await applyControl(.audio)
        default:
            break
        }
    }

    // MARK: Stop

    func wavWriteFailed() {
        guard !wavFailed else { return }
        wavFailed = true
        exitCodeOnStop = .outputIO
        Task { @MainActor in await self.stop(reason: "wav_io_error") }
    }

    func streamDidStop(_ error: Error?) {
        guard !stopping else { return }
        log.error("stream stopped unexpectedly: \(error?.localizedDescription ?? "unknown")")
        exitCodeOnStop = .streamStopped
        Task { @MainActor in await self.stop(reason: "stream_stopped", skipStopCapture: true) }
    }

    func stop(reason: String, skipStopCapture: Bool = false) async {
        guard !stopping else { return }
        stopping = true
        emitter.emit("STOPPING", [("reason", reason)])
        resolveTimer?.cancel()
        controlTimer?.cancel()
        maxDurationTimer?.cancel()

        await stopVideoStream()
        if let stream, !skipStopCapture {
            struct StreamBox: @unchecked Sendable { let stream: SCStream }
            let box = StreamBox(stream: stream)
            let stopped = await withTaskGroup(of: Bool.self) { group -> Bool in
                group.addTask {
                    do { try await box.stream.stopCapture() } catch {
                        // Already stopped / never started is fine at this point.
                    }
                    return true
                }
                group.addTask {
                    try? await Task.sleep(for: .seconds(Self.stopWatchdog))
                    return false
                }
                let first = await group.next() ?? false
                group.cancelAll()
                return first
            }
            if !stopped { log.warn("stopCapture did not return within \(Self.stopWatchdog)s; finalising anyway") }
        }

        // Final drain + WAV close on the mixer queue so it serialises with the timer.
        drainTimer?.cancel()
        let mixer = self.mixer
        let wav = self.wav
        let log = self.log
        var wavBytes: UInt64 = 0
        mixerQueue.sync {
            let tail = mixer.drainRemaining()
            do {
                try wav?.append(tail)
                try wav?.close()
            } catch {
                log.error("\(error)")
            }
            wavBytes = wav?.fileBytes ?? 0
        }
        if wavFailed, exitCodeOnStop == .ok { exitCodeOnStop = .outputIO }

        sampler?.finish(ocrTimeout: Self.ocrFinishTimeout)

        let s: (audio: Int, mic: Int, frames: Int) = output?.stats ?? (0, 0, 0)
        log.info("buffers: system=\(s.audio) mic=\(s.mic) frames=\(s.frames) written=\(mixer.written) samples")
        emitter.emit("DONE", [
            ("duration_ms", String(elapsedMs)),
            ("wav_bytes", String(wavBytes)),
            ("slides", String(sampler?.slideCount ?? 0)),
        ])
        exit(exitCodeOnStop.rawValue)
    }
}


/// Delegate for the video-only stream. Its stopping is not fatal (a pinned
/// window was closed, a display disconnected) — the session re-resolves.
@available(macOS 15, *)
final class VideoStreamDelegate: NSObject, SCStreamDelegate, @unchecked Sendable {
    private let onStop: @Sendable (Error?) -> Void
    init(onStop: @escaping @Sendable (Error?) -> Void) { self.onStop = onStop }
    func stream(_ stream: SCStream, didStopWithError error: Error) { onStop(error) }
}
