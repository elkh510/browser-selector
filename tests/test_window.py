"""window and title: parsing of xprop output and the reader that runs xprop."""

import json
import os
import sys
import tempfile
import time
import unittest

from support import bs, read, write_script

SLACK_WINDOW = """\
WM_CLASS(STRING) = "slack", "Slack"
_NET_WM_NAME(UTF8_STRING) = "Threads - Acme - Slack"
WM_NAME(STRING) = "Threads - Acme - Slack"
_NET_WM_PID(CARDINAL) = 2382881
"""
ACTIVE = "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x2e00020\n"

# A fake xprop: writes down how it was called, then does what the `mode` file
# says: print the fixtures, print them and fail, or hang.
FAKE_XPROP = """\
#!{python}
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "calls"), "a") as calls:
    calls.write(json.dumps({{"args": sys.argv[1:], "LC_ALL": os.environ.get("LC_ALL"),
                             "DISPLAY": os.environ.get("DISPLAY")}}) + "\\n")
mode = open(os.path.join(here, "mode")).read()
if mode == "hang":
    time.sleep(30)
name = "root" if sys.argv[1] == "-root" else "window"
with open(os.path.join(here, name), "rb") as fixture:
    sys.stdout.buffer.write(fixture.read())
sys.exit(1 if mode == "fail" else 0)
"""


class ActiveWindow(unittest.TestCase):
    def test_window_id(self):
        self.assertEqual(bs.parse_active_window(ACTIVE), "0x2e00020")

    def test_zero_is_no_window(self):
        self.assertIsNone(bs.parse_active_window("_NET_ACTIVE_WINDOW(WINDOW): window id # 0x0\n"))

    def test_not_found(self):
        self.assertIsNone(bs.parse_active_window("_NET_ACTIVE_WINDOW:  not found.\n"))

    def test_empty_output(self):
        self.assertIsNone(bs.parse_active_window(""))


class Window(unittest.TestCase):
    def test_class_and_title(self):
        self.assertEqual(bs.parse_window(SLACK_WINDOW), (["slack", "Slack"], "Threads - Acme - Slack"))

    def test_escaped_quotes_in_the_title(self):
        text = ('WM_CLASS(STRING) = "code", "Code"\n'
                '_NET_WM_NAME(UTF8_STRING) = "say \\"hi\\", then \\\\ - notes.txt"\n')
        self.assertEqual(bs.parse_window(text), (["code", "Code"], 'say "hi", then \\ - notes.txt'))

    def test_non_ascii_title(self):
        text = ('WM_CLASS(STRING) = "clickup", "ClickUp"\n'
                '_NET_WM_NAME(UTF8_STRING) = "Задачи ✓ | Initech"\n')
        self.assertEqual(bs.parse_window(text), (["clickup", "ClickUp"], "Задачи ✓ | Initech"))

    def test_octal_escapes_of_a_latin1_title(self):
        text = 'WM_CLASS(STRING) = "xterm", "XTerm"\nWM_NAME(STRING) = "caf\\351\\tmenu"\n'
        self.assertEqual(bs.parse_window(text), (["xterm", "XTerm"], "café\tmenu"))

    def test_octal_escapes_of_a_utf8_title(self):
        # What xprop prints for "Задачи | Initech" when the C.UTF-8 locale is missing
        escaped = "".join(f"\\{byte:03o}" for byte in "Задачи".encode())
        text = f'WM_CLASS(STRING) = "clickup", "ClickUp"\n_NET_WM_NAME(UTF8_STRING) = "{escaped} | Initech"\n'
        self.assertEqual(bs.parse_window(text), (["clickup", "ClickUp"], "Задачи | Initech"))

    def test_an_escaped_backslash_before_digits_is_not_an_octal_escape(self):
        text = 'WM_CLASS(STRING) = "xterm", "XTerm"\nWM_NAME(STRING) = "C:\\\\101\\\\320\\\\227"\n'
        self.assertEqual(bs.parse_window(text), (["xterm", "XTerm"], "C:\\101\\320\\227"))

    def test_net_wm_name_goes_before_wm_name(self):
        text = ('WM_CLASS(STRING) = "slack", "Slack"\n'
                'WM_NAME(STRING) = "old name"\n'
                '_NET_WM_NAME(UTF8_STRING) = "Threads - Acme - Slack"\n')
        self.assertEqual(bs.parse_window(text)[1], "Threads - Acme - Slack")

    def test_wm_name_when_net_wm_name_is_not_found(self):
        text = ('WM_CLASS(STRING) = "xterm", "XTerm"\n'
                '_NET_WM_NAME:  not found.\n'
                'WM_NAME(STRING) = "user@host: ~"\n'
                '_NET_WM_PID:  not found.\n')
        self.assertEqual(bs.parse_window(text), (["xterm", "XTerm"], "user@host: ~"))

    def test_wm_name_when_net_wm_name_is_empty(self):
        text = 'WM_CLASS(STRING) = "xterm", "XTerm"\n_NET_WM_NAME(UTF8_STRING) = ""\nWM_NAME(STRING) = "shell"\n'
        self.assertEqual(bs.parse_window(text), (["xterm", "XTerm"], "shell"))

    def test_no_title_at_all(self):
        text = 'WM_CLASS(STRING) = "xterm", "XTerm"\n_NET_WM_NAME:  not found.\nWM_NAME:  not found.\n'
        self.assertEqual(bs.parse_window(text), (["xterm", "XTerm"], ""))

    def test_single_element_class(self):
        text = 'WM_CLASS(STRING) = "xterm"\n_NET_WM_NAME(UTF8_STRING) = "shell"\n'
        self.assertEqual(bs.parse_window(text), (["xterm"], "shell"))

    def test_empty_parts_of_the_class_are_dropped(self):
        self.assertEqual(bs.parse_window('WM_CLASS(STRING) = "", "Slack"\n'), (["Slack"], ""))
        self.assertIsNone(bs.parse_window('WM_CLASS(STRING) = "", ""\n'))

    def test_unterminated_output(self):
        text = 'WM_CLASS(STRING) = "slack", "Slack"\n_NET_WM_NAME(UTF8_STRING) = "Threads - Acm'
        self.assertEqual(bs.parse_window(text), (["slack", "Slack"], ""))
        self.assertEqual(bs.parse_window('WM_CLASS(STRING) = "slack", "Sla'), (["slack"], ""))
        self.assertIsNone(bs.parse_window('WM_CLASS(STRING) = "sla'))
        self.assertIsNone(bs.parse_window("WM_CLASS(STRING) = "))
        self.assertEqual(bs.parse_window('WM_CLASS(STRING) = "slack", "Slack"\nWM_NAME(STRING) = "a\\'),
                         (["slack", "Slack"], ""))

    def test_a_window_without_a_class_is_no_window(self):
        text = 'WM_CLASS:  not found.\n_NET_WM_NAME(UTF8_STRING) = "Threads - Acme - Slack"\n'
        self.assertIsNone(bs.parse_window(text))

    def test_empty_output(self):
        self.assertIsNone(bs.parse_window(""))


class ReadWindow(unittest.TestCase):
    """The real reader against a fake xprop, the only program on its PATH."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.bin = directory.name
        write_script(os.path.join(self.bin, "xprop"), FAKE_XPROP.format(python=sys.executable))
        self.env = {"DISPLAY": ":99", "PATH": self.bin, "LC_ALL": "C"}
        self.fake(ACTIVE, SLACK_WINDOW)

    def fake(self, root, window, mode="ok"):
        for name, text in (("root", root), ("window", window), ("mode", mode)):
            with open(os.path.join(self.bin, name), "w", encoding="utf-8") as file:
                file.write(text)

    def calls(self):
        return [json.loads(line) for line in read(os.path.join(self.bin, "calls")).splitlines()]

    def test_reads_the_focused_window(self):
        self.assertEqual(bs.read_window(self.env), (["slack", "Slack"], "Threads - Acme - Slack"))

    def test_the_two_xprop_calls(self):
        bs.read_window(self.env)
        self.assertEqual([call["args"] for call in self.calls()],
                         [["-root", "_NET_ACTIVE_WINDOW"],
                          ["-id", "0x2e00020", "WM_CLASS", "_NET_WM_NAME", "WM_NAME", "_NET_WM_PID"]])

    def test_xprop_runs_with_a_utf8_locale_and_the_display(self):
        bs.read_window(self.env)
        self.assertEqual([(call["LC_ALL"], call["DISPLAY"]) for call in self.calls()], [("C.UTF-8", ":99")] * 2)
        self.assertEqual(self.env["LC_ALL"], "C")

    def test_non_ascii_title(self):
        self.fake(ACTIVE, 'WM_CLASS(STRING) = "clickup", "ClickUp"\n_NET_WM_NAME(UTF8_STRING) = "Задачи | Initech"\n')
        self.assertEqual(bs.read_window(self.env), (["clickup", "ClickUp"], "Задачи | Initech"))

    def test_net_wm_name_goes_before_wm_name(self):
        self.fake(ACTIVE, 'WM_CLASS(STRING) = "a", "A"\nWM_NAME(STRING) = "old"\n_NET_WM_NAME(UTF8_STRING) = "new"\n')
        self.assertEqual(bs.read_window(self.env), (["a", "A"], "new"))

    def test_no_active_window_asks_nothing_more(self):
        self.fake("_NET_ACTIVE_WINDOW(WINDOW): window id # 0x0\n", SLACK_WINDOW)
        self.assertIsNone(bs.read_window(self.env))
        self.assertEqual(len(self.calls()), 1)

    def test_no_display_is_no_window_and_xprop_is_not_run(self):
        for env in ({"PATH": self.bin}, {"PATH": self.bin, "DISPLAY": ""}):
            with self.subTest(env=env):
                self.assertIsNone(bs.read_window(env))
        self.assertEqual(self.calls(), [])

    def test_xprop_that_fails_is_no_window(self):
        self.fake(ACTIVE, SLACK_WINDOW, mode="fail")
        self.assertIsNone(bs.read_window(self.env))
        self.assertEqual(len(self.calls()), 1)

    def test_xprop_that_hangs_is_no_window_after_a_second(self):
        self.fake(ACTIVE, SLACK_WINDOW, mode="hang")
        started = time.monotonic()
        self.assertIsNone(bs.read_window(self.env))
        self.assertLess(time.monotonic() - started, 5)

    def test_no_xprop_is_no_window(self):
        os.remove(os.path.join(self.bin, "xprop"))
        self.assertIsNone(bs.read_window(self.env))


if __name__ == "__main__":
    unittest.main()
