import unittest

from vlanmanager.core.model import IpConfig, VlanSpec
from vlanmanager.core.nm import NmError
from vlanmanager.core.ops import (create_vlan_safe, delete_vlan_safe,
                                  edit_vlan_safe)


class FakeNm:
    def __init__(self, exported=None, fail_up=False):
        self.calls = []
        self.exported = exported
        self.fail_up = fail_up

    def create_vlan(self, spec):
        self.calls.append(("create_vlan", spec))

    def modify_vlan(self, name, spec):
        self.calls.append(("modify_vlan", name, spec))

    def delete_vlan(self, name):
        self.calls.append(("delete_vlan", name))

    def up(self, name):
        self.calls.append(("up", name))
        if self.fail_up:
            raise NmError("activation failed")

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
        self.assertEqual(nm.calls, [("create_vlan", NEW), ("up", "eth0.30")])

    def test_create_activation_fails_removes_connection(self):
        nm = FakeNm(fail_up=True)
        with self.assertRaises(NmError):
            create_vlan_safe(nm, NEW, lambda: True)
        self.assertEqual(nm.calls[-1], ("delete_vlan", "eth0.30"))

    def test_create_not_confirmed_deletes(self):
        nm = FakeNm()
        self.assertFalse(create_vlan_safe(nm, NEW, lambda: False))
        self.assertEqual(nm.calls[-1], ("delete_vlan", "eth0.30"))


class DeleteTest(unittest.TestCase):
    def test_delete_confirmed(self):
        nm = FakeNm(exported=OLD)
        self.assertTrue(delete_vlan_safe(nm, "eth0.20", lambda: True))
        self.assertEqual(nm.calls, [("delete_vlan", "eth0.20")])

    def test_delete_not_confirmed_recreates_identical_spec(self):
        nm = FakeNm(exported=OLD)
        self.assertFalse(delete_vlan_safe(nm, "eth0.20", lambda: False))
        self.assertEqual(nm.calls[-2:],
                         [("create_vlan", OLD), ("up", "eth0.20")])


class EditTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
