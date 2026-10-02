"""The handler as a whole: arguments, commands, fallbacks, --explain, the log."""

import os
import re
import time
import unittest
from unittest import mock

from support import CONFIG, NETBIRD, SLACK, URL, CGROUP, HandlerCase, bs, read, watchdog, write_script

SLACK_WINDOW = (["slack", "Slack"], "Threads - Acme - Slack")
CHROME_MAIN = ["google-chrome", "--profile-directory=Profile 6"]
CHROME_WORK = ["google-chrome", "--profile-directory=Profile 9"]

EXPLAIN_CONFIG = r"""
[settings]
default = chrome-work

[browser chrome-main]
command = google-chrome --profile-directory="Profile 6"

[browser chrome-work]
command = google-chrome --profile-directory="Profile 9"

[rule slack-globex]
app = slack
probe = @slack-workspace
probe_match = ^Globex$
browser = chrome-work

[rule slack-acme]
app = slack
title = - Acme - Slack$
browser = chrome-main

[rule netbird-globex]
app = netbird
probe = netbird profile list
probe_match = ^globex\s+✓
browser = chrome-work
"""


class BuildCommand(unittest.TestCase):
    def test_url_is_appended(self):
        self.assertEqual(bs.build_command(["firefox", "-P", "work"], URL), ["firefox", "-P", "work", URL])

    def test_url_inside_an_argument(self):
        self.assertEqual(bs.build_command(["chromium", "--app={url}", "--new-window"], URL),
                         ["chromium", f"--app={URL}", "--new-window"])

    def test_url_as_an_argument_of_its_own(self):
        self.assertEqual(bs.build_command(["brave-browser", "{url}", "--incognito"], URL),
                         ["brave-browser", URL, "--incognito"])

    def test_url_twice_in_one_argument(self):
        self.assertEqual(bs.build_command(["chromium", "--app={url}#{url}", "{url}"], URL),
                         ["chromium", f"--app={URL}#{URL}", URL])

    def test_the_url_is_never_split_or_expanded(self):
        url = "https://example.com/a b?q=$(reboot)&x='y'\"z\"#{url};ls"
        self.assertEqual(bs.build_command(["firefox"], url), ["firefox", url])
        self.assertEqual(bs.build_command(["firefox", "--new-tab={url}"], url), ["firefox", "--new-tab=" + url])

    def test_the_config_value_is_not_changed(self):
        argv = ["firefox"]
        bs.build_command(argv, URL)
        self.assertEqual(argv, ["firefox"])


class Commands(HandlerCase):
    def test_quoted_profile_name_with_a_space(self):
        self.write_config(CONFIG)
        self.handle(URL)
        self.assertEqual(self.started, [CHROME_MAIN + [URL]])

    def test_quoting_styles(self):
        for command in ('google-chrome --profile-directory="Profile 6"', "google-chrome '--profile-directory=Profile 6'",
                        r"google-chrome --profile-directory=Profile\ 6"):
            with self.subTest(command=command):
                self.write_config(f"[settings]\ndefault = main\n[browser main]\ncommand = {command}\n")
                self.started.clear()
                self.handle(URL)
                self.assertEqual(self.started, [CHROME_MAIN + [URL]])

    def test_url_placeholder_from_the_config(self):
        self.write_config(CONFIG)
        self.handle(URL, cgroup=SLACK, probes={"@slack-workspace": "Globex"})
        self.assertEqual(self.started, [["brave-browser", "--profile-directory=Default", URL]])

    def test_exit_code_0(self):
        self.write_config(CONFIG)
        self.assertEqual(self.handle(URL), (0, "", ""))


class Arguments(HandlerCase):
    def setUp(self):
        super().setUp()
        self.write_config(CONFIG)

    def test_unknown_dash_argument_is_refused(self):
        for argv in (["--incognito"], ["-x", URL], [URL, "--remote-debugging-port=9222"], ["-"], ["--", URL],
                     ["--config=/tmp/x", URL], ["--help"], ["--explain", "--load-extension=/tmp/x"]):
            with self.subTest(argv=argv):
                code, out, err = self.handle(*argv)
                self.assertEqual((code, out, self.started), (1, "", []))
                self.assertIn("usage:", err)

    def test_leading_whitespace_does_not_hide_a_dash(self):
        # Chromium trims an argument before it looks for a switch in it
        for arg in (" --incognito", "\t--incognito", "\n-P", " \t\r\n --no-sandbox", "\xa0--incognito",
                    "\u3000--incognito", "\x00--incognito", "\x1f-x", "\x7f--incognito"):
            with self.subTest(arg=arg):
                code, out, err = self.handle(arg)
                self.assertEqual((code, out, self.started), (1, "", []))
                code, out, err = self.handle(URL, arg)
                self.assertEqual((code, out, self.started), (1, "", []))

    def test_empty_argument_is_refused(self):
        for arg in ("", " ", "\t\n"):
            with self.subTest(arg=arg):
                code, out, err = self.handle(arg)
                self.assertEqual((code, self.started, self.log()), (1, [], ""))
                self.assertIn("usage:", err)

    def test_a_dash_inside_a_url_is_fine(self):
        for url in ("https://example.com/ --incognito", "https://a-b.example.com/-x", "about:blank",
                    "/home/dev/my page.html", "notes -draft-.html", "file:///tmp/-x.html", "mailto:a@example.com"):
            with self.subTest(url=url):
                self.started.clear()
                self.assertEqual(self.handle(url)[0], 0)
                self.assertEqual(self.started, [CHROME_MAIN + [url]])

    def test_one_url_is_expected(self):
        for argv in ([], [URL, "https://other.org/"], ["--config"], ["--check", URL], ["--version", URL],
                     ["--explain", URL, URL]):
            with self.subTest(argv=argv):
                code, out, err = self.handle(*argv)
                self.assertEqual((code, self.started), (1, []))
                self.assertIn("usage:", err)

    def test_version(self):
        code, out, err = self.handle("--version")
        self.assertEqual((code, self.started), (0, []))
        self.assertRegex(out, r"^browser-selector \d+\.\d+\.\d+\n$")

    def test_config_option_position_does_not_matter(self):
        other = self.write_config(CONFIG.replace("default = chrome-main", "default = chrome-work"), "other.ini")
        self.handle(URL, "--config", other)
        self.handle("--config", other, URL)
        self.assertEqual(self.started, [CHROME_WORK + [URL]] * 2)


class AlwaysOpensSomething(HandlerCase):
    """The rows of "A click always opens something"."""

    def test_no_config_file_last_resort(self):
        self.assertEqual(self.handle(URL)[0], 0)
        self.assertEqual(self.started, [["google-chrome", URL]])

    def test_last_resort_is_the_first_one_found(self):
        self.handle(URL, programs=("chromium", "firefox"))
        self.handle(URL, programs=("chromium",))
        self.handle(URL, programs=("brave-browser", "firefox", "chromium"))
        self.assertEqual(self.started, [["firefox", URL], ["chromium", URL], ["brave-browser", URL]])

    def test_config_not_valid_error_to_the_log_then_last_resort(self):
        self.write_config(CONFIG + "[rule broken]\ntitle = (\nbrowser = chrome-main\n")
        self.assertEqual(self.handle(URL, programs=("firefox",))[0], 0)
        self.assertEqual(self.started, [["firefox", URL]])
        self.assertIn("error: [rule broken] title: bad regex", self.log())

    def test_window_fails_next_rule_is_tried(self):
        self.write_config(CONFIG)
        self.handle(URL, cgroup=SLACK, window=None, probes={"@slack-workspace": "Globex"})
        self.assertEqual(self.started, [["brave-browser", "--profile-directory=Default", URL]])

    def test_probe_fails_next_rule_is_tried(self):
        self.write_config(CONFIG + "[rule netbird-any]\napp = netbird\nbrowser = chrome-work\n")
        self.handle(URL, cgroup=NETBIRD, probes={})
        self.assertEqual(self.started, [CHROME_WORK + [URL]])

    def test_window_and_probe_fail_no_rule_left_default(self):
        self.write_config(CONFIG)
        self.handle(URL, cgroup=SLACK, window=None, probes={})
        self.assertEqual(self.started, [CHROME_MAIN + [URL]])

    def test_a_reader_that_breaks_still_opens_the_default(self):
        self.write_config(CONFIG)
        self.assertEqual(self.handle(URL, cgroup=SLACK, window=RuntimeError("boom"))[0], 0)
        self.assertEqual(self.started, [CHROME_MAIN + [URL]])
        self.assertIn("error: window: RuntimeError", self.log())

    def test_any_exception_before_the_exec_ends_in_the_last_resort(self):
        self.write_config(CONFIG)
        for name in ("cgroup_unit", "app_ids", "load_config", "rule_matches", "build_command", "guard_is_fresh"):
            with self.subTest(broken=name), mock.patch.object(bs, name, side_effect=RuntimeError(URL)):
                self.started.clear()
                self.assertEqual(self.handle(URL, cgroup=SLACK, window=(["slack", "Slack"], "x"))[0], 0)
                self.assertEqual(self.started, [["google-chrome", URL]])
        self.assertEqual(self.log().count("error: RuntimeError before the browser was chosen: last resort\n"), 6)
        self.assertNotIn("/x", self.log())

    def test_regex_that_breaks_the_compiler_last_resort(self):
        self.write_config(CONFIG + "[rule big]\nurl = x{99999999999}\nbrowser = chrome-main\n")
        self.assertEqual(self.handle(URL)[0], 0)
        self.assertEqual(self.started, [["google-chrome", URL]])
        self.assertIn("error: [rule big] url: bad regex", self.log())

    def test_exec_refuses_an_argument_next_one_is_tried(self):
        # What os.execve says to a NUL byte in an argument
        self.write_config(CONFIG)
        code, out, err = self.handle(URL, programs=("google-chrome", "firefox"), broken=("google-chrome",),
                                     exec_error=ValueError("embedded null byte"))
        self.assertEqual((code, self.started), (0, [["firefox", URL]]))
        self.assertIn("error: google-chrome: embedded null byte\n", self.log())

    def test_real_exec_with_a_nul_byte_raises_what_is_caught(self):
        with self.assertRaises((OSError, ValueError)):
            os.execve("/nonexistent/browser", ["browser", "a\0b"], {})

    def test_program_not_found_default_browser(self):
        self.write_config(CONFIG)
        self.handle(URL, cgroup=SLACK, probes={"@slack-workspace": "Globex"}, programs=("google-chrome", "firefox"))
        self.assertEqual(self.started, [CHROME_MAIN + [URL]])
        self.assertIn("error: [browser brave-globex] command: brave-browser not found", self.log())

    def test_program_and_default_not_found_last_resort(self):
        self.write_config(CONFIG)
        self.handle(URL, cgroup=SLACK, probes={"@slack-workspace": "Globex"}, programs=("firefox", "chromium"))
        self.assertEqual(self.started, [["firefox", URL]])

    def test_default_not_found_last_resort(self):
        self.write_config(CONFIG)
        self.handle(URL, programs=("brave-browser",))
        self.assertEqual(self.started, [["brave-browser", URL]])

    def test_exec_fails_next_one_is_tried(self):
        self.write_config(CONFIG)
        self.assertEqual(self.handle(URL, broken=("google-chrome",))[0], 0)
        self.assertEqual(self.started, [["brave-browser", URL]])
        self.assertIn("error: google-chrome: Permission denied", self.log())

    def test_nothing_to_start_exits_1(self):
        self.write_config(CONFIG)
        code, out, err = self.handle(URL, programs=())
        self.assertEqual((code, self.started), (1, []))
        self.assertIn("no browser to start", err)
        code, out, err = self.handle(URL, broken=bs.LAST_RESORT)
        self.assertEqual((code, self.started), (1, []))

    def test_unwritable_log_does_not_stop_the_click(self):
        self.write_config(CONFIG)
        # The state directory cannot be made: its parent is a file
        self.env["XDG_STATE_HOME"] = self.write_config("", "not-a-directory")
        self.assertEqual(self.handle(URL)[0], 0)
        self.assertEqual(self.started, [CHROME_MAIN + [URL]])
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local")))

    def test_a_log_writer_that_breaks_does_not_stop_the_click(self):
        self.write_config(CONFIG)
        with mock.patch.object(bs.time, "strftime", side_effect=RuntimeError("boom")):
            self.assertEqual(self.handle(URL)[0], 0)
        self.assertEqual(self.started, [CHROME_MAIN + [URL]])

    def click_from_the_real_cgroup(self):
        bs.main([URL], env=self.env, read_window=lambda env: SLACK_WINDOW, which=lambda program: program,
                execve=lambda path, args, env: self.started.append(args))

    def test_cgroup_file_from_the_environment(self):
        self.write_config(CONFIG)
        self.env["BROWSER_SELECTOR_CGROUP_FILE"] = self.write_config(SLACK, "cgroup")
        self.click_from_the_real_cgroup()
        self.assertEqual(self.started, [CHROME_WORK + [URL]])

    def test_cgroup_file_is_proc_self_cgroup(self):
        self.write_config(CONFIG)
        asked = []

        def read_file(path, *args, **kwargs):
            asked.append(path)
            return SLACK if path == "/proc/self/cgroup" else real_read_file(path, *args, **kwargs)

        real_read_file = bs.read_file
        with mock.patch.object(bs, "read_file", read_file):
            self.click_from_the_real_cgroup()
        self.assertIn("/proc/self/cgroup", asked)
        self.assertEqual(self.started, [CHROME_WORK + [URL]])

    def test_the_real_proc_self_cgroup_can_be_read(self):
        with open("/proc/self/cgroup", encoding="utf-8") as file:
            self.assertEqual(bs.read_file("/proc/self/cgroup"), file.read())

    def test_cgroup_file_that_cannot_be_read(self):
        self.write_config(CONFIG)
        watchdog(self)
        fifo = os.path.join(self.tmp, "fifo")
        os.mkfifo(fifo)
        for path in (fifo, self.home, os.path.join(self.tmp, "nothing")):
            with self.subTest(path=path):
                self.started.clear()
                self.env["BROWSER_SELECTOR_CGROUP_FILE"] = path
                self.click_from_the_real_cgroup()
                self.assertEqual(self.started, [CHROME_MAIN + [URL]])


class NotOnlyHttp(HandlerCase):
    """As the default browser the handler also gets local files, about: and unknown schemes."""

    def test_passed_on_unchanged(self):
        self.write_config(CONFIG)
        for url in ("/tmp/stand/page.html", "page.html", "about:blank", "file:///tmp/page.html", "foo:bar"):
            with self.subTest(url=url):
                self.started.clear()
                self.assertEqual(self.handle(url, cgroup=SLACK, window=SLACK_WINDOW)[0], 0)
                self.assertEqual(self.started, [CHROME_WORK + [url]])
        self.assertEqual(self.log().count(" rule=slack-acme browser=chrome-work app=slack url=-\n"), 5)


class LoopGuard(HandlerCase):
    """BROWSER_SELECTOR_GUARD: a browser command that leads back to the handler."""

    def setUp(self):
        super().setUp()
        self.write_config(CONFIG)

    def test_the_browser_gets_the_time_of_the_exec(self):
        before = int(time.time())
        self.handle(URL)
        guard = int(self.exec_envs[0]["BROWSER_SELECTOR_GUARD"])
        self.assertTrue(before <= guard <= time.time(), guard)
        self.assertEqual(self.exec_envs[0]["HOME"], self.home)
        self.assertNotIn("BROWSER_SELECTOR_GUARD", self.env)

    def test_started_again_right_away_skips_the_rules(self):
        for age in (0, 1, 4):
            with self.subTest(age=age):
                self.started.clear()
                self.env["BROWSER_SELECTOR_GUARD"] = str(int(time.time()) - age)
                self.assertEqual(self.handle(URL, cgroup=SLACK, window=SLACK_WINDOW)[0], 0)
                self.assertEqual(self.started, [["google-chrome", URL]])
                self.assertEqual(self.window_reads, 0)
        self.assertIn("a command leads back to the handler", self.log())
        self.assertIn(" rule=- browser=- app=slack url=https://example.com\n", self.log())

    def test_an_older_value_is_ignored(self):
        # The browser keeps the variable: apps it starts later are routed as usual
        for value in (str(int(time.time()) - 6), str(time.time() - 3600), "0", str(time.time() + 3600)):
            with self.subTest(value=value):
                self.started.clear()
                self.env["BROWSER_SELECTOR_GUARD"] = value
                self.handle(URL, cgroup=SLACK, window=SLACK_WINDOW)
                self.assertEqual(self.started, [CHROME_WORK + [URL]])
                self.assertGreater(int(self.exec_envs[-1]["BROWSER_SELECTOR_GUARD"]), time.time() - 5)

    def test_a_value_that_is_not_a_time_is_ignored(self):
        for value in ("", "soon", "nan", "inf", "-inf", "1e999"):
            with self.subTest(value=value):
                self.started.clear()
                self.env["BROWSER_SELECTOR_GUARD"] = value
                self.handle(URL, cgroup=SLACK, window=SLACK_WINDOW)
                self.assertEqual(self.started, [CHROME_WORK + [URL]])

    def test_explain_says_so(self):
        self.env["BROWSER_SELECTOR_GUARD"] = str(int(time.time()))
        code, out, err = self.handle("--explain", URL, cgroup=SLACK, window=SLACK_WINDOW)
        self.assertTrue(out.endswith("rule: -\nbrowser: -\ncommand: google-chrome https://example.com/x\n"), out)
        self.assertIn("a command leads back to the handler", err)


class HandlerAsBrowser(HandlerCase):
    """A program that resolves to the handler itself is never started."""

    def setUp(self):
        super().setUp()
        self.link = os.path.join(self.tmp, "bin", "google-chrome")
        os.mkdir(os.path.dirname(self.link))
        os.symlink(bs.HANDLER, self.link)

    def which(self, program):
        return {"google-chrome": self.link, "firefox": "/stub/firefox"}.get(program)

    def test_the_last_resort(self):
        code, out, err = self.handle(URL, which=self.which)
        self.assertEqual((code, self.started), (0, [["firefox", URL]]))
        self.assertIn("error: google-chrome is the handler itself, not started\n", self.log())

    def test_a_browser_of_a_config_that_was_valid_once(self):
        self.write_config(CONFIG)
        with mock.patch.object(bs, "loops_back", return_value=None):
            code, out, err = self.handle(URL, which=self.which)
        self.assertEqual((code, self.started), (0, [["firefox", URL]]))

    def test_the_config_is_not_valid(self):
        self.write_config(CONFIG)
        self.assertEqual(self.handle("--check", which=self.which)[0], 2)
        self.assertEqual(self.handle(URL, which=self.which)[0], 0)
        self.assertEqual(self.started, [["firefox", URL]])
        self.assertIn("error: [browser chrome-main] command: ", self.log())

    def test_nothing_else_to_start(self):
        code, out, err = self.handle(URL, which=lambda program: self.link)
        self.assertEqual((code, self.started), (1, []))

    def test_explain(self):
        code, out, err = self.handle("--explain", URL, which=self.which)
        self.assertTrue(out.endswith("command: firefox https://example.com/x\n"), out)


class EmptyPath(HandlerCase):
    """The real `which`: an empty PATH is no PATH, the default one is searched."""

    def setUp(self):
        super().setUp()
        self.bin = os.path.join(self.tmp, "bin")
        self.chrome = write_script(os.path.join(self.bin, "google-chrome"), "#!/bin/sh\n")
        write_script(os.path.join(self.bin, "firefox"), "#!/bin/sh\n")
        self.paths = []

    def click(self, env):
        # Only the fake directory is ever searched, and exec is replaced: no real browser can start
        def execve(path, args, env):
            self.paths.append(path)
            self.started.append(args)

        with mock.patch.object(bs.os, "defpath", self.bin):
            return bs.main([URL], env=dict(env, HOME=self.home), cgroup_text="", read_window=lambda env: None,
                           execve=execve)

    def test_empty_path(self):
        self.assertEqual(self.click({"PATH": ""}), 0)
        self.assertEqual((self.paths, self.started), ([self.chrome], [["google-chrome", URL]]))

    def test_no_path(self):
        self.assertEqual(self.click({}), 0)
        self.assertEqual(self.paths, [self.chrome])

    def test_path_is_searched_in_order(self):
        other = os.path.join(self.tmp, "other")
        firefox = write_script(os.path.join(other, "firefox"), "#!/bin/sh\n")
        with open(os.path.join(other, "google-chrome"), "w") as file:
            file.write("not executable")
        self.write_config("[settings]\ndefault = main\n[browser main]\ncommand = firefox -P work\n")
        self.assertEqual(self.click({"PATH": f"{other}:{self.bin}"}), 0)
        self.assertEqual((self.paths, self.started), ([firefox], [["firefox", "-P", "work", URL]]))
        self.write_config("[bogus]\n")
        self.assertEqual(self.click({"PATH": f"{other}:{self.bin}"}), 0)
        self.assertEqual(self.paths[-1], self.chrome)


class Explain(HandlerCase):
    def setUp(self):
        super().setUp()
        self.write_config(EXPLAIN_CONFIG)

    def test_output_format(self):
        code, out, err = self.handle("--explain", URL, cgroup=SLACK, window=SLACK_WINDOW,
                                     probes={"@slack-workspace": "Acme"})
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, "url: https://example.com/x\n"
                              "unit: app-slack-2382881.scope\n"
                              "app: slack\n"
                              "window: slack, Slack\n"
                              "title: Threads - Acme - Slack\n"
                              "probe @slack-workspace: Acme\n"
                              "rule: slack-acme\n"
                              "browser: chrome-main\n"
                              "command: google-chrome '--profile-directory=Profile 6' https://example.com/x\n")

    def test_starts_nothing_and_logs_nothing(self):
        self.handle("--explain", URL, cgroup=SLACK, window=SLACK_WINDOW)
        self.assertEqual((self.started, self.log()), ([], ""))

    def test_logs_nothing_when_things_go_wrong(self):
        self.handle("--explain", URL, programs=())
        self.handle("--explain", URL, window=RuntimeError("boom"), probes={"@slack-workspace": RuntimeError("boom")})
        self.write_config("[settings]\ndefault = nowhere\n[bogus]\n[rule r]\ntitle = (\n")
        code, out, err = self.handle("--explain", URL, cgroup=SLACK, window=SLACK_WINDOW)
        self.assertIn("error: [bogus]: unknown section", err)
        self.env["BROWSER_SELECTOR_CONFIG"] = "/nonexistent/config.ini"
        self.handle("--explain", URL)
        self.handle("--explain")
        self.assertEqual(self.started, [])
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local")))

    def test_control_characters_are_escaped(self):
        out = self.handle("--explain", "https://example.com/\x1b[2J", cgroup=CGROUP.format(r"app-ev\x0ail-12.scope"),
                          window=(["slack", "Slack"], "one\ntwo\x1b[0m"))[1]
        self.assertNotIn("\x1b", out)
        self.assertIn("app: ev\\nil\n", out)
        self.assertIn("title: one\\ntwo\\x1b[0m\n", out)
        self.assertEqual(len(out.splitlines()), 8)

    def test_no_window_and_the_default(self):
        code, out, err = self.handle("--explain", URL)
        self.assertEqual(out, "url: https://example.com/x\n"
                              "unit: -\n"
                              "app: -\n"
                              "window: -\n"
                              "title: -\n"
                              "rule: -\n"
                              "browser: chrome-work\n"
                              "command: google-chrome '--profile-directory=Profile 9' https://example.com/x\n")

    def test_the_window_is_always_read_once(self):
        self.handle("--explain", URL, cgroup=NETBIRD, window=SLACK_WINDOW)
        self.assertEqual(self.window_reads, 1)
        self.handle("--explain", URL, cgroup=SLACK, window=SLACK_WINDOW)
        self.assertEqual(self.window_reads, 2)

    def test_all_app_candidates(self):
        self.env["CHROME_DESKTOP"] = "slack.desktop"
        out = self.handle("--explain", URL, cgroup=CGROUP.format("app-desktop-2381856.scope"))[1]
        self.assertIn("unit: app-desktop-2381856.scope\napp: desktop, slack\n", out)

    def test_probe_line_only_for_probes_that_ran(self):
        out = self.handle("--explain", URL, cgroup=NETBIRD,
                          probes={"netbird profile list": "NAME     ACTIVE\ndefault  \nglobex   ✓\n"})[1]
        self.assertIn("probe netbird profile list: NAME     ACTIVE | default | globex   ✓\n", out)
        self.assertNotIn("@slack-workspace", out)
        self.assertIn("rule: netbird-globex\n", out)

    def test_failed_probe(self):
        out = self.handle("--explain", URL, cgroup=NETBIRD)[1]
        self.assertIn("probe netbird profile list: -\n", out)
        self.assertIn("rule: -\n", out)

    def test_without_a_url(self):
        code, out, err = self.handle("--explain", cgroup=SLACK, window=SLACK_WINDOW,
                                     probes={"@slack-workspace": "Acme"})
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, "unit: app-slack-2382881.scope\n"
                              "app: slack\n"
                              "window: slack, Slack\n"
                              "title: Threads - Acme - Slack\n"
                              "probe @slack-workspace: Acme\n"
                              "probe netbird profile list: -\n")

    def test_no_config_file_shows_the_last_resort(self):
        self.env["BROWSER_SELECTOR_CONFIG"] = "/nonexistent/config.ini"
        code, out, err = self.handle("--explain", URL)
        self.assertEqual(code, 0)
        self.assertTrue(out.endswith("rule: -\nbrowser: -\ncommand: google-chrome https://example.com/x\n"), out)
        self.assertIn("/nonexistent/config.ini: no such file", err)

    def test_config_not_valid_shows_the_error_and_the_last_resort(self):
        self.write_config("[settings]\n")
        code, out, err = self.handle("--explain", URL, programs=("firefox",))
        self.assertEqual(code, 0)
        self.assertTrue(out.endswith("rule: -\nbrowser: -\ncommand: firefox https://example.com/x\n"), out)
        self.assertIn("error: [settings] default: missing", err)

    def test_program_not_found(self):
        code, out, err = self.handle("--explain", URL, cgroup=SLACK, window=SLACK_WINDOW, programs=("firefox",))
        self.assertEqual(code, 0)
        self.assertTrue(out.endswith("rule: slack-acme\nbrowser: -\ncommand: firefox https://example.com/x\n"),
                        out)
        self.assertIn("error: [browser chrome-main] command: google-chrome not found", err)

    def test_nothing_to_start(self):
        code, out, err = self.handle("--explain", URL, programs=())
        self.assertEqual(code, 1)
        self.assertTrue(out.endswith("rule: -\nbrowser: -\ncommand: -\n"), out)


class Log(HandlerCase):
    SECRET = "https://user:hunter2@Login.Example.com:8443/auth/callback?token=s3cr3t&next=/inbox#frag"

    def test_one_line_per_decision(self):
        self.write_config(CONFIG)
        self.handle(URL, cgroup=SLACK, window=SLACK_WINDOW)
        self.assertRegex(self.log(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4} "
                                     r"rule=slack-acme browser=chrome-work app=slack url=https://example\.com\n$")

    def test_lines_are_appended(self):
        self.write_config(CONFIG)
        self.env["CHROME_DESKTOP"] = "slack.desktop"
        self.handle(URL, cgroup=CGROUP.format("app-desktop-2381856.scope"), window=SLACK_WINDOW)
        self.handle("http://other.org/")
        lines = self.log().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].endswith(" rule=slack-acme browser=chrome-work app=desktop,slack "
                                          "url=https://example.com"), lines[0])
        self.assertTrue(lines[1].endswith(" rule=- browser=chrome-main app=slack url=http://other.org"), lines[1])

    def test_last_resort_line(self):
        self.handle(URL)
        self.assertTrue(self.log().endswith(" rule=- browser=- app=- url=https://example.com\n"), self.log())

    def assertNoSecret(self, log):
        for secret in ("user", "hunter2", "8443", "auth", "callback", "token", "s3cr3t", "inbox", "frag", "?", "@"):
            self.assertNotIn(secret, log)

    def test_never_the_path_or_the_query(self):
        self.write_config(CONFIG)
        self.handle(self.SECRET, cgroup=SLACK, window=SLACK_WINDOW)
        self.assertTrue(self.log().endswith(" url=https://login.example.com\n"), self.log())
        self.assertNoSecret(self.log())

    def test_never_the_path_or_the_query_on_the_error_paths(self):
        self.write_config(CONFIG)
        self.handle(self.SECRET, cgroup=SLACK, window=RuntimeError(self.SECRET))
        self.handle(self.SECRET, programs=())
        self.handle(self.SECRET, broken=bs.LAST_RESORT)
        self.write_config(CONFIG + "[bogus]\n")
        self.handle(self.SECRET, programs=("firefox",))
        self.env["BROWSER_SELECTOR_CONFIG"] = "/nonexistent/config.ini"
        self.handle(self.SECRET, programs=("firefox",))
        log = self.log()
        for expected in ("error: window: RuntimeError\n",
                         "error: [browser chrome-main] command: google-chrome not found\n",
                         "error: no browser to start, url=https://login.example.com\n",
                         "error: firefox: Permission denied\n",
                         "error: [bogus]: unknown section\n",
                         " rule=- browser=- app=- url=https://login.example.com\n"):
            with self.subTest(expected=expected):
                self.assertIn(expected, log)
        self.assertNoSecret(log)

    def test_state_home_from_the_environment(self):
        self.env["XDG_STATE_HOME"] = os.path.join(self.tmp, "state")
        self.handle(URL)
        self.assertTrue(read(os.path.join(self.tmp, "state", "browser-selector", "log")).endswith(
            " rule=- browser=- app=- url=https://example.com\n"))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local")))

    def test_bytes_that_are_not_utf8(self):
        # What a non-UTF-8 byte of argv or of the environment looks like in Python
        self.env["CHROME_DESKTOP"] = "sl\udcffack.desktop"
        self.assertEqual(self.handle("https://ex\udcfeample.com/x")[0], 0)
        self.assertEqual(self.started, [["google-chrome", "https://ex\udcfeample.com/x"]])
        self.assertTrue(self.log().endswith(" rule=- browser=- app=sl\\udcffack url=https://ex\\udcfeample.com\n"),
                        self.log())

    def test_control_characters_never_reach_the_log(self):
        self.write_config(CONFIG)
        self.env["CHROME_DESKTOP"] = "sla\x07ck\u202e.desktop"
        self.handle("https://exa\x1bmple.com/x", cgroup=CGROUP.format(r"app-ev\x0ail-12.scope"))
        log = self.log()
        self.assertEqual(log.count("\n"), 1)
        self.assertTrue(log.endswith(" rule=- browser=chrome-main app=ev\\nil,sla\\x07ck\\u202e "
                                     "url=https://exa\\x1bmple.com\n"), log)
        self.assertTrue(log[:-1].isprintable(), log)

    def test_a_unit_name_cannot_forge_a_line(self):
        self.write_config(CONFIG)
        unit = r"app-x\x0a2026-01-01T00:00:00+0000\x20rule=fake\x20browser=fake\x20app=fake\x20url=https:\x2f\x2fevil-1.scope"
        self.handle(URL, cgroup=CGROUP.format(unit))
        lines = self.log().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertFalse([line for line in lines if line.startswith("2026-01-01")])

    def test_error_lines_are_escaped_too(self):
        self.write_config(CONFIG + "[rule a\x1bb]\nbrowser = no\x07where\n")
        self.handle(URL)
        self.assertIn("error: [rule a\\x1bb] browser: browser no\\x07where is not defined\n", self.log())
        self.assertNotIn("\x1b", self.log())

    def test_url_origin(self):
        cases = {
            "https://example.com/x?token=1": "https://example.com",
            "http://Example.COM": "http://example.com",
            "https://user:pw@example.com:8443/x": "https://example.com",
            "https://[::1]:8080/x": "https://::1",
            "example.com/secret": "-",
            "/home/user/secret.html": "-",
            "mailto:someone@example.com": "-",
            "https://[broken/secret": "-",
            "": "-",
        }
        for url, origin in cases.items():
            with self.subTest(url=url):
                self.assertEqual(bs.url_origin(url), origin)
        self.assertFalse(re.search(r"\s", bs.url_origin("https://exa mple.com/a\nb")))


class LogFile(HandlerCase):
    """Mode and size of the log."""

    def setUp(self):
        super().setUp()
        self.addCleanup(os.umask, os.umask(0o022))

    def mode(self, path):
        return oct(os.stat(path).st_mode & 0o7777)

    def test_new_log_is_private(self):
        for umask in (0o022, 0, 0o077):
            with self.subTest(umask=oct(umask)):
                os.umask(umask)
                self.env["XDG_STATE_HOME"] = os.path.join(self.tmp, f"state-{umask}")
                self.handle(URL)
                directory = os.path.join(self.env["XDG_STATE_HOME"], "browser-selector")
                self.assertEqual(self.mode(os.path.join(directory, "log")), "0o600")
                self.assertEqual(self.mode(directory), "0o700")

    def test_mode_of_an_older_log_is_fixed(self):
        os.makedirs(os.path.dirname(self.log_path), mode=0o755)
        with open(self.log_path, "w") as file:
            file.write("old line\n")
        os.chmod(self.log_path, 0o644)
        self.handle(URL)
        self.assertEqual(self.mode(self.log_path), "0o600")
        self.assertEqual(self.mode(os.path.dirname(self.log_path)), "0o700")
        self.assertEqual(len(self.log().splitlines()), 2)
        self.assertTrue(self.log().startswith("old line\n"))

    def big_log(self, size):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        with open(self.log_path, "w") as file:
            file.write("x" * (size - 1) + "\n")

    def test_log_over_the_cap_is_renamed(self):
        self.big_log(bs.LOG_LIMIT + 1)
        self.handle(URL)
        self.assertEqual(os.path.getsize(self.log_path + ".1"), bs.LOG_LIMIT + 1)
        self.assertEqual(len(self.log().splitlines()), 1)
        self.assertIn("url=https://example.com", self.log())
        self.assertEqual(self.mode(self.log_path), "0o600")

    def test_log_at_the_cap_is_kept(self):
        self.assertEqual(bs.LOG_LIMIT, 1024 * 1024)
        self.big_log(bs.LOG_LIMIT)
        self.handle(URL)
        self.assertFalse(os.path.exists(self.log_path + ".1"))
        self.assertGreater(os.path.getsize(self.log_path), bs.LOG_LIMIT)

    def test_one_generation(self):
        self.big_log(bs.LOG_LIMIT + 1)
        self.handle(URL)
        self.big_log(bs.LOG_LIMIT + 7)
        self.handle(URL)
        self.assertEqual(os.path.getsize(self.log_path + ".1"), bs.LOG_LIMIT + 7)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.log_path))), ["log", "log.1"])

    def test_a_fifo_in_place_of_the_log_does_not_block(self):
        watchdog(self)
        os.makedirs(os.path.dirname(self.log_path))
        os.mkfifo(self.log_path)
        self.assertEqual(self.handle(URL)[0], 0)
        self.assertEqual(self.started, [["google-chrome", URL]])


if __name__ == "__main__":
    unittest.main()
