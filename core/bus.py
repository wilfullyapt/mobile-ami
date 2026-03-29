# core/bus.py — canonical short name for the IPC message bus.
# core/process_bus.py remains as the implementation file.
from core.process_bus import BusEvent, Message, ProcessBus

__all__ = ["BusEvent", "Message", "ProcessBus"]
