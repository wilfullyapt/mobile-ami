import subprocess

class TTS:
    def speak(self, text: str):
        subprocess.run(["piper", "--model", "en_US-lessac-medium", "--output_file", "/tmp/resp.wav", text])
        subprocess.run(["aplay", "/tmp/resp.wav"])
