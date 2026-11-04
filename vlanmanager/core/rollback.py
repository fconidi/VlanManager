"""Apply a change and revert it unless the user confirms."""
from __future__ import annotations

from typing import Callable


class RollbackError(Exception):
    """The undo step itself failed."""


def _undo(undo: Callable[[], None], original: BaseException | None) -> None:
    try:
        undo()
    except Exception as exc:
        raise RollbackError(str(exc)) from (original or exc)


def run_with_rollback(apply: Callable[[], None], undo: Callable[[], None],
                      ask_confirm: Callable[[], bool]) -> bool:
    try:
        apply()
    except Exception as exc:
        _undo(undo, exc)
        raise
    try:
        confirmed = ask_confirm()
    except Exception as exc:
        _undo(undo, exc)
        raise
    if confirmed:
        return True
    _undo(undo, None)
    return False
