"""Data model and validation for VLAN definitions."""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Sequence

MAX_NAME_LEN = 15
MTU_MIN, MTU_MAX = 576, 9000


@dataclass(frozen=True)
class IpConfig:
    method: str = "auto"  # "auto" | "manual" | "disabled"
    address: str | None = None  # CIDR, e.g. 192.168.20.5/24
    gateway: str | None = None
    dns: tuple[str, ...] = ()


@dataclass(frozen=True)
class VlanSpec:
    parent: str
    vlan_id: int
    name: str
    ipv4: IpConfig = IpConfig()
    ipv6: IpConfig = IpConfig()
    autoconnect: bool = True
    mtu: int | None = None


@dataclass(frozen=True)
class Nic:
    name: str
    mac: str
    state: str
    managed: bool


@dataclass(frozen=True)
class Vlan:
    spec: VlanSpec
    uuid: str
    active: bool


def default_name(parent: str, vlan_id: int) -> str:
    return f"{parent}.{vlan_id}"


def _check_ip(cfg: IpConfig, errors: list[str]) -> None:
    if cfg.method != "manual":
        return
    try:
        if not cfg.address or "/" not in cfg.address:
            raise ValueError
        ipaddress.ip_interface(cfg.address)
    except ValueError:
        errors.append("address_invalid")
    if cfg.gateway:
        try:
            ipaddress.ip_address(cfg.gateway)
        except ValueError:
            errors.append("gateway_invalid")


def validate(spec: VlanSpec, existing: Sequence[VlanSpec],
             editing: str | None = None) -> list[str]:
    errors: list[str] = []
    if not 1 <= spec.vlan_id <= 4094:
        errors.append("id_range")
    if not spec.name:
        errors.append("name_empty")
    elif len(spec.name) > MAX_NAME_LEN:
        errors.append("name_len")
    for other in existing:
        if other.name == editing:
            continue
        if other.parent == spec.parent and other.vlan_id == spec.vlan_id:
            errors.append("duplicate")
            break
    for cfg in (spec.ipv4, spec.ipv6):
        _check_ip(cfg, errors)
    if spec.mtu is not None and not MTU_MIN <= spec.mtu <= MTU_MAX:
        errors.append("mtu_range")
    return list(dict.fromkeys(errors))
