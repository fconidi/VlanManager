import unittest

from vlanmanager.core.checkpoint import (NO_TIMEOUT_MS, CheckpointError,
                                         NmCheckpoints, PERMISSION)


CP_PATH = "/org/freedesktop/NetworkManager/Checkpoint/1"


class FakeCall:
    def __init__(self, replies=None, error=None):
        self.calls = []
        self.timeouts = {}
        self.replies = replies or {}
        self.error = error

    def __call__(self, method, signature, args, timeout_ms=None):
        self.calls.append((method, signature, args))
        self.timeouts[method] = timeout_ms
        if self.error is not None:
            raise self.error
        return self.replies.get(method, ())


class NmCheckpointsTest(unittest.TestCase):
    def test_create_passes_empty_devices_timeout_and_flags(self):
        call = FakeCall({"CheckpointCreate": (CP_PATH,)})
        path = NmCheckpoints(call).create(30)
        self.assertEqual(path, CP_PATH)
        self.assertEqual(call.calls,
                         [("CheckpointCreate", "(aouu)", ([], 30, 6))])

    def test_destroy_and_rollback_call_methods(self):
        call = FakeCall({"CheckpointRollback": ({},)})
        cp = NmCheckpoints(call)
        cp.destroy(CP_PATH)
        cp.rollback(CP_PATH)
        self.assertEqual(call.calls,
                         [("CheckpointDestroy", "(o)", (CP_PATH,)),
                          ("CheckpointRollback", "(o)", (CP_PATH,))])

    def test_adjust_passes_path_and_timeout(self):
        call = FakeCall()
        NmCheckpoints(call).adjust(CP_PATH, 30)
        self.assertEqual(call.calls, [("CheckpointAdjustRollbackTimeout",
                                       "(ou)", (CP_PATH, 30))])

    def test_create_waits_without_client_timeout(self):
        call = FakeCall({"CheckpointCreate": (CP_PATH,),
                         "CheckpointRollback": ({},),
                         "GetPermissions": ({PERMISSION: "yes"},)})
        cp = NmCheckpoints(call)
        cp.create(30)
        cp.adjust(CP_PATH, 30)
        cp.destroy(CP_PATH)
        cp.rollback(CP_PATH)
        cp.available()
        self.assertEqual(call.timeouts["CheckpointCreate"], NO_TIMEOUT_MS)
        self.assertEqual(NO_TIMEOUT_MS, 2147483647)
        for method in ("CheckpointAdjustRollbackTimeout", "CheckpointDestroy",
                       "CheckpointRollback", "GetPermissions"):
            self.assertIsNone(call.timeouts[method], method)

    def test_rollback_ignores_missing_and_unmanaged_devices(self):
        call = FakeCall({"CheckpointRollback": ({"/dev/a": 0,
                                                 "/dev/b": 2,
                                                 "/dev/c": 1},)})
        NmCheckpoints(call).rollback(CP_PATH)

    def test_rollback_raises_when_a_device_failed(self):
        call = FakeCall({"CheckpointRollback": ({"/dev/a": 3},)})
        with self.assertRaises(CheckpointError):
            NmCheckpoints(call).rollback(CP_PATH)

    def test_rollback_raises_on_unexpected_reply(self):
        with self.assertRaises(CheckpointError):
            NmCheckpoints(FakeCall({"CheckpointRollback": ()})).rollback(
                CP_PATH)

    def test_dbus_error_maps_to_checkpoint_error(self):
        cp = NmCheckpoints(FakeCall(error=RuntimeError("denied")))
        for op in (lambda: cp.create(30), lambda: cp.destroy(CP_PATH),
                   lambda: cp.adjust(CP_PATH, 30),
                   lambda: cp.rollback(CP_PATH)):
            with self.assertRaises(CheckpointError):
                op()

    def test_available_false_on_dbus_error(self):
        cp = NmCheckpoints(FakeCall(error=RuntimeError("no bus")))
        self.assertFalse(cp.available())

    def test_available_true_when_permission_granted(self):
        for value in ("yes", "auth"):
            call = FakeCall({"GetPermissions": ({PERMISSION: value},)})
            self.assertTrue(NmCheckpoints(call).available())
            self.assertEqual(call.calls, [("GetPermissions", "()", ())])

    def test_available_false_when_polkit_denies(self):
        call = FakeCall({"GetPermissions": ({PERMISSION: "no"},)})
        self.assertFalse(NmCheckpoints(call).available())

    def test_available_false_on_unexpected_reply(self):
        self.assertFalse(NmCheckpoints(FakeCall({"GetPermissions": ()}))
                         .available())

    def test_module_imports_without_bus(self):
        # Constructing with the default call must not touch D-Bus.
        NmCheckpoints()


if __name__ == "__main__":
    unittest.main()
