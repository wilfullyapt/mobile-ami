import subprocess

from core.models.registry import ModelSpec


class TTS:
    """
    Text-to-speech wrapper around the Piper binary.
    Model path is driven by ModelSpec so it can be swapped via config.
    alsa_device routes aplay to a specific ALSA card (e.g. "seeed-2mic-voicecard");
    None uses the system default set by the seeed-voicecard driver install.
    """

    def __init__(self, spec: ModelSpec, alsa_device: str | None = None):
        self._model_path = spec.path  # resolved to ~/.amini/models/tts/<file> by AmiPaths
        self._alsa_device = alsa_device

    def speak(self, text: str):
        subprocess.run(
            ["piper", "--model", self._model_path, "--output_file", "/tmp/resp.wav"],
            input=text.encode(),
            check=False,
        )
        cmd = ["aplay"]
        if self._alsa_device:
            cmd.extend(["-D", self._alsa_device])
        cmd.append("/tmp/resp.wav")
        subprocess.run(cmd, check=False)
