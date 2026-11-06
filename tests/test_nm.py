import subprocess
import unittest
from unittest import mock

from vlanmanager.core import nm as nm_mod

from vlanmanager.core.model import IpConfig, VlanSpec
from vlanmanager.core.nm import NmClient, NmError, split_terse

CONN_FIELDS = ("vlan.parent,vlan.id,ipv4.method,ipv4.addresses,ipv4.gateway,"
               "ipv4.dns,ipv4.never-default,ipv6.method,ipv6.addresses,"
               "ipv6.gateway,ipv6.dns,ipv6.never-default,"
               "connection.autoconnect,802-3-ethernet.mtu,connection.id,"
               "connection.interface-name")


def conn_argv(name):
    return ("-t", "-f", CONN_FIELDS, "connection", "show", name)


UUID = "11111111-2222-3333-4444-555555555555"


def conn_argv_uuid(uuid):
    return ("-t", "-f", CONN_FIELDS, "connection", "show", "uuid", uuid)


class FakeRunner:
    def __init__(self, outputs):
        self.outputs = outputs
        self.calls = []

    def __call__(self, argv, **kw):
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
ipv4.never-default:yes
ipv6.method:disabled
ipv6.addresses:
ipv6.gateway:
ipv6.dns:
connection.autoconnect:yes
802-3-ethernet.mtu:0
connection.id:eth0.20
connection.interface-name:eth0.20
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
            conn_argv("u-30"): STATIC.replace("vlan.id:20", "vlan.id:30")
            .replace("eth0.20", "eth0.30"),
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
                                   "192.168.20.1", ("192.168.20.1", "1.1.1.1"), True),
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
            ("-g", "IP6.GATEWAY", "device", "show", "v"): r"fd00\:\:1" + "\n"})
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
        r = FakeRunner({conn_argv_uuid(UUID): STATIC})
        self.assertEqual(NmClient(r).export_spec(UUID).name, "eth0.20")
        self.assertEqual(len(r.calls), 1)

    def test_export_spec_separates_connection_and_interface_names(self):
        text = (STATIC.replace("connection.id:eth0.20",
                               "connection.id:VLAN connection 1")
                .replace("connection.interface-name:eth0.20",
                         "connection.interface-name:enp3s0.10"))
        r = FakeRunner({conn_argv_uuid(UUID): text})
        spec = NmClient(r).export_spec(UUID)
        self.assertEqual(spec.name, "enp3s0.10")
        self.assertEqual(spec.con_name, "VLAN connection 1")
        self.assertEqual(spec.connection_name, "VLAN connection 1")

    def test_export_spec_same_names_has_no_separate_con_name(self):
        r = FakeRunner({conn_argv("eth0.20"): STATIC})
        spec = NmClient(r).export_spec("eth0.20")
        self.assertIsNone(spec.con_name)
        self.assertEqual(spec.connection_name, "eth0.20")

    def test_export_spec_unescapes_uuid_parent_lookup(self):
        r = FakeRunner({
            conn_argv("v"): STATIC.replace("vlan.parent:eth0",
                                           "vlan.parent:" + UUID),
            ("-g", "connection.interface-name", "connection", "show", UUID):
                r"we\:ird" + "\n"})
        self.assertEqual(NmClient(r).export_spec("v").parent, "we:ird")

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
        self.kwargs = []
        self.error = error
        self.output = ("Connection 'x' (%s) successfully added.\n" % UUID
                       if output is None else output)

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        self.kwargs.append(kw)
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
            "ipv4.method", "auto", "ipv4.never-default", "no",
            "ipv6.method", "auto", "ipv6.never-default", "no",
            "connection.autoconnect", "yes"]])

    def test_create_vlan_static(self):
        r = WriteRunner()
        spec = VlanSpec("eth0", 20, "eth0.20", ipv4=IpConfig(
            "manual", "192.168.20.5/24", "192.168.20.1",
            ("1.1.1.1", "9.9.9.9")))
        NmClient(r).create_vlan(spec)
        argv = r.calls[0]
        i = argv.index("ipv4.method")
        self.assertEqual(argv[i:i + 10], [
            "ipv4.method", "manual", "ipv4.never-default", "no",
            "ipv4.addresses", "192.168.20.5/24",
            "ipv4.gateway", "192.168.20.1", "ipv4.dns", "1.1.1.1,9.9.9.9"])

    def test_never_default_is_written_and_read(self):
        r = WriteRunner()
        spec = VlanSpec("eth0", 20, "eth0.20", ipv4=IpConfig(never_default=True))
        NmClient(r).create_vlan(spec)
        argv = r.calls[0]
        self.assertEqual(argv[argv.index("ipv4.never-default") + 1], "yes")
        self.assertEqual(argv[argv.index("ipv6.never-default") + 1], "no")

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
        spec = VlanSpec("eth0", 20, "eth0.20")
        c.modify_vlan(UUID, spec, spec)
        self.assertEqual(r.calls[0], ["-w", "60", "connection", "up", "uuid",
                                      UUID])
        self.assertEqual(r.calls[1], ["connection", "down", "uuid", UUID])
        self.assertEqual(r.calls[2][:4], ["connection", "modify", "uuid", UUID])

    def test_modify_clears_removed_values(self):
        r = WriteRunner()
        spec = VlanSpec("eth0", 20, "eth0.20")
        NmClient(r).modify_vlan("eth0.20", spec, spec)
        argv = r.calls[0]
        self.assertEqual(argv[:3], ["connection", "modify", "eth0.20"])
        for key in ("ipv4.addresses", "ipv4.gateway", "ipv4.dns"):
            self.assertEqual(argv[argv.index(key) + 1], "")

    def test_up_down_argv(self):
        r = WriteRunner()
        c = NmClient(r)
        c.up("eth0.20")
        c.down("eth0.20")
        self.assertEqual(r.calls, [["-w", "60", "connection", "up", "eth0.20"],
                                   ["connection", "down", "eth0.20"]])
        # activation gets a longer subprocess limit than other calls
        self.assertEqual(r.kwargs[0], {"timeout_s": 70})
        self.assertEqual(r.kwargs[1], {})

    def _modify(self, current, new):
        r = WriteRunner()
        NmClient(r).modify_vlan(UUID, new, current)
        return r.calls[0]

    def test_modify_ip_only_sends_no_rename(self):
        current = VlanSpec("enp3s0", 10, "enp3s0.10",
                           con_name="VLAN connection 1")
        argv = self._modify(current, VlanSpec(
            "enp3s0", 10, "enp3s0.10", con_name="VLAN connection 1",
            ipv4=IpConfig("manual", "10.0.0.5/24")))
        self.assertNotIn("connection.id", argv)
        self.assertNotIn("connection.interface-name", argv)

    def test_modify_rename_interface_only(self):
        current = VlanSpec("enp3s0", 10, "enp3s0.10",
                           con_name="VLAN connection 1")
        argv = self._modify(current, VlanSpec(
            "enp3s0", 10, "vlan10", con_name="VLAN connection 1"))
        self.assertNotIn("connection.id", argv)
        i = argv.index("connection.interface-name")
        self.assertEqual(argv[i + 1], "vlan10")

    def test_modify_without_current_reads_stored_spec(self):
        outputs = {conn_argv_uuid(UUID): STATIC}

        def run(argv, **kw):
            run.calls.append(list(argv))
            return outputs.get(tuple(argv), "")
        run.calls = []
        NmClient(run).modify_vlan(UUID, VlanSpec("eth0", 20, "eth0.20"))
        self.assertEqual(run.calls[0], list(conn_argv_uuid(UUID)))
        self.assertNotIn("connection.interface-name", run.calls[1])

    def test_create_passes_con_name_and_ifname_separately(self):
        r = WriteRunner()
        NmClient(r).create_vlan(VlanSpec("enp3s0", 10, "enp3s0.10",
                                         con_name="VLAN connection 1"))
        argv = r.calls[0]
        self.assertEqual(argv[argv.index("con-name") + 1],
                         "VLAN connection 1")
        self.assertEqual(argv[argv.index("ifname") + 1], "enp3s0.10")

    def test_error_propagates_with_message(self):
        c = NmClient(WriteRunner(NmError("Not authorized")))
        with self.assertRaises(NmError) as cm:
            c.delete_vlan("eth0.20")
        self.assertEqual(cm.exception.message, "Not authorized")


class SubprocessRunnerTest(unittest.TestCase):
    def _run(self, returncode, stderr="", **kw):
        proc = subprocess.CompletedProcess([], returncode, "out\n", stderr)
        with mock.patch.object(nm_mod.subprocess, "run",
                               return_value=proc) as run:
            try:
                return nm_mod.subprocess_runner(["general"], **kw), run
            except NmError as exc:
                return exc, run

    def test_exit_status_is_kept_on_error(self):
        exc, _ = self._run(3, "Error: Timeout expired.\n")
        self.assertEqual(exc.code, 3)
        self.assertEqual(exc.message, "Error: Timeout expired.")

    def test_default_and_custom_timeout(self):
        _, run = self._run(0)
        self.assertEqual(run.call_args.kwargs["timeout"], 30)
        _, run = self._run(0, timeout_s=70)
        self.assertEqual(run.call_args.kwargs["timeout"], 70)

    def test_code_is_none_for_internal_errors(self):
        self.assertIsNone(NmError("nmcli_timeout").code)


if __name__ == "__main__":
    unittest.main()
