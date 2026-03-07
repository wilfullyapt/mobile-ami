import sounddevice as sd
import numpy as np

class AudioManager:
    def get_chunk(self):
        chunk = sd.rec(1024, samplerate=16000, channels=1, dtype='int16')
        sd.wait()
        return chunk.flatten()

    def record_until_silence(self, vad):
        frames = []
        with sd.InputStream(samplerate=16000, channels=1, dtype='int16') as stream:
            while True:
                data = stream.read(1024)[0]
                if vad.is_speech(data):
                    frames.append(data)
                elif len(frames) > 10:
                    break
        if not frames:
            return np.array([], dtype='int16')
        return np.concatenate(frames)

    def play(self, audio):
        sd.play(audio, 22050)
