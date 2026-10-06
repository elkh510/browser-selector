"""The handler as a process: the real `which` and the real exec.

The PATH of the handler holds nothing but fake browsers made here, so no real
browser can start. A fake browser writes its name and arguments down.
"""

import os
import subprocess
import sys
import tempfile
import time
import unittest

from support import CGROUP, ROOT, URL, read, write_script

HANDLER = os.path.join(ROOT, "browser_selector.py")
RECORD_LAUNCH = """\
printf '%s\\t' {name} "$@" >> "$RECORD"
printf '%s\\n' "$BROWSER_SELECTOR_GUARD" >> "$RECORD"
"""
# A browser command that opens the link with the handler again, the way a
# wrapper around xdg-open does. It stops by itself after ten rounds.
LOOPING_BROWSER = """\
#!/bin/sh
""" + RECORD_LAUNCH + """\
rounds=0
while read -r line; do rounds=$((rounds + 1)); done < "$RECORD"
[ "$rounds" -gt 10 ] && exit 9
exec "{python}" "{handler}" "$@"
"""
CONFIG = """\
[settings]
default = chrome-main

[browser chrome-main]
command = google-chrome --profile-directory="Profile 6"

[browser brave-globex]
command = brave-browser --profile-directory=Default --app={url}

[browser ghost]
command = no-such-browser --new-window

[rule slack]
app = slack
browser = brave-globex

[rule ghost]
url = ^https://ghost\\.example\\.com/
browser = ghost
"""


class Process(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = directory.name
        self.bin = os.path.join(self.tmp, "bin")
        self.home = os.path.join(self.tmp, "home")
        self.record = os.path.join(self.tmp, "record")
        self.config = os.path.join(self.home, ".config", "browser-selector", "config.ini")
        os.makedirs(os.path.dirname(self.config))
        os.mkdir(self.bin)
        self.cgroup = os.path.join(self.tmp, "cgroup")
        self.write(self.cgroup, CGROUP.format("app-org.example.Unknown-4711.scope"))
        # Nothing of the real session: no XDG_*, no DISPLAY, and only fake browsers on the PATH
        self.env = {"HOME": self.home, "PATH": self.bin, "RECORD": self.record,
                    "BROWSER_SELECTOR_CGROUP_FILE": self.cgroup}

    def write(self, path, text):
        with open(path, "w", encoding="utf-8") as file:
            file.write(text)

    def browsers(self, *names):
        for name in names:
            write_script(os.path.join(self.bin, name), "#!/bin/sh\n" + RECORD_LAUNCH.format(name=name))

    def run_handler(self, *argv, **env):
        return subprocess.run([sys.executable, HANDLER, *argv], env={**self.env, **env}, timeout=60,
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def click(self, url=URL, **env):
        done = self.run_handler(url, **env)
        self.assertEqual(done.stderr, b"")
        self.assertEqual(done.returncode, 0)

    def launches(self):
        """Every launch as [name, argument...], the guard variable left out."""
        with open(self.record, "rb") as file:
            return [line.decode(errors="surrogateescape").split("\t")[:-1] for line in file.read().splitlines()]

    def log(self):
        return read(os.path.join(self.home, ".local", "state", "browser-selector", "log"))

    def test_default_browser(self):
        self.browsers("google-chrome", "brave-browser", "firefox")
        self.write(self.config, CONFIG)
        self.click()
        self.assertEqual(self.launches(), [["google-chrome", "--profile-directory=Profile 6", URL]])
        self.assertIn(" rule=- browser=chrome-main app=org.example.Unknown url=https://example.com\n", self.log())

    def test_rule_hit(self):
        self.browsers("google-chrome", "brave-browser", "firefox")
        self.write(self.config, CONFIG)
        self.write(self.cgroup, CGROUP.format("app-slack-2382881.scope"))
        url = "https://example.com/a b?q=$(touch x)&r='y'#{url}"
        self.click(url)
        self.assertEqual(self.launches(), [["brave-browser", "--profile-directory=Default", "--app=" + url]])
        self.assertIn(" rule=slack browser=brave-globex app=slack url=https://example.com\n", self.log())

    def test_app_from_chrome_desktop(self):
        self.browsers("google-chrome", "brave-browser")
        self.write(self.config, CONFIG)
        self.click(CHROME_DESKTOP="slack.desktop")
        self.assertEqual(self.launches()[0][0], "brave-browser")

    def test_missing_program_falls_back_to_the_default(self):
        self.browsers("google-chrome", "firefox")
        self.write(self.config, CONFIG)
        self.click("https://ghost.example.com/x")
        self.assertEqual(self.launches(),
                         [["google-chrome", "--profile-directory=Profile 6", "https://ghost.example.com/x"]])
        self.assertIn("error: [browser ghost] command: no-such-browser not found\n", self.log())

    def test_broken_config_opens_the_last_resort(self):
        self.browsers("google-chrome", "firefox")
        self.write(self.config, CONFIG + "[rule broken]\nbrowser = nowhere\n")
        self.click()
        self.assertEqual(self.launches(), [["google-chrome", URL]])
        self.assertIn("error: [rule broken] browser: browser nowhere is not defined\n", self.log())

    def test_no_config_opens_the_last_resort_in_its_order(self):
        self.browsers("chromium", "firefox")
        self.click()
        self.assertEqual(self.launches(), [["firefox", URL]])

    def test_config_from_the_option_and_from_the_environment(self):
        self.browsers("google-chrome", "firefox")
        other = os.path.join(self.tmp, "other.ini")
        self.write(other, "[settings]\ndefault = fox\n[browser fox]\ncommand = firefox -P work\n")
        self.write(self.config, CONFIG)
        self.assertEqual(self.run_handler("--config", other, URL, BROWSER_SELECTOR_CONFIG=self.config).returncode, 0)
        self.assertEqual(self.run_handler(URL, BROWSER_SELECTOR_CONFIG=other).returncode, 0)
        self.assertEqual(self.launches(), [["firefox", "-P", "work", URL]] * 2)

    def test_program_that_cannot_be_executed_next_one_is_tried(self):
        self.browsers("brave-browser")
        write_script(os.path.join(self.bin, "google-chrome"), "#!/nonexistent/interpreter\n")
        self.click()
        self.assertEqual(self.launches(), [["brave-browser", URL]])
        self.assertIn("error: google-chrome: ", self.log())

    def test_nothing_to_start_exits_1(self):
        done = self.run_handler(URL)
        self.assertEqual(done.returncode, 1)
        self.assertIn(b"no browser to start", done.stderr)
        self.assertFalse(os.path.exists(self.record))

    def test_a_dash_argument_is_refused(self):
        self.browsers("google-chrome")
        for argv in (["--incognito"], [" --incognito"], [URL, "\t--no-sandbox"], [""]):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_handler(*argv).returncode, 1)
        self.assertFalse(os.path.exists(self.record))

    def test_local_file_and_about_are_passed_on(self):
        self.browsers("google-chrome")
        self.write(self.config, CONFIG)
        for url in (os.path.join(self.tmp, "page.html"), "about:blank"):
            self.click(url)
        self.assertEqual([launch[-1] for launch in self.launches()], [os.path.join(self.tmp, "page.html"), "about:blank"])

    def test_bytes_that_are_not_utf8(self):
        self.browsers("google-chrome")
        url = b"https://ex\xffample.com/caf\xe9"
        done = self.run_handler(url, CHROME_DESKTOP=b"sl\xfeack.desktop")
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        with open(self.record, "rb") as file:
            self.assertTrue(file.read().startswith(b"google-chrome\t" + url + b"\t"))
        self.assertIn(" rule=- browser=- app=org.example.Unknown,sl\\udcfeack url=https://ex\\udcffample.com\n",
                      self.log())

    def test_the_browser_gets_the_guard(self):
        self.browsers("google-chrome")
        before = int(time.time())
        self.click()
        with open(self.record) as file:
            guard = int(file.read().rstrip("\n").split("\t")[-1])
        self.assertTrue(before <= guard <= time.time(), guard)

    def test_a_browser_command_that_calls_the_handler_again(self):
        self.browsers("firefox")
        write_script(os.path.join(self.bin, "wrapper"),
                     LOOPING_BROWSER.format(name="wrapper", python=sys.executable, handler=HANDLER))
        self.write(self.config, "[settings]\ndefault = main\n[browser main]\ncommand = wrapper\n")
        self.assertEqual(self.run_handler("--check").returncode, 0)
        self.click()
        self.assertEqual(self.launches(), [["wrapper", URL], ["firefox", URL]])
        self.assertIn("a command leads back to the handler", self.log())

    def test_an_old_guard_does_not_stop_the_rules(self):
        self.browsers("google-chrome", "firefox")
        self.write(self.config, CONFIG)
        self.click(BROWSER_SELECTOR_GUARD=str(int(time.time()) - 60))
        self.assertEqual(self.launches(), [["google-chrome", "--profile-directory=Profile 6", URL]])

    def test_a_program_that_is_the_handler_itself_is_not_started(self):
        self.browsers("firefox")
        os.symlink(HANDLER, os.path.join(self.bin, "google-chrome"))
        self.click()
        self.assertEqual(self.launches(), [["firefox", URL]])
        self.write(self.config, "[settings]\ndefault = main\n[browser main]\ncommand = google-chrome\n")
        done = self.run_handler("--check")
        self.assertEqual(done.returncode, 2)
        self.assertIn(b"[browser main] command: ", done.stderr)

    def test_check_exit_codes(self):
        self.write(self.config, CONFIG)
        self.assertEqual(self.run_handler("--check").returncode, 0)
        self.write(self.config, CONFIG + "[rule big]\nurl = x{99999999999}\nbrowser = chrome-main\n")
        done = self.run_handler("--check")
        self.assertEqual(done.returncode, 2)
        self.assertIn(b"[rule big] url: bad regex", done.stderr)
        self.assertNotIn(b"Traceback", done.stderr)

    def test_config_with_a_bom(self):
        self.browsers("google-chrome", "firefox")
        with open(self.config, "w", encoding="utf-8-sig") as file:
            file.write(CONFIG)
        self.assertEqual(self.run_handler("--check").returncode, 0)
        self.click()
        self.assertEqual(self.launches(), [["google-chrome", "--profile-directory=Profile 6", URL]])

    def test_explain_starts_nothing(self):
        self.browsers("google-chrome", "firefox")
        self.write(self.config, CONFIG)
        done = self.run_handler("--explain", URL)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout.decode(), "url: https://example.com/x\n"
                                               "unit: app-org.example.Unknown-4711.scope\n"
                                               "app: org.example.Unknown\n"
                                               "window: -\n"
                                               "title: -\n"
                                               "rule: -\n"
                                               "browser: chrome-main\n"
                                               "command: google-chrome '--profile-directory=Profile 6' "
                                               "https://example.com/x\n")
        self.assertFalse(os.path.exists(self.record))
        self.assertEqual(self.log(), "")


if __name__ == "__main__":
    unittest.main()
