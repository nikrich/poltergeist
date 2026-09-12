import AVFoundation
import CoreMedia
import Foundation
import GhostbrainCaptureCore
import ScreenCaptureKit

/// SCStream sink. One serial handler queue per output type (given to
/// `addStreamOutput`). Sample buffers are converted to value types *here*, on
/// the handler queue, before anything crosses to the session (CMSampleBuffer
/// is not Sendable).
@available(macOS 15, *)
final class StreamOutput: NSObject, SCStreamOutput, SCStreamDelegate, @unchecked Sendable {
    let audioQueue = DispatchQueue(label: "ghostbrain-capture.audio", qos: .userInitiated)
    let micQueue = DispatchQueue(label: "ghostbrain-capture.mic", qos: .userInitiated)
    let videoQueue = DispatchQueue(label: "ghostbrain-capture.video", qos: .utility)

    private let mixer: Mixer
    private let log: Logger
    private let sampler: FrameSampler?
    private let offsetProvider: @Sendable () -> Int
    private let onStop: @Sendable (Error?) -> Void

    private var systemConverter: PCMConverter?
    private var micConverter: PCMConverter?
    private let videoLock = NSLock()
    private var _videoEnabled = false
    private var audioBuffers = 0
    private var micBuffers = 0
    private var frames = 0

    var videoEnabled: Bool {
        get { videoLock.lock(); defer { videoLock.unlock() }; return _videoEnabled }
        set { videoLock.lock(); _videoEnabled = newValue; videoLock.unlock() }
    }

    var stats: (audio: Int, mic: Int, frames: Int) {
        videoLock.lock(); defer { videoLock.unlock() }
        return (audioBuffers, micBuffers, frames)
    }

    init(mixer: Mixer, sampler: FrameSampler?, log: Logger,
         offsetProvider: @escaping @Sendable () -> Int, onStop: @escaping @Sendable (Error?) -> Void) {
        self.mixer = mixer
        self.sampler = sampler
        self.log = log
        self.offsetProvider = offsetProvider
        self.onStop = onStop
    }

    // MARK: SCStreamOutput

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard sampleBuffer.isValid else { return }
        switch type {
        case .audio:
            handleAudio(sampleBuffer, lane: .system)
        case .microphone:
            handleAudio(sampleBuffer, lane: .mic)
        case .screen:
            handleVideo(sampleBuffer)
        @unknown default:
            break
        }
    }

    private func handleAudio(_ sb: CMSampleBuffer, lane: Mixer.Lane) {
        guard let desc = CMSampleBufferGetFormatDescription(sb) else { return }
        let format = AVAudioFormat(cmAudioFormatDescription: desc)
        let converter: PCMConverter
        switch lane {
        case .system:
            if let c = systemConverter, c.inputFormat == format { converter = c }
            else {
                guard let c = PCMConverter(inputFormat: format) else { log.warn("system audio: unsupported format \(format)"); return }
                log.debug("system audio format: \(format)")
                systemConverter = c; converter = c
            }
        case .mic:
            if let c = micConverter, c.inputFormat == format { converter = c }
            else {
                guard let c = PCMConverter(inputFormat: format) else { log.warn("mic audio: unsupported format \(format)"); return }
                log.debug("mic audio format: \(format)")
                micConverter = c; converter = c
            }
        }
        let frameCount = CMSampleBufferGetNumSamples(sb)
        guard frameCount > 0 else { return }
        guard let pcm = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frameCount)) else { return }
        pcm.frameLength = AVAudioFrameCount(frameCount)
        let status = CMSampleBufferCopyPCMDataIntoAudioBufferList(sb, at: 0, frameCount: Int32(frameCount), into: pcm.mutableAudioBufferList)
        guard status == noErr else {
            log.debug("\(lane.name): CMSampleBufferCopyPCMDataIntoAudioBufferList failed (\(status))")
            return
        }
        let samples = converter.convert(pcm)
        mixer.push(samples, lane: lane)
        videoLock.lock()
        if lane == .system { audioBuffers += 1 } else { micBuffers += 1 }
        videoLock.unlock()
    }

    private func handleVideo(_ sb: CMSampleBuffer) {
        guard let sampler, videoEnabled else { return }
        guard let attachments = CMSampleBufferGetSampleAttachmentsArray(sb, createIfNecessary: false) as? [[String: Any]],
              let statusRaw = attachments.first?[SCStreamFrameInfo.status.rawValue] as? Int,
              let status = SCFrameStatus(rawValue: statusRaw), status == .complete
        else { return }
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sb) else { return }
        videoLock.lock(); frames += 1; videoLock.unlock()
        sampler.process(pixelBuffer: pixelBuffer, offsetMs: offsetProvider())
    }

    // MARK: SCStreamDelegate

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        onStop(error)
    }
}
