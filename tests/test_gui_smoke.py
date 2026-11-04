import os
import threading
import time
import unittest

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk
    HAVE_GTK = Gtk.init_check()[0]
except (ImportError, ValueError):
    HAVE_GTK = False

from vlanmanager.core.model import IpConfig, Nic, Vlan, VlanSpec
from vlanmanager.core.nm import NmError
from vlanmanager.i18n import set_language, tr

if HAVE_GTK:
    from vlanmanager.gui import worker, window


class FakeNm:
    def __init__(self, running=True, nics=None, vlans=None, error=None):
        self.running = running
        self.error = error
        self.calls = []
        self.nics = nics if nics is not None else [
            Nic("eth0", "aa:bb:cc:dd:ee:01", "connected", True),
            Nic("eth1", "aa:bb:cc:dd:ee:02", "unmanaged", False)]
        self.vlans = vlans if vlans is not None else [
            Vlan(VlanSpec("eth0", 20, "eth0.20",
                          ipv4=IpConfig("manual", "192.168.20.5/24")),
                 "uuid-1", True)]

    def is_running(self):
        self.calls.append(("is_running", threading.get_ident()))
        return self.running

    def list_nics(self):
        if self.error:
            raise self.error
        return list(self.nics)

    def list_vlans(self):
        return list(self.vlans)


def pump(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > end:
            return False
        while Gtk.events_pending():
            Gtk.main_iteration()
        time.sleep(0.005)
    return True


def tree_rows(win):
    rows = []

    def walk(model, path, it):
        rows.append(model[it][0])
        return False
    win.store.foreach(walk)
    return rows


@unittest.skipUnless(HAVE_GTK, "GTK or display not available")
class MainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Gtk.Application()
        cls.app.register(None)

    def setUp(self):
        set_language("en")
        self.windows = []

    def tearDown(self):
        for w in self.windows:
            w.destroy()

    def make(self, nm, wait=True, module_ok=True):
        win = window.MainWindow(self.app, nm,
                                check_8021q=lambda: module_ok)
        self.windows.append(win)
        if wait:
            self.assertTrue(pump(lambda: win.loaded))
        return win

    def select(self, win, name):
        def walk(model, path, it):
            if model[it][0] == name:
                win.tree.expand_all()
                win.tree.get_selection().select_path(path)
                return True
            return False
        win.store.foreach(walk)
        pump(lambda: False, 0.05)

    def test_window_lists_nics_and_vlans(self):
        win = self.make(FakeNm())
        self.assertEqual(tree_rows(win), ["eth0", "eth0.20", "eth1"])

    def test_unmanaged_nic_disables_add(self):
        win = self.make(FakeNm())
        self.select(win, "eth0")
        self.assertTrue(win.btn_add.get_sensitive())
        self.assertFalse(win.btn_edit.get_sensitive())
        self.select(win, "eth1")
        self.assertFalse(win.btn_add.get_sensitive())
        self.select(win, "eth0.20")
        self.assertTrue(win.btn_edit.get_sensitive())
        self.assertTrue(win.btn_delete.get_sensitive())

    def test_unmanaged_nic_has_tooltip(self):
        win = self.make(FakeNm())
        found = []

        def walk(model, path, it):
            if model[it][0] == "eth1":
                found.append(model[it][win.COL_TOOLTIP])
            return False
        win.store.foreach(walk)
        self.assertEqual(found, [tr("tooltip_unmanaged")])

    def test_nm_not_running_shows_error_bar(self):
        win = self.make(FakeNm(running=False), wait=False)
        self.assertTrue(pump(
            lambda: win.stack.get_visible_child_name() == "error"))
        self.assertEqual(win.stack.get_visible_child_name(), "error")
        self.assertEqual(win.error_label.get_text(), tr("nm_not_running"))

    def test_is_running_not_called_on_main_thread(self):
        nm = FakeNm()
        win = self.make(nm)
        self.assertTrue(nm.calls)
        self.assertNotIn(threading.get_ident(), [t for _, t in nm.calls])

    def test_retry_recovers_from_error_page(self):
        nm = FakeNm(error=NmError("nmcli_timeout"))
        win = self.make(nm, wait=False)
        self.assertTrue(pump(
            lambda: win.stack.get_visible_child_name() == "error"))
        nm.error = None
        win.btn_retry.clicked()
        self.assertTrue(pump(lambda: win.loaded))
        self.assertEqual(win.stack.get_visible_child_name(), "main")
        self.assertEqual(tree_rows(win), ["eth0", "eth0.20", "eth1"])

    def test_nmcli_missing_shows_error_bar(self):
        win = self.make(FakeNm(running=False, error=NmError("nmcli_missing")), wait=False)
        self.assertTrue(pump(
            lambda: win.stack.get_visible_child_name() == "error"))
        self.assertEqual(win.error_label.get_text(), tr("nmcli_missing"))

    def test_missing_8021q_shows_warning_bar(self):
        win = self.make(FakeNm(), module_ok=False)
        self.assertTrue(pump(lambda: win.warn_bar.get_revealed()))
        ok = self.make(FakeNm())
        pump(lambda: False, 0.1)
        self.assertFalse(ok.warn_bar.get_revealed())

    def test_run_async_delivers_result_on_main_loop(self):
        main = threading.get_ident()
        seen = {}

        def work():
            seen["worker"] = threading.get_ident()
            return 42

        def done(result, error):
            seen["done"] = threading.get_ident()
            seen["result"] = (result, error)

        worker.run_async(work, done)
        self.assertTrue(pump(lambda: "result" in seen))
        self.assertEqual(seen["result"], (42, None))
        self.assertEqual(seen["done"], main)
        self.assertNotEqual(seen["worker"], main)

    def test_run_async_delivers_exception(self):
        seen = {}
        boom = ValueError("boom")

        def work():
            raise boom

        worker.run_async(work, lambda r, e: seen.update(r=r, e=e))
        self.assertTrue(pump(lambda: "e" in seen))
        self.assertIsNone(seen["r"])
        self.assertIs(seen["e"], boom)


if __name__ == "__main__":
    unittest.main()
