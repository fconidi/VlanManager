"""VLAN operations that are reverted unless the user confirms them."""
from __future__ import annotations

from typing import Callable

from .model import VlanSpec
from .nm import NmClient
from .rollback import run_with_rollback


def create_vlan_safe(nm: NmClient, spec: VlanSpec,
                     ask_confirm: Callable[[], bool]) -> bool:
    nm.create_vlan(spec)
    return run_with_rollback(lambda: nm.up(spec.name),
                             lambda: nm.delete_vlan(spec.name), ask_confirm)


def edit_vlan_safe(nm: NmClient, name: str, spec: VlanSpec,
                   ask_confirm: Callable[[], bool]) -> bool:
    old = nm.export_spec(name)
    current = [name]  # connection name as it is right now

    def apply() -> None:
        nm.modify_vlan(name, spec)
        current[0] = spec.name
        nm.up(spec.name)

    def undo() -> None:
        nm.modify_vlan(current[0], old)
        nm.up(old.name)

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
        nm.create_vlan(old)
        nm.up(old.name)

    return run_with_rollback(apply, undo, ask_confirm)
