"""
HailoSTT — Speech-to-text wrapper using the Hailo-10H AI accelerator.

This is the activation stub for Hailo-accelerated Whisper inference.
It presents the same interface as core/sst.py (STT class) so the rest of
the codebase needs no changes when switching backends via config.yaml.

== Activation path ==

1. Export Whisper Tiny to ONNX:
       python -c "import whisper; m = whisper.load_model('tiny'); m.export('whisper_tiny.onnx')"
   Or use the official openai/whisper ONNX export script.

2. Convert ONNX → HEF using the Hailo Dataflow Compiler (DFC):
       hailomz compile whisper_tiny --hw-arch hailo10h --ckpt whisper_tiny.onnx

3. Place the resulting .hef file at:
       ~/.amini/models/hailo/whisper_tiny.hef

4. Update config.yaml:
       models:
         stt:
           name: tiny
           backend: hailo
           path: hailo/whisper_tiny.hef   # filename → ~/.amini/models/hailo/

5. Install the Hailo Python SDK (hailort) on the Pi:
       pip install hailort

The ModelOrchestrator will then route STT loads to HailoSTT automatically.

== Hailo slot note ==

The Hailo-10H has a single exclusive compute slot. If WAKE is also on Hailo,
ModelOrchestrator.swap() must release WAKE before loading STT and reclaim it
after transcription completes. This is the intended use of the existing
_hailo_slot_taken + swap() mechanism in model_orchestrator.py.
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)


class HailoSTT:
    """
    Hailo-10H accelerated Whisper STT wrapper.

    Interface mirrors core/sst.py::STT — expose .transcribe(audio) → str.
    """

    def __init__(self, spec):
        """
        Load the Whisper HEF model onto the Hailo device.

        spec.path is the absolute path to the .hef file (resolved by
        ModelRegistry/AmiPaths from config.yaml path: hailo/whisper_tiny.hef).
        """
        self._spec = spec
        self._runner = None
        self._loaded = False
        self._load(spec.path)

    def _load(self, hef_path: str) -> None:
        try:
            import hailo_platform as hp  # type: ignore[import]
            devices = hp.Device.scan()
            if not devices:
                raise RuntimeError("No Hailo device detected on this system.")
            self._device = hp.Device(devices[0])
            self._hef = hp.HEF(hef_path)
            self._runner = self._device.create_infer_model(self._hef)
            self._loaded = True
            logger.info("HailoSTT: loaded %s on %s", hef_path, devices[0])
        except ImportError:
            logger.error(
                "HailoSTT: hailo_platform not installed. "
                "Install with: pip install hailort"
            )
            raise
        except Exception as exc:
            logger.error("HailoSTT: failed to load %s — %s", hef_path, exc)
            raise

    def transcribe(self, audio: np.ndarray, language: str = "en") -> str:
        """
        Run Hailo-accelerated Whisper inference on a 16 kHz int16 audio array.

        Returns the transcribed text string.
        """
        if not self._loaded or self._runner is None:
            raise RuntimeError("HailoSTT is not loaded.")

        # Normalise int16 → float32 [-1, 1] if needed
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0

        # --- Hailo inference (implementation depends on HEF structure) ---
        # The exact input/output tensor names and shapes depend on how the
        # Whisper ONNX model was compiled. Placeholder below shows the pattern.
        #
        # with self._runner.configure() as configured:
        #     input_vstream_params = configured.get_input_vstream_params()
        #     output_vstream_params = configured.get_output_vstream_params()
        #     with hp.InferVStreams(configured, input_vstream_params, output_vstream_params) as vstreams:
        #         input_data = {input_vstream_params[0].name: audio[np.newaxis, :]}
        #         vstreams.send(input_data)
        #         raw = vstreams.recv()
        #     tokens = raw[output_vstream_params[0].name][0]
        #     text = self._decode_tokens(tokens)
        # return text

        raise NotImplementedError(
            "HailoSTT.transcribe() is a stub. "
            "Complete the hailo_platform inference loop once the .hef is available."
        )

    def close(self) -> None:
        """Release the Hailo device handle."""
        self._runner = None
        self._loaded = False
        logger.info("HailoSTT: closed")
