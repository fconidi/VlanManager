import unittest

from vlanmanager.core.model import IpConfig, VlanSpec
from vlanmanager.core.nm import NmClient, NmError, split_terse

CONN_FIELDS = ("vlan.parent,vlan.id,ipv4.method,ipv4.addresses,ipv4.gateway,"
               "ipv4.dns,ipv6.method,ipv6.addresses,ipv6.gateway,ipv6.dns,"
               "connection.autoconnect,802-3-ethernet.mtu")


def conn_argv(name):
    return ("-t", "-f", CONN_FIELDS, "connection", "show", name)


UUID = "11111111-2222-3333-4444-555555555555"


def conn_argv_uuid(uuid):
    return ("-t", "-f", CONN_FIELDS, "connection", "show", "uuid", uuid)


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

    def test_gateway_reads_active_config_not_profile(self):
        r = FakeRunner({("-g", "IP4.GATEWAY", "device", "show", "eth0.20"):
                        "10.1.1.1\n"})
        self.assertEqual(NmClient(r).gateway("eth0.20"), "10.1.1.1")
        self.assertEqual(len(r.calls), 1)

    def test_gateway_falls_back_to_ipv6(self):
        r = FakeRunner({
            ("-g", "IP4.GATEWAY", "device", "show", "v"): "\n",
            ("-g", "IP6.GATEWAY", "device", "show", "v"): "fd00::1\n"})
        self.assertEqual(NmClient(r).gateway("v"), "fd00::1")

    def test_gateway_dash_dash_is_none(self):
        r = FakeRunner({
            ("-g", "IP4.GATEWAY", "device", "show", "v"): "--\n",
            ("-g", "IP6.GATEWAY", "device", "show", "v"): "--\n"})
        self.assertIsNone(NmClient(r).gateway("v"))

    def test_gateway_error_is_none(self):
        r = FakeRunner({
            ("-g", "IP4.GATEWAY", "device", "show", "v"): NmError("gone"),
            ("-g", "IP6.GATEWAY", "device", "show", "v"): NmError("gone")})
        self.assertIsNone(NmClient(r).gateway("v"))

    def test_export_spec_by_uuid_addresses_uuid_and_reads_name(self):
        r = FakeRunner({
            conn_argv_uuid(UUID): STATIC,
            ("-g", "connection.id", "connection", "show", "uuid", UUID):
                "eth0.20\n"})
        self.assertEqual(NmClient(r).export_spec(UUID).name, "eth0.20")

    def test_is_running_false_when_nmcli_errors(self):
        r = FakeRunner({("-t", "-f", "RUNNING", "general"):
                        NmError("not running")})
        self.assertFalse(NmClient(r).is_running())

    def test_is_running_true(self):
        r = FakeRunner({("-t", "-f", "RUNNING", "general"): "running\n"})
        self.assertTrue(NmClient(r).is_running())


class WriteRunner:
    def __init__(self, error=None, output=None):
        self.calls = []
        self.error = error
        self.output = ("Connection 'x' (%s) successfully added.\n" % UUID
                       if output is None else output)

    def __call__(self, argv):
        self.calls.append(list(argv))
        if self.error:
            raise self.error
        return self.output


class NmWriteTest(unittest.TestCase):
    def test_create_vlan_dhcp(self):
        r = WriteRunner()
        NmClient(r).create_vlan(VlanSpec("eth0", 20, "eth0.20"))
        self.assertEqual(r.calls, [[
            "connection", "add", "type", "vlan", "con-name", "eth0.20",
            "ifname", "eth0.20", "dev", "eth0", "id", "20",
            "ipv4.method", "auto", "ipv6.method", "auto",
            "connection.autoconnect", "yes"]])

    def test_create_vlan_static(self):
        r = WriteRunner()
        spec = VlanSpec("eth0", 20, "eth0.20", ipv4=IpConfig(
            "manual", "192.168.20.5/24", "192.168.20.1",
            ("1.1.1.1", "9.9.9.9")))
        NmClient(r).create_vlan(spec)
        argv = r.calls[0]
        i = argv.index("ipv4.method")
        self.assertEqual(argv[i:i + 8], [
            "ipv4.method", "manual", "ipv4.addresses", "192.168.20.5/24",
            "ipv4.gateway", "192.168.20.1", "ipv4.dns", "1.1.1.1,9.9.9.9"])

    def test_create_with_mtu_adds_802_3_ethernet_mtu(self):
        r = WriteRunner()
        NmClient(r).create_vlan(VlanSpec("eth0", 20, "eth0.20", mtu=1400))
        argv = r.calls[0]
        i = argv.index("802-3-ethernet.mtu")
        self.assertEqual(argv[i + 1], "1400")

    def test_delete_vlan(self):
        r = WriteRunner()
        NmClient(r).delete_vlan("eth0.20")
        self.assertEqual(r.calls, [["connection", "delete", "eth0.20"]])

    def test_create_returns_uuid(self):
        r = WriteRunner(output="Connection 'eth0.20' (%s) successfully "
                               "added.\n" % UUID)
        self.assertEqual(
            NmClient(r).create_vlan(VlanSpec("eth0", 20, "eth0.20")), UUID)

    def test_create_without_uuid_in_output_raises(self):
        with self.assertRaises(NmError):
            NmClient(WriteRunner(output="ok\n")).create_vlan(
                VlanSpec("eth0", 20, "eth0.20"))

    def test_delete_by_uuid_argv(self):
        r = WriteRunner()
        NmClient(r).delete_vlan(UUID)
        self.assertEqual(r.calls, [["connection", "delete", "uuid", UUID]])

    def test_up_down_modify_by_uuid_argv(self):
        r = WriteRunner()
        c = NmClient(r)
        c.up(UUID)
        c.down(UUID)
        c.modify_vlan(UUID, VlanSpec("eth0", 20, "eth0.20"))
        self.assertEqual(r.calls[0], ["connection", "up", "uuid", UUID])
        self.assertEqual(r.calls[1], ["connection", "down", "uuid", UUID])
        self.assertEqual(r.calls[2][:4], ["connection", "modify", "uuid", UUID])

    def test_modify_clears_removed_values(self):
        r = WriteRunner()
        NmClient(r).modify_vlan("eth0.20", VlanSpec("eth0", 20, "eth0.20"))
        argv = r.calls[0]
        self.assertEqual(argv[:3], ["connection", "modify", "eth0.20"])
        for key in ("ipv4.addresses", "ipv4.gateway", "ipv4.dns"):
            self.assertEqual(argv[argv.index(key) + 1], "")

    def test_up_down_argv(self):
        r = WriteRunner()
        c = NmClient(r)
        c.up("eth0.20")
        c.down("eth0.20")
        self.assertEqual(r.calls, [["connection", "up", "eth0.20"],
                                   ["connection", "down", "eth0.20"]])

    def test_error_propagates_with_message(self):
        c = NmClient(WriteRunner(NmError("Not authorized")))
        with self.assertRaises(NmError) as cm:
            c.delete_vlan("eth0.20")
        self.assertEqual(cm.exception.message, "Not authorized")


if __name__ == "__main__":
    unittest.main()
