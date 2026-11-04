"""VLAN operations that are reverted unless the user confirms them."""
from __future__ import annotations

from typing import Callable

from .model import VlanSpec
from .nm import _UUID_RE, NmClient
from .rollback import run_with_rollback


def create_vlan_safe(nm: NmClient, spec: VlanSpec,
                     ask_confirm: Callable[[], bool]) -> bool:
    uuid = nm.create_vlan(spec)
    return run_with_rollback(lambda: nm.up(uuid),
                             lambda: nm.delete_vlan(uuid), ask_confirm)


def edit_vlan_safe(nm: NmClient, name: str, spec: VlanSpec,
                   ask_confirm: Callable[[], bool]) -> bool:
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

    return run_with_rollback(apply, undo, ask_confirm)


def delete_vlan_safe(nm: NmClient, name: str,
                     ask_confirm: Callable[[], bool]) -> bool:
    old = nm.export_spec(name)
    deleted = [False]

    def apply() -> None:
        nm.delete_vlan(name)
        deleted[0] = True

    def undo() -> None:
        if not deleted[0]:
            return  # nothing was removed, so nothing to recreate
        nm.up(nm.create_vlan(old))

    return run_with_rollback(apply, undo, ask_confirm)
