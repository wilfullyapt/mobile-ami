import numpy as np
import openwakeword

from core.model_registry import ModelSpec


class WakeDetector:
    """
    Wake-word detection wrapper around OpenWakeWord.
    Wakeword name is driven by ModelSpec.name.
    """

    def __init__(self, spec: ModelSpec):
        # spec.path is ~/.amini/models/wake/ — download models there, not library cache
        openwakeword.utils.download_models(target_directory=spec.path or None)
        self._model = openwakeword.Model(wakeword=spec.name)

    def detect(self, audio_chunk: np.ndarray) -> bool:
        return self._model.predict(audio_chunk) > 0.5
