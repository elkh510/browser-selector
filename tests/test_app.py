"""app: the unit name from the cgroup file and CHROME_DESKTOP."""

import unittest

from support import CGROUP, bs


class CgroupUnit(unittest.TestCase):
    def test_last_component_of_the_v2_line(self):
        self.assertEqual(bs.cgroup_unit(CGROUP.format("app-slack-2382881.scope")), "app-slack-2382881.scope")

    def test_empty_file(self):
        self.assertIsNone(bs.cgroup_unit(""))

    def test_root_cgroup(self):
        self.assertIsNone(bs.cgroup_unit("0::/\n"))

    def test_garbage(self):
        self.assertIsNone(bs.cgroup_unit("not a cgroup file\n"))

    def test_v1_takes_the_systemd_hierarchy(self):
        text = ("12:pids:/user.slice/user-1000.slice/user@1000.service\n"
                "5:memory:/user.slice/user-1000.slice/user@1000.service\n"
                "1:name=systemd:/user.slice/user-1000.slice/user@1000.service/app.slice/app-slack-77.scope\n")
        self.assertEqual(bs.cgroup_unit(text), "app-slack-77.scope")

    def test_v1_without_a_systemd_hierarchy(self):
        self.assertIsNone(bs.cgroup_unit("12:pids:/user.slice\n5:memory:/user.slice\n"))

    def test_hybrid_prefers_the_v2_line(self):
        text = "1:name=systemd:/user.slice/old.service\n0::/user.slice/app-slack-1.scope\n"
        self.assertEqual(bs.cgroup_unit(text), "app-slack-1.scope")


class UnitAppId(unittest.TestCase):
    def test_real_unit_names(self):
        names = {
            "app-slack-2382881.scope": "slack",
            "app-desktop-2381856.scope": "desktop",
            "app-gnome-netbird-14016.scope": "netbird",
            "warp-taskbar.service": "warp-taskbar",
            "app-com.microsoft.VSCode-2079352.scope": "com.microsoft.VSCode",
        }
        for unit, app in names.items():
            with self.subTest(unit=unit):
                self.assertEqual(bs.unit_app_id(unit), app)

    def test_systemd_escapes_are_decoded(self):
        self.assertEqual(bs.unit_app_id(r"app-gnome-google\x2dchrome-4242.scope"), "google-chrome")

    def test_an_escaped_dash_is_not_a_separator(self):
        self.assertEqual(bs.unit_app_id(r"app-tool\x2d2024-4242.scope"), "tool-2024")
        self.assertEqual(bs.unit_app_id(r"tool\x2d2024.service"), "tool-2024")
        self.assertEqual(bs.unit_app_id(r"app\x2dgnome\x2dtool-7.scope"), "app-gnome-tool")

    def test_non_ascii_escapes(self):
        self.assertEqual(bs.unit_app_id(r"app-caf\xc3\xa9-1.scope"), "café")

    def test_gnome_is_dropped_only_after_app(self):
        self.assertEqual(bs.unit_app_id("gnome-terminal-server.service"), "gnome-terminal-server")

    def test_other_suffixes_stay(self):
        self.assertEqual(bs.unit_app_id("app.slice"), "app.slice")

    def test_template_instance_is_dropped(self):
        names = {
            "app-slack@autostart.service": "slack",
            "app-gnome-slack@autostart.service": "slack",
            r"app-gnome-user\x2ddirs\x2dupdate\x2dgtk@autostart.service": "user-dirs-update-gtk",
            "app-org.gnome.Terminal@4f2a9c.service": "org.gnome.Terminal",
            "app-slack@12345.service": "slack",
            "app-slack-77@autostart.service": "slack",
        }
        for unit, app in names.items():
            with self.subTest(unit=unit):
                self.assertEqual(bs.unit_app_id(unit), app)

    def test_flatpak_scope(self):
        self.assertEqual(bs.unit_app_id("app-flatpak-org.mozilla.firefox-12345.scope"), "org.mozilla.firefox")
        self.assertEqual(bs.unit_app_id("app-flatpak-com.slack.Slack-987654321.scope"), "com.slack.Slack")
        self.assertEqual(bs.unit_app_id("flatpak-helper.service"), "flatpak-helper")

    def test_an_autostarted_app_matches_a_plain_rule(self):
        unit = bs.cgroup_unit(CGROUP.format("app-slack@autostart.service"))
        self.assertEqual(bs.app_ids(unit, {}), ["slack"])


class AppIds(unittest.TestCase):
    def test_unit_and_chrome_desktop_are_both_candidates(self):
        env = {"CHROME_DESKTOP": "slack.desktop"}
        self.assertEqual(bs.app_ids("app-desktop-2381856.scope", env), ["desktop", "slack"])

    def test_the_same_id_is_listed_once(self):
        self.assertEqual(bs.app_ids("app-slack-2382881.scope", {"CHROME_DESKTOP": "slack.desktop"}), ["slack"])

    def test_chrome_desktop_alone(self):
        self.assertEqual(bs.app_ids(None, {"CHROME_DESKTOP": "code-url-handler.desktop"}), ["code-url-handler"])

    def test_chrome_desktop_without_the_suffix(self):
        self.assertEqual(bs.app_ids(None, {"CHROME_DESKTOP": "slack"}), ["slack"])

    def test_nothing_known(self):
        self.assertEqual(bs.app_ids(None, {}), [])
        self.assertEqual(bs.app_ids(None, {"CHROME_DESKTOP": ""}), [])


if __name__ == "__main__":
    unittest.main()
