import unittest

from vlanmanager.core.model import IpConfig, VlanSpec
from vlanmanager.core.nm import NmClient, NmError, split_terse

CONN_FIELDS = ("vlan.parent,vlan.id,ipv4.method,ipv4.addresses,ipv4.gateway,"
               "ipv4.dns,ipv6.method,ipv6.addresses,ipv6.gateway,ipv6.dns,"
               "connection.autoconnect,802-3-ethernet.mtu")


def conn_argv(name):
    return ("-t", "-f", CONN_FIELDS, "connection", "show", name)


class FakeRunner:
    def __init__(self, outputs):
        self.outputs = outputs
        self.calls = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        out = self.outputs[tuple(argv)]
        if isinstance(out, Exception):
            raise out
        return out


STATIC = """\
vlan.parent:eth0
vlan.id:20
ipv4.method:manual
ipv4.addresses:192.168.20.5/24
ipv4.gateway:192.168.20.1
ipv4.dns:192.168.20.1, 1.1.1.1
ipv6.method:disabled
ipv6.addresses:
ipv6.gateway:
ipv6.dns:
connection.autoconnect:yes
802-3-ethernet.mtu:0
"""


class SplitTerseTest(unittest.TestCase):
    def test_split_terse_keeps_escaped_colons(self):
        self.assertEqual(
            split_terse(r"eth0:aa\:bb\:cc\:dd\:ee\:ff:connected"),
            ["eth0", "aa:bb:cc:dd:ee:ff", "connected"])

    def test_split_terse_ipv6(self):
        self.assertEqual(split_terse(r"fd00\:\:5/64"), ["fd00::5/64"])


class NmClientTest(unittest.TestCase):
    def test_list_nics_only_ethernet(self):
        r = FakeRunner({
            ("-t", "-f", "DEVICE,TYPE,STATE", "device"):
                "eth0:ethernet:connected\nwlan0:wifi:connected\n"
                "lo:loopback:unmanaged\neth1:ethernet:unmanaged\n",
            ("-g", "GENERAL.HWADDR", "device", "show", "eth0"):
                r"AA\:BB\:CC\:DD\:EE\:01" + "\n",
            ("-g", "GENERAL.HWADDR", "device", "show", "eth1"):
                r"AA\:BB\:CC\:DD\:EE\:02" + "\n",
        })
        nics = NmClient(r).list_nics()
        self.assertEqual([n.name for n in nics], ["eth0", "eth1"])
        self.assertEqual(nics[0].mac, "AA:BB:CC:DD:EE:01")
        self.assertEqual(nics[0].state, "connected")
        self.assertTrue(nics[0].managed)
        self.assertFalse(nics[1].managed)

    def test_list_vlans_marks_active(self):
        r = FakeRunner({
            ("-t", "-f", "NAME,UUID,TYPE", "connection", "show"):
                "Wired:u-0:802-3-ethernet\neth0.20:u-20:vlan\n"
                "eth0.30:u-30:vlan\n",
            ("-t", "-f", "NAME,UUID,DEVICE", "connection", "show",
             "--active"): "Wired:u-0:eth0\neth0.20:u-20:eth0.20\n",
            conn_argv("u-20"): STATIC,
            conn_argv("u-30"): STATIC.replace("vlan.id:20", "vlan.id:30"),
        })
        vlans = NmClient(r).list_vlans()
        self.assertEqual([v.spec.name for v in vlans],
                         ["eth0.20", "eth0.30"])
        self.assertEqual([v.active for v in vlans], [True, False])
        self.assertEqual(vlans[0].uuid, "u-20")
        self.assertEqual(vlans[1].spec.vlan_id, 30)

    def test_export_spec_static_ipv4(self):
        r = FakeRunner({conn_argv("eth0.20"): STATIC})
        self.assertEqual(
            NmClient(r).export_spec("eth0.20"),
            VlanSpec(parent="eth0", vlan_id=20, name="eth0.20",
                     ipv4=IpConfig("manual", "192.168.20.5/24",
                                   "192.168.20.1", ("192.168.20.1", "1.1.1.1")),
                     ipv6=IpConfig("disabled"),
                     autoconnect=True, mtu=None))

    def test_export_spec_resolves_uuid_parent_and_mtu(self):
        uuid = "11111111-2222-3333-4444-555555555555"
        r = FakeRunner({
            conn_argv("v"): STATIC.replace("vlan.parent:eth0",
                                           "vlan.parent:" + uuid)
            .replace("mtu:0", "mtu:1400").replace("autoconnect:yes",
                                                  "autoconnect:no"),
            ("-g", "connection.interface-name", "connection", "show", uuid):
                "eth0\n",
        })
        spec = NmClient(r).export_spec("v")
        self.assertEqual(spec.parent, "eth0")
        self.assertEqual(spec.mtu, 1400)
        self.assertFalse(spec.autoconnect)

    def test_gateway(self):
        r = FakeRunner({conn_argv("eth0.20"): STATIC})
        self.assertEqual(NmClient(r).gateway("eth0.20"), "192.168.20.1")

    def test_is_running_false_when_nmcli_errors(self):
        r = FakeRunner({("-t", "-f", "RUNNING", "general"):
                        NmError("not running")})
        self.assertFalse(NmClient(r).is_running())

    def test_is_running_true(self):
        r = FakeRunner({("-t", "-f", "RUNNING", "general"): "running\n"})
        self.assertTrue(NmClient(r).is_running())


if __name__ == "__main__":
    unittest.main()
