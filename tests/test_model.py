import unittest

from vlanmanager.core.model import IpConfig, VlanSpec, default_name, validate


def spec(**kw):
    base = dict(parent="eth0", vlan_id=20, name="eth0.20")
    base.update(kw)
    return VlanSpec(**base)


class ModelTests(unittest.TestCase):
    def test_default_name(self):
        self.assertEqual(default_name("eth0", 20), "eth0.20")

    def test_id_bounds(self):
        self.assertIn("id_range", validate(spec(vlan_id=0), []))
        self.assertIn("id_range", validate(spec(vlan_id=4095), []))
        self.assertNotIn("id_range", validate(spec(vlan_id=1), []))
        self.assertNotIn("id_range", validate(spec(vlan_id=4094), []))

    def test_name_too_long(self):
        self.assertIn("name_len", validate(spec(name="a" * 16), []))
        self.assertNotIn("name_len", validate(spec(name="a" * 15), []))
        self.assertIn("name_empty", validate(spec(name=""), []))

    def test_duplicate_parent_id(self):
        other = spec(name="custom")
        self.assertIn("duplicate", validate(spec(), [other]))
        self.assertNotIn("duplicate", validate(other, [other], editing="custom"))

    def test_manual_requires_valid_cidr(self):
        bad = spec(ipv4=IpConfig("manual", "192.168.20.5"))
        self.assertIn("address_invalid", validate(bad, []))
        ok = spec(ipv4=IpConfig("manual", "192.168.20.5/24"))
        self.assertNotIn("address_invalid", validate(ok, []))
        ok6 = spec(ipv6=IpConfig("manual", "fd00::5/64"))
        self.assertEqual(validate(ok6, []), [])
        gw = spec(ipv4=IpConfig("manual", "192.168.20.5/24", "not-an-ip"))
        self.assertIn("gateway_invalid", validate(gw, []))
        auto = spec(ipv4=IpConfig("auto", "garbage"))
        self.assertEqual(validate(auto, []), [])

    def test_mtu_range(self):
        self.assertIn("mtu_range", validate(spec(mtu=100), []))
        self.assertNotIn("mtu_range", validate(spec(mtu=None), []))
        self.assertNotIn("mtu_range", validate(spec(mtu=1500), []))


if __name__ == "__main__":
    unittest.main()
