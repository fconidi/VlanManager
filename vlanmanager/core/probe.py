"""Probes: 8021q kernel module availability and gateway reachability."""
from __future__ import annotations

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


def module_8021q_available(run: Callable[[list[str]], int] = _run_rc,
                           sysfs_exists: Callable[[], bool] = _sysfs_has_8021q
                           ) -> bool:
    return run(["modprobe", "-n", "8021q"]) == 0 or sysfs_exists()


def ping_gateway(gateway: str, timeout_s: int = 2,
                 run: Callable[[list[str]], int] = _run_rc) -> bool:
    try:
        addr = ipaddress.ip_address(gateway)
    except ValueError:
        return False
    argv = ["ping"]
    if addr.version == 6:
        argv.append("-6")
    argv += ["-c", "1", "-W", str(timeout_s), gateway]
    return run(argv) == 0


def verify_vlan(nm, name: str, ping=ping_gateway) -> tuple[bool, str]:
    gateway = nm.gateway(name)
    if not gateway:
        return False, "no_gateway"
    if not ping(gateway):
        return False, "ping_failed"
    return True, "ok"
