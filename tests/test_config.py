"""Config: every error the contract lists, with its section and key."""

import os
import re
import unittest

from support import CONFIG, ROOT, URL, HandlerCase, bs, read, watchdog

BROWSER = """
[settings]
default = main

[browser main]
command = google-chrome
"""


class Validation(unittest.TestCase):
    def assertError(self, text, where):
        """One of the errors starts with `where`: the section and the key."""
        config, errors = bs.parse_config(text)
        self.assertIsNone(config)
        self.assertTrue(any(error.startswith(where) for error in errors), errors)

    def test_valid_config(self):
        config, errors = bs.parse_config(CONFIG)
        self.assertEqual(errors, [])
        self.assertEqual(config["default"], "chrome-main")
        self.assertEqual(config["probe_timeout"], 2)
        self.assertEqual(config["browsers"]["chrome-main"], ["google-chrome", "--profile-directory=Profile 6"])
        self.assertEqual([rule["name"] for rule in config["rules"]],
                         ["cloudflare", "slack-acme", "slack-globex", "netbird-globex"])

    def test_unknown_section(self):
        self.assertError(BROWSER + "[bogus]\nkey = 1\n", "[bogus]: unknown section")
        self.assertError(BROWSER + "[browser]\ncommand = firefox\n", "[browser]: unknown section")
        self.assertError(BROWSER + "[settings extra]\ndefault = main\n", "[settings extra]: unknown section")
        self.assertError(BROWSER + "[DEFAULT]\nbrowser = main\n", "[DEFAULT]: unknown section")

    def test_unknown_key(self):
        self.assertError(BROWSER + "[rule r]\nbrowser = main\nhost = x\n", "[rule r] host: unknown key")
        self.assertError(BROWSER.replace("command = google-chrome", "command = google-chrome\nprofile = x"),
                         "[browser main] profile: unknown key")
        self.assertError(BROWSER.replace("default = main", "default = main\nfallback = main"),
                         "[settings] fallback: unknown key")

    def test_keys_are_case_sensitive(self):
        self.assertError(BROWSER + "[rule r]\nbrowser = main\nApp = slack\n", "[rule r] App: unknown key")

    def test_missing_default(self):
        self.assertError("[browser main]\ncommand = google-chrome\n", "[settings] default: missing")
        self.assertError("[settings]\nprobe_timeout = 2\n[browser main]\ncommand = google-chrome\n",
                         "[settings] default: missing")

    def test_missing_command(self):
        self.assertError("[settings]\ndefault = main\n[browser main]\n", "[browser main] command: missing")
        self.assertError("[settings]\ndefault = main\n[browser main]\ncommand =\n", "[browser main] command: missing")

    def test_missing_browser(self):
        self.assertError(BROWSER + "[rule r]\napp = slack\n", "[rule r] browser: missing")

    def test_browser_not_defined(self):
        self.assertError(BROWSER + "[rule r]\nbrowser = other\n", "[rule r] browser: browser other is not defined")
        self.assertError(BROWSER.replace("default = main", "default = other"),
                         "[settings] default: browser other is not defined")

    def test_regex_does_not_compile(self):
        for key in ("app", "window", "title", "url"):
            with self.subTest(key=key):
                self.assertError(BROWSER + f"[rule r]\n{key} = (\nbrowser = main\n", f"[rule r] {key}: bad regex")
        self.assertError(BROWSER + "[rule r]\nprobe = true\nprobe_match = [\nbrowser = main\n",
                         "[rule r] probe_match: bad regex")

    def test_probe_and_probe_match_come_together(self):
        self.assertError(BROWSER + "[rule r]\nprobe = true\nbrowser = main\n", "[rule r] probe_match: missing")
        self.assertError(BROWSER + "[rule r]\nprobe_match = x\nbrowser = main\n", "[rule r] probe: missing")

    def test_command_that_would_loop(self):
        programs = ("xdg-open", "gio open", "gnome-open", "sensible-browser", "browser-selector",
                    "/usr/bin/xdg-open", "/home/user/.local/bin/browser-selector", "./browser_selector.py")
        for command in programs:
            with self.subTest(command=command):
                self.assertError(f"[settings]\ndefault = main\n[browser main]\ncommand = {command}\n",
                                 "[browser main] command: ")

    def test_every_error_is_reported_at_once(self):
        text = "[browser main]\ncommand = xdg-open\n[rule r]\ntitle = (\n[bogus]\n"
        errors = bs.parse_config(text)[1]
        for where in ("[settings] default:", "[browser main] command:", "[rule r] title:",
                      "[rule r] browser:", "[bogus]:"):
            with self.subTest(where=where):
                self.assertTrue(any(error.startswith(where) for error in errors), errors)

    # Not in the list of the contract, but they would break a run later.

    def test_probe_timeout_must_be_a_number_from_0_to_30(self):
        for value in ("soon", "0", "-1", "nan", "inf", "1e7", "30.5"):
            with self.subTest(value=value):
                self.assertError(BROWSER.replace("default = main", f"default = main\nprobe_timeout = {value}"),
                                 "[settings] probe_timeout: ")

    def test_probe_timeout_in_range(self):
        for value in ("0.1", "2", "30"):
            with self.subTest(value=value):
                config, errors = bs.parse_config(BROWSER.replace("default = main",
                                                                 f"default = main\nprobe_timeout = {value}"))
                self.assertEqual((config["probe_timeout"], errors), (float(value), []))

    def test_regex_that_breaks_the_compiler(self):
        # re.compile raises OverflowError here, not re.error
        self.assertError(BROWSER + "[rule r]\nurl = x{99999999999}\nbrowser = main\n", "[rule r] url: bad regex")
        self.assertError(BROWSER + "[rule r]\ntitle = " + "(" * 5000 + ")" * 5000 + "\nbrowser = main\n",
                         "[rule r] title: bad regex")

    def test_command_with_a_nul_byte(self):
        self.assertError("[settings]\ndefault = main\n[browser main]\ncommand = firefox --name=a\0b\n",
                         "[browser main] command: ")

    def test_command_that_would_loop_through_another_program(self):
        for command in ("env xdg-open", "env -u X /usr/bin/gio open", f"python3 {bs.HANDLER}",
                        "sh /home/user/.local/bin/browser-selector"):
            with self.subTest(command=command):
                self.assertError(f"[settings]\ndefault = main\n[browser main]\ncommand = {command}\n",
                                 "[browser main] command: ")

    def test_command_with_an_open_quote(self):
        self.assertError('[settings]\ndefault = main\n[browser main]\ncommand = chrome "Profile 6\n',
                         "[browser main] command: ")

    def test_probe_that_cannot_run(self):
        self.assertError(BROWSER + "[rule r]\nprobe = @nothing\nprobe_match = x\nbrowser = main\n",
                         "[rule r] probe: unknown built-in")
        self.assertError(BROWSER + "[rule r]\nprobe =\nprobe_match = x\nbrowser = main\n", "[rule r] probe: empty")
        self.assertError(BROWSER + "[rule r]\nprobe = sh -c 'x\nprobe_match = x\nbrowser = main\n", "[rule r] probe: ")

    def test_broken_ini_names_the_section(self):
        config, errors = bs.parse_config(BROWSER + "[browser main]\ncommand = firefox\n")
        self.assertIsNone(config)
        self.assertEqual(len(errors), 1)
        self.assertIn("main", errors[0])
        self.assertNotIn("\n", errors[0])

    def test_format_details(self):
        text = BROWSER + ("; a comment\n# another one\n"
                          "[rule r]\nurl = ^https://x\\.com/#frag;%(y)s\nbrowser = main\n")
        config, errors = bs.parse_config(text)
        self.assertEqual(errors, [])
        self.assertEqual(config["rules"][0]["url"].pattern, r"^https://x\.com/#frag;%(y)s")

    def test_regex_flags(self):
        rule = bs.parse_config(BROWSER + "[rule r]\napp = a\nwindow = w\ntitle = t\nurl = u\n"
                                         "probe = true\nprobe_match = p\nbrowser = main\n")[0]["rules"][0]
        self.assertTrue(rule["app"].flags & re.IGNORECASE)
        self.assertTrue(rule["window"].flags & re.IGNORECASE)
        self.assertFalse(rule["title"].flags & re.IGNORECASE)
        self.assertFalse(rule["url"].flags & re.IGNORECASE)
        self.assertTrue(rule["probe_match"].flags & re.MULTILINE)
        self.assertFalse(rule["probe_match"].flags & re.IGNORECASE)


class HandlerItself(HandlerCase):
    """A command that resolves to the handler under another name."""

    def setUp(self):
        super().setUp()
        self.link = os.path.join(self.tmp, "bin", "my-browser")
        os.mkdir(os.path.dirname(self.link))
        os.symlink(bs.HANDLER, self.link)
        self.text = "[settings]\ndefault = main\n[browser main]\ncommand = {} --new-tab\n"

    def test_a_path_to_a_link_to_the_handler(self):
        errors = bs.parse_config(self.text.format(self.link))[1]
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith("[browser main] command: "), errors)

    def test_a_program_that_resolves_to_the_handler(self):
        text = self.text.format("my-browser")
        self.assertEqual(bs.parse_config(text)[1], [])
        errors = bs.parse_config(text, which=lambda program: self.link)[1]
        self.assertTrue(errors and errors[0].startswith("[browser main] command: "), errors)

    def test_check_resolves_the_program_on_the_path(self):
        self.write_config(self.text.format("my-browser"))
        self.env["PATH"] = os.path.dirname(self.link)
        code, out, err = self.handle("--check", which=lambda program: self.link if program == "my-browser" else None)
        self.assertEqual(code, 2)
        self.assertIn("[browser main] command: ", err)

    def test_check_with_the_real_which(self):
        path = self.write_config(self.text.format("my-browser"))
        env = {"HOME": self.home, "PATH": os.path.dirname(self.link)}
        errors = bs.load_config(path, lambda program: bs.shutil.which(program, path=env["PATH"]))[1]
        self.assertTrue(errors and errors[0].startswith("[browser main] command: "), errors)


class LoadConfig(HandlerCase):
    """What can sit at the config path."""

    def setUp(self):
        super().setUp()
        self.path = self.write_config(BROWSER)
        # A reader that blocks would hang the whole run: fail instead.
        watchdog(self)

    def test_valid_file(self):
        config, errors = bs.load_config(self.path)
        self.assertEqual((config["default"], errors), ("main", []))

    def test_no_file(self):
        self.assertEqual(bs.load_config(os.path.join(self.tmp, "nothing.ini")), (None, []))

    def test_utf8_bom(self):
        with open(self.path, "w", encoding="utf-8-sig") as file:
            file.write(BROWSER.lstrip())
        self.assertEqual(read(self.path)[0], "\ufeff")
        config, errors = bs.load_config(self.path)
        self.assertEqual((config["default"], errors), ("main", []))

    def assertNotValid(self, path, text=""):
        config, errors = bs.load_config(path)
        self.assertIsNone(config)
        self.assertEqual(len(errors), 1)
        self.assertIn(text, errors[0])

    def test_directory(self):
        self.assertNotValid(self.home, "not a regular file")

    def test_fifo(self):
        fifo = os.path.join(self.tmp, "fifo")
        os.mkfifo(fifo)
        self.assertNotValid(fifo, "not a regular file")

    def test_device(self):
        self.assertNotValid("/dev/null", "not a regular file")

    @unittest.skipIf(os.geteuid() == 0, "root reads every file")
    def test_unreadable_file(self):
        os.chmod(self.path, 0)
        self.assertNotValid(self.path, "PermissionError")

    def test_not_utf8(self):
        with open(self.path, "wb") as file:
            file.write(BROWSER.encode() + b"[rule r]\ntitle = caf\xe9\nbrowser = main\n")
        self.assertNotValid(self.path, "UnicodeDecodeError")

    def test_a_click_with_a_fifo_as_the_config_opens_the_last_resort(self):
        fifo = os.path.join(self.tmp, "fifo")
        os.mkfifo(fifo)
        self.env["BROWSER_SELECTOR_CONFIG"] = fifo
        self.assertEqual(self.handle("--check")[0], 2)
        self.assertEqual(self.handle(URL)[0], 0)
        self.assertEqual(self.started, [["google-chrome", URL]])
        self.assertIn("not a regular file", self.log())


class Check(HandlerCase):
    def test_valid_config_exits_0(self):
        self.write_config(CONFIG)
        code, out, err = self.handle("--check")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("ok", out)

    def test_invalid_config_exits_2_and_names_section_and_key(self):
        self.write_config(BROWSER + "[rule r]\ntitle = (\nbrowser = other\n")
        code, out, err = self.handle("--check")
        self.assertEqual(code, 2)
        self.assertIn("[rule r] title: bad regex", err)
        self.assertIn("[rule r] browser: browser other is not defined", err)

    def test_no_config_file_exits_2(self):
        code, out, err = self.handle("--check")
        self.assertEqual(code, 2)
        self.assertIn("config.ini: no such file", err)

    def test_regex_that_breaks_the_compiler_exits_2(self):
        self.write_config(BROWSER + "[rule r]\nurl = x{99999999999}\nbrowser = main\n")
        code, out, err = self.handle("--check")
        self.assertEqual(code, 2)
        self.assertIn("[rule r] url: bad regex", err)

    def test_probe_timeout_out_of_range_exits_2(self):
        self.write_config(BROWSER.replace("default = main", "default = main\nprobe_timeout = 1e7"))
        code, out, err = self.handle("--check")
        self.assertEqual(code, 2)
        self.assertIn("[settings] probe_timeout: ", err)

    def test_check_starts_nothing_and_reads_nothing(self):
        self.write_config(CONFIG)
        self.handle("--check")
        self.assertEqual((self.started, self.window_reads, self.probe_runs, self.log()), ([], 0, [], ""))


class ConfigPath(HandlerCase):
    def test_default_path_is_under_xdg_config_home(self):
        self.assertEqual(bs.config_path({"HOME": "/h"}, None), "/h/.config/browser-selector/config.ini")
        self.assertEqual(bs.config_path({"HOME": "/h", "XDG_CONFIG_HOME": "/c"}, None),
                         "/c/browser-selector/config.ini")

    def test_option_beats_the_default_path(self):
        self.write_config("[bogus]\n")
        other = self.write_config(CONFIG, "other.ini")
        self.assertEqual(self.handle("--check")[0], 2)
        self.assertEqual(self.handle("--config", other, "--check")[0], 0)

    def test_environment_beats_the_default_path(self):
        self.write_config("[bogus]\n")
        self.env["BROWSER_SELECTOR_CONFIG"] = self.write_config(CONFIG, "good.ini")
        self.assertEqual(self.handle("--check")[0], 0)

    def test_option_beats_the_environment(self):
        good = self.write_config(CONFIG, "good.ini")
        bad = self.write_config("[bogus]\n", "bad.ini")
        self.env["BROWSER_SELECTOR_CONFIG"] = bad
        self.assertEqual(self.handle("--config", good, "--check")[0], 0)
        self.env["BROWSER_SELECTOR_CONFIG"] = good
        self.assertEqual(self.handle("--config", bad, "--check")[0], 2)
        self.assertEqual(bs.config_path({"HOME": "/h", "BROWSER_SELECTOR_CONFIG": "/env.ini"}, "/option.ini"),
                         "/option.ini")


class ExampleConfig(HandlerCase):
    """config.example.ini is valid and sends the documented cases where it says."""

    def setUp(self):
        super().setUp()
        self.env["BROWSER_SELECTOR_CONFIG"] = os.path.join(ROOT, "config.example.ini")

    def started_by(self, url="https://example.com/", **context):
        self.started.clear()
        self.assertEqual(self.handle(url, **context)[0], 0)
        return self.started[0]

    def test_is_valid_and_has_no_comments(self):
        self.assertEqual(self.handle("--check")[0], 0)
        text = read(self.env["BROWSER_SELECTOR_CONFIG"])
        self.assertFalse([line for line in text.splitlines() if line.lstrip().startswith(("#", ";"))])

    def test_cases(self):
        unit = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/{}\n".format
        slack = unit("app-slack-2382881.scope")
        chrome = "google-chrome"
        cases = [
            ("default", {}, [chrome, "--profile-directory=Profile 6"]),
            ("slack acme", {"cgroup": slack, "window": (["slack", "Slack"], "Threads - Acme - Slack")},
             [chrome, "--profile-directory=Profile 9"]),
            ("slack globex", {"cgroup": slack, "window": (["slack", "Slack"], "general (Channel) - Globex - Slack")},
             ["brave-browser", "--profile-directory=Default"]),
            ("clickup desktop", {"cgroup": unit("app-desktop-2381856.scope"),
                                 "window": (["clickup", "ClickUp"],
                                            "Overview | Project Management | Initech (Overview)")},
             [chrome, "--profile-directory=Profile 15"]),
            ("clickup", {"cgroup": unit("app-clickup-99.scope"), "window": (["clickup", "ClickUp"], "Home | Initech")},
             [chrome, "--profile-directory=Profile 15"]),
            ("clickup, a task named like the workspace",
             {"cgroup": unit("app-clickup-99.scope"),
              "window": (["clickup", "ClickUp"], "Sync | Initech (draft) | Other Team (Board)")},
             [chrome, "--profile-directory=Profile 6"]),
            ("clickup, the name inside another part",
             {"cgroup": unit("app-clickup-99.scope"),
              "window": (["clickup", "ClickUp"], "Report | Initech invoices | Other Team")},
             [chrome, "--profile-directory=Profile 6"]),
            ("clickup, a longer workspace name",
             {"cgroup": unit("app-clickup-99.scope"), "window": (["clickup", "ClickUp"], "Home | Initech Labs")},
             [chrome, "--profile-directory=Profile 6"]),
            ("netbird globex", {"cgroup": unit("app-gnome-netbird-14016.scope"),
                                "probes": {"netbird profile list": "NAME     ACTIVE\ndefault  \nglobex   ✓\n"}},
             ["brave-browser", "--profile-directory=Default"]),
            ("netbird default", {"cgroup": unit("app-gnome-netbird-14016.scope"),
                                 "probes": {"netbird profile list": "NAME     ACTIVE\ndefault  ✓\nglobex   \n"}},
             [chrome, "--profile-directory=Profile 6"]),
            ("cloudflare", {"url": "https://acme.cloudflareaccess.com/cdn-cgi/access/login"},
             [chrome, "--profile-directory=Profile 9"]),
        ]
        for name, context, command in cases:
            with self.subTest(case=name):
                url = context.get("url", "https://example.com/")
                self.assertEqual(self.started_by(**context), command + [url])


class DesktopEntry(unittest.TestCase):
    def test_mime_types(self):
        # Every type xdg-settings registers a browser for, so it has nothing to add to the entry
        lines = read(os.path.join(ROOT, "browser-selector.desktop")).splitlines()
        self.assertIn("MimeType=x-scheme-handler/unknown;x-scheme-handler/about;text/html;"
                      "x-scheme-handler/http;x-scheme-handler/https;", lines)
        self.assertIn("Exec=@BIN@ %u", lines)
        self.assertIn("NoDisplay=true", lines)

    def test_the_settings_entry_is_no_browser(self):
        # It is shown in the app grid, and discovery of another tool must not take it for a browser
        lines = read(os.path.join(ROOT, "browser-selector-settings.desktop")).splitlines()
        self.assertIn("Exec=@BIN@ --settings", lines)
        self.assertFalse([line for line in lines if line.startswith(("MimeType", "NoDisplay"))])
        self.assertEqual({os.path.basename(name) for name in os.listdir(ROOT) if name.endswith(".desktop")},
                         bs.OWN_ENTRIES)


if __name__ == "__main__":
    unittest.main()
