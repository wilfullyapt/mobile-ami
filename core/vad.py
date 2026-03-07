import numpy as np
import webrtcvad

class VAD:
    def __init__(self):
        self.vad = webrtcvad.Vad(2)

    def is_speech(self, audio: np.ndarray):
        return self.vad.is_speech(audio.tobytes(), 16000)
