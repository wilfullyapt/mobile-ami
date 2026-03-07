from faster_whisper import WhisperModel

class STT:
    def __init__(self):
        self.model = WhisperModel("tiny", device="cpu", compute_type="int8")

    def transcribe(self, audio):
        segments, _ = self.model.transcribe(audio, beam_size=5)
        return " ".join(seg.text for seg in segments)

    # NOTE: For full Hailo speed, replace with Hailo SDK .hef inference after compiling Whisper
