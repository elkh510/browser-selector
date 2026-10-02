"""Rules: matching, order, the lazy window read and probes."""

import os
import tempfile
import time
import unittest

from support import CONFIG, FIXTURES, NETBIRD, SLACK, URL, CGROUP, HandlerCase, bs, read, watchdog

HEAD = """
[settings]
default = main

[browser main]
command = google-chrome

[browser a]
command = firefox

[browser b]
command = chromium
"""
SLACK_WINDOW = (["slack", "Slack"], "Threads - Acme - Slack")
NETBIRD_GLOBEX = "NAME     ACTIVE\ndefault  \nglobex   ✓\n"
NETBIRD_DEFAULT = "NAME     ACTIVE\ndefault  ✓\nglobex   \n"


class Matching(HandlerCase):
    def program(self, rules, url=URL, **context):
        """The program started for a click with the given rules."""
        self.write_config(HEAD + rules)
        self.started.clear()
        code, out, err = self.handle(url, **context)
        self.assertEqual(code, 0, err)
        return self.started[0][0]

    def test_no_rule_matches_the_default(self):
        self.assertEqual(self.program("[rule r]\napp = slack\nbrowser = a\n"), "google-chrome")

    def test_first_matching_rule_wins(self):
        rules = "[rule one]\nurl = example\nbrowser = a\n[rule two]\nurl = example\nbrowser = b\n"
        self.assertEqual(self.program(rules), "firefox")

    def test_rules_are_tried_in_file_order(self):
        rules = "[rule one]\nurl = nothing\nbrowser = a\n[rule two]\nurl = example\nbrowser = b\n"
        self.assertEqual(self.program(rules), "chromium")

    def test_a_rule_without_conditions_matches_everything(self):
        self.assertEqual(self.program("[rule all]\nbrowser = a\n"), "firefox")

    def test_all_conditions_must_hold(self):
        rules = "[rule r]\napp = slack\nurl = ^https://example\\.com/\ntitle = Acme\nbrowser = a\n"
        self.assertEqual(self.program(rules, cgroup=SLACK, window=SLACK_WINDOW), "firefox")
        self.assertEqual(self.program(rules, cgroup=NETBIRD, window=SLACK_WINDOW), "google-chrome")
        self.assertEqual(self.program(rules, url="https://other.org/", cgroup=SLACK, window=SLACK_WINDOW),
                         "google-chrome")
        self.assertEqual(self.program(rules, cgroup=SLACK, window=(["slack", "Slack"], "Threads - Globex - Slack")),
                         "google-chrome")

    def test_app_matches_either_candidate(self):
        rules = "[rule r]\napp = slack\nbrowser = a\n"
        desktop = CGROUP.format("app-desktop-2381856.scope")
        self.assertEqual(self.program(rules, cgroup=desktop), "google-chrome")
        self.env["CHROME_DESKTOP"] = "slack.desktop"
        self.assertEqual(self.program(rules, cgroup=desktop), "firefox")
        self.assertEqual(self.program(rules), "firefox")

    def test_app_is_a_case_insensitive_full_match(self):
        rules = "[rule r]\napp = SLACK\nbrowser = a\n"
        self.assertEqual(self.program(rules, cgroup=SLACK), "firefox")
        self.assertEqual(self.program(rules, cgroup=CGROUP.format("app-slack-beta-1.scope")), "google-chrome")
        rules = "[rule r]\napp = desktop|clickup\nbrowser = a\n"
        self.assertEqual(self.program(rules, cgroup=CGROUP.format("app-clickup-1.scope")), "firefox")
        self.assertEqual(self.program(rules, cgroup=CGROUP.format("app-clickup-desktop-1.scope")), "google-chrome")

    def test_window_matches_either_part_of_the_class(self):
        window = (["crx_abc", "Google-chrome"], "Mail")
        self.assertEqual(self.program("[rule r]\nwindow = google-chrome\nbrowser = a\n", window=window), "firefox")
        self.assertEqual(self.program("[rule r]\nwindow = crx_.*\nbrowser = a\n", window=window), "firefox")
        self.assertEqual(self.program("[rule r]\nwindow = chrome\nbrowser = a\n", window=window), "google-chrome")

    def test_title_is_a_case_sensitive_search(self):
        self.assertEqual(self.program("[rule r]\ntitle = - Acme - Slack$\nbrowser = a\n", window=SLACK_WINDOW),
                         "firefox")
        self.assertEqual(self.program("[rule r]\ntitle = acme\nbrowser = a\n", window=SLACK_WINDOW),
                         "google-chrome")

    def test_url_is_a_case_sensitive_search(self):
        rules = "[rule r]\nurl = example\\.com/x$\nbrowser = a\n"
        self.assertEqual(self.program(rules), "firefox")
        self.assertEqual(self.program(rules, url="https://EXAMPLE.com/x"), "google-chrome")

    def test_probe_match_is_a_multiline_search(self):
        rules = "[rule r]\nprobe = netbird profile list\nprobe_match = ^globex\\s+✓\nbrowser = a\n"
        self.assertEqual(self.program(rules, probes={"netbird profile list": NETBIRD_GLOBEX}), "firefox")
        self.assertEqual(self.program(rules, probes={"netbird profile list": NETBIRD_DEFAULT}), "google-chrome")


class LazyWindow(HandlerCase):
    def test_not_read_when_no_rule_needs_it(self):
        self.write_config(HEAD + "[rule r]\napp = slack\nbrowser = a\n")
        self.handle(URL, cgroup=SLACK, window=SLACK_WINDOW)
        self.assertEqual(self.window_reads, 0)

    def test_not_read_when_an_earlier_rule_matches(self):
        self.write_config(CONFIG)
        self.handle("https://acme.cloudflareaccess.com/login", cgroup=SLACK, window=SLACK_WINDOW)
        self.assertEqual(self.window_reads, 0)

    def test_not_read_when_the_cheaper_conditions_fail(self):
        self.write_config(CONFIG)
        self.handle(URL, cgroup=NETBIRD, window=SLACK_WINDOW)
        self.assertEqual(self.window_reads, 0)
        self.write_config(HEAD + "[rule r]\nurl = nothing\nwindow = slack\ntitle = Slack\nbrowser = a\n")
        self.handle(URL, cgroup=SLACK, window=SLACK_WINDOW)
        self.assertEqual(self.window_reads, 0)

    def test_read_once_for_many_rules(self):
        rules = "".join(f"[rule r{n}]\nwindow = nothing{n}\ntitle = nothing\nbrowser = a\n" for n in range(5))
        self.write_config(HEAD + rules)
        self.handle(URL, window=SLACK_WINDOW)
        self.assertEqual(self.window_reads, 1)

    def test_read_once_when_there_is_no_window(self):
        rules = "".join(f"[rule r{n}]\ntitle = Slack\nbrowser = a\n" for n in range(5))
        self.write_config(HEAD + rules)
        self.handle(URL, window=None)
        self.assertEqual(self.window_reads, 1)
        self.assertEqual(self.started, [["google-chrome", URL]])

    def test_the_window_is_read_before_the_probe(self):
        self.write_config(HEAD + "[rule r]\ntitle = nothing\nprobe = slow\nprobe_match = x\nbrowser = a\n")
        self.handle(URL, window=SLACK_WINDOW, probes={"slow": "x"})
        self.assertEqual((self.window_reads, self.probe_runs), (1, []))


class Probes(HandlerCase):
    def test_same_probe_runs_once(self):
        rules = "".join(f"[rule r{n}]\nprobe = netbird profile list\nprobe_match = ^nothing{n}\nbrowser = a\n"
                        for n in range(4))
        self.write_config(HEAD + rules + "[rule other]\nprobe = other\nprobe_match = x\nbrowser = b\n")
        self.handle(URL, probes={"netbird profile list": NETBIRD_GLOBEX})
        self.assertEqual([command for command, timeout in self.probe_runs], ["netbird profile list", "other"])

    def test_a_failed_probe_runs_once_too(self):
        rules = "".join(f"[rule r{n}]\nprobe = gone\nprobe_match = x\nbrowser = a\n" for n in range(3))
        self.write_config(HEAD + rules)
        self.handle(URL)
        self.assertEqual(len(self.probe_runs), 1)
        self.assertEqual(self.started, [["google-chrome", URL]])

    def test_not_run_when_the_cheaper_conditions_fail(self):
        self.write_config(CONFIG)
        self.handle(URL, cgroup=CGROUP.format("app-desktop-1.scope"))
        self.assertEqual(self.probe_runs, [])

    def test_timeout_comes_from_the_settings(self):
        self.write_config(CONFIG)
        self.handle(URL, cgroup=NETBIRD)
        self.assertEqual(self.probe_runs, [("netbird profile list", 2.0)])
        self.write_config(CONFIG.replace("default = chrome-main", "default = chrome-main\nprobe_timeout = 0.5"))
        self.handle(URL, cgroup=NETBIRD)
        self.assertEqual(self.probe_runs[-1], ("netbird profile list", 0.5))


class BrokenReaders(HandlerCase):
    """A reader that raises is a condition that is false: the next rule is tried."""

    RULES = ("[rule one]\ntitle = Slack\nbrowser = a\n"
             "[rule two]\nprobe = netbird profile list\nprobe_match = globex\nbrowser = a\n"
             "[rule three]\ntitle = Slack\nprobe = netbird profile list\nprobe_match = x\nbrowser = a\n"
             "[rule four]\nurl = example\nbrowser = b\n")

    def test_window_reader_raises(self):
        self.write_config(HEAD + self.RULES)
        code, out, err = self.handle(URL, window=RuntimeError("boom"),
                                     probes={"netbird profile list": NETBIRD_GLOBEX})
        self.assertEqual((code, self.started), (0, [["firefox", URL]]))
        self.assertEqual(self.window_reads, 1)
        self.assertEqual(self.log().count("error: window: RuntimeError\n"), 1)

    def test_probe_runner_raises(self):
        self.write_config(HEAD + self.RULES)
        code, out, err = self.handle(URL, window=None, probes={"netbird profile list": OverflowError("too big")})
        self.assertEqual((code, self.started), (0, [["chromium", URL]]))
        self.assertEqual(len(self.probe_runs), 1)
        self.assertEqual(self.log().count("error: probe netbird profile list: OverflowError\n"), 1)

    def test_both_raise_and_a_later_rule_still_matches(self):
        self.write_config(HEAD + self.RULES)
        self.handle(URL, window=MemoryError(), probes={"netbird profile list": RecursionError()})
        self.assertEqual(self.started, [["chromium", URL]])
        self.assertEqual(self.log().count("error: "), 2)

    def test_explain_shows_the_error_and_goes_on(self):
        self.write_config(HEAD + self.RULES)
        code, out, err = self.handle("--explain", URL, window=RuntimeError("boom"))
        self.assertEqual(code, 0)
        self.assertIn("window: -\ntitle: -\n", out)
        self.assertIn("rule: four\nbrowser: b\n", out)
        self.assertIn("error: window: RuntimeError\n", err)


class RunProbe(unittest.TestCase):
    """The real probe runner, with harmless commands."""

    env = dict(os.environ)

    def test_stdout(self):
        self.assertEqual(bs.run_probe("printf '%s\\n' 'globex   ✓'", 2, self.env), "globex   ✓\n")

    def test_no_shell(self):
        self.assertEqual(bs.run_probe("echo $HOME ; echo x", 2, self.env), "$HOME ; echo x\n")

    def test_failure(self):
        self.assertIsNone(bs.run_probe("false", 2, self.env))

    def test_missing_binary(self):
        self.assertIsNone(bs.run_probe("/nonexistent/browser-selector-probe --list", 2, self.env))
        self.assertIsNone(bs.run_probe("browser-selector-no-such-probe", 2, self.env))

    def test_failure_after_output(self):
        self.assertIsNone(bs.run_probe("sh -c 'echo globex; exit 3'", 2, self.env))

    def test_program_that_cannot_be_started(self):
        self.assertIsNone(bs.run_probe("/etc/hostname", 2, self.env))
        self.assertIsNone(bs.run_probe("echo a\0b", 2, self.env))

    def test_timeout(self):
        started = time.monotonic()
        self.assertIsNone(bs.run_probe("sleep 10", 0.2, self.env))
        self.assertLess(time.monotonic() - started, 2)

    def test_timeout_after_some_output(self):
        started = time.monotonic()
        self.assertIsNone(bs.run_probe("sh -c 'echo globex; exec sleep 10'", 0.3, self.env))
        self.assertLess(time.monotonic() - started, 2)

    def test_timeout_when_stdout_is_closed_and_the_probe_stays(self):
        started = time.monotonic()
        self.assertIsNone(bs.run_probe("sh -c 'echo globex; exec >&-; exec sleep 10'", 0.3, self.env))
        self.assertLess(time.monotonic() - started, 2)

    def test_output_is_read_up_to_the_cap_and_the_probe_is_killed(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_file = os.path.join(directory, "pid")
            started = time.monotonic()
            output = bs.run_probe(f"sh -c 'echo $$ > {pid_file}; exec yes'", 5, self.env)
            self.assertLess(time.monotonic() - started, 4)
            self.assertEqual(bs.PROBE_LIMIT, 64 * 1024)
            self.assertEqual(output, "y\n" * (bs.PROBE_LIMIT // 2))
            # The probe was killed and reaped: its pid is gone
            with self.assertRaises(ProcessLookupError):
                os.kill(int(read(pid_file)), 0)

    def test_output_just_under_the_cap_is_complete(self):
        size = bs.PROBE_LIMIT - 1
        self.assertEqual(bs.run_probe(f"head -c {size} /dev/zero", 5, self.env), "\0" * size)


class RealProbeInARule(HandlerCase):
    def test_a_probe_over_the_cap_is_matched_against_what_was_read(self):
        self.write_config(HEAD + "[rule noisy]\nprobe = yes globex\nprobe_match = ^globex$\nbrowser = a\n")
        # The probe needs the real PATH, the browsers do not get one: exec and which are replaced
        self.env["PATH"] = os.environ.get("PATH", os.defpath)
        bs.main([URL], env=self.env, cgroup_text="", read_window=lambda env: None,
                which=lambda program: program, execve=lambda path, args, env: self.started.append(args))
        self.assertEqual(self.started, [["firefox", URL]])


class SlackWorkspace(HandlerCase):
    def state(self, text):
        """An XDG_CONFIG_HOME whose Slack state file has this text."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        os.makedirs(os.path.join(directory.name, "Slack", "storage"))
        with open(os.path.join(directory.name, "Slack", "storage", "root-state.json"), "w") as file:
            file.write(text)
        return {"XDG_CONFIG_HOME": directory.name}

    def test_selected_workspace_of_the_fixture(self):
        self.assertEqual(bs.run_probe("@slack-workspace", 2, {"XDG_CONFIG_HOME": FIXTURES}), "Acme")

    def test_other_workspace_selected(self):
        text = read(os.path.join(FIXTURES, "Slack", "storage", "root-state.json"))
        env = self.state(text.replace('"selectedWorkspaceId": "T01ACME0001"', '"selectedWorkspaceId": "T01ABCDEF12"'))
        self.assertEqual(bs.run_probe("@slack-workspace", 2, env), "Globex")

    def test_falls_back_to_home(self):
        self.assertIsNone(bs.run_probe("@slack-workspace", 2, {"HOME": self.home}))
        os.makedirs(os.path.join(self.home, ".config"))
        os.symlink(os.path.join(FIXTURES, "Slack"), os.path.join(self.home, ".config", "Slack"))
        self.assertEqual(bs.run_probe("@slack-workspace", 2, {"HOME": self.home}), "Acme")

    def test_unusable_state_file(self):
        for text in ("", "not json", "[]", "{}", '{"workspaces": {}, "workspacesMeta": {"selectedWorkspaceId": "T1"}}',
                     '{"workspaces": {"T1": {"name": 5}}, "workspacesMeta": {"selectedWorkspaceId": "T1"}}'):
            with self.subTest(text=text):
                self.assertIsNone(bs.run_probe("@slack-workspace", 2, self.state(text)))

    def test_rule_with_the_real_reader(self):
        self.write_config(CONFIG.replace("^Globex$", "^Acme$"))
        self.env["XDG_CONFIG_HOME"] = FIXTURES
        self.env["BROWSER_SELECTOR_CONFIG"] = os.path.join(self.home, ".config", "browser-selector", "config.ini")
        self.click()
        self.assertEqual(self.started, [["brave-browser", "--profile-directory=Default", URL]])

    def click(self):
        """A click from Slack with the real probe runner."""
        bs.main([URL], env=self.env, cgroup_text=SLACK, read_window=lambda env: None,
                which=lambda program: program, execve=lambda path, args, env: self.started.append(args))

    def test_state_file_that_breaks_the_json_parser(self):
        # RecursionError, not ValueError: the rule is false and the next one is tried
        self.env.update(self.state("[" * 200000))
        self.env["BROWSER_SELECTOR_CONFIG"] = self.write_config(
            CONFIG + "[rule slack-again]\napp = slack\nprobe = @slack-workspace\nprobe_match = x\n"
                     "browser = chrome-work\n[rule slack-any]\napp = slack\nbrowser = chrome-work\n")
        self.click()
        self.assertEqual(self.started, [["google-chrome", "--profile-directory=Profile 9", URL]])
        self.assertEqual(self.log().count("error: probe @slack-workspace: RecursionError\n"), 1)

    def test_state_file_that_is_a_fifo(self):
        directory = self.state("")["XDG_CONFIG_HOME"]
        os.remove(os.path.join(directory, "Slack", "storage", "root-state.json"))
        os.mkfifo(os.path.join(directory, "Slack", "storage", "root-state.json"))
        watchdog(self)
        self.assertIsNone(bs.run_probe("@slack-workspace", 2, {"XDG_CONFIG_HOME": directory}))


if __name__ == "__main__":
    unittest.main()
