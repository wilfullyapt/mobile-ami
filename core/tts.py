import subprocess

class TTS:
    def speak(self, text: str):
        subprocess.run(
            ["piper", "--model", "/opt/voice-assistant/piper-voices/en_US-lessac-medium.onnx", "--output_file", "/tmp/resp.wav"],
            input=text.encode(),
        )
        subprocess.run(["aplay", "/tmp/resp.wav"])
