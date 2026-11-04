"""Main window: NICs with their VLANs, and the toolbar."""
from __future__ import annotations

import threading
from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from ..core import ops, probe  # noqa: E402
from ..core.checkpoint import CheckpointError, NmCheckpoints  # noqa: E402
from ..core.model import Nic, Vlan, VlanSpec  # noqa: E402
from ..core.nm import NmClient, NmError  # noqa: E402
from ..i18n import tr  # noqa: E402
from . import dialogs  # noqa: E402
from .worker import run_async  # noqa: E402

_NM_CODES = ("nmcli_missing", "nmcli_timeout")
_GREY = "#888888"


def _error_text(exc: Exception) -> str:
    if isinstance(exc, NmError):
        # Codes are translated; anything else is the raw nmcli message.
        return tr(exc.message) if exc.message in _NM_CODES else exc.message
    return str(exc)


class MainWindow(Gtk.ApplicationWindow):
    (COL_NAME, COL_ID, COL_STATE, COL_IP, COL_COLOR, COL_TOOLTIP,
     COL_KIND, COL_MANAGED) = range(8)

    def __init__(self, app: Gtk.Application, nm: NmClient,
                 check_8021q: Callable[[], bool] = probe.module_8021q_available):
        super().__init__(application=app, title=tr("window_title"))
        self.nm = nm
        self.loaded = False
        self._busy = False
        self.nics: list[Nic] = []
        self.vlans: list[Vlan] = []
        self.set_default_size(720, 440)

        self.store = Gtk.TreeStore(str, str, str, str, str, str, str, bool)
        self._build()
        self._update_buttons()

        run_async(check_8021q, self._on_module_checked)
        self.refresh()

    # layout

    def _build(self) -> None:
        self.stack = Gtk.Stack()
        self.add(self.stack)

        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.stack.add_named(main, "main")

        self.warn_bar = Gtk.InfoBar(message_type=Gtk.MessageType.WARNING,
                                    revealed=False, no_show_all=True)
        self.warn_bar.get_content_area().add(
            Gtk.Label(label=tr("warn_8021q_missing"), wrap=True))
        self.warn_bar.get_content_area().show_all()
        main.pack_start(self.warn_bar, False, False, 0)

        bar = Gtk.Box(spacing=6, margin=6)
        self.btn_add = Gtk.Button(label=tr("btn_add"))
        self.btn_edit = Gtk.Button(label=tr("btn_edit"))
        self.btn_delete = Gtk.Button(label=tr("btn_delete"))
        self.btn_toggle = Gtk.Button(label=tr("btn_deactivate"))
        self.btn_refresh = Gtk.Button(label=tr("btn_refresh"))
        for b in (self.btn_add, self.btn_edit, self.btn_delete,
                  self.btn_toggle, self.btn_refresh):
            bar.pack_start(b, False, False, 0)
        main.pack_start(bar, False, False, 0)
        self.btn_add.connect("clicked", self._on_add)
        self.btn_edit.connect("clicked", self._on_edit)
        self.btn_delete.connect("clicked", self._on_delete)
        self.btn_toggle.connect("clicked", self._on_toggle)
        self.btn_refresh.connect("clicked", lambda _b: self.refresh())

        self.info_bar = Gtk.InfoBar(message_type=Gtk.MessageType.INFO,
                                    revealed=False, no_show_all=True,
                                    show_close_button=True)
        self.info_label = Gtk.Label(wrap=True, xalign=0)
        self.info_bar.get_content_area().add(self.info_label)
        self.info_bar.get_content_area().show_all()
        self.info_bar.connect("response", lambda b, _r: b.set_revealed(False))
        main.pack_start(self.info_bar, False, False, 0)

        self.tree = Gtk.TreeView(model=self.store)
        self.tree.set_tooltip_column(self.COL_TOOLTIP)
        for title, col in ((tr("col_name"), self.COL_NAME),
                           (tr("col_vlan_id"), self.COL_ID),
                           (tr("col_state"), self.COL_STATE),
                           (tr("col_ip"), self.COL_IP)):
            column = Gtk.TreeViewColumn(title, Gtk.CellRendererText(),
                                        text=col, foreground=self.COL_COLOR)
            column.set_resizable(True)
            self.tree.append_column(column)
        self.tree.get_selection().connect("changed",
                                          lambda _s: self._update_buttons())
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.add(self.tree)
        main.pack_start(scroll, True, True, 0)

        err = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        info = Gtk.InfoBar(message_type=Gtk.MessageType.ERROR, revealed=True)
        self.error_label = Gtk.Label(wrap=True)
        info.get_content_area().add(self.error_label)
        self.btn_retry = Gtk.Button(label=tr("btn_retry"))
        self.btn_retry.connect("clicked", lambda _b: self.refresh())
        info.add_action_widget(self.btn_retry, Gtk.ResponseType.NONE)
        err.pack_start(info, False, False, 0)
        self.stack.add_named(err, "error")
        self.show_all()
        self.stack.set_visible_child_name("main")
        self.warn_bar.hide()

    def _show_error(self, text: str) -> None:
        self.error_label.set_text(text)
        self.stack.set_visible_child_name("error")

    # data

    def refresh(self) -> None:
        def load() -> tuple[bool, list[Nic], list[Vlan]]:
            if not self.nm.is_running():
                # is_running hides failures; let a missing or hung nmcli
                # surface as its own error instead of "not running".
                try:
                    self.nm.list_nics()
                except NmError as exc:
                    if exc.message in _NM_CODES:
                        raise
                return False, [], []
            return True, self.nm.list_nics(), self.nm.list_vlans()

        run_async(load, self._on_loaded)

    def _on_loaded(self, result, error) -> None:
        if error is not None:
            self._show_error(_error_text(error))
            return
        running, self.nics, self.vlans = result
        if not running:
            self._show_error(tr("nm_not_running"))
            return
        self.stack.set_visible_child_name("main")
        self._fill()
        self.loaded = True

    def _on_module_checked(self, available, error) -> None:
        if error is None and not available:
            self.warn_bar.set_revealed(True)
            self.warn_bar.show()

    def _fill(self) -> None:
        selected = self._selected_name()
        self.store.clear()
        for nic in self.nics:
            grey = None if nic.managed else _GREY
            tip = None if nic.managed else tr("tooltip_unmanaged")
            it = self.store.append(None, [nic.name, "", nic.state, "", grey,
                                          tip, "nic", nic.managed])
            for v in self.vlans:
                if v.spec.parent != nic.name:
                    continue
                state = tr("state_active" if v.active else "state_inactive")
                self.store.append(it, [v.spec.name, str(v.spec.vlan_id),
                                       state, self._ip_text(v), grey, tip,
                                       "vlan", nic.managed])
        self.tree.expand_all()
        if selected:
            self._select(selected)
        self._update_buttons()

    @staticmethod
    def _ip_text(v: Vlan) -> str:
        cfg = v.spec.ipv4
        if cfg.method == "manual":
            return cfg.address or ""
        return tr("method_auto") if cfg.method == "auto" else ""

    def _select(self, name: str) -> None:
        def walk(model, path, it):
            if model[it][self.COL_NAME] == name:
                self.tree.get_selection().select_path(path)
                return True
            return False
        self.store.foreach(walk)

    # selection

    def _selected_row(self):
        model, it = self.tree.get_selection().get_selected()
        return model[it] if it else None

    def _selected_name(self) -> str | None:
        row = self._selected_row()
        return row[self.COL_NAME] if row else None

    def selected_vlan(self) -> Vlan | None:
        row = self._selected_row()
        if not row or row[self.COL_KIND] != "vlan":
            return None
        return next((v for v in self.vlans
                     if v.spec.name == row[self.COL_NAME]), None)

    def _update_buttons(self) -> None:
        row = self._selected_row()
        is_vlan = bool(row) and row[self.COL_KIND] == "vlan"
        managed = True if row is None else row[self.COL_MANAGED]
        idle = not self._busy
        self.btn_add.set_sensitive(idle and managed)
        self.btn_edit.set_sensitive(idle and is_vlan and managed)
        self.btn_delete.set_sensitive(idle and is_vlan and managed)
        self.btn_toggle.set_sensitive(idle and is_vlan and managed)
        vlan = self.selected_vlan()
        self.btn_toggle.set_label(tr("btn_deactivate" if vlan and vlan.active
                                     else "btn_activate"))

    def _parent_of_selection(self) -> str | None:
        vlan = self.selected_vlan()
        if vlan:
            return vlan.spec.parent
        row = self._selected_row()
        return row[self.COL_NAME] if row else None

    # messages

    def _show_info(self, text: str, kind=Gtk.MessageType.INFO) -> None:
        self.info_bar.set_message_type(kind)
        self.info_label.set_text(text)
        self.info_bar.show()
        self.info_bar.set_revealed(True)

    def _show_error_dialog(self, text: str) -> None:
        dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                message_type=Gtk.MessageType.ERROR,
                                buttons=Gtk.ButtonsType.CLOSE, text=text)
        dlg.set_title(tr("dialog_error_title"))
        dlg.connect("response", lambda d, _r: d.destroy())
        dlg.show()

    def _confirm_delete(self, name: str) -> bool:
        dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                message_type=Gtk.MessageType.QUESTION,
                                text=tr("confirm_delete"),
                                secondary_text=name)
        dlg.set_title(tr("dialog_delete_title"))
        dlg.add_button(tr("btn_cancel"), Gtk.ResponseType.CANCEL)
        dlg.add_button(tr("btn_delete"), Gtk.ResponseType.OK)
        try:
            return dlg.run() == Gtk.ResponseType.OK
        finally:
            dlg.destroy()

    # operations

    def ask_confirm(self) -> bool:
        """Show the confirm dialog from a worker thread and wait for it.

        The result is always set, so the worker can never block forever.
        """
        result = [False]
        done = threading.Event()

        def show() -> bool:
            try:
                result[0] = bool(dialogs.ConfirmDialog(
                    self, ops.CONFIRM_TIMEOUT_S).ask())
            except Exception:
                result[0] = False
            finally:
                done.set()
            return False

        GLib.idle_add(show)
        done.wait()
        return result[0]

    def _start(self, work: Callable[[], object], on_ok=None) -> None:
        self._busy = True
        self._update_buttons()

        def finished(result, error) -> None:
            self._busy = False
            self.refresh()  # UUIDs may have changed, whatever the outcome
            self._update_buttons()
            if error is not None:
                text = _error_text(error)
                if isinstance(error, CheckpointError):
                    text += "\n\n" + tr("destroy_failed_hint")
                self._show_error_dialog(text)
            elif on_ok:
                on_ok(result)

        run_async(work, finished)

    def _safe_kwargs(self) -> dict:
        return dict(checkpoints=NmCheckpoints(),
                    confirm_timeout_s=ops.CONFIRM_TIMEOUT_S)

    def _report(self, result) -> None:
        confirmed, reason = result
        if not confirmed:
            self._show_info(tr("op_reverted"), Gtk.MessageType.WARNING)
        elif reason:
            self._show_info(tr(reason), Gtk.MessageType.INFO
                            if reason == "ok" else Gtk.MessageType.WARNING)

    def _on_add(self, _btn) -> None:
        dlg = dialogs.VlanDialog(self, self.nics,
                                 [v.spec for v in self.vlans],
                                 preselect=self._parent_of_selection())
        spec = dlg.run_and_get()
        if spec is None:
            return
        self._start(lambda: self._apply(
            lambda: ops.create_vlan_safe(self.nm, spec, self.ask_confirm,
                                         **self._safe_kwargs()), spec),
            self._report)

    def _on_edit(self, _btn) -> None:
        vlan = self.selected_vlan()
        if vlan is None:
            return
        others = [v.spec for v in self.vlans]
        dlg = dialogs.VlanDialog(self, self.nics, others, editing=vlan.spec)
        spec = dlg.run_and_get()
        if spec is None:
            return
        self._start(lambda: self._apply(
            lambda: ops.edit_vlan_safe(self.nm, vlan.uuid, spec,
                                       self.ask_confirm,
                                       **self._safe_kwargs()), spec),
            self._report)

    def _apply(self, op: Callable[[], bool], spec: VlanSpec):
        """Worker: run the operation, then check the new VLAN works."""
        confirmed = op()
        if not confirmed:
            return False, None
        return True, probe.verify_vlan(self.nm, spec.name)[1]

    def _on_delete(self, _btn) -> None:
        vlan = self.selected_vlan()
        if vlan is None or not self._confirm_delete(vlan.spec.name):
            return

        def work():
            return ops.delete_vlan_safe(self.nm, vlan.uuid, self.ask_confirm,
                                        **self._safe_kwargs()), None

        self._start(work, self._report)

    def _on_toggle(self, _btn) -> None:
        vlan = self.selected_vlan()
        if vlan is None:
            return
        action = self.nm.down if vlan.active else self.nm.up
        self._start(lambda: action(vlan.uuid))
