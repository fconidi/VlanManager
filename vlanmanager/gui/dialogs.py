"""Dialogs: VLAN form, confirm-or-revert countdown."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from ..core.model import (MAX_NAME_LEN, IpConfig, Nic, VlanSpec,  # noqa: E402
                          default_name, validate)
from ..core.ops import CONFIRM_TIMEOUT_S  # noqa: E402
from ..i18n import tr  # noqa: E402

_METHODS = ("auto", "manual", "disabled")


def autofill_name(parent: str, vlan_id: int) -> str:
    """Default interface name, shortened to the kernel limit if needed."""
    name = default_name(parent, vlan_id)
    if len(name) <= MAX_NAME_LEN:
        return name
    suffix = f".{vlan_id}"
    return parent[:max(MAX_NAME_LEN - len(suffix), 0)] + suffix


class _IpBox(Gtk.Grid):
    """Method, address, gateway and DNS for one address family."""

    def __init__(self, title: str):
        super().__init__(row_spacing=4, column_spacing=8)
        self.method = Gtk.ComboBoxText()
        for m in _METHODS:
            self.method.append(m, tr("method_" + m))
        self.method.set_active(0)
        self.address = Gtk.Entry(hexpand=True)
        self.gateway = Gtk.Entry(hexpand=True)
        self.dns = Gtk.Entry(hexpand=True)
        rows = ((tr("field_ipv4_method" if title == "ipv4"
                    else "field_ipv6_method"), self.method),
                (tr("field_address"), self.address),
                (tr("field_gateway"), self.gateway),
                (tr("field_dns"), self.dns))
        for i, (text, widget) in enumerate(rows):
            label = Gtk.Label(label=text, halign=Gtk.Align.END)
            self.attach(label, 0, i, 1, 1)
            self.attach(widget, 1, i, 1, 1)
        self.method.connect("changed", lambda _c: self._sync())
        self._sync()

    def _sync(self) -> None:
        manual = self.method.get_active_id() == "manual"
        for w in (self.address, self.gateway, self.dns):
            w.set_sensitive(manual)

    def load(self, cfg: IpConfig) -> None:
        self.method.set_active_id(cfg.method)
        self.address.set_text(cfg.address or "")
        self.gateway.set_text(cfg.gateway or "")
        self.dns.set_text(", ".join(cfg.dns))

    def config(self) -> IpConfig:
        method = self.method.get_active_id() or "auto"
        if method != "manual":
            return IpConfig(method)
        dns = tuple(p for p in self.dns.get_text().replace(",", " ").split())
        return IpConfig("manual", self.address.get_text().strip() or None,
                        self.gateway.get_text().strip() or None, dns)


class VlanDialog(Gtk.Dialog):
    def __init__(self, parent_window, nics: list[Nic],
                 existing: list[VlanSpec], editing: VlanSpec | None = None,
                 preselect: str | None = None):
        super().__init__(
            title=tr("dialog_edit_title" if editing else "dialog_add_title"),
            transient_for=parent_window, modal=True)
        self.existing = list(existing)
        self.editing = editing
        self._name_manual = editing is not None
        self._setting_name = False

        self.add_button(tr("btn_cancel"), Gtk.ResponseType.CANCEL)
        self.ok_button = self.add_button(tr("btn_ok"), Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)

        grid = Gtk.Grid(row_spacing=6, column_spacing=8, margin=12)
        self.parent_combo = Gtk.ComboBoxText()
        for nic in nics:
            if nic.managed:
                self.parent_combo.append(nic.name, nic.name)
        self.id_spin = Gtk.SpinButton.new_with_range(1, 4094, 1)
        self.id_spin.set_numeric(True)
        self.name_entry = Gtk.Entry(hexpand=True, max_length=0)
        self.autoconnect = Gtk.CheckButton(label=tr("field_autoconnect"),
                                           active=True)
        self.mtu_entry = Gtk.Entry(placeholder_text="auto")
        self.ipv4_box = _IpBox("ipv4")
        self.ipv6_box = _IpBox("ipv6")
        self.ipv4_method, self.ipv4_address = (self.ipv4_box.method,
                                               self.ipv4_box.address)
        self.ipv4_gateway, self.ipv4_dns = (self.ipv4_box.gateway,
                                            self.ipv4_box.dns)
        self.ipv6_method, self.ipv6_address = (self.ipv6_box.method,
                                               self.ipv6_box.address)
        self.ipv6_gateway, self.ipv6_dns = (self.ipv6_box.gateway,
                                            self.ipv6_box.dns)

        rows = ((tr("field_parent"), self.parent_combo),
                (tr("field_vlan_id"), self.id_spin),
                (tr("field_name"), self.name_entry),
                (tr("field_mtu"), self.mtu_entry))
        for i, (text, widget) in enumerate(rows):
            grid.attach(Gtk.Label(label=text, halign=Gtk.Align.END),
                        0, i, 1, 1)
            grid.attach(widget, 1, i, 1, 1)
        grid.attach(self.autoconnect, 1, len(rows), 1, 1)
        grid.attach(Gtk.Label(label=tr("field_ipv4"), halign=Gtk.Align.START),
                    0, len(rows) + 1, 2, 1)
        grid.attach(self.ipv4_box, 0, len(rows) + 2, 2, 1)
        grid.attach(Gtk.Label(label=tr("field_ipv6"), halign=Gtk.Align.START),
                    0, len(rows) + 3, 2, 1)
        grid.attach(self.ipv6_box, 0, len(rows) + 4, 2, 1)
        self.error_label = Gtk.Label(wrap=True, xalign=0)
        self.error_label.get_style_context().add_class("error")
        grid.attach(self.error_label, 0, len(rows) + 5, 2, 1)
        self.get_content_area().add(grid)

        if editing:
            if not self.parent_combo.set_active_id(editing.parent):
                self.parent_combo.append(editing.parent, editing.parent)
                self.parent_combo.set_active_id(editing.parent)
            self.parent_combo.set_sensitive(False)
            self.id_spin.set_value(editing.vlan_id)
            self._set_name(editing.name)
            self.autoconnect.set_active(editing.autoconnect)
            self.mtu_entry.set_text("" if editing.mtu is None
                                    else str(editing.mtu))
            self.ipv4_box.load(editing.ipv4)
            self.ipv6_box.load(editing.ipv6)
        else:
            if not (preselect
                    and self.parent_combo.set_active_id(preselect)):
                self.parent_combo.set_active(0)
            self._autofill()

        self.parent_combo.connect("changed", lambda _c: self._on_key_changed())
        self.id_spin.connect("value-changed", lambda _s: self._on_key_changed())
        self.name_entry.connect("changed", self._on_name_changed)
        for w in (self.mtu_entry, self.ipv4_address, self.ipv4_gateway,
                  self.ipv4_dns, self.ipv6_address, self.ipv6_gateway,
                  self.ipv6_dns):
            w.connect("changed", lambda _w: self._update())
        for combo in (self.ipv4_method, self.ipv6_method):
            combo.connect("changed", lambda _c: self._update())
        self.autoconnect.connect("toggled", lambda _c: self._update())
        self.show_all()
        self._update()

    # name handling

    def _set_name(self, text: str) -> None:
        self._setting_name = True
        try:
            self.name_entry.set_text(text)
        finally:
            self._setting_name = False

    def _autofill(self) -> None:
        parent = self.parent_combo.get_active_id() or ""
        self._set_name(autofill_name(parent, self.id_spin.get_value_as_int()))

    def _on_key_changed(self) -> None:
        if not self._name_manual:
            self._autofill()
        self._update()

    def _on_name_changed(self, _entry) -> None:
        if not self._setting_name:
            self._name_manual = True
        self._update()

    # validation

    def _mtu(self) -> tuple[int | None, bool]:
        text = self.mtu_entry.get_text().strip()
        if not text:
            return None, True
        if not text.isdigit():
            return None, False
        return int(text), True

    def current_spec(self) -> VlanSpec:
        mtu, _ = self._mtu()
        return VlanSpec(
            parent=self.parent_combo.get_active_id() or "",
            vlan_id=self.id_spin.get_value_as_int(),
            name=self.name_entry.get_text().strip(),
            ipv4=self.ipv4_box.config(), ipv6=self.ipv6_box.config(),
            autoconnect=self.autoconnect.get_active(), mtu=mtu)

    def errors(self) -> list[str]:
        spec = self.current_spec()
        errors = validate(spec, self.existing,
                          editing=self.editing.name if self.editing else None)
        if not self._mtu()[1] and "mtu_range" not in errors:
            errors.append("mtu_range")
        return errors

    def _update(self) -> None:
        errors = self.errors()
        has_parent = bool(self.parent_combo.get_active_id())
        self.error_label.set_text(tr(errors[0]) if errors else "")
        self.ok_button.set_sensitive(not errors and has_parent)

    def run_and_get(self) -> VlanSpec | None:
        try:
            response = self.run()
            if response == Gtk.ResponseType.OK and self.ok_button.get_sensitive():
                return self.current_spec()
            return None
        finally:
            self.destroy()


class ConfirmDialog(Gtk.Dialog):
    """Keep returns True; every other way of closing returns False."""

    def __init__(self, parent_window, seconds: int = CONFIRM_TIMEOUT_S):
        super().__init__(title=tr("dialog_confirm_title"),
                         transient_for=parent_window, modal=True)
        self.remaining = int(seconds)
        self.label = Gtk.Label(wrap=True, margin=12)
        self.get_content_area().add(self.label)
        self.btn_revert = self.add_button(tr("btn_revert"),
                                          Gtk.ResponseType.CANCEL)
        self.btn_keep = self.add_button(tr("btn_keep"), Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.CANCEL)
        self._timer = 0
        self._show_remaining()
        self.connect("destroy", self._stop_timer)
        self.show_all()

    def _show_remaining(self) -> None:
        self.label.set_text(tr("confirm_countdown", seconds=self.remaining))

    def _stop_timer(self, *_args) -> None:
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _tick(self) -> bool:
        self.remaining -= 1
        if self.remaining <= 0:
            self._timer = 0
            self.response(Gtk.ResponseType.CANCEL)
            return False
        self._show_remaining()
        return True

    def ask(self) -> bool:
        if self.remaining <= 0:
            self.destroy()
            return False
        self._timer = GLib.timeout_add_seconds(1, self._tick)
        try:
            return self.run() == Gtk.ResponseType.OK
        finally:
            self._stop_timer()
            self.destroy()
