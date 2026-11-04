"""VLAN operations that are reverted unless the user confirms them."""
from __future__ import annotations

from typing import Callable

from .checkpoint import CheckpointError, NmCheckpoints
from .model import VlanSpec
from .nm import _UUID_RE, NmClient
from .rollback import run_with_rollback

# NetworkManager reverts on its own this long after the confirm dialog
# would have expired, so the dialog always decides first.
CHECKPOINT_MARGIN_S = 10


def _nm_rollback(cp: NmCheckpoints, path: str,
                 original: BaseException | None) -> None:
    try:
        cp.rollback(path)
    except CheckpointError as exc:
        raise exc from (original or exc.__cause__)
    except Exception as exc:
        raise CheckpointError(str(exc)) from (original or exc)


def _run_with_checkpoint(cp: NmCheckpoints, path: str,
                         apply: Callable[[], None],
                         ask_confirm: Callable[[], bool]) -> bool:
    """Like run_with_rollback, with NetworkManager doing the revert."""
    try:
        apply()
    except Exception as exc:
        _nm_rollback(cp, path, exc)
        raise
    try:
        confirmed = ask_confirm()
    except Exception as exc:
        _nm_rollback(cp, path, exc)
        raise
    if confirmed:
        cp.destroy(path)
        return True
    _nm_rollback(cp, path, None)
    return False


def _checkpoint(cp: NmCheckpoints | None,
                confirm_timeout_s: int) -> str | None:
    """Create a checkpoint, or return None to use the in-process undo."""
    if cp is None or not cp.available():
        return None
    try:
        return cp.create(confirm_timeout_s + CHECKPOINT_MARGIN_S)
    except CheckpointError:
        return None  # nothing applied yet: the in-process undo still works


def create_vlan_safe(nm: NmClient, spec: VlanSpec,
                     ask_confirm: Callable[[], bool],
                     checkpoints: NmCheckpoints | None = None,
                     confirm_timeout_s: int = 20) -> bool:
    path = _checkpoint(checkpoints, confirm_timeout_s)
    if path is not None:
        return _run_with_checkpoint(checkpoints, path,
                                    lambda: nm.up(nm.create_vlan(spec)),
                                    ask_confirm)
    uuid = nm.create_vlan(spec)
    return run_with_rollback(lambda: nm.up(uuid),
                             lambda: nm.delete_vlan(uuid), ask_confirm)


def edit_vlan_safe(nm: NmClient, name: str, spec: VlanSpec,
                   ask_confirm: Callable[[], bool],
                   checkpoints: NmCheckpoints | None = None,
                   confirm_timeout_s: int = 20) -> bool:
    old = nm.export_spec(name)
    by_uuid = _UUID_RE.match(name) is not None
    current = [name]  # identifier of the connection as it is right now

    def apply() -> None:
        nm.modify_vlan(name, spec)
        if not by_uuid:
            current[0] = spec.name
        nm.up(current[0])

    def undo() -> None:
        nm.modify_vlan(current[0], old)
        if not by_uuid:
            current[0] = old.name
        nm.up(current[0])

    path = _checkpoint(checkpoints, confirm_timeout_s)
    if path is not None:
        return _run_with_checkpoint(checkpoints, path, apply, ask_confirm)
    return run_with_rollback(apply, undo, ask_confirm)


def delete_vlan_safe(nm: NmClient, name: str,
                     ask_confirm: Callable[[], bool],
                     checkpoints: NmCheckpoints | None = None,
                     confirm_timeout_s: int = 20) -> bool:
    old = nm.export_spec(name)
    deleted = [False]

    def apply() -> None:
        nm.delete_vlan(name)
        deleted[0] = True

    def undo() -> None:
        if not deleted[0]:
            return  # nothing was removed, so nothing to recreate
        nm.up(nm.create_vlan(old))

    path = _checkpoint(checkpoints, confirm_timeout_s)
    if path is not None:
        return _run_with_checkpoint(checkpoints, path, apply, ask_confirm)
    return run_with_rollback(apply, undo, ask_confirm)
