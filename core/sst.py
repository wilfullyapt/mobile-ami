import numpy as np
from faster_whisper import WhisperModel

from core.model_registry import ModelSpec, Backend, QuantType


class STT:
    """
    Speech-to-text wrapper around faster-whisper.
    Model size, device, and quantization are driven by ModelSpec.
    """

    def __init__(self, spec: ModelSpec):
        device = "cpu" if spec.backend == Backend.CPU else "cuda"
        compute = spec.quant.value if spec.quant != QuantType.NONE else "float32"
        self._model = WhisperModel(
            spec.version,
            device=device,
            compute_type=compute,
            download_root=spec.path or None,  # cache to ~/.amini/models/stt when set
        )

    def transcribe(self, audio: np.ndarray, beam_size: int = 5) -> str:
        segments, _ = self._model.transcribe(audio, beam_size=beam_size)
        return " ".join(seg.text for seg in segments).strip()

    # NOTE: For full Hailo speed, replace with Hailo SDK .hef inference after compiling Whisper.
