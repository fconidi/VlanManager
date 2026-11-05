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
    name: str  # kernel interface name
    ipv4: IpConfig = IpConfig()
    ipv6: IpConfig = IpConfig()
    autoconnect: bool = True
    mtu: int | None = None
    # NetworkManager connection name, when it differs from the interface name
    con_name: str | None = None

    @property
    def connection_name(self) -> str:
        return self.con_name or self.name


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


def _check_ip(cfg: IpConfig, version: int, errors: list[str]) -> None:
    if cfg.method != "manual":
        return
    try:
        if not cfg.address or "/" not in cfg.address:
            raise ValueError
        if ipaddress.ip_interface(cfg.address).version != version:
            raise ValueError
    except ValueError:
        errors.append("address_invalid")
    if cfg.gateway:
        try:
            if ipaddress.ip_address(cfg.gateway).version != version:
                raise ValueError
        except ValueError:
            errors.append("gateway_invalid")
    for dns in cfg.dns:
        try:
            if ipaddress.ip_address(dns).version != version:
                raise ValueError
        except ValueError:
            errors.append("dns_invalid")
            break


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
    for version, cfg in ((4, spec.ipv4), (6, spec.ipv6)):
        _check_ip(cfg, version, errors)
    if spec.mtu is not None and not MTU_MIN <= spec.mtu <= MTU_MAX:
        errors.append("mtu_range")
    return list(dict.fromkeys(errors))
