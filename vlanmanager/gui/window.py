"""Main window: NICs with their VLANs, and the toolbar."""
from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from ..core import probe  # noqa: E402
from ..core.model import Nic, Vlan  # noqa: E402
from ..core.nm import NmClient, NmError  # noqa: E402
from ..i18n import tr  # noqa: E402
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
        self.nics: list[Nic] = []
        self.vlans: list[Vlan] = []
        self.set_default_size(720, 440)

        self.store = Gtk.TreeStore(str, str, str, str, str, str, str, bool)
        self._build()
        self._update_buttons()

        if not nm.is_running():
            self._show_error(tr("nm_not_running"))
            return
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
        self.btn_refresh = Gtk.Button(label=tr("btn_refresh"))
        for b in (self.btn_add, self.btn_edit, self.btn_delete,
                  self.btn_refresh):
            bar.pack_start(b, False, False, 0)
        main.pack_start(bar, False, False, 0)
        self.btn_add.connect("clicked", self._on_add)
        self.btn_edit.connect("clicked", self._on_edit)
        self.btn_delete.connect("clicked", self._on_delete)
        self.btn_refresh.connect("clicked", lambda _b: self.refresh())

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
        def load() -> tuple[list[Nic], list[Vlan]]:
            return self.nm.list_nics(), self.nm.list_vlans()

        run_async(load, self._on_loaded)

    def _on_loaded(self, result, error) -> None:
        if error is not None:
            self._show_error(_error_text(error))
            return
        self.nics, self.vlans = result
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
        self.btn_add.set_sensitive(managed)
        self.btn_edit.set_sensitive(is_vlan and managed)
        self.btn_delete.set_sensitive(is_vlan and managed)

    # actions (completed together with the dialogs)

    def _on_add(self, _btn) -> None:
        try:
            from . import dialogs  # noqa: F401
        except ImportError:
            return

    def _on_edit(self, _btn) -> None:
        try:
            from . import dialogs  # noqa: F401
        except ImportError:
            return

    def _on_delete(self, _btn) -> None:
        try:
            from . import dialogs  # noqa: F401
        except ImportError:
            return
