"""Probes: 8021q kernel module availability and gateway reachability."""
from __future__ import annotations

import glob
import ipaddress
import os
import subprocess
from typing import Callable

_TIMEOUT_RC = 124
_MISSING_RC = 127


def _run_rc(argv: list[str]) -> int:
    try:
        return subprocess.run(argv, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=15).returncode
    except subprocess.TimeoutExpired:
        return _TIMEOUT_RC
    except OSError:
        return _MISSING_RC


def _sysfs_has_8021q() -> bool:
    return os.path.exists("/sys/module/8021q")


def _release() -> str:
    return os.uname().release


def _builtin_has_8021q() -> bool:
    path = f"/lib/modules/{_release()}/modules.builtin"
    with open(path, encoding="utf-8", errors="replace") as fh:
        return any(line.strip().endswith("/8021q.ko") for line in fh)


def _ko_exists() -> bool:
    pattern = f"/lib/modules/{_release()}/kernel/net/8021q/8021q.ko*"
    return bool(glob.glob(pattern))


def _safe(check: Callable[[], bool]) -> bool:
    try:
        return bool(check())
    except Exception:
        return False


def module_8021q_available(run: Callable[[list[str]], int] = _run_rc,
                           sysfs_exists: Callable[[], bool] = _sysfs_has_8021q,
                           builtin_has: Callable[[], bool] = _builtin_has_8021q,
                           ko_exists: Callable[[], bool] = _ko_exists
                           ) -> bool:
    if _safe(sysfs_exists) or _safe(builtin_has) or _safe(ko_exists):
        return True
    for modprobe in ("modprobe", "/sbin/modprobe", "/usr/sbin/modprobe"):
        if run([modprobe, "-n", "8021q"]) == 0:
            return True
    return False


def ping_gateway(gateway: str, iface: str, timeout_s: int = 2,
                 run: Callable[[list[str]], int] = _run_rc) -> bool:
    try:
        addr = ipaddress.ip_address(gateway)
    except ValueError:
        return False
    argv = ["ping"]
    if addr.version == 6:
        argv.append("-6")
    argv += ["-I", iface, "-c", "1", "-W", str(timeout_s), gateway]
    return run(argv) == 0


def verify_vlan(nm, iface: str, ping=ping_gateway) -> tuple[bool, str]:
    gateway = nm.gateway(iface)
    if not gateway:
        return False, "no_gateway"
    if not ping(gateway, iface):
        return False, "ping_failed"
    return True, "ok"
