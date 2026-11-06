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

    def test_manual_address_and_gateway_match_ip_family(self):
        wrong_v4 = spec(ipv4=IpConfig("manual", "2001:db8::2/64",
                                          "2001:db8::1"))
        self.assertIn("address_invalid", validate(wrong_v4, []))
        self.assertIn("gateway_invalid", validate(wrong_v4, []))
        wrong_v6 = spec(ipv6=IpConfig("manual", "192.0.2.2/24",
                                          "192.0.2.1"))
        self.assertIn("address_invalid", validate(wrong_v6, []))
        self.assertIn("gateway_invalid", validate(wrong_v6, []))

    def test_manual_dns_addresses_are_valid_and_match_ip_family(self):
        bad = spec(ipv4=IpConfig("manual", "192.0.2.2/24", dns=("garbage",)))
        self.assertIn("dns_invalid", validate(bad, []))
        wrong_family = spec(ipv6=IpConfig("manual", "2001:db8::2/64",
                                              dns=("192.0.2.53",)))
        self.assertIn("dns_invalid", validate(wrong_family, []))
        good = spec(ipv4=IpConfig("manual", "192.0.2.2/24",
                                   dns=("192.0.2.53", "198.51.100.53")))
        self.assertNotIn("dns_invalid", validate(good, []))

    def test_mtu_range(self):
        self.assertIn("mtu_range", validate(spec(mtu=100), []))
        self.assertNotIn("mtu_range", validate(spec(mtu=None), []))
        self.assertNotIn("mtu_range", validate(spec(mtu=1500), []))

    def test_name_must_be_valid_and_unused(self):
        for bad in ("a b", "a/b", "a:b", ".", ".."):
            self.assertIn("name_invalid", validate(spec(name=bad), []), bad)
        self.assertIn("name_taken", validate(spec(name="lo"), []))
        self.assertIn("name_taken", validate(spec(name="eth1"), [], reserved=("eth1",)))
        other = spec(parent="eth1", vlan_id=99, name="vlan99")
        self.assertIn("name_taken", validate(spec(name="vlan99"), [other]))
        self.assertNotIn("name_taken", validate(spec(name="vlan99"), [other], editing="vlan99"))
        self.assertEqual(validate(spec(name="eth0.20"), []), [])

    def test_ip_sanity_checks(self):
        net = spec(ipv4=IpConfig("manual", "192.168.60.0/24"))
        self.assertIn("address_network", validate(net, []))
        same = spec(ipv4=IpConfig("manual", "192.168.60.5/24", "192.168.60.5"))
        self.assertIn("gateway_same", validate(same, []))
        out = spec(ipv4=IpConfig("manual", "192.168.60.5/24", "10.0.0.1"))
        self.assertIn("gateway_outside", validate(out, []))
        ok = spec(ipv4=IpConfig("manual", "192.168.60.5/24", "192.168.60.1"))
        self.assertEqual(validate(ok, []), [])
        v6 = spec(ipv6=IpConfig("manual", "2001:db8::5/64", "fe80::1"))
        self.assertEqual(validate(v6, []), [])

    def test_mtu_cannot_exceed_parent(self):
        self.assertIn("mtu_parent", validate(spec(mtu=9000), [], parent_mtu=1500))
        self.assertNotIn("mtu_parent", validate(spec(mtu=1500), [], parent_mtu=1500))
        self.assertNotIn("mtu_parent", validate(spec(mtu=9000), [], parent_mtu=None))


if __name__ == "__main__":
    unittest.main()
