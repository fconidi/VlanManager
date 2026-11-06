# Changelog

## 0.1.2

- Added an option to keep a VLAN from becoming the default route.
- Rejected interface names that are invalid or already used by another interface.
- Rejected host addresses equal to the network address, gateways equal to the address or outside its subnet, and MTU values above the parent interface MTU.
- Showed an error for out-of-range VLAN IDs instead of silently correcting them.
- Kept VLANs whose parent interface is missing visible, so they can be edited or deleted.
- Disabled Add when no managed interface is available and Add/Edit when the 8021q module is missing.
- Translated interface states and the MTU placeholder.

## 0.1.1

- Validate that static addresses, gateways and DNS servers match their IPv4 or IPv6 fields.

## 0.1.0

- First version.
- List wired interfaces and their VLANs.
- Create, edit, delete, activate and deactivate 802.1Q VLANs through NetworkManager, with DHCP or static IPv4/IPv6.
- Reachability check of the gateway through the VLAN interface.
- Automatic revert of unconfirmed changes, performed by NetworkManager through a checkpoint, with an in-app fallback.
- Italian and English interface.
- Menu entries in Network and in SysLinuxOS Tools, with its own icon.
