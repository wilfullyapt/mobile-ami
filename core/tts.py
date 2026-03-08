import subprocess

from core.model_registry import ModelSpec


class TTS:
    """
    Text-to-speech wrapper around the Piper binary.
    Model path is driven by ModelSpec so it can be swapped via config.
    """

    def __init__(self, spec: ModelSpec):
        self._model_path = spec.path  # resolved to ~/.amini/models/tts/<file> by AmiPaths

    def speak(self, text: str):
        subprocess.run(
            ["piper", "--model", self._model_path, "--output_file", "/tmp/resp.wav"],
            input=text.encode(),
            check=False,
        )
        subprocess.run(["aplay", "/tmp/resp.wav"], check=False)
