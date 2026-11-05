"""NetworkManager flow simulation without a switch or live connections."""
import unittest

from vlanmanager.core.model import IpConfig, VlanSpec
from vlanmanager.core.nm import NmClient, NmError, _CONN_FIELDS
from vlanmanager.core.ops import create_vlan_safe
from vlanmanager.core.probe import verify_vlan


UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SPEC = VlanSpec("eth0", 4093, "eth0.4093", ipv4=IpConfig("auto"),
                ipv6=IpConfig("disabled"), autoconnect=False)


class UnpluggedEthernet:
    """Stateful nmcli boundary with a managed Ethernet port and no carrier."""

    def __init__(self):
        self.profile = None
        self.calls = []

    def __call__(self, argv, **_kwargs):
        self.calls.append(argv)
        if argv[:4] == ["connection", "add", "type", "vlan"]:
            fields = dict(zip(argv[4::2], argv[5::2]))
            self.profile = {
                "connection.id": fields["con-name"],
                "connection.interface-name": fields["ifname"],
                "vlan.parent": fields["dev"],
                "vlan.id": fields["id"],
                "ipv4.method": fields["ipv4.method"],
                "ipv6.method": fields["ipv6.method"],
                "connection.autoconnect": fields["connection.autoconnect"],
            }
            return f"Connection 'eth0.4093' ({UUID}) successfully added.\n"
        if argv[:3] == ["-w", "60", "connection"]:
            raise NmError("No carrier", code=4)
        if argv[:2] == ["connection", "delete"]:
            self.profile = None
            return ""
        if argv == ["-t", "-f", "NAME,UUID,TYPE", "connection", "show"]:
            return (f"eth0.4093:{UUID}:vlan\n" if self.profile else "")
        if argv == ["-t", "-f", "NAME,UUID,DEVICE", "connection",
                    "show", "--active"]:
            return ""
        if argv[:4] == ["-t", "-f", _CONN_FIELDS, "connection"]:
            return "".join(f"{key}:{self.profile.get(key, '')}\n"
                           for key in _CONN_FIELDS.split(","))
        if argv[:2] == ["-g", "IP4.GATEWAY"]:
            return "\n"
        if argv[:2] == ["-g", "IP6.GATEWAY"]:
            return "\n"
        raise AssertionError(f"Unexpected nmcli call: {argv}")


class SimulatedCheckpoint:
    def __init__(self, backend):
        self.backend = backend
        self.saved = None
        self.adjusted = False

    def available(self):
        return True

    def create(self, _timeout):
        self.saved = self.backend.profile
        return "/checkpoint/test"

    def adjust(self, _path, _timeout):
        self.adjusted = True

    def rollback(self, _path):
        self.backend.profile = self.saved

    def destroy(self, _path):
        self.saved = None


class SimulatedFlowTest(unittest.TestCase):
    def test_unconfirmed_create_reverts_without_carrier(self):
        backend = UnpluggedEthernet()
        client = NmClient(backend)
        checkpoint = SimulatedCheckpoint(backend)
        self.assertFalse(create_vlan_safe(client, SPEC, lambda: False,
                                          checkpoints=checkpoint))
        self.assertTrue(checkpoint.adjusted)
        self.assertEqual(client.list_vlans(), [])

    def test_confirmed_create_keeps_inactive_profile_and_reports_no_gateway(self):
        backend = UnpluggedEthernet()
        client = NmClient(backend)
        checkpoint = SimulatedCheckpoint(backend)
        self.assertTrue(create_vlan_safe(client, SPEC, lambda: True,
                                         checkpoints=checkpoint))
        vlans = client.list_vlans()
        self.assertEqual(len(vlans), 1)
        self.assertEqual(vlans[0].spec, SPEC)
        self.assertFalse(vlans[0].active)
        self.assertEqual(verify_vlan(client, SPEC.name), (False, "no_gateway"))


if __name__ == "__main__":
    unittest.main()
