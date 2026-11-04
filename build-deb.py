#!/usr/bin/python3
"""Build the vlanmanager Debian package from an explicit file list."""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

MODULES = (
    "__init__.py", "__main__.py", "i18n.py",
    "core/__init__.py", "core/checkpoint.py", "core/model.py", "core/nm.py",
    "core/ops.py", "core/probe.py", "core/rollback.py",
    "gui/__init__.py", "gui/dialogs.py", "gui/window.py", "gui/worker.py",
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build VlanManager for Debian")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parent
    package = source / "vlanmanager"
    match = re.search(r'__version__ = "([^"]+)"',
                      (package / "__init__.py").read_text(encoding="utf-8"))
    if match is None:
        raise ValueError("package version is missing")
    version = match.group(1)
    with tempfile.TemporaryDirectory(prefix="package-", dir=output) as tmp:
        root = Path(tmp)

        def install(origin: Path, relative: str, executable: bool = False):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(origin, target)
            target.chmod(0o755 if executable else 0o644)

        for name in MODULES:
            install(package / name, f"usr/share/vlanmanager/vlanmanager/{name}")
        install(source / "packaging/vlanmanager", "usr/bin/vlanmanager", True)
        install(source / "packaging/org.syslinuxos.VlanManager.desktop",
                "usr/share/applications/org.syslinuxos.VlanManager.desktop")
        install(source / "packaging/org.syslinuxos.VlanManager.menu",
                "etc/xdg/menus/applications-merged/"
                "org.syslinuxos.VlanManager.menu")
        install(source / "data/org.syslinuxos.VlanManager.svg",
                "usr/share/icons/hicolor/scalable/apps/"
                "org.syslinuxos.VlanManager.svg")
        for name in ("README.md", "CHANGELOG.md", "LICENSE"):
            install(source / name, f"usr/share/doc/vlanmanager/{name}")
        control = root / "DEBIAN"
        control.mkdir()
        (control / "control").write_text(
            f"Package: vlanmanager\nVersion: {version}\nArchitecture: all\n"
            "Section: net\nPriority: optional\n"
            "Maintainer: Franco Conidi <fconidi@gmail.com>\n"
            "Depends: python3 (>= 3.11), python3-gi, gir1.2-gtk-3.0, "
            "network-manager, iputils-ping\n"
            "Description: Create and manage 802.1Q VLANs on wired interfaces\n"
            " VlanManager is a graphical tool to add VLANs to a wired network\n"
            " interface through NetworkManager, with DHCP or static addressing,\n"
            " a reachability check and automatic revert of unconfirmed changes.\n",
            encoding="utf-8")
        root.chmod(0o755)
        for directory in root.rglob("*"):
            if directory.is_dir():
                directory.chmod(0o755)
        artifact = output / f"vlanmanager_{version}_all.deb"
        subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(root),
                        str(artifact)], check=True)
        print(artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
