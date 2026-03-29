"""
ProcessBus — typed IPC message queue for inter-component communication.

Provides a publish/subscribe message bus built on multiprocessing.Queue so
that components can be incrementally moved into separate OS processes (e.g.
isolating audio capture, Hailo inference, or the pipeline) without changing
their call sites.

Current use: same-process coordination with clean, typed message contracts.
Future use: cross-process IPC once AudioProcess / HailoProcess are extracted.

Usage
-----
    bus = ProcessBus()

    # Consumer — subscribe before the producer starts
    q = bus.subscribe(BusEvent.WAKE_WORD)
    msg = q.get(timeout=5)   # blocks until a WAKE_WORD message arrives

    # Producer — publish from any thread or process
    bus.publish(BusEvent.WAKE_WORD, source="wake_detector")
"""

import enum
import multiprocessing
import multiprocessing.queues
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Event catalogue
# ---------------------------------------------------------------------------

class BusEvent(str, enum.Enum):
    """All typed event kinds that flow through the bus."""

    # Audio pipeline events
    AUDIO_CHUNK     = "audio_chunk"      # Raw 1024-sample int16 PCM array
    AUDIO_RECORDING = "audio_recording"  # Full VAD-gated utterance (np.ndarray)

    # Detection events
    WAKE_WORD       = "wake_word"        # Wake word detected; payload = score (float)
    SPEECH_DETECTED = "speech_detected"  # VAD pre-check found speech in a chunk

    # Inference events
    INFERENCE_DONE  = "inference_done"   # Hailo/CPU model result; payload = dict

    # Device control events
    BUTTON_PRESS    = "button_press"     # Physical button; payload = button name (str)
    MODE_CHANGE     = "mode_change"      # Interaction mode transition; payload = new mode value
    OWNER_CHANGE    = "owner_change"     # Owner established/updated; payload = name (str)

    # Output events
    SPEAK           = "speak"            # TTS request; payload = text (str)

    # System events
    STATUS_UPDATE   = "status_update"    # Device status snapshot; payload = dict
    SHUTDOWN        = "shutdown"         # Ordered shutdown; payload = reason (str)


# ---------------------------------------------------------------------------
# Message envelope
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """Typed wrapper for every bus message."""
    event: BusEvent
    payload: Any = None
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    source: Optional[str] = None  # originating component name


# ---------------------------------------------------------------------------
# ProcessBus
# ---------------------------------------------------------------------------

class ProcessBus:
    """
    Multi-subscriber IPC bus.

    Each subscriber gets its own bounded Queue so a slow consumer never
    blocks a fast producer or other consumers. When a queue is full, the
    oldest-compatible message is dropped (non-blocking put_nowait).

    Thread-safety: publish/subscribe are protected by a multiprocessing.Lock
    so the bus can be shared across processes via Manager or fork.
    """

    def __init__(self, maxsize: int = 256):
        self._maxsize = maxsize
        self._lock = multiprocessing.Lock()
        self._subscribers: dict[BusEvent, list[multiprocessing.Queue]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def subscribe(self, event: BusEvent) -> multiprocessing.Queue:
        """
        Register a new subscriber for *event*.

        Returns a fresh Queue; call .get() on it to receive messages.
        """
        q: multiprocessing.Queue = multiprocessing.Queue(maxsize=self._maxsize)
        with self._lock:
            self._subscribers.setdefault(event, []).append(q)
        return q

    def unsubscribe(self, event: BusEvent, queue: multiprocessing.Queue) -> None:
        """Deregister a previously subscribed queue."""
        with self._lock:
            subs = self._subscribers.get(event, [])
            try:
                subs.remove(queue)
            except ValueError:
                pass

    def publish(
        self,
        event: BusEvent,
        payload: Any = None,
        source: Optional[str] = None,
    ) -> int:
        """
        Broadcast *event* to all registered subscribers.

        Returns the number of queues the message was delivered to.
        Drops silently (non-blocking) if a subscriber queue is full.
        """
        msg = Message(event=event, payload=payload, source=source)
        with self._lock:
            queues = list(self._subscribers.get(event, []))
        delivered = 0
        for q in queues:
            try:
                q.put_nowait(msg)
                delivered += 1
            except Exception:
                pass  # Queue full — drop rather than block the publisher
        return delivered

    def subscriber_count(self, event: BusEvent) -> int:
        """Return the number of active subscribers for *event*."""
        with self._lock:
            return len(self._subscribers.get(event, []))
