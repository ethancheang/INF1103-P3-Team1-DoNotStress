"""CheckinWorker: runs a check-in on a background thread (advanced feature: threading)."""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Mapping
from typing import Any

from checkin_pipeline import CheckinPipeline
from data_manager import DataStoreError, RecordRepository

logger = logging.getLogger(__name__)


class CheckinWorker:
    """Keeps the desktop window responsive while Gemini is working.

    ``start`` returns at once; the AI call, the Logic evaluation and the save
    run on a daemon thread. The outcome is put on a thread-safe queue that
    the window reads with ``poll`` from its own (main) thread, because
    Tkinter widgets must only be touched from the main thread.

    Outcome: ``(True, evaluated_record)`` or ``(False, error_code)``. As in
    the web app, answers the AI could not finish are saved as a pending row.

    Relationships: the pipeline and the store are created by the app and
    only used here (association).
    """

    def __init__(self, pipeline: CheckinPipeline, store: RecordRepository) -> None:
        self.__pipeline = pipeline
        self.__store = store
        self.__results: queue.Queue[tuple[bool, Any]] = queue.Queue()
        self.__thread: threading.Thread | None = None

    @property
    def busy(self) -> bool:
        """True while a check-in is still being processed."""
        return self.__thread is not None and self.__thread.is_alive()

    def start(self, record: Mapping[str, Any]) -> None:
        """Process ``record`` in the background. Only one check-in runs at a time."""
        if self.busy:
            raise RuntimeError("A check-in is already being processed.")
        self.__thread = threading.Thread(target=self.__work, args=(dict(record),), daemon=True, name="checkin-worker")
        self.__thread.start()

    def poll(self) -> tuple[bool, Any] | None:
        """The finished outcome, or None while the work is still running."""
        try:
            return self.__results.get_nowait()
        except queue.Empty:
            return None

    def wait(self, timeout: float | None = None) -> tuple[bool, Any] | None:
        """Block until the outcome is ready (used by tests and scripts)."""
        try:
            return self.__results.get(timeout=timeout)
        except queue.Empty:
            return None

    def run(self, record: Mapping[str, Any]) -> tuple[bool, Any]:
        """Process one check-in on the calling thread and return the outcome."""
        try:
            ok, outcome = self.__pipeline.process(record)
        except Exception as exc:  # noqa: BLE001 - never let the worker thread die silently
            logger.warning("Desktop check-in failed: %s", type(exc).__name__)
            ok, outcome = False, "unavailable"
        if not ok:
            self.__save_quietly(lambda: self.__store.save_pending(record))
            return False, outcome
        saved = self.__save_quietly(lambda: self.__store.save(outcome))
        if saved:
            outcome = {**outcome, "record_id": saved.get("record_id")}
        return True, outcome

    def __work(self, record: dict[str, Any]) -> None:
        self.__results.put(self.run(record))

    @staticmethod
    def __save_quietly(save: Any) -> dict[str, Any] | None:
        """Run one save; a storage problem is logged and the student still sees the result."""
        try:
            result = save()
            return result if isinstance(result, dict) else None
        except DataStoreError as exc:
            logger.warning("Desktop check-in could not be saved: %s", exc)
            return None
