"""Data model and validation for VLAN definitions."""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Sequence

MAX_NAME_LEN = 15
MTU_MIN, MTU_MAX = 576, 9000
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class IpConfig:
    method: str = "auto"  # "auto" | "manual" | "disabled"
    address: str | None = None  # CIDR, e.g. 192.168.20.5/24
    gateway: str | None = None
    dns: tuple[str, ...] = ()
    never_default: bool = False  # do not use this VLAN as default route


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
        iface = ipaddress.ip_interface(cfg.address)
        if iface.version != version:
            raise ValueError
    except ValueError:
        errors.append("address_invalid")
        iface = None
    if iface is not None and version == 4 and iface.network.prefixlen < 31 \
            and iface.ip == iface.network.network_address:
        errors.append("address_network")
    if cfg.gateway:
        try:
            gateway = ipaddress.ip_address(cfg.gateway)
            if gateway.version != version:
                raise ValueError
        except ValueError:
            errors.append("gateway_invalid")
        else:
            if iface is not None:
                if gateway == iface.ip:
                    errors.append("gateway_same")
                elif version == 4 and gateway not in iface.network:
                    errors.append("gateway_outside")
    for dns in cfg.dns:
        try:
            if ipaddress.ip_address(dns).version != version:
                raise ValueError
        except ValueError:
            errors.append("dns_invalid")
            break


def validate(spec: VlanSpec, existing: Sequence[VlanSpec],
             editing: str | None = None, reserved: Sequence[str] = (),
             parent_mtu: int | None = None) -> list[str]:
    errors: list[str] = []
    if not 1 <= spec.vlan_id <= 4094:
        errors.append("id_range")
    if not spec.name:
        errors.append("name_empty")
    elif len(spec.name) > MAX_NAME_LEN:
        errors.append("name_len")
    elif not _NAME_RE.match(spec.name) or spec.name in (".", ".."):
        errors.append("name_invalid")
    elif spec.name == "lo" or spec.name in reserved:
        errors.append("name_taken")
    for other in existing:
        if other.name == editing:
            continue
        if other.parent == spec.parent and other.vlan_id == spec.vlan_id:
            errors.append("duplicate")
        elif other.name == spec.name and spec.name:
            errors.append("name_taken")
    for version, cfg in ((4, spec.ipv4), (6, spec.ipv6)):
        _check_ip(cfg, version, errors)
    if spec.mtu is not None and not MTU_MIN <= spec.mtu <= MTU_MAX:
        errors.append("mtu_range")
    elif spec.mtu is not None and parent_mtu and spec.mtu > parent_mtu:
        errors.append("mtu_parent")
    return list(dict.fromkeys(errors))
