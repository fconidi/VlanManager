"""Entry point: python3 -m vlanmanager."""
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from .core.nm import NmClient  # noqa: E402
from .gui.window import MainWindow  # noqa: E402


class VlanManagerApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="org.syslinuxos.VlanManager")

    def do_activate(self) -> None:
        win = self.props.active_window or MainWindow(self, NmClient())
        win.present()


def main() -> int:
    return VlanManagerApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
