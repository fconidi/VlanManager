import unittest

from vlanmanager.core.checkpoint import (CheckpointError, NmCheckpoints,
                                         PERMISSION)


CP_PATH = "/org/freedesktop/NetworkManager/Checkpoint/1"


class FakeCall:
    def __init__(self, replies=None, error=None):
        self.calls = []
        self.replies = replies or {}
        self.error = error

    def __call__(self, method, signature, args):
        self.calls.append((method, signature, args))
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

    def test_dbus_error_maps_to_checkpoint_error(self):
        cp = NmCheckpoints(FakeCall(error=RuntimeError("denied")))
        for op in (lambda: cp.create(30), lambda: cp.destroy(CP_PATH),
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
