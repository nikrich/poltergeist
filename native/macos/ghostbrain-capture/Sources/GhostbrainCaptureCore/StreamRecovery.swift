import Foundation

/// Retry schedule for the audio stream after macOS stops it (display
/// unplugged, a meeting app starts screen sharing, "Stream was stopped by the
/// system"). The WAV keeps growing on the wall clock meanwhile, so an outage
/// becomes silence instead of ending the recording. Recovery gives up only
/// after `maxDowntime` of continuous failure.
public struct StreamRecovery: Sendable {
    public static let defaultDelays: [TimeInterval] = [0.5, 1, 2, 4, 5]

    public let delays: [TimeInterval]
    public let maxDowntime: TimeInterval
    public private(set) var restarts = 0
    private var attempt = 0
    private var downSince: TimeInterval?

    public init(delays: [TimeInterval] = StreamRecovery.defaultDelays, maxDowntime: TimeInterval = 120) {
        precondition(!delays.isEmpty)
        self.delays = delays
        self.maxDowntime = maxDowntime
    }

    /// Delay before the next restart attempt, or nil once the stream has been
    /// down for longer than `maxDowntime` (the caller then stops for good).
    public mutating func nextDelay(now: TimeInterval) -> TimeInterval? {
        let since = downSince ?? now
        downSince = since
        guard now - since < maxDowntime else { return nil }
        let d = delays[min(attempt, delays.count - 1)]
        attempt += 1
        return d
    }

    /// The stream is running again: the next outage starts a fresh schedule.
    public mutating func recovered() {
        restarts += 1
        attempt = 0
        downSince = nil
    }
}
