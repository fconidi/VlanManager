import os
import re
import unittest
from unittest import mock

from vlanmanager import i18n


class I18nTest(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("en")

    def test_it_and_en_have_same_keys(self):
        self.assertEqual(set(i18n._IT), set(i18n._EN))

    def test_missing_key_returns_key(self):
        self.assertEqual(i18n.tr("no_such_key_xyz"), "no_such_key_xyz")

    def test_format_substitution(self):
        for lang in ("it", "en"):
            i18n.set_language(lang)
            self.assertIn("15", i18n.tr("confirm_countdown", seconds=15))

    def test_all_validation_codes_translated(self):
        codes = ["id_range", "name_empty", "name_len", "duplicate",
                 "address_invalid", "gateway_invalid", "dns_invalid",
                 "mtu_range",
                 "ok", "no_gateway", "ping_failed",
                 "nmcli_missing", "nmcli_timeout"]
        for lang in ("it", "en"):
            i18n.set_language(lang)
            for c in codes:
                self.assertNotEqual(i18n.tr(c), c, (lang, c))

    def test_gui_keys_present(self):
        keys = ["window_title", "btn_add", "btn_edit", "btn_delete",
                "btn_refresh", "btn_ok", "btn_cancel", "btn_keep",
                "btn_revert", "col_name", "col_vlan_id", "col_state",
                "col_ip", "field_parent", "field_vlan_id", "field_name",
                "field_ipv4_method", "field_ipv6_method", "method_auto",
                "method_manual", "method_disabled", "field_address",
                "field_gateway", "field_dns", "field_autoconnect",
                "field_mtu", "confirm_delete", "tooltip_unmanaged",
                "nm_not_running", "warn_8021q_missing", "native_vlan_note",
                "polkit_denied"]
        for lang in (i18n._IT, i18n._EN):
            for k in keys:
                self.assertIn(k, lang)

    def test_reachability_causes_mentioned(self):
        i18n.set_language("en")
        text = i18n.tr("no_gateway") + i18n.tr("ping_failed")
        self.assertIn("tagged", text)
        self.assertIn("trunk", text)
        self.assertIn("DHCP", text)

    def test_language_from_lang_env(self):
        with mock.patch.dict(os.environ, {"LANG": "it_IT.UTF-8"}):
            self.assertEqual(i18n.detect_language(), "it")
        with mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8"}):
            self.assertEqual(i18n.detect_language(), "en")
        with mock.patch.dict(os.environ, {"LANG": "de_DE"}):
            self.assertEqual(i18n.detect_language(), "en")

    def test_set_language_switches(self):
        i18n.set_language("it")
        self.assertEqual(i18n.tr("btn_cancel"), "Annulla")
        i18n.set_language("en")
        self.assertEqual(i18n.tr("btn_cancel"), "Cancel")

    def test_italian_uses_accented_letters(self):
        self.assertIn("già", i18n._IT["duplicate"])

    def test_italian_has_no_ascii_accent_substitutes(self):
        pat = re.compile(r"[a-z]'(\s|$|[.,;:!?])")
        for key, value in i18n._IT.items():
            self.assertIsNone(pat.search(value), (key, value))

    def test_italian_reachability_causes_mentioned(self):
        for key in ("no_gateway", "ping_failed"):
            self.assertIn("trunk", i18n._IT[key])
            self.assertIn("DHCP", i18n._IT[key])


if __name__ == "__main__":
    unittest.main()
