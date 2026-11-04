"""Run blocking work off the GTK main loop."""
from __future__ import annotations

import threading
from typing import Callable, TypeVar

from gi.repository import GLib

T = TypeVar("T")


def run_async(fn: Callable[[], T],
              on_done: Callable[[T | None, Exception | None], None]) -> None:
    """Run fn in a thread and call on_done(result, error) on the main loop."""
    def target() -> None:
        result: T | None = None
        error: Exception | None = None
        try:
            result = fn()
        except Exception as exc:
            error = exc

        def deliver() -> bool:
            on_done(result, error)
            return False

        GLib.idle_add(deliver)

    threading.Thread(target=target, daemon=True).start()
