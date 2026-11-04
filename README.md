# VlanManager

A small GTK3 application to create and manage 802.1Q VLANs on wired network
interfaces through NetworkManager. Made for SysLinuxOS and Debian-based systems.

## Features

- Lists wired network interfaces and existing VLANs
- Create, edit, delete, activate and deactivate VLANs
- IPv4 and IPv6 configuration, DHCP or static
- Reachability check of the gateway through the VLAN interface
- Automatic revert: if a change is not confirmed within 20 seconds, the
  previous configuration is restored. The revert is performed by NetworkManager
  itself through a checkpoint, with an in-app fallback.

## Requirements

- `python3`
- `python3-gi` and `gir1.2-gtk-3.0`
- `network-manager`
- `iputils-ping`
- the `8021q` kernel module

## Run

    python3 -m vlanmanager

## Limits

- Wired interfaces only. A Wi-Fi client cannot tag 802.1Q frames: the access
  point decides the VLAN of a Wi-Fi connection.
- Untagged traffic stays on the base connection (the native VLAN).
- Interfaces not managed by NetworkManager are shown but not modified.
- Some network cards and drivers handle VLAN tags or a larger MTU poorly.
- Permissions come from polkit through NetworkManager. The application does
  not need root privileges.
- The revert checkpoint covers all network devices. After a change is applied,
  the revert window is the confirmation time (20 seconds) plus about 10
  seconds of margin; while the change is being applied NetworkManager keeps a
  longer safety timer. Other network changes made in that window are reverted
  too.

## License

GPL-3.0
