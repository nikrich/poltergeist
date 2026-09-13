import Foundation

/// Decides which delivered frames are "new slides".
///
/// Compares every frame against the *last kept* frame. A change must be
/// stable for `settleFrames` consecutive frames (so animations and A/B
/// oscillation never settle), at least `minIntervalMs` must have passed since
/// the previous kept slide, and no more than `maxSlides` are kept per session.
/// It is driven only by frames actually delivered — SCStream sends nothing
/// for static content, which simply means no new slide.
public struct SlideDetector: Sendable {
    public enum Decision: Equatable, Sendable {
        case keep(diff: Double)
        case skip(Reason)

        public enum Reason: Equatable, Sendable {
            case unchanged
            case settling
            case debounced
            case maxSlides
        }
    }

    public let changeThreshold: Double
    public let settleFrames: Int
    public let minIntervalMs: Int
    public let maxSlides: Int

    public private(set) var keptCount = 0
    public private(set) var lastKeptOffsetMs: Int?
    private var lastKept: Thumbnail?
    private var candidate: Thumbnail?
    private var candidateStable = 0

    public init(changeThreshold: Double = 0.04, settleFrames: Int = 2, minIntervalMs: Int = 3000, maxSlides: Int = 600) {
        self.changeThreshold = changeThreshold
        self.settleFrames = max(1, settleFrames)
        self.minIntervalMs = minIntervalMs
        self.maxSlides = maxSlides
    }

    public mutating func observe(_ frame: Thumbnail, offsetMs: Int) -> Decision {
        guard keptCount < maxSlides else { return .skip(.maxSlides) }

        let diffFromKept: Double
        if let kept = lastKept {
            diffFromKept = FrameDiff.meanAbsDiff(frame, kept)
            if diffFromKept < changeThreshold {
                candidate = nil
                candidateStable = 0
                return .skip(.unchanged)
            }
        } else {
            diffFromKept = 1.0
        }

        if let cand = candidate, FrameDiff.meanAbsDiff(frame, cand) < changeThreshold {
            candidateStable += 1
        } else {
            candidateStable = 1
        }
        candidate = frame // track the newest so slow fades still settle once still

        guard candidateStable >= settleFrames else { return .skip(.settling) }
        if let last = lastKeptOffsetMs, offsetMs - last < minIntervalMs {
            return .skip(.debounced)
        }

        lastKept = frame
        lastKeptOffsetMs = offsetMs
        keptCount += 1
        candidate = nil
        candidateStable = 0
        return .keep(diff: diffFromKept)
    }
}
