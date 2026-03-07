import numpy as np
import webrtcvad

from core.model_registry import ModelSpec


class VAD:
    """
    Voice Activity Detection wrapper around WebRTC VAD.
    Sensitivity level is driven by ModelSpec.version (0 = least aggressive, 3 = most).
    """

    def __init__(self, spec: ModelSpec):
        sensitivity = int(spec.version) if spec.version.isdigit() else 2
        self._vad = webrtcvad.Vad(sensitivity)

    def is_speech(self, audio: np.ndarray) -> bool:
        return self._vad.is_speech(audio.tobytes(), 16000)
