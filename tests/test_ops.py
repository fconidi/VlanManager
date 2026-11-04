import unittest

from vlanmanager.core.model import IpConfig, VlanSpec
from vlanmanager.core.checkpoint import CheckpointError
from vlanmanager.core.nm import NmError
from vlanmanager.core import ops
from vlanmanager.core.ops import (create_vlan_safe, deactivate_vlan_safe,
                                  delete_vlan_safe, edit_vlan_safe)


NEW_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class FakeNm:
    def __init__(self, exported=None, fail_up=False):
        self.calls = []
        self.exported = exported
        self.fail_up = fail_up  # True, or an NmError to raise

    def create_vlan(self, spec):
        self.calls.append(("create_vlan", spec))
        return NEW_UUID

    def modify_vlan(self, name, spec, current=None):
        self.calls.append(("modify_vlan", name, spec))

    def delete_vlan(self, name):
        self.calls.append(("delete_vlan", name))

    def up(self, name):
        self.calls.append(("up", name))
        if isinstance(self.fail_up, NmError):
            raise self.fail_up
        if self.fail_up:
            raise NmError("activation failed")

    def down(self, name):
        self.calls.append(("down", name))

    def export_spec(self, name):
        return self.exported

    def names(self):
        return [c[0] for c in self.calls]


OLD = VlanSpec("eth0", 20, "eth0.20",
               ipv4=IpConfig("manual", "192.168.20.5/24", "192.168.20.1",
                             ("1.1.1.1", "8.8.8.8")))
NEW = VlanSpec("eth0", 30, "eth0.30")


class CreateTest(unittest.TestCase):
    def test_create_confirmed(self):
        nm = FakeNm()
        self.assertTrue(create_vlan_safe(nm, NEW, lambda: True))
        self.assertEqual(nm.calls, [("create_vlan", NEW), ("up", NEW_UUID)])

    def test_create_activation_fails_removes_connection(self):
        nm = FakeNm(fail_up=True)
        with self.assertRaises(NmError):
            create_vlan_safe(nm, NEW, lambda: True)
        self.assertEqual(nm.calls[-1], ("delete_vlan", NEW_UUID))

    def test_create_safe_undo_deletes_by_uuid(self):
        nm = FakeNm()
        create_vlan_safe(nm, NEW, lambda: False)
        self.assertIn(("delete_vlan", NEW_UUID), nm.calls)
        self.assertNotIn(("delete_vlan", "eth0.30"), nm.calls)

    def test_create_not_confirmed_deletes(self):
        nm = FakeNm()
        self.assertFalse(create_vlan_safe(nm, NEW, lambda: False))
        self.assertEqual(nm.calls[-1], ("delete_vlan", NEW_UUID))


class DeleteTest(unittest.TestCase):
    def test_delete_confirmed(self):
        nm = FakeNm(exported=OLD)
        self.assertTrue(delete_vlan_safe(nm, "eth0.20", lambda: True))
        self.assertEqual(nm.calls, [("delete_vlan", "eth0.20")])

    def test_delete_not_confirmed_recreates_identical_spec(self):
        nm = FakeNm(exported=OLD)
        self.assertFalse(delete_vlan_safe(nm, "eth0.20", lambda: False))
        self.assertEqual(nm.calls[-2:],
                         [("create_vlan", OLD), ("up", NEW_UUID)])

    def test_delete_failure_does_not_recreate(self):
        nm = FakeNm(exported=OLD)

        def boom(name):
            nm.calls.append(("delete_vlan", name))
            raise NmError("delete failed")
        nm.delete_vlan = boom
        with self.assertRaises(NmError):
            delete_vlan_safe(nm, "eth0.20", lambda: True)
        self.assertNotIn("create_vlan", nm.names())


class EditTest(unittest.TestCase):
    def test_edit_by_uuid_keeps_addressing_by_uuid(self):
        nm = FakeNm(exported=OLD)
        u = "11111111-2222-3333-4444-555555555555"
        edit_vlan_safe(nm, u, NEW, lambda: False)
        self.assertEqual(nm.calls, [("modify_vlan", u, NEW), ("up", u),
                                    ("modify_vlan", u, OLD), ("up", u)])

    def test_edit_confirmed(self):
        nm = FakeNm(exported=OLD)
        self.assertTrue(edit_vlan_safe(nm, "eth0.20", NEW, lambda: True))
        self.assertEqual(nm.calls, [("modify_vlan", "eth0.20", NEW),
                                    ("up", "eth0.30")])

    def test_edit_not_confirmed_restores_previous_spec(self):
        nm = FakeNm(exported=OLD)
        self.assertFalse(edit_vlan_safe(nm, "eth0.20", NEW, lambda: False))
        self.assertEqual(nm.calls[-2:],
                         [("modify_vlan", "eth0.30", OLD), ("up", "eth0.20")])


CP_PATH = "/org/freedesktop/NetworkManager/Checkpoint/7"
# two bounded activation steps + 20 s confirm + 10 s margin
CP_WINDOW = 150


class FakeCheckpoints:
    def __init__(self, available=True, fail_create=False,
                 fail_rollback=False, fail_adjust=False, log=None):
        self._available = available
        self.fail_create = fail_create
        self.fail_rollback = fail_rollback
        self.fail_adjust = fail_adjust
        self.calls = log if log is not None else []

    def available(self):
        return self._available

    def create(self, timeout_s):
        self.calls.append(("cp_create", timeout_s))
        if self.fail_create:
            raise CheckpointError("denied")
        return CP_PATH

    def adjust(self, path, timeout_s):
        self.calls.append(("cp_adjust", path, timeout_s))
        if self.fail_adjust:
            raise CheckpointError("adjust failed")

    def destroy(self, path):
        self.calls.append(("cp_destroy", path))

    def rollback(self, path):
        self.calls.append(("cp_rollback", path))
        if self.fail_rollback:
            raise self.fail_rollback if isinstance(
                self.fail_rollback, Exception) else RuntimeError(
                    "rollback broke")


def _shared():
    """A fake NM and fake checkpoints recording into one call log."""
    nm = FakeNm(exported=OLD)
    cp = FakeCheckpoints(log=nm.calls)
    return nm, cp


class CheckpointOpsTest(unittest.TestCase):
    def test_confirmed_destroys_checkpoint_not_rollback(self):
        nm, cp = _shared()
        self.assertTrue(create_vlan_safe(nm, NEW, lambda: True,
                                         checkpoints=cp))
        self.assertEqual(nm.calls, [("cp_create", CP_WINDOW), ("create_vlan", NEW),
                                    ("up", NEW_UUID),
                                    ("cp_adjust", CP_PATH, 30),
                                    ("cp_destroy", CP_PATH)])

    def test_timeout_is_confirm_timeout_plus_margin(self):
        nm, cp = _shared()
        create_vlan_safe(nm, NEW, lambda: True, checkpoints=cp,
                         confirm_timeout_s=45)
        self.assertEqual(nm.calls[0], ("cp_create", 175))
        self.assertIn(("cp_adjust", CP_PATH, 55), nm.calls)

    def test_adjust_once_after_apply_before_confirm(self):
        nm, cp = _shared()

        def ask():
            nm.calls.append(("ask",))
            return True
        edit_vlan_safe(nm, "eth0.20", NEW, ask, checkpoints=cp)
        self.assertEqual(nm.calls, [("cp_create", CP_WINDOW),
                                    ("modify_vlan", "eth0.20", NEW),
                                    ("up", "eth0.30"),
                                    ("cp_adjust", CP_PATH, 30), ("ask",),
                                    ("cp_destroy", CP_PATH)])
        self.assertEqual(sum(c[0] == "cp_adjust" for c in nm.calls), 1)

    def test_adjust_error_rolls_back_via_checkpoint(self):
        nm, cp = _shared()
        cp.fail_adjust = True
        asked = []
        with self.assertRaises(CheckpointError):
            create_vlan_safe(nm, NEW, lambda: asked.append(1) or True,
                             checkpoints=cp)
        self.assertEqual(asked, [])
        self.assertEqual(nm.calls[-2:], [("cp_adjust", CP_PATH, 30),
                                         ("cp_rollback", CP_PATH)])

    def test_failed_device_rollback_error_surfaces(self):
        nm, cp = _shared()
        cp.fail_rollback = CheckpointError("device failed")
        with self.assertRaises(CheckpointError):
            delete_vlan_safe(nm, "eth0.20", lambda: False, checkpoints=cp)
        nm, cp = _shared()
        cp.fail_rollback = CheckpointError("device failed")
        nm.fail_up = True
        with self.assertRaises(CheckpointError) as ctx:
            create_vlan_safe(nm, NEW, lambda: True, checkpoints=cp)
        self.assertIsInstance(ctx.exception.__cause__, NmError)

    def test_not_confirmed_rolls_back_via_checkpoint_without_inprocess_undo(
            self):
        for run in (
                lambda nm, cp: create_vlan_safe(nm, NEW, lambda: False,
                                                checkpoints=cp),
                lambda nm, cp: edit_vlan_safe(nm, "eth0.20", NEW,
                                              lambda: False, checkpoints=cp),
                lambda nm, cp: delete_vlan_safe(nm, "eth0.20", lambda: False,
                                                checkpoints=cp)):
            nm, cp = _shared()
            self.assertFalse(run(nm, cp))
            self.assertEqual(nm.calls[0], ("cp_create", CP_WINDOW))
            self.assertEqual(nm.calls[-1], ("cp_rollback", CP_PATH))
            self.assertNotIn(("cp_destroy", CP_PATH), nm.calls)
            # only the forward change happened, no in-process undo step
            self.assertEqual(len(nm.calls), {"create_vlan": 5,
                                             "modify_vlan": 5,
                                             "delete_vlan": 4}[nm.calls[1][0]])

    def test_apply_error_rolls_back_via_checkpoint(self):
        nm, cp = _shared()
        nm.fail_up = True
        with self.assertRaises(NmError):
            create_vlan_safe(nm, NEW, lambda: True, checkpoints=cp)
        self.assertEqual(nm.calls, [("cp_create", CP_WINDOW), ("create_vlan", NEW),
                                    ("up", NEW_UUID),
                                    ("cp_rollback", CP_PATH)])

    def test_ask_confirm_error_rolls_back_via_checkpoint(self):
        nm, cp = _shared()

        def ask():
            raise ValueError("dialog failed")
        with self.assertRaises(ValueError):
            delete_vlan_safe(nm, "eth0.20", ask, checkpoints=cp)
        self.assertEqual(nm.calls, [("cp_create", CP_WINDOW),
                                    ("delete_vlan", "eth0.20"),
                                    ("cp_adjust", CP_PATH, 30),
                                    ("cp_rollback", CP_PATH)])

    def test_rollback_failure_surfaces_as_checkpoint_error(self):
        nm, cp = _shared()
        cp.fail_rollback = True
        with self.assertRaises(CheckpointError):
            create_vlan_safe(nm, NEW, lambda: False, checkpoints=cp)
        nm, cp = _shared()
        cp.fail_rollback = True
        nm.fail_up = True
        with self.assertRaises(CheckpointError) as ctx:
            create_vlan_safe(nm, NEW, lambda: True, checkpoints=cp)
        self.assertIsInstance(ctx.exception.__cause__, NmError)

    def test_falls_back_to_inprocess_undo_when_unavailable(self):
        nm = FakeNm(exported=OLD)
        cp = FakeCheckpoints(available=False, log=nm.calls)
        self.assertFalse(create_vlan_safe(nm, NEW, lambda: False,
                                          checkpoints=cp))
        self.assertEqual(nm.calls, [("create_vlan", NEW), ("up", NEW_UUID),
                                    ("delete_vlan", NEW_UUID)])

    def test_falls_back_to_inprocess_undo_when_create_fails(self):
        nm = FakeNm(exported=OLD)
        cp = FakeCheckpoints(fail_create=True, log=nm.calls)
        self.assertFalse(delete_vlan_safe(nm, "eth0.20", lambda: False,
                                          checkpoints=cp))
        self.assertEqual(nm.calls, [("cp_create", CP_WINDOW),
                                    ("delete_vlan", "eth0.20"),
                                    ("create_vlan", OLD), ("up", NEW_UUID)])


    def test_checkpoint_window_covers_two_activations(self):
        self.assertEqual(CP_WINDOW, 2 * ops.ACTIVATION_TIMEOUT_S
                         + ops.CONFIRM_TIMEOUT_S + ops.CHECKPOINT_MARGIN_S)


SOFT_TIMEOUT = NmError("Error: Timeout expired.", code=3)
SOFT_FAILED = NmError("Error: Connection activation failed.", code=4)
HARD = NmError("Error: Not authorized.", code=1)


class ActivationFailureTest(unittest.TestCase):
    def _asked(self):
        asked = []

        def ask():
            asked.append(1)
            return True
        return asked, ask

    def test_soft_up_failure_on_create_continues_to_confirm(self):
        for err in (SOFT_TIMEOUT, SOFT_FAILED):
            for with_cp in (False, True):
                nm = FakeNm(exported=OLD, fail_up=err)
                cp = FakeCheckpoints(log=nm.calls) if with_cp else None
                asked, ask = self._asked()
                self.assertTrue(create_vlan_safe(nm, NEW, ask,
                                                 checkpoints=cp))
                self.assertEqual(asked, [1])
                self.assertNotIn("delete_vlan", nm.names())
                self.assertNotIn("cp_rollback", nm.names())

    def test_soft_up_failure_on_edit_continues_to_confirm(self):
        for err in (SOFT_TIMEOUT, SOFT_FAILED):
            nm = FakeNm(exported=OLD, fail_up=err)
            cp = FakeCheckpoints(log=nm.calls)
            asked, ask = self._asked()
            self.assertTrue(edit_vlan_safe(nm, "eth0.20", NEW, ask,
                                           checkpoints=cp))
            self.assertEqual(asked, [1])
            self.assertNotIn("cp_rollback", nm.names())

    def test_hard_up_failure_rolls_back(self):
        nm = FakeNm(exported=OLD, fail_up=HARD)
        asked, ask = self._asked()
        with self.assertRaises(NmError):
            create_vlan_safe(nm, NEW, ask)
        self.assertEqual(asked, [])
        self.assertEqual(nm.calls[-1], ("delete_vlan", NEW_UUID))
        nm = FakeNm(exported=OLD, fail_up=HARD)
        cp = FakeCheckpoints(log=nm.calls)
        with self.assertRaises(NmError):
            edit_vlan_safe(nm, "eth0.20", NEW, ask, checkpoints=cp)
        self.assertEqual(asked, [])
        self.assertEqual(nm.calls[-1], ("cp_rollback", CP_PATH))


class InactiveVlanTest(unittest.TestCase):
    def _run(self, op):
        nm = FakeNm(exported=OLD)
        cp = FakeCheckpoints(log=nm.calls)
        result = op(nm, cp)
        self.assertFalse([c for c in nm.calls if c[0].startswith("cp_")])
        return nm, result

    def test_delete_inactive_uses_inprocess_undo_without_up(self):
        nm, result = self._run(lambda nm, cp: delete_vlan_safe(
            nm, "eth0.20", lambda: False, checkpoints=cp, active=False))
        self.assertFalse(result)
        self.assertEqual(nm.calls, [("delete_vlan", "eth0.20"),
                                    ("create_vlan", OLD)])

    def test_edit_inactive_uses_inprocess_undo_without_up(self):
        nm, result = self._run(lambda nm, cp: edit_vlan_safe(
            nm, "eth0.20", NEW, lambda: False, checkpoints=cp, active=False))
        self.assertFalse(result)
        self.assertEqual(nm.calls, [("modify_vlan", "eth0.20", NEW),
                                    ("modify_vlan", "eth0.30", OLD)])

    def test_edit_inactive_confirmed_does_not_activate(self):
        nm, result = self._run(lambda nm, cp: edit_vlan_safe(
            nm, "eth0.20", NEW, lambda: True, checkpoints=cp, active=False))
        self.assertTrue(result)
        self.assertNotIn("up", nm.names())

    def test_active_still_uses_checkpoint(self):
        for op in (lambda nm, cp: delete_vlan_safe(
                       nm, "eth0.20", lambda: True, checkpoints=cp,
                       active=True),
                   lambda nm, cp: edit_vlan_safe(
                       nm, "eth0.20", NEW, lambda: True, checkpoints=cp,
                       active=True)):
            nm = FakeNm(exported=OLD)
            cp = FakeCheckpoints(log=nm.calls)
            self.assertTrue(op(nm, cp))
            self.assertEqual(nm.calls[0], ("cp_create", CP_WINDOW))
            self.assertEqual(nm.calls[-1], ("cp_destroy", CP_PATH))

    def test_edit_uses_connection_name_to_follow_rename(self):
        old = VlanSpec("enp3s0", 10, "enp3s0.10", con_name="VLAN connection 1")
        new = VlanSpec("enp3s0", 10, "vlan10", con_name="VLAN connection 1")
        nm = FakeNm(exported=old)
        edit_vlan_safe(nm, "VLAN connection 1", new, lambda: True)
        self.assertEqual(nm.calls[-1], ("up", "VLAN connection 1"))


class DeactivateTest(unittest.TestCase):
    def test_confirmed_keeps_it_down(self):
        nm = FakeNm()
        self.assertTrue(deactivate_vlan_safe(nm, NEW_UUID, lambda: True))
        self.assertEqual(nm.calls, [("down", NEW_UUID)])

    def test_not_confirmed_brings_it_up_again(self):
        nm = FakeNm()
        self.assertFalse(deactivate_vlan_safe(nm, NEW_UUID, lambda: False))
        self.assertEqual(nm.calls, [("down", NEW_UUID), ("up", NEW_UUID)])

    def test_uses_checkpoint_when_available(self):
        nm = FakeNm()
        cp = FakeCheckpoints(log=nm.calls)
        self.assertFalse(deactivate_vlan_safe(nm, NEW_UUID, lambda: False,
                                              checkpoints=cp))
        self.assertEqual(nm.calls, [("cp_create", CP_WINDOW),
                                    ("down", NEW_UUID),
                                    ("cp_adjust", CP_PATH, 30),
                                    ("cp_rollback", CP_PATH)])


if __name__ == "__main__":
    unittest.main()
