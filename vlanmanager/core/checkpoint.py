"""NetworkManager checkpoints: NM itself reverts unless they are confirmed.

A checkpoint is created before a change. Destroying it keeps the change;
rolling it back, or letting its timeout expire (for example because the
application exited), makes NetworkManager restore the previous state.
"""
from __future__ import annotations

from typing import Callable

# call(method, signature, args, timeout_ms=None); None means CALL_TIMEOUT_MS.
Call = Callable[..., object]

NM_NAME = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
NM_IFACE = "org.freedesktop.NetworkManager"
PERMISSION = "org.freedesktop.NetworkManager.checkpoint-rollback"

FLAG_DESTROY_ALL = 0x01
FLAG_DELETE_NEW_CONNECTIONS = 0x02
FLAG_DISCONNECT_NEW_DEVICES = 0x04
FLAG_ALLOW_OVERLAPPING = 0x08

CALL_TIMEOUT_MS = 15000
# G_MAXINT: wait without a client-side limit (a polkit prompt may be open).
NO_TIMEOUT_MS = 2147483647

# CheckpointRollback per-device results.
RESULT_OK, RESULT_NO_DEVICE, RESULT_UNMANAGED, RESULT_FAILED = 0, 1, 2, 3


class CheckpointError(Exception):
    """A checkpoint could not be created, destroyed or rolled back."""


def _dbus_call() -> Call:
    """Build a call function bound to NetworkManager on the system bus."""
    proxy = []

    def call(method: str, signature: str, args: tuple,
             timeout_ms: int | None = None) -> object:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        if not proxy:
            bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            proxy.append(Gio.DBusProxy.new_sync(
                bus, Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES
                | Gio.DBusProxyFlags.DO_NOT_CONNECT_SIGNALS,
                None, NM_NAME, NM_PATH, NM_IFACE, None))
        params = GLib.Variant(signature, args) if args else None
        reply = proxy[0].call_sync(
            method, params, Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION,
            CALL_TIMEOUT_MS if timeout_ms is None else timeout_ms, None)
        return reply.unpack() if reply is not None else ()

    return call


class NmCheckpoints:
    def __init__(self, call: Call | None = None):
        self._call = call or _dbus_call()

    def _invoke(self, method: str, signature: str, args: tuple,
                **kwargs) -> object:
        try:
            return self._call(method, signature, args, **kwargs)
        except CheckpointError:
            raise
        except Exception as exc:
            raise CheckpointError(str(exc)) from exc

    def create(self, timeout_s: int) -> str:
        """Checkpoint all devices; rollback removes connections made since."""
        flags = FLAG_DELETE_NEW_CONNECTIONS | FLAG_DISCONNECT_NEW_DEVICES
        reply = self._invoke("CheckpointCreate", "(aouu)",
                             ([], int(timeout_s), flags),
                             timeout_ms=NO_TIMEOUT_MS)
        try:
            return str(reply[0])
        except (TypeError, IndexError) as exc:
            raise CheckpointError("unexpected reply") from exc

    def adjust(self, path: str, timeout_s: int) -> None:
        """Restart the rollback countdown at timeout_s from now."""
        self._invoke("CheckpointAdjustRollbackTimeout", "(ou)",
                     (path, int(timeout_s)))

    def destroy(self, path: str) -> None:
        self._invoke("CheckpointDestroy", "(o)", (path,))

    def rollback(self, path: str) -> None:
        reply = self._invoke("CheckpointRollback", "(o)", (path,))
        try:
            results = dict(reply[0])
        except (TypeError, IndexError, ValueError) as exc:
            raise CheckpointError("unexpected reply") from exc
        failed = sorted(dev for dev, res in results.items()
                        if res == RESULT_FAILED)
        if failed:
            raise CheckpointError("rollback failed: " + ", ".join(failed))

    def available(self) -> bool:
        """True when NM answers and polkit does not refuse checkpoints."""
        try:
            reply = self._call("GetPermissions", "()", ())
            return reply[0].get(PERMISSION) in ("yes", "auth")
        except Exception:
            return False
