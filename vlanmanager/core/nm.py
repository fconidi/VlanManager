"""NetworkManager access through nmcli: parsing and listing."""
from __future__ import annotations

import os
import re
import subprocess
from typing import Callable

from .model import IpConfig, Nic, Vlan, VlanSpec

# run(argv, timeout_s=...) -> stdout; timeout_s is optional.
Runner = Callable[..., str]

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}$")
_ADDED_UUID_RE = re.compile(
    r"\(([0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})\)")


def _sel(ident: str) -> list[str]:
    """Connection selector: names are ambiguous in NM, UUIDs are not."""
    return ["uuid", ident] if _UUID_RE.match(ident) else [ident]

_CONN_FIELDS = ("vlan.parent,vlan.id,ipv4.method,ipv4.addresses,"
                "ipv4.gateway,ipv4.dns,ipv4.never-default,ipv6.method,"
                "ipv6.addresses,ipv6.gateway,ipv6.dns,ipv6.never-default,"
                "connection.autoconnect,"
                "802-3-ethernet.mtu,connection.id,connection.interface-name")


NMCLI_TIMEOUT_S = 30
# Seconds nmcli waits for an activation (DHCP can take about 45 s).
ACTIVATION_TIMEOUT_S = 60
# Extra time given to nmcli itself beyond its own activation wait.
ACTIVATION_PROCESS_MARGIN_S = 10

# nmcli exit status
NMCLI_EXIT_TIMEOUT = 3
NMCLI_EXIT_ACTIVATION_FAILED = 4


class NmError(Exception):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.message = message
        self.code = code  # nmcli exit status, None when nmcli did not answer


def subprocess_runner(argv: list[str],
                      timeout_s: int = NMCLI_TIMEOUT_S) -> str:
    env = dict(os.environ, LC_ALL="C")
    try:
        proc = subprocess.run(["nmcli", *argv], capture_output=True,
                              text=True, env=env, timeout=timeout_s)
    except FileNotFoundError:
        raise NmError("nmcli_missing") from None
    except subprocess.TimeoutExpired:
        raise NmError("nmcli_timeout") from None
    if proc.returncode != 0:
        raise NmError(proc.stderr.strip(), code=proc.returncode)
    return proc.stdout


def split_terse(line: str) -> list[str]:
    """Split a terse nmcli line on unescaped colons and unescape the parts."""
    parts: list[str] = []
    cur: list[str] = []
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line) and line[i + 1] in ":\\":
            cur.append(line[i + 1])
            i += 2
            continue
        if ch == ":":
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    parts.append("".join(cur))
    return parts


def _lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


def _first(value: str) -> str | None:
    first = value.split(",")[0].strip()
    return first or None


def _getval(out: str) -> str:
    """Value printed by `nmcli -g`, with its escaped colons restored."""
    out = out.strip()
    return split_terse(out)[0] if out else ""


def _ip_config(f: dict[str, str], prefix: str) -> IpConfig:
    method = f.get(prefix + ".method", "") or "auto"
    dns = tuple(d.strip() for d in f.get(prefix + ".dns", "").split(",")
                if d.strip())
    return IpConfig(method=method,
                    address=_first(f.get(prefix + ".addresses", "")),
                    gateway=f.get(prefix + ".gateway", "").strip() or None,
                    dns=dns,
                    never_default=f.get(prefix + ".never-default", "")
                    .strip().lower() == "yes")


def _ip_args(prefix: str, cfg: IpConfig) -> list[str]:
    args = [prefix + ".method", cfg.method,
            prefix + ".never-default", "yes" if cfg.never_default else "no"]
    if cfg.method == "manual":
        args += [prefix + ".addresses", cfg.address or "",
                 prefix + ".gateway", cfg.gateway or "",
                 prefix + ".dns", ",".join(cfg.dns)]
    return args


def _spec_to_args(spec: VlanSpec, modify: bool = False) -> list[str]:
    """Property arguments shared by `connection add` and `connection modify`.

    When modifying, values that are no longer set are sent as empty strings
    so that NetworkManager clears them.
    """
    args: list[str] = []
    for prefix, cfg in (("ipv4", spec.ipv4), ("ipv6", spec.ipv6)):
        args += _ip_args(prefix, cfg)
        if modify and cfg.method != "manual":
            args += [prefix + ".addresses", "", prefix + ".gateway", "",
                     prefix + ".dns", ""]
    args += ["connection.autoconnect", "yes" if spec.autoconnect else "no"]
    if spec.mtu is not None:
        args += ["802-3-ethernet.mtu", str(spec.mtu)]
    elif modify:
        args += ["802-3-ethernet.mtu", "0"]
    return args


class NmClient:
    def __init__(self, run: Runner = subprocess_runner):
        self._run = run

    def is_running(self) -> bool:
        try:
            out = self._run(["-t", "-f", "RUNNING", "general"])
        except NmError:
            return False
        return out.strip() == "running"

    def list_nics(self) -> list[Nic]:
        out = self._run(["-t", "-f", "DEVICE,TYPE,STATE", "device"])
        nics = []
        for line in _lines(out):
            parts = split_terse(line)
            if len(parts) < 3 or parts[1] != "ethernet":
                continue
            name, _, state = parts[:3]
            mac = self._run(["-g", "GENERAL.HWADDR", "device", "show",
                             name]).strip()
            mac = split_terse(mac)[0] if mac else ""
            nics.append(Nic(name=name, mac=mac, state=state,
                            managed=state != "unmanaged"))
        return nics

    def list_vlans(self) -> list[Vlan]:
        out = self._run(["-t", "-f", "NAME,UUID,TYPE", "connection", "show"])
        active_out = self._run(["-t", "-f", "NAME,UUID,DEVICE",
                                "connection", "show", "--active"])
        active = {split_terse(ln)[1] for ln in _lines(active_out)
                  if len(split_terse(ln)) >= 3}
        vlans = []
        for line in _lines(out):
            parts = split_terse(line)
            if len(parts) < 3 or parts[2] != "vlan":
                continue
            name, uuid = parts[0], parts[1]
            spec = self._parse_connection(name, self._read(uuid))
            vlans.append(Vlan(spec=spec, uuid=uuid, active=uuid in active))
        return vlans

    def export_spec(self, ident: str) -> VlanSpec:
        return self._parse_connection(ident, self._read(ident))

    def gateway(self, iface: str) -> str | None:
        """Gateway of the active configuration of a device."""
        for prop in ("IP4.GATEWAY", "IP6.GATEWAY"):
            try:
                out = self._run(["-g", prop, "device", "show", iface])
            except NmError:
                continue
            value = _getval(out)
            if value and value != "--":
                return value
        return None

    def _read(self, ident: str) -> str:
        return self._run(["-t", "-f", _CONN_FIELDS, "connection", "show",
                          *_sel(ident)])

    def _parse_connection(self, name: str, text: str) -> VlanSpec:
        f: dict[str, str] = {}
        for line in _lines(text):
            parts = split_terse(line)
            f[parts[0]] = parts[1] if len(parts) > 1 else ""
        parent = f.get("vlan.parent", "")
        if _UUID_RE.match(parent):
            iface = _getval(self._run(["-g", "connection.interface-name",
                                       "connection", "show", parent]))
            parent = iface or parent
        mtu_raw = f.get("802-3-ethernet.mtu", "").strip()
        mtu = int(mtu_raw) if mtu_raw.isdigit() and int(mtu_raw) > 0 else None
        con_id = f.get("connection.id", "").strip() or name
        # Without an explicit interface name, keep the connection name.
        iface = f.get("connection.interface-name", "").strip() or con_id
        return VlanSpec(
            parent=parent,
            vlan_id=int(f.get("vlan.id") or 0),
            name=iface,
            con_name=con_id if con_id != iface else None,
            ipv4=_ip_config(f, "ipv4"),
            ipv6=_ip_config(f, "ipv6"),
            autoconnect=f.get("connection.autoconnect", "yes") != "no",
            mtu=mtu)

    def create_vlan(self, spec: VlanSpec) -> str:
        out = self._run(["connection", "add", "type", "vlan",
                   "con-name", spec.connection_name, "ifname", spec.name,
                   "dev", spec.parent, "id", str(spec.vlan_id),
                   *_spec_to_args(spec)])
        found = _ADDED_UUID_RE.search(out or "")
        if not found:
            raise NmError("connection UUID missing from nmcli output")
        return found.group(1)

    def modify_vlan(self, ident: str, spec: VlanSpec,
                    current: VlanSpec | None = None) -> None:
        """Write spec over the connection; current is what is stored now."""
        if current is None:
            current = self.export_spec(ident)
        argv = ["connection", "modify", *_sel(ident),
                "vlan.parent", spec.parent, "vlan.id", str(spec.vlan_id)]
        if spec.connection_name != current.connection_name:
            argv += ["connection.id", spec.connection_name]
        if spec.name != current.name:
            argv += ["connection.interface-name", spec.name]
        self._run(argv + _spec_to_args(spec, modify=True))

    def delete_vlan(self, ident: str) -> None:
        self._run(["connection", "delete", *_sel(ident)])

    def up(self, ident: str) -> None:
        self._run(["-w", str(ACTIVATION_TIMEOUT_S), "connection", "up",
                   *_sel(ident)],
                  timeout_s=ACTIVATION_TIMEOUT_S + ACTIVATION_PROCESS_MARGIN_S)

    def down(self, ident: str) -> None:
        self._run(["connection", "down", *_sel(ident)])
