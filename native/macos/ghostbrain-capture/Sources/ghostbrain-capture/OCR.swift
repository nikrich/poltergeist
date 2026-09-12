import CoreGraphics
import Foundation
import Vision

/// Value wrapper so a CGImage can cross queue boundaries under Swift 6.
struct ImageBox: @unchecked Sendable {
    let image: CGImage
}

enum OCRResult: Sendable {
    case text(String, confidence: Double)
    case skipped
    case failed(String)

    var kind: String {
        switch self {
        case .text: return "accurate"
        case .skipped: return "skipped"
        case .failed: return "failed"
        }
    }
}

/// Serial Vision queue with a bounded backlog. When more than `maxPending`
/// frames are waiting the newest one is marked `skipped` instead of queued so
/// a slide flurry can never make the stop sequence wait on minutes of OCR.
final class OCRQueue: @unchecked Sendable {
    let maxPending: Int
    let languages: [String]
    private let queue = DispatchQueue(label: "ghostbrain-capture.ocr", qos: .utility)
    private let group = DispatchGroup()
    private let lock = NSLock()
    private var pending = 0

    init(languages: [String], maxPending: Int = 8) {
        self.languages = languages
        self.maxPending = maxPending
    }

    var pendingCount: Int {
        lock.lock(); defer { lock.unlock() }
        return pending
    }

    func enqueue(_ box: ImageBox, completion: @escaping @Sendable (OCRResult) -> Void) {
        lock.lock()
        if pending >= maxPending {
            lock.unlock()
            completion(.skipped)
            return
        }
        pending += 1
        lock.unlock()
        group.enter()
        queue.async { [self] in
            let result = Self.recognize(box.image, languages: languages)
            lock.lock(); pending -= 1; lock.unlock()
            completion(result)
            group.leave()
        }
    }

    /// Wait for in-flight work. Returns false on timeout.
    func drain(timeout: TimeInterval) -> Bool {
        group.wait(timeout: .now() + timeout) == .success
    }

    static func recognize(_ image: CGImage, languages: [String]) -> OCRResult {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = true
        request.recognitionLanguages = languages
        let handler = VNImageRequestHandler(cgImage: image, options: [:])
        do {
            try handler.perform([request])
        } catch {
            return .failed(error.localizedDescription)
        }
        let observations = request.results ?? []
        // Vision returns observations in reading order top-to-bottom already,
        // but sort by the box top (y is bottom-up) to be safe, then x.
        let sorted = observations.sorted { a, b in
            let ay = a.boundingBox.maxY, by = b.boundingBox.maxY
            if abs(ay - by) > 0.01 { return ay > by }
            return a.boundingBox.minX < b.boundingBox.minX
        }
        var lines: [String] = []
        var confidence: Double = 0
        for o in sorted {
            guard let top = o.topCandidates(1).first else { continue }
            lines.append(top.string)
            confidence += Double(top.confidence)
        }
        let avg = lines.isEmpty ? 0 : confidence / Double(lines.count)
        return .text(lines.joined(separator: "\n"), confidence: avg)
    }
}
