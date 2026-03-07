import openwakeword
import numpy as np

class WakeDetector:
    def __init__(self):
        openwakeword.utils.download_models()  # first run
        self.model = openwakeword.Model(wakeword="hey assistant")

    def detect(self, audio_chunk: np.ndarray):
        return self.model.predict(audio_chunk) > 0.5
