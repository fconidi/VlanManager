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

from unittest import mock

from vlanmanager.core.model import IpConfig, Nic, Vlan, VlanSpec
from vlanmanager.core.nm import NmError
from vlanmanager.i18n import set_language, tr

if HAVE_GTK:
    from vlanmanager.gui import dialogs, worker, window


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

    def up(self, ident):
        self.calls.append(("up", ident))

    def down(self, ident):
        self.calls.append(("down", ident))


class NoCheckpoints:
    def available(self):
        return False


_APP = []


def shared_app():
    if not _APP:
        app = Gtk.Application()
        app.register(None)
        _APP.append(app)
    return _APP[0]


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
        cls.app = shared_app()

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


NICS = [Nic("eth0", "aa:bb:cc:dd:ee:01", "connected", True),
        Nic("eth1", "aa:bb:cc:dd:ee:02", "unmanaged", False),
        Nic("eth2", "aa:bb:cc:dd:ee:03", "connected", True)]
EXISTING = [VlanSpec("eth0", 20, "eth0.20")]


def set_combo(combo, value):
    for i, row in enumerate(combo.get_model()):
        if row[0] == value:
            combo.set_active(i)
            return
    raise AssertionError(value)


@unittest.skipUnless(HAVE_GTK, "GTK or display not available")
class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = shared_app()

    def setUp(self):
        set_language("en")
        self.parent = Gtk.Window()
        self.dialogs = []

    def tearDown(self):
        for d in self.dialogs:
            d.destroy()
        self.parent.destroy()

    def make(self, editing=None, preselect=None):
        d = dialogs.VlanDialog(self.parent, NICS, EXISTING, editing=editing,
                               preselect=preselect)
        self.dialogs.append(d)
        return d

    def test_parent_combo_lists_managed_nics_only(self):
        d = self.make()
        self.assertEqual([r[0] for r in d.parent_combo.get_model()],
                         ["eth0", "eth2"])

    def test_dialog_ok_disabled_for_duplicate(self):
        d = self.make()
        set_combo(d.parent_combo, "eth0")
        d.id_spin.set_value(20)
        self.assertFalse(d.ok_button.get_sensitive())
        self.assertEqual(d.error_label.get_text(), tr("duplicate"))
        d.id_spin.set_value(30)
        self.assertTrue(d.ok_button.get_sensitive())
        self.assertEqual(d.error_label.get_text(), "")

    def test_dialog_ok_disabled_for_long_name(self):
        d = self.make()
        set_combo(d.parent_combo, "eth0")
        d.id_spin.set_value(30)
        d.name_entry.set_text("x" * 16)
        self.assertFalse(d.ok_button.get_sensitive())
        self.assertEqual(d.error_label.get_text(), tr("name_len"))

    def test_dialog_name_autofill(self):
        d = self.make()
        set_combo(d.parent_combo, "eth0")
        d.id_spin.set_value(20)
        self.assertEqual(d.name_entry.get_text(), "eth0.20")
        d.id_spin.set_value(21)
        self.assertEqual(d.name_entry.get_text(), "eth0.21")
        d.name_entry.set_text("mine")
        d.id_spin.set_value(22)
        self.assertEqual(d.name_entry.get_text(), "mine")

    def test_dialog_autofill_truncates_long_default(self):
        self.assertEqual(dialogs.autofill_name("enp0s31f6abcdef", 100),
                         "enp0s31f6ab.100")
        self.assertEqual(dialogs.autofill_name("eth0", 5), "eth0.5")
        for parent, vid in (("verylongparentname", 4094), ("a" * 40, 1)):
            self.assertLessEqual(len(dialogs.autofill_name(parent, vid)), 15)

    def test_long_parent_autofill_in_dialog_is_valid(self):
        nics = [Nic("enp0s31f6abcdef", "m", "connected", True)]
        d = dialogs.VlanDialog(self.parent, nics, [])
        self.dialogs.append(d)
        d.id_spin.set_value(100)
        self.assertEqual(d.name_entry.get_text(), "enp0s31f6ab.100")
        self.assertTrue(d.ok_button.get_sensitive())

    def test_dialog_returns_spec_for_static_ipv4(self):
        d = self.make()
        set_combo(d.parent_combo, "eth2")
        d.id_spin.set_value(30)
        d.ipv4_method.set_active_id("manual")
        d.ipv4_address.set_text("10.0.30.5/24")
        d.ipv4_gateway.set_text("10.0.30.1")
        d.ipv4_dns.set_text("1.1.1.1, 8.8.8.8")
        d.mtu_entry.set_text("1500")
        d.autoconnect.set_active(False)
        self.assertTrue(d.ok_button.get_sensitive())
        GLib.idle_add(lambda: d.response(Gtk.ResponseType.OK))
        spec = d.run_and_get()
        self.assertEqual(spec, VlanSpec(
            "eth2", 30, "eth2.30",
            ipv4=IpConfig("manual", "10.0.30.5/24", "10.0.30.1",
                          ("1.1.1.1", "8.8.8.8")),
            ipv6=IpConfig("auto"), autoconnect=False, mtu=1500))

    def test_dialog_cancel_returns_none(self):
        d = self.make()
        GLib.idle_add(lambda: d.response(Gtk.ResponseType.CANCEL))
        self.assertIsNone(d.run_and_get())

    def test_edit_dialog_prefills_and_keeps_own_name_valid(self):
        d = self.make(editing=EXISTING[0])
        self.assertEqual(d.name_entry.get_text(), "eth0.20")
        self.assertEqual(d.id_spin.get_value_as_int(), 20)
        self.assertTrue(d.ok_button.get_sensitive())
        self.assertFalse(d.parent_combo.get_sensitive())

    def test_edit_dialog_keeps_connection_name(self):
        editing = VlanSpec("eth0", 20, "eth0.20", con_name="VLAN connection 1")
        d = dialogs.VlanDialog(self.parent, NICS, [editing], editing=editing)
        self.dialogs.append(d)
        d.mtu_entry.set_text("1400")
        self.assertEqual(d.current_spec().con_name, "VLAN connection 1")
        self.assertEqual(d.current_spec().name, "eth0.20")

    def test_non_decimal_digit_mtu_is_an_error(self):
        d = self.make()
        set_combo(d.parent_combo, "eth0")
        d.id_spin.set_value(30)
        d.mtu_entry.set_text("\u00b2")
        self.assertIn("mtu_range", d.errors())
        self.assertIsNone(d.current_spec().mtu)
        self.assertFalse(d.ok_button.get_sensitive())
        self.assertEqual(d.error_label.get_text(), tr("mtu_range"))

    def test_confirm_dialog_returns_false_on_timeout(self):
        d = dialogs.ConfirmDialog(self.parent, seconds=1)
        self.dialogs.append(d)
        start = time.monotonic()
        self.assertFalse(d.ask())
        self.assertLess(time.monotonic() - start, 4)

    def test_confirm_dialog_countdown_text(self):
        d = dialogs.ConfirmDialog(self.parent, seconds=7)
        self.dialogs.append(d)
        self.assertIn("7", d.label.get_text())

    def test_confirm_dialog_keep_returns_true(self):
        d = dialogs.ConfirmDialog(self.parent, seconds=20)
        self.dialogs.append(d)
        GLib.idle_add(d.btn_keep.clicked)
        self.assertTrue(d.ask())

    def test_confirm_dialog_revert_returns_false(self):
        d = dialogs.ConfirmDialog(self.parent, seconds=20)
        self.dialogs.append(d)
        GLib.idle_add(d.btn_revert.clicked)
        self.assertFalse(d.ask())

    def test_confirm_dialog_close_paths_return_false(self):
        for kind in ("esc", "x", "destroy"):
            d = dialogs.ConfirmDialog(self.parent, seconds=20)
            self.dialogs.append(d)
            if kind == "esc":
                GLib.idle_add(lambda: d.response(Gtk.ResponseType.CANCEL))
            elif kind == "x":
                GLib.idle_add(lambda: d.response(Gtk.ResponseType.DELETE_EVENT))
            else:
                GLib.idle_add(d.destroy)
            self.assertFalse(d.ask(), kind)


@unittest.skipUnless(HAVE_GTK, "GTK or display not available")
class OperationTests(MainWindowTests):
    """Reuses the window helpers of MainWindowTests."""

    def refreshes(self, nm):
        return len([c for c in nm.calls if c[0] == "is_running"])

    def _ask_from_worker(self, act):
        """Run win.ask_confirm on a thread; act(dialog) fires once shown."""
        win = self.make(FakeNm())
        real = dialogs.ConfirmDialog
        threads = []

        class Spy(real):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                threads.append(threading.get_ident())
                GLib.timeout_add(50, lambda: (act(self), False)[1])

        out = {}
        with mock.patch.object(dialogs, "ConfirmDialog", Spy):
            t = threading.Thread(
                target=lambda: out.update(r=win.ask_confirm()))
            t.start()
            self.assertTrue(pump(lambda: "r" in out, 5))
        t.join(2)
        self.assertEqual(threads, [threading.get_ident()])
        return out["r"]

    def test_ask_confirm_marshals_and_returns_false_when_destroyed(self):
        self.assertIs(self._ask_from_worker(lambda d: d.destroy()), False)

    def test_ask_confirm_returns_true_on_keep(self):
        self.assertIs(self._ask_from_worker(lambda d: d.btn_keep.clicked()),
                      True)

    def test_delete_flow_calls_delete_vlan_safe_with_uuid(self):
        nm = FakeNm()
        win = self.make(nm)
        self.select(win, "eth0.20")
        before = self.refreshes(nm)
        called = {}

        def fake(nm_, ident, ask, checkpoints=None, confirm_timeout_s=None,
                 active=None):
            called.update(ident=ident, cp=checkpoints,
                          timeout=confirm_timeout_s, active=active,
                          thread=threading.get_ident())
            return True

        with mock.patch.object(win, "_confirm_delete", return_value=True), \
                mock.patch.object(window.ops, "delete_vlan_safe", fake):
            win.btn_delete.clicked()
            self.assertTrue(pump(lambda: self.refreshes(nm) > before))
        self.assertEqual(called["ident"], "uuid-1")
        self.assertIs(called["active"], True)
        self.assertIsNotNone(called["cp"])
        self.assertEqual(called["timeout"], window.ops.CONFIRM_TIMEOUT_S)
        self.assertEqual(dialogs.ConfirmDialog.__init__.__defaults__[0],
                         window.ops.CONFIRM_TIMEOUT_S)
        self.assertNotEqual(called["thread"], threading.get_ident())

    def test_delete_not_confirmed_by_user_does_nothing(self):
        nm = FakeNm()
        win = self.make(nm)
        self.select(win, "eth0.20")
        fake = mock.Mock()
        with mock.patch.object(win, "_confirm_delete", return_value=False), \
                mock.patch.object(window.ops, "delete_vlan_safe", fake):
            win.btn_delete.clicked()
            pump(lambda: False, 0.2)
        fake.assert_not_called()

    def test_refresh_after_failed_op_and_error_shown_raw(self):
        nm = FakeNm()
        win = self.make(nm)
        self.select(win, "eth0.20")
        before = self.refreshes(nm)
        errors = []

        def boom(*a, **k):
            raise NmError("Error: Connection 'x' is not valid")

        with mock.patch.object(win, "_confirm_delete", return_value=True), \
                mock.patch.object(win, "_show_error_dialog", errors.append), \
                mock.patch.object(window.ops, "delete_vlan_safe", boom):
            win.btn_delete.clicked()
            self.assertTrue(pump(lambda: self.refreshes(nm) > before))
        self.assertEqual(errors, ["Error: Connection 'x' is not valid"])

    def test_checkpoint_error_adds_hint(self):
        from vlanmanager.core.checkpoint import CheckpointError
        nm = FakeNm()
        win = self.make(nm)
        self.select(win, "eth0.20")
        errors = []

        def boom(*a, **k):
            raise CheckpointError("destroy denied")

        with mock.patch.object(win, "_confirm_delete", return_value=True), \
                mock.patch.object(win, "_show_error_dialog", errors.append), \
                mock.patch.object(window.ops, "delete_vlan_safe", boom):
            win.btn_delete.clicked()
            self.assertTrue(pump(lambda: errors))
        self.assertIn("destroy denied", errors[0])
        self.assertIn(tr("destroy_failed_hint"), errors[0])

    def test_toggle_calls_down_then_up_with_uuid(self):
        nm = FakeNm()
        win = self.make(nm)
        self.select(win, "eth0.20")
        self.assertEqual(win.btn_toggle.get_label(), tr("btn_deactivate"))
        before = self.refreshes(nm)
        with mock.patch.object(window, "NmCheckpoints", NoCheckpoints), \
                mock.patch.object(win, "ask_confirm", return_value=True):
            win.btn_toggle.clicked()
            self.assertTrue(pump(lambda: self.refreshes(nm) > before))
        self.assertIn(("down", "uuid-1"), nm.calls)
        self.assertNotIn(("up", "uuid-1"), nm.calls)
        nm.vlans = [Vlan(nm.vlans[0].spec, "uuid-1", False)]
        win.refresh()
        self.assertTrue(pump(lambda: self.refreshes(nm) > before + 1))
        pump(lambda: win.btn_toggle.get_label() == tr("btn_activate"), 1)
        self.select(win, "eth0.20")
        self.assertEqual(win.btn_toggle.get_label(), tr("btn_activate"))
        before = self.refreshes(nm)
        win.btn_toggle.clicked()
        self.assertTrue(pump(lambda: self.refreshes(nm) > before))
        self.assertIn(("up", "uuid-1"), nm.calls)

    def test_deactivate_asks_and_revert_brings_it_up(self):
        nm = FakeNm()
        win = self.make(nm)
        self.select(win, "eth0.20")
        shown = []
        real = dialogs.ConfirmDialog

        class Spy(real):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                shown.append(1)
                GLib.timeout_add(50, lambda: (self.btn_revert.clicked(),
                                              False)[1])

        before = self.refreshes(nm)
        with mock.patch.object(window, "NmCheckpoints", NoCheckpoints), \
                mock.patch.object(dialogs, "ConfirmDialog", Spy):
            win.btn_toggle.clicked()
            self.assertTrue(pump(lambda: self.refreshes(nm) > before))
        self.assertEqual(shown, [1])
        self.assertEqual([c for c in nm.calls if c[0] in ("up", "down")],
                         [("down", "uuid-1"), ("up", "uuid-1")])
        self.assertEqual(win.info_label.get_text(), tr("op_reverted"))

    def test_rollback_error_adds_hint(self):
        from vlanmanager.core.rollback import RollbackError
        nm = FakeNm()
        win = self.make(nm)
        self.select(win, "eth0.20")
        errors = []

        def boom(*a, **k):
            raise RollbackError("Error: unknown connection")

        with mock.patch.object(win, "_confirm_delete", return_value=True), \
                mock.patch.object(win, "_show_error_dialog", errors.append), \
                mock.patch.object(window.ops, "delete_vlan_safe", boom):
            win.btn_delete.clicked()
            self.assertTrue(pump(lambda: errors))
        self.assertIn("Error: unknown connection", errors[0])
        self.assertIn(tr("rollback_failed_hint"), errors[0])

    def test_ask_confirm_refuses_main_thread(self):
        win = self.make(FakeNm())
        with self.assertRaises(RuntimeError):
            win.ask_confirm()

    def test_ask_confirm_wait_is_bounded(self):
        self.assertEqual(window._CONFIRM_WAIT_S,
                         window.ops.CONFIRM_TIMEOUT_S + 60)
        win = self.make(FakeNm())
        out = {}
        with mock.patch.object(window, "_CONFIRM_WAIT_S", 0.2), \
                mock.patch.object(window.GLib, "idle_add",
                                  lambda *a, **k: 0):
            t = threading.Thread(
                target=lambda: out.update(r=win.ask_confirm()))
            t.start()
            t.join(3)
        self.assertIs(out.get("r"), False)

    def test_create_verifies_with_interface_name_and_shows_info(self):
        nm = FakeNm()
        win = self.make(nm)
        spec = VlanSpec("eth0", 30, "eth0.30")
        seen = {}

        def fake_create(nm_, s, ask, checkpoints=None, confirm_timeout_s=None):
            seen["spec"] = s
            return True

        def fake_verify(nm_, iface):
            seen["iface"] = iface
            return False, "no_gateway"

        before = self.refreshes(nm)
        with mock.patch.object(dialogs.VlanDialog, "run_and_get",
                               return_value=spec), \
                mock.patch.object(window.ops, "create_vlan_safe",
                                  fake_create), \
                mock.patch.object(window.probe, "verify_vlan", fake_verify):
            win.btn_add.clicked()
            self.assertTrue(pump(lambda: self.refreshes(nm) > before))
        self.assertEqual(seen, {"spec": spec, "iface": "eth0.30"})
        self.assertEqual(win.info_label.get_text(), tr("no_gateway"))
        self.assertTrue(win.info_bar.get_revealed())

    def test_reverted_op_says_so(self):
        nm = FakeNm()
        win = self.make(nm)
        spec = VlanSpec("eth0", 30, "eth0.30")
        before = self.refreshes(nm)
        with mock.patch.object(dialogs.VlanDialog, "run_and_get",
                               return_value=spec), \
                mock.patch.object(window.ops, "create_vlan_safe",
                                  lambda *a, **k: False):
            win.btn_add.clicked()
            self.assertTrue(pump(lambda: self.refreshes(nm) > before))
        self.assertEqual(win.info_label.get_text(), tr("op_reverted"))

    def test_edit_passes_uuid_and_spec(self):
        nm = FakeNm()
        win = self.make(nm)
        self.select(win, "eth0.20")
        new = VlanSpec("eth0", 20, "eth0.20", mtu=1400)
        seen = {}

        def fake_edit(nm_, ident, s, ask, checkpoints=None,
                      confirm_timeout_s=None, active=None):
            seen.update(ident=ident, spec=s, active=active)
            return False

        before = self.refreshes(nm)
        with mock.patch.object(dialogs.VlanDialog, "run_and_get",
                               return_value=new), \
                mock.patch.object(window.ops, "edit_vlan_safe", fake_edit):
            win.btn_edit.clicked()
            self.assertTrue(pump(lambda: self.refreshes(nm) > before))
        self.assertEqual(seen, {"ident": "uuid-1", "spec": new,
                                "active": True})

    def _verify_raises(self, kind):
        nm = FakeNm()
        win = self.make(nm)
        errors = []
        before = self.refreshes(nm)

        def boom(nm_, iface):
            raise NmError("nmcli timed out talking to device")

        patches = [mock.patch.object(win, "_show_error_dialog",
                                     errors.append),
                   mock.patch.object(window.probe, "verify_vlan", boom)]
        if kind == "create":
            spec = VlanSpec("eth0", 30, "eth0.30")
            patches.append(mock.patch.object(
                window.ops, "create_vlan_safe", lambda *a, **k: True))
            click = win.btn_add
        else:
            self.select(win, "eth0.20")
            spec = VlanSpec("eth0", 20, "eth0.20", mtu=1400)
            patches.append(mock.patch.object(
                window.ops, "edit_vlan_safe", lambda *a, **k: True))
            click = win.btn_edit
        patches.append(mock.patch.object(
            dialogs.VlanDialog, "run_and_get", return_value=spec))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        click.clicked()
        self.assertTrue(pump(lambda: self.refreshes(nm) > before))
        pump(lambda: win.info_label.get_text() != "", 1)
        self.assertEqual(errors, [])
        self.assertEqual(win.info_label.get_text(), tr("verify_unavailable"))
        self.assertNotEqual(win.info_label.get_text(), tr("op_reverted"))

    def test_create_verify_error_is_not_fatal(self):
        self._verify_raises("create")

    def test_edit_verify_error_is_not_fatal(self):
        self._verify_raises("edit")

    def test_add_enabled_without_selection(self):
        win = self.make(FakeNm())
        win.tree.get_selection().unselect_all()
        pump(lambda: False, 0.05)
        self.assertTrue(win.btn_add.get_sensitive())
        self.assertFalse(win.btn_toggle.get_sensitive())


if __name__ == "__main__":
    unittest.main()
