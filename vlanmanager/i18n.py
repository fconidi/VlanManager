"""Italian and English UI strings."""
import os

_EN = {
    # validation codes
    "id_range": "The VLAN ID must be between 1 and 4094.",
    "name_empty": "The interface name must not be empty.",
    "name_len": "The interface name must be at most 15 characters.",
    "duplicate": "A VLAN with this ID or name already exists on this interface.",
    "address_invalid": "The IP address is not valid (use address/prefix, e.g. 192.168.10.5/24).",
    "gateway_invalid": "The gateway address is not valid.",
    "mtu_range": "The MTU must be between 576 and 9000.",
    # probe codes
    "ok": "The VLAN is working: the gateway answered.",
    "no_gateway": ("No gateway was obtained, so reachability could not be "
                   "checked. Likely causes: the switch port is not tagged "
                   "for this VLAN, the VLAN is not allowed on the trunk, or "
                   "there is no DHCP server on this VLAN."),
    "ping_failed": ("The gateway did not answer. Likely causes: the switch "
                    "port is not tagged for this VLAN, the VLAN is not "
                    "allowed on the trunk, or there is no DHCP server on "
                    "this VLAN."),
    # nm errors
    "nmcli_missing": "nmcli was not found. Install NetworkManager.",
    "nmcli_timeout": "NetworkManager did not respond in time.",
    # GUI
    "window_title": "VLAN Manager",
    "btn_add": "Add",
    "btn_edit": "Edit",
    "btn_delete": "Delete",
    "btn_refresh": "Refresh",
    "btn_ok": "OK",
    "btn_cancel": "Cancel",
    "btn_keep": "Keep",
    "btn_revert": "Revert",
    "col_name": "Name",
    "col_vlan_id": "VLAN ID",
    "col_state": "State",
    "col_ip": "IP",
    "field_parent": "Parent interface",
    "field_vlan_id": "VLAN ID",
    "field_name": "Name",
    "field_ipv4_method": "IPv4 method",
    "field_ipv6_method": "IPv6 method",
    "method_auto": "DHCP",
    "method_manual": "Static",
    "method_disabled": "Disabled",
    "field_address": "Address",
    "field_gateway": "Gateway",
    "field_dns": "DNS",
    "field_autoconnect": "Connect automatically",
    "field_mtu": "MTU",
    "confirm_countdown": ("Keep this configuration? It will be reverted "
                          "automatically in {seconds} seconds."),
    "confirm_delete": "Delete this VLAN? The connection will be removed.",
    "tooltip_unmanaged": "This interface is not managed by NetworkManager.",
    "state_active": "Active",
    "state_inactive": "Inactive",
    "nm_not_running": "NetworkManager is not running.",
    "warn_8021q_missing": ("The 8021q kernel module is not available; "
                           "VLANs cannot be created."),
    "native_vlan_note": ("Untagged traffic stays on the base connection "
                         "(native VLAN)."),
    "polkit_denied": ("Permission denied. You need administrator "
                      "authorization to change network settings."),
}

_IT = {
    "id_range": "L'ID VLAN deve essere compreso tra 1 e 4094.",
    "name_empty": "Il nome dell'interfaccia non può essere vuoto.",
    "name_len": "Il nome dell'interfaccia può avere al massimo 15 caratteri.",
    "duplicate": "Esiste già una VLAN con questo ID o nome su questa interfaccia.",
    "address_invalid": "L'indirizzo IP non è valido (usa indirizzo/prefisso, es. 192.168.10.5/24).",
    "gateway_invalid": "L'indirizzo del gateway non è valido.",
    "mtu_range": "L'MTU deve essere compreso tra 576 e 9000.",
    "ok": "La VLAN funziona: il gateway ha risposto.",
    "no_gateway": ("Nessun gateway ottenuto, quindi la raggiungibilità non "
                   "è verificabile. Cause probabili: la porta dello switch "
                   "non è taggata per questa VLAN, la VLAN non è permessa "
                   "sul trunk, oppure su questa VLAN non c'è un server DHCP."),
    "ping_failed": ("Il gateway non ha risposto. Cause probabili: la porta "
                    "dello switch non è taggata per questa VLAN, la VLAN non "
                    "è permessa sul trunk, oppure su questa VLAN non c'è un "
                    "server DHCP."),
    "nmcli_missing": "nmcli non trovato. Installa NetworkManager.",
    "nmcli_timeout": "NetworkManager non ha risposto in tempo.",
    "window_title": "Gestione VLAN",
    "btn_add": "Aggiungi",
    "btn_edit": "Modifica",
    "btn_delete": "Elimina",
    "btn_refresh": "Aggiorna",
    "btn_ok": "OK",
    "btn_cancel": "Annulla",
    "btn_keep": "Mantieni",
    "btn_revert": "Ripristina",
    "col_name": "Nome",
    "col_vlan_id": "ID VLAN",
    "col_state": "Stato",
    "col_ip": "IP",
    "field_parent": "Interfaccia padre",
    "field_vlan_id": "ID VLAN",
    "field_name": "Nome",
    "field_ipv4_method": "Metodo IPv4",
    "field_ipv6_method": "Metodo IPv6",
    "method_auto": "DHCP",
    "method_manual": "Statico",
    "method_disabled": "Disabilitato",
    "field_address": "Indirizzo",
    "field_gateway": "Gateway",
    "field_dns": "DNS",
    "field_autoconnect": "Connetti automaticamente",
    "field_mtu": "MTU",
    "confirm_countdown": ("Mantenere questa configurazione? Verrà "
                          "ripristinata automaticamente tra {seconds} secondi."),
    "confirm_delete": "Eliminare questa VLAN? La connessione verrà rimossa.",
    "tooltip_unmanaged": "Questa interfaccia non è gestita da NetworkManager.",
    "state_active": "Attiva",
    "state_inactive": "Inattiva",
    "nm_not_running": "NetworkManager non è in esecuzione.",
    "warn_8021q_missing": ("Il modulo del kernel 8021q non è disponibile; "
                           "non è possibile creare VLAN."),
    "native_vlan_note": ("Il traffico senza tag resta sulla connessione base "
                         "(VLAN nativa)."),
    "polkit_denied": ("Permesso negato. Servono le autorizzazioni di "
                      "amministratore per modificare le impostazioni di rete."),
}

_LANGS = {"en": _EN, "it": _IT}


def detect_language() -> str:
    lang = os.environ.get("LANG", "")
    return "it" if lang.lower().startswith("it") else "en"


_current = detect_language()


def set_language(code: str) -> None:
    global _current
    _current = "it" if str(code).lower().startswith("it") else "en"


def tr(key: str, **fmt) -> str:
    text = _LANGS[_current].get(key, key)
    return text.format(**fmt) if fmt else text
