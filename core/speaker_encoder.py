"""
Speaker encoder wrapper using Resemblyzer (GE2E model).

Resemblyzer produces a 256-dimensional d-vector embedding for any audio clip
using the Generalized End-to-End (GE2E) loss speaker-verification model.
Embeddings from the same voice cluster tightly in the embedding space;
different speakers diverge. Cosine similarity is used for comparison.

The pretrained model weights (~17 MB) download automatically on first use
to the path specified by the ModelSpec (default: ~/.amini/models/speaker/).
"""

import logging
from typing import Optional

import numpy as np

from core.model_registry import ModelSpec

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 16000  # Resemblyzer expects 16 kHz mono audio


class SpeakerEncoder:
    """
    Thin wrapper around Resemblyzer's VoiceEncoder.

    Usage::

        encoder = SpeakerEncoder(spec)
        embedding = encoder.embed(audio_np)        # shape (256,), float32
        score = encoder.similarity(emb_a, emb_b)   # cosine similarity 0–1
    """

    def __init__(self, spec: ModelSpec):
        # Import here so missing library doesn't break module load on devices
        # that haven't installed resemblyzer yet.
        from resemblyzer import VoiceEncoder  # type: ignore[import]
        logger.info("Loading SpeakerEncoder (Resemblyzer GE2E) from %s", spec.path)
        self._encoder = VoiceEncoder(device="cpu")
        self._spec = spec

    def embed(self, audio: np.ndarray) -> np.ndarray:
        """
        Produce a 256-dim L2-normalised speaker embedding from raw audio.

        audio: int16 or float32 numpy array recorded at 16 kHz, mono.
               int16 arrays are scaled to float32 in [-1, 1] automatically.
        Returns: shape (256,) float32 array.
        """
        from resemblyzer import preprocess_wav  # type: ignore[import]

        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        elif audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        wav = preprocess_wav(audio, source_sr=_SAMPLE_RATE)
        return self._encoder.embed_utterance(wav)

    @staticmethod
    def similarity(emb_a: np.ndarray, emb_b: np.ndarray) -> float:
        """
        Cosine similarity between two L2-normalised embeddings.

        Both inputs are assumed to be unit-norm (as produced by embed()).
        Returns a float in [0, 1] where 1 = identical voice.
        """
        return float(np.dot(emb_a, emb_b))
