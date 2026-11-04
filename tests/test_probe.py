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
        self.assertTrue(probe.ping_gateway("10.0.0.1", "v", 3, run=r))
        self.assertEqual(r.calls, [["ping", "-I", "v", "-c", "1", "-W", "3", "10.0.0.1"]])

    def test_ping_argv_ipv6_uses_dash_6(self):
        r = Recorder()
        probe.ping_gateway("fd00::1", "v", 2, run=r)
        self.assertEqual(r.calls,
                         [["ping", "-6", "-I", "v", "-c", "1", "-W", "2", "fd00::1"]])

    def test_ping_argv_binds_interface(self):
        r = Recorder()
        probe.ping_gateway("10.0.0.1", "eth0.20", run=r)
        self.assertEqual(r.calls, [["ping", "-I", "eth0.20", "-c", "1",
                                    "-W", "2", "10.0.0.1"]])

    def test_ping_false_on_nonzero(self):
        self.assertFalse(probe.ping_gateway("10.0.0.1", "v", run=Recorder(1)))

    def test_ping_invalid_gateway_false(self):
        r = Recorder()
        self.assertFalse(probe.ping_gateway("not an ip", "v", run=r))
        self.assertEqual(r.calls, [])

    def test_default_run_missing_binary(self):
        self.assertNotEqual(probe._run_rc(["/nonexistent/binary-xyz"]), 0)


class VerifyTests(unittest.TestCase):
    def test_verify_no_gateway(self):
        called = []
        res = probe.verify_vlan(FakeNm(None), "v", ping=lambda g, i: called.append(g))
        self.assertEqual(res, (False, "no_gateway"))
        self.assertEqual(called, [])

    def test_verify_ping_failed(self):
        res = probe.verify_vlan(FakeNm("10.0.0.1"), "v", ping=lambda g, i: False)
        self.assertEqual(res, (False, "ping_failed"))

    def test_verify_passes_interface(self):
        seen = []
        probe.verify_vlan(FakeNm("10.0.0.1"), "eth0.20",
                          ping=lambda g, i: seen.append((g, i)) or True)
        self.assertEqual(seen, [("10.0.0.1", "eth0.20")])

    def test_verify_ok(self):
        res = probe.verify_vlan(FakeNm("10.0.0.1"), "v", ping=lambda g, i: True)
        self.assertEqual(res, (True, "ok"))


class ModuleTests(unittest.TestCase):
    def avail(self, run=lambda a: 1, sysfs=False, builtin=False, ko=False):
        return probe.module_8021q_available(
            run=run, sysfs_exists=lambda: sysfs,
            builtin_has=lambda: builtin, ko_exists=lambda: ko)

    def test_8021q_false_when_nothing_found(self):
        self.assertFalse(self.avail())

    def test_module_available_via_modprobe(self):
        r = Recorder(0)
        self.assertTrue(self.avail(run=r))
        self.assertEqual(r.calls, [["modprobe", "-n", "8021q"]])

    def test_modprobe_tried_by_absolute_path(self):
        r = Recorder(127)
        self.assertFalse(self.avail(run=r))
        self.assertEqual([c[0] for c in r.calls],
                         ["modprobe", "/sbin/modprobe", "/usr/sbin/modprobe"])

    def test_module_available_via_sysfs(self):
        self.assertTrue(self.avail(sysfs=True))

    def test_8021q_builtin_detected(self):
        self.assertTrue(self.avail(builtin=True))

    def test_8021q_ko_file_detected(self):
        self.assertTrue(self.avail(ko=True))

    def test_never_raises(self):
        def boom():
            raise OSError("x")
        self.assertFalse(probe.module_8021q_available(
            run=lambda a: 1, sysfs_exists=lambda: False,
            builtin_has=boom, ko_exists=boom))


if __name__ == "__main__":
    unittest.main()
