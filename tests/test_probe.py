import unittest

from vlanmanager.core import probe


class FakeNm:
    def __init__(self, gw):
        self.gw = gw

    def gateway(self, name):
        return self.gw


class Recorder:
    def __init__(self, rc=0):
        self.rc = rc
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        return self.rc


class PingTests(unittest.TestCase):
    def test_ping_argv_ipv4(self):
        r = Recorder()
        self.assertTrue(probe.ping_gateway("10.0.0.1", 3, run=r))
        self.assertEqual(r.calls, [["ping", "-c", "1", "-W", "3", "10.0.0.1"]])

    def test_ping_argv_ipv6_uses_dash_6(self):
        r = Recorder()
        probe.ping_gateway("fd00::1", 2, run=r)
        self.assertEqual(r.calls,
                         [["ping", "-6", "-c", "1", "-W", "2", "fd00::1"]])

    def test_ping_false_on_nonzero(self):
        self.assertFalse(probe.ping_gateway("10.0.0.1", run=Recorder(1)))

    def test_ping_invalid_gateway_false(self):
        r = Recorder()
        self.assertFalse(probe.ping_gateway("not an ip", run=r))
        self.assertEqual(r.calls, [])

    def test_default_run_missing_binary(self):
        self.assertNotEqual(probe._run_rc(["/nonexistent/binary-xyz"]), 0)


class VerifyTests(unittest.TestCase):
    def test_verify_no_gateway(self):
        called = []
        res = probe.verify_vlan(FakeNm(None), "v", ping=lambda g: called.append(g))
        self.assertEqual(res, (False, "no_gateway"))
        self.assertEqual(called, [])

    def test_verify_ping_failed(self):
        res = probe.verify_vlan(FakeNm("10.0.0.1"), "v", ping=lambda g: False)
        self.assertEqual(res, (False, "ping_failed"))

    def test_verify_ok(self):
        res = probe.verify_vlan(FakeNm("10.0.0.1"), "v", ping=lambda g: True)
        self.assertEqual(res, (True, "ok"))


class ModuleTests(unittest.TestCase):
    def test_module_available_false_when_modprobe_fails_and_no_sysfs(self):
        self.assertFalse(probe.module_8021q_available(
            run=lambda a: 1, sysfs_exists=lambda: False))

    def test_module_available_via_modprobe(self):
        r = Recorder(0)
        self.assertTrue(probe.module_8021q_available(
            run=r, sysfs_exists=lambda: False))
        self.assertEqual(r.calls, [["modprobe", "-n", "8021q"]])

    def test_module_available_via_sysfs(self):
        self.assertTrue(probe.module_8021q_available(
            run=lambda a: 1, sysfs_exists=lambda: True))


if __name__ == "__main__":
    unittest.main()
