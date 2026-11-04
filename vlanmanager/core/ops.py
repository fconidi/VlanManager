"""VLAN operations that are reverted unless the user confirms them."""
from __future__ import annotations

from typing import Callable

from .checkpoint import CheckpointError, NmCheckpoints
from .model import VlanSpec
from .nm import (_UUID_RE, ACTIVATION_TIMEOUT_S, NMCLI_EXIT_ACTIVATION_FAILED,
                 NMCLI_EXIT_TIMEOUT, NmClient, NmError)
from .rollback import run_with_rollback

# NetworkManager reverts on its own this long after the confirm dialog
# would have expired, so the dialog always decides first.
CHECKPOINT_MARGIN_S = 10
# Seconds the user has to confirm a change before it is reverted.
CONFIRM_TIMEOUT_S = 20
# Time a change may need before the dialog shows: creating or modifying the
# connection and activating it, each bounded by the activation timeout.
APPLY_WINDOW_S = 2 * ACTIVATION_TIMEOUT_S
# Activation results that leave a usable profile behind: the check after the
# confirmation explains them (no DHCP, VLAN not allowed on the trunk).
_SOFT_UP_CODES = (NMCLI_EXIT_TIMEOUT, NMCLI_EXIT_ACTIVATION_FAILED)


def _activate(nm: NmClient, ident: str) -> None:
    """Bring a connection up; a timeout or failed activation is not fatal."""
    try:
        nm.up(ident)
    except NmError as exc:
        if exc.code not in _SOFT_UP_CODES:
            raise


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
                         ask_confirm: Callable[[], bool],
                         confirm_timeout_s: int) -> bool:
    """Like run_with_rollback, with NetworkManager doing the revert."""
    try:
        apply()
        # The countdown started at creation; restart it for the dialog.
        cp.adjust(path, confirm_timeout_s + CHECKPOINT_MARGIN_S)
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
        # Long enough for a slow activation; shortened once it is done.
        return cp.create(APPLY_WINDOW_S + confirm_timeout_s
                         + CHECKPOINT_MARGIN_S)
    except CheckpointError:
        return None  # nothing applied yet: the in-process undo still works


def create_vlan_safe(nm: NmClient, spec: VlanSpec,
                     ask_confirm: Callable[[], bool],
                     checkpoints: NmCheckpoints | None = None,
                     confirm_timeout_s: int = CONFIRM_TIMEOUT_S) -> bool:
    path = _checkpoint(checkpoints, confirm_timeout_s)
    if path is not None:
        return _run_with_checkpoint(checkpoints, path,
                                    lambda: _activate(nm,
                                                      nm.create_vlan(spec)),
                                    ask_confirm, confirm_timeout_s)
    uuid = nm.create_vlan(spec)
    return run_with_rollback(lambda: _activate(nm, uuid),
                             lambda: nm.delete_vlan(uuid), ask_confirm)


def _protected(apply: Callable[[], None], undo: Callable[[], None],
               ask_confirm: Callable[[], bool],
               checkpoints: NmCheckpoints | None, confirm_timeout_s: int,
               active: bool) -> bool:
    """Revert through a checkpoint for an active VLAN, in-process otherwise.

    A checkpoint only covers realized devices, so it cannot restore the
    profile of a VLAN that is not active.
    """
    path = _checkpoint(checkpoints, confirm_timeout_s) if active else None
    if path is not None:
        return _run_with_checkpoint(checkpoints, path, apply, ask_confirm,
                                    confirm_timeout_s)
    return run_with_rollback(apply, undo, ask_confirm)


def edit_vlan_safe(nm: NmClient, name: str, spec: VlanSpec,
                   ask_confirm: Callable[[], bool],
                   checkpoints: NmCheckpoints | None = None,
                   confirm_timeout_s: int = CONFIRM_TIMEOUT_S,
                   active: bool = True) -> bool:
    old = nm.export_spec(name)
    by_uuid = _UUID_RE.match(name) is not None
    current = [name]  # identifier of the connection as it is right now

    def apply() -> None:
        nm.modify_vlan(name, spec, old)
        if not by_uuid:
            current[0] = spec.connection_name
        if active:  # an inactive VLAN stays inactive
            _activate(nm, current[0])

    def undo() -> None:
        nm.modify_vlan(current[0], old, spec)
        if not by_uuid:
            current[0] = old.connection_name
        if active:
            nm.up(current[0])

    return _protected(apply, undo, ask_confirm, checkpoints,
                      confirm_timeout_s, active)


def delete_vlan_safe(nm: NmClient, name: str,
                     ask_confirm: Callable[[], bool],
                     checkpoints: NmCheckpoints | None = None,
                     confirm_timeout_s: int = CONFIRM_TIMEOUT_S,
                     active: bool = True) -> bool:
    old = nm.export_spec(name)
    deleted = [False]

    def apply() -> None:
        nm.delete_vlan(name)
        deleted[0] = True

    def undo() -> None:
        if not deleted[0]:
            return  # nothing was removed, so nothing to recreate
        uuid = nm.create_vlan(old)
        if active:
            nm.up(uuid)

    return _protected(apply, undo, ask_confirm, checkpoints,
                      confirm_timeout_s, active)


def deactivate_vlan_safe(nm: NmClient, ident: str,
                         ask_confirm: Callable[[], bool],
                         checkpoints: NmCheckpoints | None = None,
                         confirm_timeout_s: int = CONFIRM_TIMEOUT_S,
                         active: bool = True) -> bool:
    return _protected(lambda: nm.down(ident), lambda: nm.up(ident),
                      ask_confirm, checkpoints, confirm_timeout_s, active)
