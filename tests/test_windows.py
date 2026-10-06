"""What the windows are made of, without a window: `ask`, the picker flow, the test page,
the recent lines, the default browser of the system. And the module with the windows itself,
as far as it can be looked at without a display."""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from support import CONFIG, FIXTURES, ROOT, SLACK, URL, HandlerCase, bs, read, write_script

GUI = os.path.join(ROOT, "browser_selector_gui.py")
# For a python that imports the modules of the checkout: no display, no browser, no bytecode left behind.
CHILD_ENV = {"PATH": "/nonexistent", "PYTHONDONTWRITEBYTECODE": "1"}
ASK_CONFIG = """
[settings]
default = ask

[browser chrome-main]
name = Google Chrome - main
icon = google-chrome
command = google-chrome --profile-directory="Profile 6"

[browser fox]
command = firefox -P work

[rule slack]
app = slack
browser = fox

[rule netbird]
app = netbird
browser = ask
"""
NETBIRD = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/app-gnome-netbird-14016.scope\n"
BROWSERS = [("chrome-main", "Google Chrome - main", "google-chrome"), ("fox", "fox", "")]


class AskInTheConfig(unittest.TestCase):
    def test_default_and_rule_may_name_ask(self):
        config, errors = bs.parse_config(ASK_CONFIG)
        self.assertEqual(errors, [])
        self.assertEqual((config["default"], config["rules"][1]["browser"]), ("ask", "ask"))

    def test_ask_cannot_be_defined(self):
        config, errors = bs.parse_config(ASK_CONFIG + "[browser ask]\ncommand = firefox\n")
        self.assertEqual(errors, ["[browser ask]: ask is a reserved name"])

    def test_name_and_icon(self):
        config = bs.parse_config(ASK_CONFIG)[0]
        self.assertEqual(config["shown"], {"chrome-main": ("Google Chrome - main", "google-chrome"),
                                           "fox": ("fox", "")})
        self.assertEqual(config["browsers"]["fox"], ["firefox", "-P", "work"])

    def test_name_and_icon_are_optional_and_free_text(self):
        text = "[settings]\ndefault = b\n[browser b]\nname = R&D <b> 100%\nicon = /opt/b/icon.png\ncommand = b\n"
        self.assertEqual(bs.parse_config(text)[0]["shown"], {"b": ("R&D <b> 100%", "/opt/b/icon.png")})
        self.assertEqual(bs.parse_config("[settings]\ndefault = b\n[browser b]\nname =\ncommand = b\n")[0]["shown"],
                         {"b": ("b", "")})

    def test_ask_with_no_browser_at_all_is_valid(self):
        self.assertEqual(bs.parse_config("[settings]\ndefault = ask\n")[1], [])


class Picker(HandlerCase):
    def setUp(self):
        super().setUp()
        self.write_config(ASK_CONFIG)
        self.env["DISPLAY"] = ":99"

    def test_a_rule_decides_nothing_is_loaded(self):
        self.assertEqual(self.handle(URL, cgroup=SLACK)[0], 0)
        self.assertEqual(self.started, [["firefox", "-P", "work", URL]])
        self.assertEqual((self.window_loads, self.picks), (0, []))

    def test_default_ask_shows_the_picker_and_starts_what_was_picked(self):
        self.assertEqual(self.handle(URL, pick="chrome-main"), (0, "", ""))
        self.assertEqual(self.started, [["google-chrome", "--profile-directory=Profile 6", URL]])
        self.assertEqual(self.picks, [("example.com", [], BROWSERS)])
        self.assertTrue(self.log().endswith(" rule=- browser=chrome-main app=- url=https://example.com\n"), self.log())

    def test_a_rule_that_asks(self):
        self.write_config(ASK_CONFIG.replace("default = ask", "default = chrome-main"))
        self.assertEqual(self.handle(URL, cgroup=NETBIRD, pick="fox")[0], 0)
        self.assertEqual(self.started, [["firefox", "-P", "work", URL]])
        self.assertEqual(self.picks, [("example.com", ["netbird"], BROWSERS)])
        self.assertTrue(self.log().endswith(" rule=netbird browser=fox app=netbird url=https://example.com\n"))

    def test_the_picker_gets_the_host_never_the_link(self):
        self.handle("https://user:pw@login.example.com/callback?token=s3cr3t", pick="fox")
        self.assertEqual(self.picks[0][0], "login.example.com")
        for url, shown in (("about:blank", "about:blank"), ("/home/dev/page.html", "/home/dev/page.html"),
                           ("https://[broken", "https://[broken"), ("https://ex\x1bample.com/", "ex\\x1bample.com")):
            self.assertEqual(bs.link_label(url), shown)

    def test_the_picker_gets_printable_app_ids(self):
        self.env["CHROME_DESKTOP"] = "sla\x07ck\u202e.desktop"
        self.handle(URL, pick="fox")
        self.assertEqual(self.picks[0][1], ["sla\\x07ck\\u202e"])

    def test_closed_window_starts_nothing_and_exits_0(self):
        self.assertEqual(self.handle(URL, pick=None), (0, "", ""))
        self.assertEqual(self.started, [])
        self.assertEqual(len(self.picks), 1)
        self.assertTrue(self.log().endswith(" rule=- browser=ask app=- url=https://example.com closed\n"), self.log())

    def test_no_display_last_resort(self):
        del self.env["DISPLAY"]
        self.assertEqual(self.handle(URL, pick="fox")[0], 0)
        self.assertEqual(self.started, [["google-chrome", URL]])
        self.assertEqual(self.window_loads, 0)
        self.assertIn("error: picker: no display: last resort\n", self.log())
        self.assertTrue(self.log().endswith(" rule=- browser=- app=- url=https://example.com\n"), self.log())

    def test_wayland_display_is_a_display(self):
        del self.env["DISPLAY"]
        self.env["WAYLAND_DISPLAY"] = "wayland-0"
        self.handle(URL, pick="fox")
        self.assertEqual(self.started, [["firefox", "-P", "work", URL]])

    def test_window_that_cannot_be_shown_last_resort(self):
        for error, logged in ((bs.NoWindow("the display cannot be opened"), "the display cannot be opened"),
                              (ImportError("No module named 'gi'"), "ImportError"),
                              (RuntimeError(URL), "RuntimeError")):
            with self.subTest(error=error):
                self.started.clear()
                self.assertEqual(self.handle(URL, pick=error)[0], 0)
                self.assertEqual(self.started, [["google-chrome", URL]])
                self.assertIn(f"error: picker: {logged}: last resort\n", self.log())
        self.assertNotIn("/x", self.log())

    def test_a_rule_that_asks_and_no_window_is_the_last_resort_not_the_default(self):
        self.write_config(ASK_CONFIG.replace("default = ask", "default = fox"))
        self.handle(URL, cgroup=NETBIRD, pick=bs.NoWindow("no display"))
        self.assertEqual(self.started, [["google-chrome", URL]])

    def test_a_module_that_cannot_be_loaded_last_resort(self):
        def windows():
            raise bs.NoWindow("GTK 4 and libadwaita are needed")

        code = bs.main([URL], env=self.env, cgroup_text="", read_window=lambda env: None, windows=windows,
                       which=lambda program: program, execve=lambda path, args, env: self.started.append(args))
        self.assertEqual((code, self.started), (0, [["google-chrome", URL]]))
        self.assertIn("error: picker: GTK 4 and libadwaita are needed: last resort\n", self.log())

    def test_a_picker_that_returns_something_else(self):
        self.assertEqual(self.handle(URL, pick="no-such-browser")[0], 0)
        self.assertEqual(self.started, [["google-chrome", URL]])

    def test_picked_program_is_not_installed_last_resort(self):
        self.handle(URL, pick="fox", programs=("google-chrome", "chromium"))
        self.assertEqual(self.started, [["google-chrome", URL]])
        self.assertIn("error: [browser fox] command: firefox not found\n", self.log())

    def test_picked_program_is_not_installed_the_default_when_it_is_a_browser(self):
        self.write_config(ASK_CONFIG.replace("default = ask", "default = chrome-main"))
        self.handle(URL, cgroup=NETBIRD, pick="fox", programs=("google-chrome",))
        self.assertEqual(self.started, [["google-chrome", "--profile-directory=Profile 6", URL]])

    def test_nothing_to_pick_from_last_resort(self):
        self.write_config("[settings]\ndefault = ask\n")
        self.handle(URL, pick="fox")
        self.assertEqual((self.started, self.window_loads), ([["google-chrome", URL]], 0))
        self.assertIn("error: picker: no browser to pick from: last resort\n", self.log())

    def test_rule_with_a_missing_program_and_default_ask_is_the_last_resort(self):
        self.handle(URL, cgroup=SLACK, pick="chrome-main", programs=("google-chrome",))
        self.assertEqual((self.started, self.picks), ([["google-chrome", URL]], []))

    def test_explain_shows_ask_and_no_window(self):
        code, out, err = self.handle("--explain", URL, pick="fox")
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(out.endswith("rule: -\nbrowser: ask\ncommand: -\n"), out)
        code, out, err = self.handle("--explain", URL, cgroup=NETBIRD, programs=())
        self.assertEqual(code, 0)
        self.assertTrue(out.endswith("rule: netbird\nbrowser: ask\ncommand: -\n"), out)
        self.assertEqual((self.started, self.window_loads, self.log()), ([], 0, ""))

    def test_the_guard_skips_the_picker_too(self):
        self.env["BROWSER_SELECTOR_GUARD"] = str(int(bs.time.time()))
        self.handle(URL, pick="fox")
        self.assertEqual((self.started, self.window_loads), ([["google-chrome", URL]], 0))


class TryClick(unittest.TestCase):
    """The test page of the settings window."""

    def click(self, text=CONFIG, url=URL, apps=(), seen=None, probes=None, programs=("google-chrome", "firefox")):
        config = bs.parse_config(text)[0]
        return bs.try_click(config, url, list(apps), seen, {}, lambda program: program if program in programs else None,
                            run_probe=lambda command, timeout, env: (probes or {}).get(command))

    def test_no_rule_the_default(self):
        self.assertEqual(self.click(),
                         (None, "chrome-main", ["google-chrome", "--profile-directory=Profile 6", URL], []))

    def test_url_rule(self):
        url = "https://acme.cloudflareaccess.com/x"
        self.assertEqual(self.click(url=url)[:3],
                         ("cloudflare", "chrome-work", ["google-chrome", "--profile-directory=Profile 9", url]))

    def test_app_and_title_typed_in_by_hand(self):
        seen = (["Slack"], "Threads - Acme - Slack")
        self.assertEqual(self.click(apps=["slack"], seen=seen)[:2], ("slack-acme", "chrome-work"))
        self.assertEqual(self.click(apps=["slack"], seen=(["Slack"], "Other"))[:2], (None, "chrome-main"))
        self.assertEqual(self.click(apps=["slack"])[:2], (None, "chrome-main"))

    def test_probes_run(self):
        rule, browser, argv, notes = self.click(apps=["slack"], probes={"@slack-workspace": "Globex"},
                                                programs=("brave-browser",))
        self.assertEqual((rule, browser, argv), ("slack-globex", "brave-globex",
                                                 ["brave-browser", "--profile-directory=Default", URL]))

    def test_the_same_answer_as_the_handler(self):
        class Click(HandlerCase):
            def runTest(self):
                pass

        case = Click()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.write_config(CONFIG)
        for context in ({}, {"cgroup": SLACK, "window": (["slack", "Slack"], "Threads - Acme - Slack")},
                        {"cgroup": SLACK, "probes": {"@slack-workspace": "Globex"}}):
            case.started.clear()
            case.handle(URL, **context)
            apps = ["slack"] if context else []
            answer = self.click(apps=apps, seen=context.get("window"), probes=context.get("probes"),
                                programs=("google-chrome", "brave-browser", "firefox", "chromium"))
            self.assertEqual(answer[2], case.started[0])

    def test_program_not_installed(self):
        rule, browser, argv, notes = self.click(programs=("firefox",))
        self.assertEqual((rule, browser, argv), (None, None, ["firefox", URL]))
        self.assertEqual(notes, ["[browser chrome-main] command: google-chrome not found"])

    def test_nothing_to_start(self):
        self.assertEqual(self.click(programs=())[:3], (None, None, None))

    def test_ask(self):
        self.assertEqual(self.click(ASK_CONFIG)[:3], (None, "ask", None))
        self.assertEqual(self.click(ASK_CONFIG, apps=["netbird"])[:3], ("netbird", "ask", None))
        self.assertEqual(self.click(ASK_CONFIG, apps=["slack"])[:3], ("slack", "fox", ["firefox", "-P", "work", URL]))

    def test_a_probe_that_breaks_is_a_note(self):
        config = bs.parse_config(CONFIG)[0]

        def run_probe(command, timeout, env):
            raise RuntimeError("boom")

        rule, browser, argv, notes = bs.try_click(config, URL, ["slack"], None, {}, lambda program: program, run_probe)
        self.assertEqual((rule, notes), (None, ["probe @slack-workspace: RuntimeError"]))


class LogTail(HandlerCase):
    def write_log(self, text, name="log"):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        with open(os.path.join(os.path.dirname(self.log_path), name), "w", encoding="utf-8") as file:
            file.write(text)

    def test_no_log(self):
        self.assertEqual(bs.log_tail(self.env), [])

    def test_the_last_lines_oldest_first(self):
        self.write_log("".join(f"line {number}\n" for number in range(300)))
        self.assertEqual(bs.log_tail(self.env, 3), ["line 297", "line 298", "line 299"])
        self.assertEqual(len(bs.log_tail(self.env)), 200)

    def test_the_lines_before_the_log_was_renamed(self):
        self.write_log("old 1\nold 2\n", "log.1")
        self.write_log("new 1\n")
        self.assertEqual(bs.log_tail(self.env), ["old 1", "old 2", "new 1"])
        self.assertEqual(bs.log_tail(self.env, 2), ["old 2", "new 1"])

    def test_the_lines_the_handler_writes(self):
        self.write_config(CONFIG)
        self.handle(URL, cgroup=SLACK)
        self.handle("https://other.org/")
        lines = bs.log_tail(self.env)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].endswith("rule=- browser=chrome-main app=- url=https://other.org"), lines)

    def test_a_log_that_is_not_a_file_or_not_utf8(self):
        os.makedirs(self.log_path)
        self.assertEqual(bs.log_tail(self.env), [])
        os.rmdir(self.log_path)
        with open(self.log_path, "wb") as file:
            file.write(b"caf\xe9\n")
        self.assertEqual(len(bs.log_tail(self.env)), 1)


class FakeXdgSettings:
    """Stands in for subprocess.run: an xdg-settings that keeps the default browser in a variable."""

    def __init__(self, default="firefox.desktop", known=("firefox.desktop", "google-chrome.desktop",
                                                         "browser-selector.desktop")):
        self.default, self.known, self.calls = default, known, []

    def __call__(self, argv, **options):
        self.calls.append(list(argv))
        code, out = 0, ""
        if argv[:3] == ("xdg-settings", "get", "default-web-browser"):
            out = (self.default or "") + "\n"
        elif argv[:3] == ("xdg-settings", "set", "default-web-browser") and argv[3] in self.known:
            self.default = argv[3]
        else:
            code = 2
        return subprocess.CompletedProcess(argv, code, out, "")


class SystemDefault(HandlerCase):
    def previous(self):
        return read(os.path.join(self.home, ".local/state/browser-selector/previous-default"))

    def test_status(self):
        self.assertEqual(bs.system_default(self.env, FakeXdgSettings()), "firefox.desktop")
        self.assertIsNone(bs.system_default(self.env, FakeXdgSettings(default="")))

    def test_xdg_settings_is_not_there_or_hangs(self):
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("xdg-settings", 60)):
            with mock.patch.object(bs.subprocess, "run", side_effect=error) as run:
                self.assertIsNone(bs.system_default(self.env, run))
                self.assertIn("xdg-settings", bs.make_default(self.env, run))

    def test_the_real_call(self):
        seen = {}

        def run(argv, **options):
            seen.update(options, argv=argv)
            return subprocess.CompletedProcess(argv, 0, "x.desktop\n", "")

        self.assertEqual(bs.system_default(self.env, run), "x.desktop")
        self.assertEqual(seen["argv"], ("xdg-settings", "get", "default-web-browser"))
        self.assertEqual((seen["env"], seen["stdin"]), (self.env, subprocess.DEVNULL))
        self.assertTrue(seen["timeout"])

    def test_switch_writes_down_the_previous_one(self):
        run = FakeXdgSettings()
        self.assertIsNone(bs.make_default(self.env, run))
        self.assertEqual((run.default, self.previous()), ("browser-selector.desktop", "firefox.desktop\n"))
        self.assertEqual(run.calls[-1], ["xdg-settings", "set", "default-web-browser", "browser-selector.desktop"])
        self.assertEqual(bs.previous_default(self.env), "firefox.desktop")

    def test_switch_twice_keeps_the_real_previous_one(self):
        run = FakeXdgSettings()
        bs.make_default(self.env, run)
        self.assertIsNone(bs.make_default(self.env, run))
        self.assertEqual(self.previous(), "firefox.desktop\n")

    def test_switch_that_fails(self):
        run = FakeXdgSettings(known=("firefox.desktop",))
        self.assertIn("could not make browser-selector.desktop the default", bs.make_default(self.env, run))
        self.assertEqual(run.default, "firefox.desktop")
        # No previous default is written down for a switch that did not happen
        self.assertEqual(self.previous(), "")
        self.assertIsNone(bs.previous_default(self.env))

    def test_switch_that_fails_for_a_quoted_entry_says_why(self):
        run = FakeXdgSettings(known=("firefox.desktop",))
        self.assertNotIn("reserved character", bs.make_default(self.env, run))
        write_script(os.path.join(self.home, ".local/share/applications/browser-selector.desktop"),
                     '[Desktop Entry]\nExec="/home/a b/.local/bin/browser-selector" %u\n')
        self.assertIn("a home directory with a reserved character in its path cannot be registered",
                      bs.make_default(self.env, run))

    def test_a_relative_xdg_directory_is_no_directory(self):
        env = {"HOME": "/h", "XDG_CONFIG_HOME": "relative", "XDG_STATE_HOME": "./state", "XDG_DATA_HOME": "data",
               "XDG_DATA_DIRS": "share:/usr/share:../x"}
        self.assertEqual(bs.config_path(env, None), "/h/.config/browser-selector/config.ini")
        self.assertEqual(bs.previous_default_file(env), "/h/.local/state/browser-selector/previous-default")
        self.assertEqual(bs.application_dirs(env)[:2], ["/h/.local/share/applications", "/usr/share/applications"])
        self.assertNotIn("share/applications", bs.application_dirs(env))

    def test_the_way_back(self):
        run = FakeXdgSettings()
        bs.make_default(self.env, run)
        self.assertIsNone(bs.restore_default(self.env, run))
        self.assertEqual(run.default, "firefox.desktop")

    def test_no_way_back_without_a_previous_one(self):
        run = FakeXdgSettings(default="browser-selector.desktop")
        self.assertEqual(bs.restore_default(self.env, run), "the previous default browser is not known")
        self.assertEqual([call[1] for call in run.calls], [])

    def test_a_previous_one_that_is_gone(self):
        run = FakeXdgSettings()
        bs.make_default(self.env, run)
        run.known = ("browser-selector.desktop",)
        self.assertIn("could not make firefox.desktop the default", bs.restore_default(self.env, run))
        self.assertEqual(run.default, "browser-selector.desktop")

    def test_a_previous_default_file_nobody_should_trust(self):
        path = os.path.join(self.home, ".local/state/browser-selector/previous-default")
        for text in ("", "--help\n", "x.desktop --unset\n", "browser-selector.desktop\n", "no-suffix\n",
                     "a\nb.desktop\n"):
            with self.subTest(text=text):
                write_script(path, text)
                self.assertIsNone(bs.previous_default(self.env))
        os.remove(path)
        os.mkfifo(path)
        self.assertIsNone(bs.previous_default(self.env))


class FirstConfig(HandlerCase):
    """--init-config: what install.sh starts a new config with."""

    def setUp(self):
        super().setUp()
        root = os.path.join(FIXTURES, "discovery", "desktop")
        self.env = {"HOME": os.path.join(root, "home"), "XDG_DATA_DIRS": os.path.join(root, "share"),
                    "XDG_STATE_HOME": os.path.join(self.tmp, "state"),
                    "BROWSER_SELECTOR_CONFIG": os.path.join(self.tmp, "config", "config.ini")}
        for name in ("SNAP_APPLICATIONS", "FLATPAK_APPLICATIONS"):
            patch = mock.patch.object(bs, name, "/nonexistent")
            patch.start()
            self.addCleanup(patch.stop)

    def which(self, program):
        return program if os.path.isabs(program) else "/usr/bin/" + program

    def default(self, entry, previous=None):
        if previous:
            write_script(os.path.join(self.env["XDG_STATE_HOME"], "browser-selector", "previous-default"), previous)
        return bs.first_config(self.env, self.which, FakeXdgSettings(default=entry))["settings"]["default"]

    def test_every_browser_found_and_no_rules(self):
        model = bs.first_config(self.env, self.which, FakeXdgSettings())
        self.assertEqual(list(model["browsers"]), ["brave-home", "chromium-work", "chrome-acme", "chrome-main",
                                                   "chrome-side", "firefox-default", "firefox-default-release"])
        self.assertEqual((model["rules"], model["unknown"]), ({}, {}))
        self.assertEqual(bs.check_model(model, self.which), [])

    def test_the_default_is_the_browser_that_was_the_system_default(self):
        self.assertEqual(self.default("firefox.desktop"), "firefox-default-release")
        self.assertEqual(self.default("brave-browser.desktop"), "brave-home")
        self.assertEqual(self.default("chromium-browser.desktop"), "chromium-work")

    def test_of_its_profiles_the_one_it_opens_by_itself(self):
        self.assertEqual(self.default("google-chrome.desktop"), "chrome-acme")
        self.assertEqual(self.default("com.google.Chrome.desktop"), "chrome-acme")

    def test_a_system_default_that_was_not_found_the_first_browser(self):
        self.assertEqual(self.default("epiphany.desktop"), "brave-home")
        self.assertEqual(self.default(""), "brave-home")

    def test_the_handler_is_the_default_already_the_previous_one(self):
        self.assertEqual(self.default("browser-selector.desktop", "firefox.desktop\n"), "firefox-default-release")
        self.assertEqual(self.default("browser-selector.desktop"), "firefox-default-release")

    def init(self):
        with mock.patch.object(bs, "system_default", return_value="google-chrome.desktop"):
            return self.handle("--init-config", which=self.which)

    def test_init_config_writes_the_file(self):
        code, out, err = self.init()
        self.assertEqual((code, err), (0, ""))
        self.assertIn("browsers found: 7, default = chrome-acme", out)
        text = read(self.env["BROWSER_SELECTOR_CONFIG"])
        self.assertTrue(text.startswith("[settings]\ndefault = chrome-acme\n\n[browser brave-home]\n"), text)
        self.assertNotIn("[rule", text)
        self.assertEqual(self.handle("--check", which=self.which)[0], 0)
        self.assertEqual(self.started, [])

    def test_init_config_never_touches_a_config_that_is_there(self):
        for text in ("[settings]\ndefault = mine\n[browser mine]\ncommand = firefox\n", "not a config", ""):
            write_script(self.env["BROWSER_SELECTOR_CONFIG"], text)
            code, out, err = self.init()
            self.assertEqual((code, read(self.env["BROWSER_SELECTOR_CONFIG"])), (0, text))
            self.assertIn("kept", out)

    def test_init_config_leaves_a_dangling_link_alone(self):
        os.makedirs(os.path.dirname(self.env["BROWSER_SELECTOR_CONFIG"]))
        os.symlink(os.path.join(self.tmp, "gone"), self.env["BROWSER_SELECTOR_CONFIG"])
        self.assertEqual(self.init()[0], 0)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "gone")))

    def test_init_config_with_no_browser_writes_nothing(self):
        self.env["XDG_DATA_DIRS"] = os.path.join(self.tmp, "nothing")
        self.env["HOME"] = self.home
        code, out, err = self.init()
        self.assertEqual(code, 1)
        self.assertIn("no browser found", err)
        self.assertFalse(os.path.exists(self.env["BROWSER_SELECTOR_CONFIG"]))


class SettingsOption(HandlerCase):
    def test_settings_runs_the_window_with_the_config_path(self):
        seen = []

        class Windows:
            @staticmethod
            def settings(path, env):
                seen.append(path)
                return 0

        self.env["DISPLAY"] = ":99"
        code = bs.main(["--config", "/tmp/x.ini", "--settings"], env=self.env, windows=lambda: Windows)
        self.assertEqual((code, seen), (0, ["/tmp/x.ini"]))

    def test_no_display(self):
        code, out, err = self.handle("--settings")
        self.assertEqual((code, self.window_loads), (1, 0))
        self.assertIn("the settings window cannot be shown: no display", err)

    def test_a_start_without_a_url_is_the_settings_window(self):
        # The icon in the app grid: Exec has %u and there is no URL to put there
        for argv in ([], ["--config", "/tmp/x.ini"]):
            with self.subTest(argv=argv):
                code, out, err = self.handle(*argv)
                self.assertEqual((code, self.started), (1, []))
                self.assertIn("the settings window cannot be shown: no display", err)

    def test_gi_is_not_installed(self):
        self.env["DISPLAY"] = ":99"
        code, out, err = self.handle("--settings", settings=ImportError("No module named 'gi'"))
        self.assertEqual(code, 1)
        self.assertIn("the settings window cannot be shown: No module named 'gi'", err)

    def test_no_gtk(self):
        self.env["DISPLAY"] = ":99"
        code, out, err = self.handle("--settings", settings=bs.NoWindow("GTK 4 and libadwaita are needed"))
        self.assertEqual(code, 1)
        self.assertIn("GTK 4 and libadwaita are needed", err)

    def test_settings_takes_no_url(self):
        self.assertEqual(self.handle("--settings", URL)[0], 1)
        self.assertEqual(self.handle("--discover", URL)[0], 1)
        self.assertEqual(self.handle("--init-config", URL)[0], 1)


class NoGtkForAClickARuleDecides(unittest.TestCase):
    """The real loader, in a process of its own: what is imported after a click."""

    SCRIPT = """
import json, sys
sys.path.insert(0, {root!r})
import browser_selector as bs
started = []
code = bs.main([{url!r}], env={env!r}, cgroup_text={cgroup!r}, read_window=lambda env: None,
               which=lambda program: program, execve=lambda path, args, env: started.append(args))
print(json.dumps([code, started, sorted(name for name in sys.modules if name.split(".")[0] in
                                        ("gi", "browser_selector_gui"))]))
"""

    def click(self, config, **env):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.ini")
            with open(path, "w", encoding="utf-8") as file:
                file.write(config)
            env = dict({"HOME": tmp, "BROWSER_SELECTOR_CONFIG": path}, **env)
            script = self.SCRIPT.format(root=ROOT, url=URL, env=env, cgroup=SLACK)
            # No display in the environment of the child: nothing here may open a window
            done = subprocess.run([sys.executable, "-c", script], env=dict(CHILD_ENV, PATH=os.path.join(tmp, "empty")),
                                  timeout=60, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.log = read(os.path.join(tmp, ".local", "state", "browser-selector", "log"))
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_rule_hit(self):
        self.assertEqual(self.click(ASK_CONFIG), [0, [["firefox", "-P", "work", URL]], []])

    def test_default_browser(self):
        self.assertEqual(self.click(CONFIG.replace("app = slack", "app = other")),
                         [0, [["google-chrome", "--profile-directory=Profile 6", URL]], []])

    def test_ask_without_a_display_does_not_load_it_either(self):
        self.assertEqual(self.click(ASK_CONFIG.replace("app = slack", "app = other")),
                         [0, [["google-chrome", URL]], []])

    def test_ask_with_a_display_loads_it_in_a_child(self):
        # The other side of the tests above. A display nobody answers on: no window, the last resort
        self.assertEqual(self.click(ASK_CONFIG.replace("app = slack", "app = other"), DISPLAY="/nonexistent/x:0"),
                         [0, [["google-chrome", URL]], []])
        if "GTK 4 and libadwaita are needed" in self.log:
            self.skipTest("no GTK 4 and libadwaita for python here")
        self.assertIn("error: picker: the display cannot be opened: last resort\n", self.log)

    def test_the_module_is_not_imported_at_the_top(self):
        source = read(os.path.join(ROOT, "browser_selector.py"))
        self.assertEqual(re.findall(r"^(?:import|from) .*(?:gi|gui)\b.*$", source, re.MULTILINE), [])
        self.assertEqual(len(re.findall(r"import browser_selector_gui", source)), 1)


class InChild(unittest.TestCase):
    """The picker runs in a child process: whatever happens to it, the handler goes on."""

    def test_what_the_function_returns(self):
        self.assertEqual(bs.in_child(lambda: "chrome-main"), "chrome-main")
        self.assertIsNone(bs.in_child(lambda: None))
        self.assertEqual(bs.in_child(lambda: "Работа \u2713"), "Работа \u2713")

    def test_it_is_another_process(self):
        self.assertNotEqual(bs.in_child(lambda: str(os.getpid())), str(os.getpid()))

    def test_no_window(self):
        def function():
            raise bs.NoWindow("the display cannot be opened")

        with self.assertRaisesRegex(bs.NoWindow, "^the display cannot be opened$"):
            bs.in_child(function)

    def test_any_other_exception_is_named_and_nothing_more(self):
        def function():
            raise RuntimeError("https://example.com/secret")

        with self.assertRaisesRegex(bs.NoWindow, "^RuntimeError$"):
            bs.in_child(function)

    def test_a_child_that_dies(self):
        import signal
        for function in (lambda: os._exit(3), os.abort, lambda: os.kill(os.getpid(), signal.SIGKILL),
                         lambda: sys.exit(0)):
            with self.subTest(function=function), self.assertRaisesRegex(bs.NoWindow, "ended with wait status"):
                bs.in_child(function)

    def test_no_child_is_left_behind(self):
        bs.in_child(lambda: "x")
        with self.assertRaises(ChildProcessError):
            os.waitpid(-1, os.WNOHANG)

    def test_closed_standard_streams(self):
        # A handler started with stdout and stderr closed: what the window says on fd 2 is not the answer
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        answer = os.path.join(directory.name, "answer")
        script = ("import os, sys\nsys.path.insert(0, %r)\nimport browser_selector as bs\n"
                  "def pick():\n    os.write(2, b'Gtk-WARNING: something\\n')\n    return 'fox'\n"
                  "try:\n    result = repr(bs.in_child(pick))\n"
                  "except bs.NoWindow as error:\n    result = 'NoWindow: %%s' %% error\n"
                  "open(%r, 'w').write(result)\n" % (ROOT, answer))
        subprocess.run(["/bin/sh", "-c", 'exec "$0" -c "$1" >&- 2>&-', sys.executable, script], env=CHILD_ENV,
                       timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(read(answer), "'fox'")

    def test_the_handler_opens_the_last_resort_when_the_picker_dies(self):
        class Click(HandlerCase):
            def runTest(self):
                pass

        case = Click()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.write_config(ASK_CONFIG)
        started = []
        with mock.patch.object(bs, "load_windows", side_effect=os.abort):
            code = bs.main([URL], env=dict(case.env, DISPLAY=":99"), cgroup_text="", read_window=lambda env: None,
                           which=lambda program: program, execve=lambda path, args, env: started.append(args))
        self.assertEqual((code, started), (0, [["google-chrome", URL]]))
        self.assertRegex(case.log(), "error: picker: the window ended with wait status \\d+: last resort\n")

    def test_the_real_loader_is_called_in_the_child_only(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        note = os.path.join(directory.name, "pid")

        def pick(link, apps, browsers):
            write_script(note, f"{os.getpid()} {link} {browsers[0][0]}")
            return "fox"

        fake = type(sys)("browser_selector_gui")
        fake.pick = pick
        with mock.patch.object(bs, "load_windows", return_value=fake) as load:
            self.assertEqual(bs.ask({"DISPLAY": ":99"}, URL, [], bs.parse_config(ASK_CONFIG)[0]), "fox")
            self.assertEqual(load.call_count, 0)
        pid, link, first = read(note).split()
        self.assertEqual((link, first), ("example.com", "chrome-main"))
        self.assertNotEqual(int(pid), os.getpid())


class LoadWindows(unittest.TestCase):
    def test_the_directory_of_the_handler_and_the_running_module(self):
        fake = type(sys)("browser_selector_gui")
        with mock.patch.dict(sys.modules, {"browser_selector_gui": fake}), mock.patch.object(sys, "path", ["/x"]):
            self.assertIs(bs.load_windows(), fake)
            self.assertEqual(sys.path, [os.path.dirname(bs.HANDLER), "/x"])
            self.assertIs(sys.modules["browser_selector"], bs)
            bs.load_windows()
            self.assertEqual(sys.path, [os.path.dirname(bs.HANDLER), "/x"])


class WindowsModule(unittest.TestCase):
    """browser_selector_gui.py without a display: its source, and the libraries of this machine."""

    FORBIDDEN = ("EntryRow", "SwitchRow", "ToolbarView", "Adw.Dialog", "AlertDialog", "NavigationView",
                 "FileDialog", "MessageDialog", "PasswordEntryRow", "SpinRow", "AboutWindow", "AboutDialog",
                 "Adw.Banner", "ColorDialog", "FontDialog", "add_titled_with_icon", "CssProvider")
    # Deprecated since, and warned about by the GTK and libadwaita of Ubuntu 26.04.
    DEPRECATED = ("Gtk.Dialog", "Gtk.ComboBox", "Gtk.TreeView", "Gtk.InfoBar", "Gtk.Statusbar", "Gtk.FileChooser",
                  "Adw.Leaflet", "Adw.Flap", "Adw.Squeezer", "Adw.ViewSwitcherTitle", "Adw.PreferencesWindow",
                  "get_style_context", ".show()", ".hide()", "Gtk.StyleContext")

    def setUp(self):
        self.source = read(GUI)

    def test_it_compiles(self):
        compile(self.source, GUI, "exec")

    def test_nothing_newer_than_gtk_4_6_and_libadwaita_1_1(self):
        for name in self.FORBIDDEN:
            self.assertNotIn(name, self.source)

    def test_nothing_deprecated_later(self):
        for name in self.DEPRECATED:
            self.assertNotIn(name, self.source)

    def test_the_logic_is_not_in_the_window(self):
        for word in ("configparser", "subprocess", "open(", "os.replace", "re.compile", "json"):
            self.assertNotIn(word, self.source)

    def test_every_name_exists_in_the_libraries_of_this_machine(self):
        # Meaningful where this machine has the oldest versions the contract names: Ubuntu 22.04
        names = sorted(set(re.findall(r"\b(Gtk|Adw|Gdk|Gio|GLib)\.([A-Za-z_]+(?:\.[A-Za-z_]+)?)", self.source)))
        script = ("import sys, gi\n"
                  "gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1')\n"
                  "from gi.repository import Adw, Gdk, Gio, GLib, Gtk\n"
                  "print(Gtk.get_minor_version(), Adw.MINOR_VERSION)\n"
                  "for module, name in %r:\n"
                  "    value = locals()[module]\n"
                  "    for part in name.split('.'):\n"
                  "        value = getattr(value, part, None)\n"
                  "        if value is None:\n"
                  "            print('missing', module + '.' + name)\n"
                  "            break\n" % (names,))
        # Without a display: the libraries are loaded, no window can be shown
        done = subprocess.run([sys.executable, "-c", script], env=CHILD_ENV, timeout=60,
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if done.returncode != 0:
            self.skipTest("no GTK 4 and libadwaita for python here: " + done.stderr.decode().strip()[-200:])
        lines = done.stdout.decode().splitlines()
        self.assertGreater(len(names), 40)
        self.assertEqual(lines[1:], [], "GTK 4.%s, libadwaita 1.%s" % tuple(lines[0].split()))

    def test_without_a_display_it_says_so_and_does_not_exit(self):
        script = ("import sys\nsys.path.insert(0, %r)\nimport browser_selector as bs\n"
                  "try:\n    import browser_selector_gui as gui\nexcept bs.NoWindow as error:\n"
                  "    print('skip', error)\n    sys.exit(0)\n"
                  "for function in (lambda: gui.pick('example.com', [], [('a', 'A', '')]),\n"
                  "                 lambda: gui.settings('/nonexistent/config.ini', {})):\n"
                  "    try:\n        function()\n        print('shown')\n"
                  "    except bs.NoWindow as error:\n        print('NoWindow:', error)\n" % ROOT)
        done = subprocess.run([sys.executable, "-c", script], env=CHILD_ENV, timeout=60,
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = done.stdout.decode()
        if out.startswith("skip"):
            self.skipTest(out.strip())
        self.assertEqual((done.returncode, out), (0, "NoWindow: the display cannot be opened\n" * 2), done.stderr)


if __name__ == "__main__":
    unittest.main()
