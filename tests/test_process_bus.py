"""Unit tests for core/process_bus.py"""

import time
import threading
import pytest
from core.process_bus import BusEvent, Message, ProcessBus


# ---------------------------------------------------------------------------
# Message dataclass
# ---------------------------------------------------------------------------

class TestMessage:
    def test_has_timestamp(self):
        msg = Message(event=BusEvent.WAKE_WORD)
        assert msg.timestamp is not None

    def test_payload_defaults_none(self):
        msg = Message(event=BusEvent.SHUTDOWN)
        assert msg.payload is None

    def test_source_defaults_none(self):
        msg = Message(event=BusEvent.SPEAK, payload="hello")
        assert msg.source is None

    def test_custom_payload_stored(self):
        msg = Message(event=BusEvent.MODE_CHANGE, payload="ally", source="main")
        assert msg.payload == "ally"
        assert msg.source == "main"


# ---------------------------------------------------------------------------
# Subscribe / publish
# ---------------------------------------------------------------------------

class TestSubscribePublish:
    def test_subscriber_receives_published_message(self):
        bus = ProcessBus()
        q = bus.subscribe(BusEvent.WAKE_WORD)
        bus.publish(BusEvent.WAKE_WORD, payload=0.9)
        msg = q.get(timeout=1)
        assert msg.event == BusEvent.WAKE_WORD
        assert msg.payload == 0.9

    def test_publish_returns_delivery_count(self):
        bus = ProcessBus()
        bus.subscribe(BusEvent.SPEAK)
        bus.subscribe(BusEvent.SPEAK)
        count = bus.publish(BusEvent.SPEAK, payload="hello")
        assert count == 2

    def test_publish_to_no_subscribers_returns_zero(self):
        bus = ProcessBus()
        count = bus.publish(BusEvent.SHUTDOWN)
        assert count == 0

    def test_multiple_subscribers_each_receive_message(self):
        bus = ProcessBus()
        q1 = bus.subscribe(BusEvent.MODE_CHANGE)
        q2 = bus.subscribe(BusEvent.MODE_CHANGE)
        bus.publish(BusEvent.MODE_CHANGE, payload="manual")
        msg1 = q1.get(timeout=1)
        msg2 = q2.get(timeout=1)
        assert msg1.payload == "manual"
        assert msg2.payload == "manual"

    def test_subscriber_only_receives_its_event_type(self):
        bus = ProcessBus()
        q_wake = bus.subscribe(BusEvent.WAKE_WORD)
        bus.publish(BusEvent.SPEAK, payload="hello")
        with pytest.raises(Exception):
            q_wake.get(timeout=0.05)  # should timeout — no WAKE_WORD published

    def test_source_propagated_in_message(self):
        bus = ProcessBus()
        q = bus.subscribe(BusEvent.OWNER_CHANGE)
        bus.publish(BusEvent.OWNER_CHANGE, payload="Alice", source="ally_agent")
        msg = q.get(timeout=1)
        assert msg.source == "ally_agent"


# ---------------------------------------------------------------------------
# Unsubscribe
# ---------------------------------------------------------------------------

class TestUnsubscribe:
    def test_unsubscribed_queue_stops_receiving(self):
        bus = ProcessBus()
        q = bus.subscribe(BusEvent.SPEAK)
        bus.unsubscribe(BusEvent.SPEAK, q)
        count = bus.publish(BusEvent.SPEAK, payload="test")
        assert count == 0

    def test_unsubscribe_unknown_queue_is_noop(self):
        import multiprocessing
        bus = ProcessBus()
        fake_q = multiprocessing.Queue()
        # Should not raise
        bus.unsubscribe(BusEvent.SPEAK, fake_q)


# ---------------------------------------------------------------------------
# subscriber_count
# ---------------------------------------------------------------------------

class TestSubscriberCount:
    def test_count_zero_before_subscribe(self):
        bus = ProcessBus()
        assert bus.subscriber_count(BusEvent.WAKE_WORD) == 0

    def test_count_increments_on_subscribe(self):
        bus = ProcessBus()
        bus.subscribe(BusEvent.WAKE_WORD)
        bus.subscribe(BusEvent.WAKE_WORD)
        assert bus.subscriber_count(BusEvent.WAKE_WORD) == 2

    def test_count_decrements_on_unsubscribe(self):
        bus = ProcessBus()
        q = bus.subscribe(BusEvent.SPEAK)
        bus.subscribe(BusEvent.SPEAK)
        bus.unsubscribe(BusEvent.SPEAK, q)
        assert bus.subscriber_count(BusEvent.SPEAK) == 1


# ---------------------------------------------------------------------------
# Bounded queue / drop-on-full
# ---------------------------------------------------------------------------

class TestBoundedQueue:
    def test_full_queue_does_not_block_publisher(self):
        bus = ProcessBus(maxsize=2)
        q = bus.subscribe(BusEvent.AUDIO_CHUNK)
        # Publish 5 messages; queue holds only 2 — should not block
        start = time.monotonic()
        for i in range(5):
            bus.publish(BusEvent.AUDIO_CHUNK, payload=i)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, "publish() blocked unexpectedly"

    def test_messages_delivered_up_to_capacity(self):
        bus = ProcessBus(maxsize=3)
        q = bus.subscribe(BusEvent.AUDIO_CHUNK)
        for i in range(10):
            bus.publish(BusEvent.AUDIO_CHUNK, payload=i)
        # At most 3 messages in queue
        count = 0
        while not q.empty():
            q.get_nowait()
            count += 1
        assert count <= 3


# ---------------------------------------------------------------------------
# Thread-safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_publish_does_not_lose_subscriptions(self):
        bus = ProcessBus()
        queues = [bus.subscribe(BusEvent.STATUS_UPDATE) for _ in range(5)]

        errors = []

        def publisher():
            try:
                for _ in range(20):
                    bus.publish(BusEvent.STATUS_UPDATE, payload="ping")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=publisher) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors

    def test_all_bus_events_are_unique_strings(self):
        values = [e.value for e in BusEvent]
        assert len(values) == len(set(values))
