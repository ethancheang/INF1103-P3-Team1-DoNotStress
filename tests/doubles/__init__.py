"""Test doubles: stand-ins for the live AI, the records file and the display.

They implement the same interfaces as the real classes, so the tests run the
real pipeline without a live API, network or files.
"""

from .in_memory_record_repository import InMemoryRecordRepository
from .mock_ai_manager import MockAIManager
from .recording_display import RecordingDisplay
from .scripted_text_generator import ScriptedTextGenerator

__all__ = ["InMemoryRecordRepository", "MockAIManager", "RecordingDisplay", "ScriptedTextGenerator"]
