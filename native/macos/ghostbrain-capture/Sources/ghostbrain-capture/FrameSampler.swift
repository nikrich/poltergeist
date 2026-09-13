import CoreGraphics
import CoreVideo
import Foundation
import GhostbrainCaptureCore
import ImageIO
import UniformTypeIdentifiers
import VideoToolbox

/// Turns delivered BGRA frames into kept slides: thumbnail → SlideDetector →
/// JPEG on disk → OCR → slides.jsonl → `SLIDE` stdout line. All state lives on
/// `queue`; SCStream calls `process` from its own handler queue (one at a time).
final class FrameSampler: @unchecked Sendable {
    static let maxLongEdge = 1600
    static let jpegQuality: CGFloat = 0.7
    static let manifestInterval: TimeInterval = 5

    let framesDir: URL
    let log: Logger
    let emitter: StdoutEmitter
    private let queue = DispatchQueue(label: "ghostbrain-capture.slides", qos: .utility)
    private let ocr: OCRQueue
    private var detector: SlideDetector
    private let slideLog: SlideLog
    private var manifestTimer: DispatchSourceTimer?
    private let durationProvider: @Sendable () -> Int
    private var finished = false
    private let lock = NSLock()
    private var _slideCount = 0

    var slideCount: Int {
        lock.lock(); defer { lock.unlock() }
        return _slideCount
    }

    init(framesDir: URL, wavName: String, startedAt: Date, options: RunOptions, target: SlideTarget,
         log: Logger, emitter: StdoutEmitter, durationProvider: @escaping @Sendable () -> Int) throws {
        self.framesDir = framesDir
        self.log = log
        self.emitter = emitter
        self.durationProvider = durationProvider
        ocr = OCRQueue(languages: options.ocrLangs)
        detector = SlideDetector(changeThreshold: options.slideThreshold, settleFrames: 2, minIntervalMs: 3000, maxSlides: options.maxFrames)
        slideLog = try SlideLog(directory: framesDir, wavName: wavName, startedAt: startedAt, fps: options.fps, target: target)

        let t = DispatchSource.makeTimerSource(queue: queue)
        t.schedule(deadline: .now() + Self.manifestInterval, repeating: Self.manifestInterval)
        t.setEventHandler { @Sendable [weak self] in self?.writeManifest() }
        t.resume()
        manifestTimer = t
    }

    func updateTarget(_ target: SlideTarget) {
        queue.async { [self] in slideLog.target = target }
    }

    /// Called on the SCStream video handler queue with a locked-free pixel buffer.
    func process(pixelBuffer: CVPixelBuffer, offsetMs: Int) {
        guard CVPixelBufferGetPixelFormatType(pixelBuffer) == kCVPixelFormatType_32BGRA else { return }
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        guard let base = CVPixelBufferGetBaseAddress(pixelBuffer) else {
            CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly)
            return
        }
        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        let thumb = Thumbnail.fromBGRA(UnsafeRawPointer(base), width: width, height: height, bytesPerRow: CVPixelBufferGetBytesPerRow(pixelBuffer))
        CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly)

        let decision = queue.sync { detector.observe(thumb, offsetMs: offsetMs) }
        switch decision {
        case .skip(let reason):
            log.debug("frame @\(offsetMs)ms skipped (\(reason))")
        case .keep(let diff):
            var cg: CGImage?
            VTCreateCGImageFromCVPixelBuffer(pixelBuffer, options: nil, imageOut: &cg)
            guard let image = cg else {
                log.warn("frame @\(offsetMs)ms: could not create CGImage")
                return
            }
            keep(image: image, offsetMs: offsetMs, diff: diff)
        }
    }

    private func keep(image original: CGImage, offsetMs: Int, diff: Double) {
        let index = queue.sync { detector.keptCount } // already incremented by observe
        let image = Self.downscale(original, maxLongEdge: Self.maxLongEdge) ?? original
        let name = SlideLog.imageName(index: index, offsetMs: offsetMs)
        let url = framesDir.appendingPathComponent(name)
        guard let data = Self.jpeg(image, quality: Self.jpegQuality) else {
            log.warn("slide \(index): JPEG encode failed")
            return
        }
        do {
            try data.write(to: url, options: .atomic)
        } catch {
            log.error("slide \(index): write \(url.path) failed: \(error.localizedDescription)")
            return
        }
        log.info("slide \(index) kept @\(offsetMs)ms diff=\(String(format: "%.3f", diff)) \(image.width)x\(image.height)")
        let width = image.width, height = image.height
        ocr.enqueue(ImageBox(image: image)) { [self] result in
            queue.async { [self] in
                let record: SlideRecord
                switch result {
                case .text(let text, let confidence):
                    record = SlideRecord(index: index, offsetMs: offsetMs, image: name, width: width, height: height,
                                         text: text, ocr: "accurate", confidence: confidence, diff: diff)
                case .skipped:
                    log.warn("slide \(index): OCR backlog full, skipped")
                    record = SlideRecord(index: index, offsetMs: offsetMs, image: name, width: width, height: height,
                                         text: "", ocr: "skipped", confidence: 0, diff: diff)
                case .failed(let why):
                    log.warn("slide \(index): OCR failed: \(why)")
                    record = SlideRecord(index: index, offsetMs: offsetMs, image: name, width: width, height: height,
                                         text: "", ocr: "failed", confidence: 0, diff: diff)
                }
                do {
                    try slideLog.append(record)
                } catch {
                    log.error("\(error)")
                }
                lock.lock(); _slideCount += 1; lock.unlock()
                emitter.emit("SLIDE", [
                    ("index", String(index)),
                    ("offset_ms", String(offsetMs)),
                    ("image", name),
                    ("chars", String(record.text.count)),
                ])
            }
        }
    }

    private func writeManifest() {
        guard !finished else { return }
        do {
            try slideLog.writeManifest(durationMs: durationProvider())
        } catch {
            log.warn("\(error)")
        }
    }

    /// Stop the timer, wait for OCR (bounded), write the final manifest.
    func finish(ocrTimeout: TimeInterval) {
        manifestTimer?.cancel()
        manifestTimer = nil
        if !ocr.drain(timeout: ocrTimeout) {
            log.warn("OCR still running after \(ocrTimeout)s; finishing without it")
        }
        queue.sync {
            do {
                try slideLog.writeManifest(durationMs: durationProvider())
            } catch {
                log.error("\(error)")
            }
            finished = true
            slideLog.close()
        }
    }

    static func downscale(_ image: CGImage, maxLongEdge: Int) -> CGImage? {
        let w = image.width, h = image.height
        let longEdge = max(w, h)
        guard longEdge > maxLongEdge else { return image }
        let scale = CGFloat(maxLongEdge) / CGFloat(longEdge)
        let nw = max(1, Int((CGFloat(w) * scale).rounded())), nh = max(1, Int((CGFloat(h) * scale).rounded()))
        guard let ctx = CGContext(data: nil, width: nw, height: nh, bitsPerComponent: 8, bytesPerRow: 0,
                                  space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue)
        else { return nil }
        ctx.interpolationQuality = .high
        ctx.draw(image, in: CGRect(x: 0, y: 0, width: nw, height: nh))
        return ctx.makeImage()
    }

    static func jpeg(_ image: CGImage, quality: CGFloat) -> Data? {
        let data = NSMutableData()
        guard let dest = CGImageDestinationCreateWithData(data, UTType.jpeg.identifier as CFString, 1, nil) else { return nil }
        CGImageDestinationAddImage(dest, image, [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
        guard CGImageDestinationFinalize(dest) else { return nil }
        return data as Data
    }
}
