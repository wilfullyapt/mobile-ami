import numpy as np
import openwakeword

from core.model_registry import ModelSpec


class WakeDetector:
    """
    Wake-word detection wrapper around OpenWakeWord.
    Wakeword name is driven by ModelSpec.name.
    """

    def __init__(self, spec: ModelSpec):
        openwakeword.utils.download_models()  # no-op if already cached
        self._model = openwakeword.Model(wakeword=spec.name)

    def detect(self, audio_chunk: np.ndarray) -> bool:
        return self._model.predict(audio_chunk) > 0.5
