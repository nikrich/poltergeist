"""Audio capture + local transcription. Records meetings (system audio +
mic — natively via ScreenCaptureKit on macOS 15+, via ffmpeg + BlackHole as
the macOS fallback, via WASAPI loopback on Windows), transcribes with
whisper.cpp, links transcripts (and, natively, slide key-frames) to the
matching calendar event."""
