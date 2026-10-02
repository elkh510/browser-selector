"""Discovery: desktop entries, Chromium `Local State`, Firefox `profiles.ini`, snap and flatpak."""

import contextlib
import io
import json
import os
import shlex
import tempfile
import unittest
from unittest import mock

from support import FIXTURES, HandlerCase, bs, write_script

DISCOVERY = os.path.join(FIXTURES, "discovery")
# What --discover prints for the fixture of the desktop of the user.
DESKTOP = """\
[browser brave-home]
name = Brave Web Browser - home
icon = brave-browser
command = /usr/bin/brave-browser-stable --profile-directory="Profile 1"

[browser chromium-work]
name = Chromium Web Browser - Work
icon = chromium
command = chromium --profile-directory=Default

[browser chrome-acme]
name = Google Chrome - acme
icon = google-chrome
command = /usr/bin/google-chrome-stable --profile-directory="Profile 15"

[browser chrome-main]
name = Google Chrome - main
icon = google-chrome
command = /usr/bin/google-chrome-stable --profile-directory="Profile 6"

[browser chrome-side]
name = Google Chrome - Side
icon = google-chrome
command = /usr/bin/google-chrome-stable --profile-directory="Profile 9"

[browser firefox-default]
name = Firefox Web Browser - default
icon = firefox
command = firefox -P default

[browser firefox-default-release]
name = Firefox Web Browser - default-release
icon = firefox
command = firefox -P default-release
"""


def everything(program):
    """A `which` for which every program is installed."""
    return program if os.path.isabs(program) else "/usr/bin/" + program


def fixture_env(name):
    """The environment of a home of tests/fixtures/discovery, no directory of the real system in it."""
    root = os.path.join(DISCOVERY, name)
    return {"HOME": os.path.join(root, "home"), "XDG_DATA_DIRS": os.path.join(root, "share")}


class NoSystemDirectories(unittest.TestCase):
    """The snapd and flatpak directories of the machine the tests run on are never read."""

    snap = flatpak = "/nonexistent"

    def setUp(self):
        for name, path in (("SNAP_APPLICATIONS", self.snap), ("FLATPAK_APPLICATIONS", self.flatpak)):
            patch = mock.patch.object(bs, name, path)
            patch.start()
            self.addCleanup(patch.stop)

    def sections(self, env, which=everything):
        return {browser["section"]: browser for browser in bs.discover(env, which)}


class Desktop(NoSystemDirectories, HandlerCase):
    """The fixture models the desktop of the user: what design-gui.md says it has to find."""

    def setUp(self):
        NoSystemDirectories.setUp(self)
        HandlerCase.setUp(self)
        self.env = fixture_env("desktop")

    def test_discover_prints_the_sections(self):
        code, out, err = self.handle("--discover", which=everything)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, DESKTOP)

    def test_the_output_is_the_browsers_of_a_valid_config(self):
        out = self.handle("--discover", which=everything)[1]
        config, errors = bs.parse_config("[settings]\ndefault = chrome-main\n" + out, everything)
        self.assertEqual(errors, [])
        self.assertEqual(config["browsers"]["chrome-acme"],
                         ["/usr/bin/google-chrome-stable", "--profile-directory=Profile 15"])
        self.assertEqual(config["shown"]["chrome-acme"], ("Google Chrome - acme", "google-chrome"))

    def test_nothing_is_changed_or_started(self):
        before = sorted(os.walk(os.path.join(DISCOVERY, "desktop")))
        self.handle("--discover", which=everything)
        self.assertEqual(sorted(os.walk(os.path.join(DISCOVERY, "desktop"))), before)
        self.assertEqual((self.started, self.window_loads), ([], 0))
        self.assertFalse(os.path.exists(os.path.join(self.env["HOME"], ".local", "state")))

    def test_two_entries_of_one_browser_are_one_browser(self):
        found = self.sections(self.env)
        self.assertEqual(found["chrome-main"]["entries"], ["com.google.Chrome.desktop", "google-chrome.desktop"])
        self.assertEqual(found["brave-home"]["entries"], ["brave-browser.desktop", "com.brave.Browser.desktop"])

    def test_web_apps_and_the_own_entries_do_not_show_up(self):
        text = self.handle("--discover", which=everything)[1]
        for word in ("Google Drive", "app-id", "Browser Selector", "browser-selector", "Files", "nautilus"):
            self.assertNotIn(word, text)

    def test_the_profile_a_browser_opens_by_itself(self):
        current = [name for name, browser in self.sections(self.env).items() if browser["current"]]
        self.assertEqual(current, ["brave-home", "chromium-work", "chrome-acme", "firefox-default-release"])

    def test_a_profile_directory_that_is_not_in_local_state_is_not_a_profile(self):
        # Brave has a Default directory on disk, info_cache knows Profile 1 only
        self.assertTrue(os.path.isdir(os.path.join(self.env["HOME"], ".config/BraveSoftware/Brave-Browser/Default")))
        self.assertEqual([name for name in self.sections(self.env) if name.startswith("brave")], ["brave-home"])

    def test_a_program_that_is_not_installed_is_left_out(self):
        found = self.sections(self.env, lambda program: None if "brave" in program else everything(program))
        self.assertNotIn("brave-home", found)
        self.assertIn("chrome-side", found)

    def test_xdg_config_home(self):
        env = dict(self.env, XDG_CONFIG_HOME=os.path.join(self.tmp, "empty"))
        self.assertEqual([name for name in self.sections(env) if not name.startswith("firefox")],
                         ["brave", "chromium", "chrome"])

    def test_nothing_found(self):
        self.env = {"HOME": self.home, "XDG_DATA_DIRS": os.path.join(self.tmp, "nothing")}
        code, out, err = self.handle("--discover", which=everything)
        self.assertEqual((code, out), (0, ""))
        self.assertIn("no browser found", err)


class Snap(NoSystemDirectories):
    snap = os.path.join(DISCOVERY, "snap", "snapd")

    def test_snap(self):
        found = self.sections(fixture_env("snap"))
        hint = "env BAMF_DESKTOP_FILE_HINT=/var/lib/snapd/desktop/applications/{0}_{0}.desktop /snap/bin/{0}"
        self.assertEqual({name: browser["command"] for name, browser in found.items()}, {
            "chromium-person-1": hint.format("chromium") + " --profile-directory=Default",
            "chromium-work": hint.format("chromium") + ' --profile-directory="Profile 1"',
            "firefox-default": hint.format("firefox") + " -P default",
        })
        self.assertEqual(found["chromium-work"]["icon"], "/snap/chromium/3248/chromium.png")
        self.assertTrue(found["chromium-work"]["current"])

    def test_a_browser_that_is_not_a_snap_reads_the_snap_data_when_it_has_no_other(self):
        # On Ubuntu /usr/bin/firefox and chromium-browser are wrappers around the snap
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("chromium", "firefox"):
                write_script(os.path.join(tmp, "applications", name + ".desktop"),
                             f"[Desktop Entry]\nName={name}\nExec={name} %u\nMimeType=x-scheme-handler/http;\n")
            home = os.path.join(DISCOVERY, "snap", "home")
            with mock.patch.object(bs, "SNAP_APPLICATIONS", "/nonexistent"):
                found = self.sections({"HOME": home, "XDG_DATA_DIRS": tmp})
                self.assertEqual(list(found), ["chromium-not-the-snap", "firefox-not-the-snap"])
                found = self.sections({"HOME": home, "XDG_DATA_DIRS": tmp, "XDG_CONFIG_HOME": tmp})
                self.assertEqual(list(found), ["chromium-person-1", "chromium-work", "firefox-not-the-snap"])

    def test_application_dirs(self):
        env = {"HOME": "/h", "XDG_DATA_DIRS": "/usr/share/ubuntu:/usr/local/share/::/usr/share/:/usr/share"}
        self.assertEqual(bs.application_dirs(env), [
            "/h/.local/share/applications", "/usr/share/ubuntu/applications", "/usr/local/share/applications",
            "/usr/share/applications", self.snap, "/h/.local/share/flatpak/exports/share/applications", self.flatpak])
        self.assertEqual(bs.application_dirs({"HOME": "/h", "XDG_DATA_HOME": "/d"})[:3],
                         ["/d/applications", "/usr/local/share/applications", "/usr/share/applications"])


class Flatpak(NoSystemDirectories):
    flatpak = os.path.join(DISCOVERY, "flatpak", "system")

    def test_flatpak(self):
        found = self.sections(fixture_env("flatpak"))
        run = "/usr/bin/flatpak run --branch=stable --arch=x86_64 --command={} --file-forwarding {}"
        self.assertEqual({name: browser["command"] for name, browser in found.items()}, {
            "brave-home": run.format("brave", "com.brave.Browser") + " --profile-directory=Default",
            "brave-work": run.format("brave", "com.brave.Browser") + ' --profile-directory="Profile 2"',
            "firefox-default-release": run.format("firefox", "org.mozilla.firefox") + " -P default-release",
        })
        self.assertEqual(found["brave-work"]["name"], "Brave - Work")

    def test_a_flatpak_nobody_knows(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_script(os.path.join(tmp, "applications", "org.gnome.Epiphany.desktop"),
                         "[Desktop Entry]\nName=Web\nMimeType=x-scheme-handler/http;\n"
                         "Exec=/usr/bin/flatpak run --command=epiphany org.gnome.Epiphany @@u %U @@\n")
            with mock.patch.object(bs, "FLATPAK_APPLICATIONS", "/nonexistent"):
                found = self.sections({"HOME": tmp, "XDG_DATA_DIRS": tmp})
        self.assertEqual({name: browser["command"] for name, browser in found.items()},
                         {"epiphany": "/usr/bin/flatpak run --command=epiphany org.gnome.Epiphany"})


class Home(NoSystemDirectories):
    """A home made for one test: one browser, and whatever the test puts next to it."""

    def setUp(self):
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = directory.name
        self.env = {"HOME": self.home, "XDG_DATA_DIRS": os.path.join(self.home, "share")}

    def entry(self, name, text, place="share/applications"):
        if "[Desktop Entry]" not in text:
            text = ("[Desktop Entry]\nType=Application\nName=Chrome\n"
                    f"MimeType=text/html;x-scheme-handler/http;\n{text}\n")
        return write_script(os.path.join(self.home, place, name), text)

    def local_state(self, text, directory=".config/google-chrome"):
        if not isinstance(text, str):
            text = json.dumps({"profile": {"info_cache": {key: value if isinstance(value, dict) else {"name": value}
                                                          for key, value in text.items()}}})
        write_script(os.path.join(self.home, directory, "Local State"), text)

    def chrome(self, state=None):
        """The sections for a google-chrome with this Local State: {section: (name, command)}."""
        self.entry("google-chrome.desktop", "Exec=google-chrome %U")
        if state is not None:
            self.local_state(state)
        return {name: (browser["name"], browser["command"]) for name, browser in self.sections(self.env).items()}


class ChromiumProfiles(Home):
    def test_no_local_state(self):
        self.assertEqual(self.chrome(), {"chrome": ("Chrome", "google-chrome")})

    def test_corrupt_local_state(self):
        for text in ("", "not json", "[]", "{}", '{"profile": 5}', '{"profile": {}}', '{"profile": {"info_cache": []}}',
                     '{"profile": {"info_cache": {}}}', '{"profile": {"info_cache": {"Default": "x"}}}', "[" * 200000):
            with self.subTest(text=text[:40]):
                self.assertEqual(self.chrome(text), {"chrome": ("Chrome", "google-chrome")})

    def test_local_state_that_is_not_a_file(self):
        os.makedirs(os.path.join(self.home, ".config/google-chrome/Local State"))
        self.assertEqual(self.chrome(), {"chrome": ("Chrome", "google-chrome")})

    def test_one_profile_gets_the_flag_too(self):
        # The section is named after the profile: it must open that one when a second profile appears
        self.assertEqual(self.chrome({"Default": "Person 1"}),
                         {"chrome-person-1": ("Chrome - Person 1", "google-chrome --profile-directory=Default")})
        self.local_state(json.dumps({"profile": {"info_cache": {"Profile 3": {"name": "Work"}},
                                                 "last_used": "Profile 3"}}))
        self.assertEqual(self.chrome(),
                         {"chrome-work": ("Chrome - Work", 'google-chrome --profile-directory="Profile 3"')})

    def test_shortcut_name_wins(self):
        found = self.chrome({"Default": {"name": "Person 1", "shortcut_name": "Home"},
                             "Profile 1": {"name": "Work", "shortcut_name": ""},
                             "Profile 2": {"shortcut_name": 7, "gaia_name": "x"}})
        self.assertEqual(found, {
            "chrome-home": ("Chrome - Home", "google-chrome --profile-directory=Default"),
            "chrome-work": ("Chrome - Work", 'google-chrome --profile-directory="Profile 1"'),
            "chrome-profile-2": ("Chrome - Profile 2", 'google-chrome --profile-directory="Profile 2"')})

    def test_duplicate_display_names(self):
        found = self.chrome({"Default": "Work", "Profile 1": "Work", "Profile 2": "Home"})
        self.assertEqual(found, {
            "chrome-work-default": ("Chrome - Work (Default)", "google-chrome --profile-directory=Default"),
            "chrome-work-profile-1": ("Chrome - Work (Profile 1)", 'google-chrome --profile-directory="Profile 1"'),
            "chrome-home": ("Chrome - Home", 'google-chrome --profile-directory="Profile 2"')})

    def test_names_that_need_slugging(self):
        found = self.chrome({"Default": "R&D / Ops_team!", "Profile 1": "  Jörg's  ", "Profile 2": "Работа",
                             "Profile 3": "???", "Profile 4": "a\x1b[2J\nb", "Profile 5": "ask"})
        self.assertEqual(list(found), ["chrome-r-d-ops-team", "chrome-jörg-s", "chrome-работа", "chrome",
                                       "chrome-a-2j-b", "chrome-ask"])
        self.assertEqual(found["chrome-r-d-ops-team"][0], "Chrome - R&D / Ops_team!")
        self.assertEqual(found["chrome-jörg-s"][0], "Chrome - Jörg's")
        self.assertEqual(found["chrome-a-2j-b"][0], "Chrome - a [2J b")

    def test_slugs_that_collide(self):
        found = self.chrome({"Default": "My Work", "Profile 1": "my-work", "Profile 2": "MY_WORK"})
        self.assertEqual(list(found), ["chrome-my-work", "chrome-my-work-2", "chrome-my-work-3"])

    def test_a_profile_directory_that_needs_quotes(self):
        found = self.chrome({"Default": "a", 'Pro"file \\1': "b"})
        argv = shlex.split(found["chrome-b"][1])
        self.assertEqual(argv, ["google-chrome", '--profile-directory=Pro"file \\1'])

    def test_every_family(self):
        cases = {"brave-browser": "BraveSoftware/Brave-Browser", "chromium-browser": "chromium",
                 "microsoft-edge-stable": "microsoft-edge", "vivaldi-stable": "vivaldi"}
        for program, directory in cases.items():
            self.entry(program + ".desktop", f"Exec=/usr/bin/{program} %U")
            self.local_state({"Default": "One", "Profile 1": "Two"}, ".config/" + directory)
        self.assertEqual(sorted(self.sections(self.env)), ["brave-one", "brave-two", "chromium-one", "chromium-two",
                                                           "edge-one", "edge-two", "vivaldi-one", "vivaldi-two"])


class FirefoxProfiles(Home):
    def firefox(self, text=None):
        self.entry("firefox.desktop", "Exec=firefox %u")
        if text is not None:
            write_script(os.path.join(self.home, ".mozilla/firefox/profiles.ini"), text)
        return {name: (browser["command"], browser["current"]) for name, browser in self.sections(self.env).items()}

    def test_no_profiles_ini(self):
        self.assertEqual(self.firefox(), {"firefox": ("firefox", True)})

    def test_corrupt_profiles_ini(self):
        for text in ("", "Name=default\n", "[General]\nVersion=2\n", "[Profile0]\nPath=x\n", "\0\xff[["):
            with self.subTest(text=text):
                self.assertEqual(self.firefox(text), {"firefox": ("firefox", True)})

    def test_one_section_per_profile(self):
        found = self.firefox("[Profile0]\nName=default\nDefault=1\n[Profile1]\nName=Work stuff\n")
        self.assertEqual(found, {"firefox-default": ("firefox -P default", True),
                                 "firefox-work-stuff": ('firefox -P "Work stuff"', False)})

    def test_the_profile_of_the_installation_wins_over_default_1(self):
        found = self.firefox("[Install4F96]\nDefault=b.release\n[Profile0]\nName=old\nPath=a.old\nDefault=1\n"
                             "[Profile1]\nName=release\nPath=b.release\n")
        self.assertEqual({name: current for name, (_, current) in found.items()},
                         {"firefox-old": False, "firefox-release": True})


class DesktopEntries(Home):
    def commands(self):
        return {name: browser["command"] for name, browser in self.sections(self.env).items()}

    def test_field_codes_and_a_quoted_exec(self):
        self.entry("my.desktop", r'Exec="/opt/My Browser/browser" --class "two words" --title=My\sBrowser '
                                 r'%u %i %c %k --cost=100%% "--path=C:\\\\x" --money=\\$5')
        browser = self.sections(self.env)["browser"]
        self.assertEqual(shlex.split(browser["command"]),
                         ["/opt/My Browser/browser", "--class", "two words", "--title=My", "Browser", "--cost=100%",
                          "--path=C:\\x", "--money=$5"])
        self.assertEqual(browser["command"], '"/opt/My Browser/browser" --class "two words" --title=My Browser '
                                             '--cost=100% --path="C:\\\\x" --money="$5"')

    def test_every_field_code_goes(self):
        for code in "fFuUdDnNickvm":
            with self.subTest(code=code):
                self.assertEqual(bs.exec_argv(f"browser %{code} --new-tab"), ["browser", "--new-tab"])
        self.assertEqual(bs.exec_argv("browser --icon=%i"), ["browser", "--icon="])
        self.assertEqual(bs.exec_argv("browser %%u %"), ["browser", "%u", "%"])

    def test_split_exec(self):
        cases = {
            "firefox %u": ["firefox", "%u"],
            '"/opt/My Browser/b" --x': ["/opt/My Browser/b", "--x"],
            r'"a \" b" "c \$HOME \` \\ d"': ['a " b', "c $HOME ` \\ d"],
            r'"a\nb"': ["a\\nb"],
            "sh -c 'x \"$HOME\" \\y'": ["sh", "-c", 'x "$HOME" \\y'],
            r"a\ b c": ["a b", "c"],
            '  a   "" \'\'  ': ["a", "", ""],
            'pre"fix"\'ed\'': ["prefixed"],
            "": [],
        }
        for text, argv in cases.items():
            with self.subTest(text=text):
                self.assertEqual([word for word, plain in bs.split_exec(text)], argv)
        # A word is plain when no quote and no backslash made it
        self.assertEqual(bs.split_exec("a --b=c \"d\" e'f' g\\ h"),
                         [("a", True), ("--b=c", True), ("d", False), ("ef", False), ("g h", False)])
        for text in ('"open', "'open", 'a "b\\"'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                bs.split_exec(text)

    def test_exec_that_cannot_be_split(self):
        self.entry("broken.desktop", 'Exec=browser "unclosed %u')
        self.entry("empty.desktop", "Exec=%u")
        self.entry("none.desktop", "Icon=x")
        self.assertEqual(self.commands(), {})

    def test_what_is_not_a_browser(self):
        self.entry("mail.desktop", "[Desktop Entry]\nName=Mail\nExec=mail %u\nMimeType=x-scheme-handler/mailto;\n")
        self.entry("https-only.desktop", "[Desktop Entry]\nName=H\nExec=h %u\nMimeType=x-scheme-handler/https;\n")
        self.entry("hidden.desktop", "Exec=hidden %u\nHidden=true")
        self.entry("link.desktop", "[Desktop Entry]\nType=Link\nURL=http://x\nMimeType=x-scheme-handler/http;\n")
        self.entry("no-exec.desktop", "Icon=x")
        self.entry("tryexec.desktop", "Exec=sh -c browser %u\nTryExec=no-such-program")
        self.entry("notes.txt", "Exec=notes %u")
        self.entry("action.desktop", "[Desktop Entry]\nName=A\nExec=a\n[Desktop Action x]\nExec=a %u\n"
                                     "MimeType=x-scheme-handler/http;\n")
        self.assertEqual(self.sections(self.env, lambda p: None if p == "no-such-program" else p), {})

    def test_entries_that_lead_back_to_the_handler(self):
        self.entry("opener.desktop", "Exec=xdg-open %u")
        self.entry("wrapper.desktop", "Exec=env X=1 gio open %u")
        self.entry("self.desktop", f"Exec=python3 {bs.HANDLER} %u")
        self.entry("renamed.desktop", "Exec=my-handler %u")
        self.entry("browser-selector.desktop", "Exec=other %u")
        self.assertEqual(self.sections(self.env, lambda p: bs.HANDLER if p == "my-handler" else p), {})

    def test_the_entry_of_the_user_stands_for_the_one_of_the_system(self):
        self.entry("firefox.desktop", "Exec=firefox %u")
        self.entry("firefox.desktop", "Exec=firefox --private-window %u", ".local/share/applications")
        self.assertEqual(self.commands(), {"firefox": "firefox --private-window"})
        self.entry("firefox.desktop", "Exec=firefox %u\nHidden=true", ".local/share/applications")
        self.assertEqual(self.commands(), {})

    def test_name_and_icon(self):
        self.entry("a.desktop", "[Desktop Entry]\nName[de]=Netz\nName=Web \x07 Browser\nIcon=/opt/a/icon.png\n"
                                "Exec=a-browser %u\nMimeType=x-scheme-handler/http;\n# Name=Comment\nName=Second\n")
        self.entry("b.desktop", "[Desktop Entry]\nExec=/opt/b/b-browser %u\nMimeType=x-scheme-handler/http;\n")
        found = self.sections(self.env)
        self.assertEqual((found["a-browser"]["name"], found["a-browser"]["icon"]), ("Web Browser", "/opt/a/icon.png"))
        self.assertEqual((found["b-browser"]["name"], found["b-browser"]["icon"]), ("b-browser", ""))
        self.assertNotIn("icon", bs.browser_items(found["b-browser"]))

    def test_same_program_under_two_paths(self):
        program = write_script(os.path.join(self.home, "bin", "real-browser"), "#!/bin/sh\n")
        os.symlink(program, os.path.join(self.home, "bin", "browser"))
        self.entry("one.desktop", f"Exec={program} %U")
        self.entry("two.desktop", "Exec=browser %U")
        found = self.sections(self.env, lambda p: p if os.path.isabs(p) else os.path.join(self.home, "bin", p))
        self.assertEqual([browser["entries"] for browser in found.values()], [["one.desktop", "two.desktop"]])

    def test_a_desktop_file_that_is_a_fifo_or_a_directory(self):
        self.entry("ok.desktop", "Exec=ok %u")
        os.mkfifo(os.path.join(self.home, "share/applications/fifo.desktop"))
        os.mkdir(os.path.join(self.home, "share/applications/dir.desktop"))
        self.assertEqual(list(self.commands()), ["ok"])


LINE_BREAKS = ("\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", " ", " ")


class ForeignData(Home):
    """What a desktop entry, a `Local State` or a `profiles.ini` says is data of somebody else:
    it never writes a line of the config, and one odd piece never stops the rest."""

    EVIL = "x\rcommand = firefox --attacker-chosen-program\r[browser tail]"

    def found(self):
        """(sections as {name: command}, notes)"""
        notes = []
        found = bs.discover(self.env, everything, notes.append)
        return {browser["section"]: browser["command"] for browser in found}, notes

    def test_a_profile_directory_cannot_write_lines_into_the_config(self):
        self.entry("google-chrome.desktop", "Exec=google-chrome %U")
        self.local_state(json.dumps({"profile": {"info_cache": {self.EVIL: {}}, "last_used": self.EVIL}}))
        found, notes = self.found()
        self.assertEqual(found, {"chrome": "google-chrome"})
        self.assertEqual(len(notes), 1)
        self.assertIn("left out", notes[0])
        self.assertTrue(notes[0].isprintable(), notes)
        # The config of a new install, written and read back: it starts what the entry says
        path = os.path.join(self.home, "config.ini")
        model = bs.with_discovered(bs.empty_model(), bs.discover(self.env, everything))[0]
        self.assertEqual(bs.save_model(path, model), [])
        self.assertEqual(bs.load_config(path)[0]["browsers"], {"chrome": ["google-chrome"]})

    def test_a_profile_directory_with_a_line_break_is_left_out(self):
        for char in LINE_BREAKS + ("\n", "\x00", "\x1b", "\ud800"):
            with self.subTest(char=repr(char)):
                self.assertEqual(self.chrome({f"a{char}b": "Odd", "Default": "Good"}),
                                 {"chrome-good": ("Chrome - Good", "google-chrome --profile-directory=Default")})

    def test_one_odd_profile_does_not_stop_the_rest(self):
        for directory in ("a\n#b", "a\x00b", "a\ud800b", "", "{url}", "My {url} profile"):
            with self.subTest(directory=repr(directory)):
                self.chrome({directory: "Odd", "Default": "Good"})
                found, notes = self.found()
                self.assertEqual(found, {"chrome-good": "google-chrome --profile-directory=Default"})
                self.assertEqual(len(notes), 1)

    def test_the_directory_as_a_name_is_one_line(self):
        self.assertEqual(self.chrome({"My  Dir": {}, "Default": "Good"})["chrome-my-dir"],
                         ("Chrome - My Dir", 'google-chrome --profile-directory="My  Dir"'))

    def main(self, *argv, encoding="utf-8"):
        out = io.TextIOWrapper(io.BytesIO(), encoding=encoding)
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(bs, "system_default", return_value=None):
            code = bs.main(list(argv), env=self.env, which=everything)
        out.flush()
        return code, out.buffer.getvalue().decode(encoding), err.getvalue()

    def test_discover_and_init_config_go_on_without_the_odd_one(self):
        self.chrome({"a\ud800b": "Odd", "a\n#b": "Odd too", "Default": "Good"})
        code, out, err = self.main("--discover")
        self.assertEqual((code, out), (0, "[browser chrome-good]\nname = Chrome - Good\n"
                                          "command = google-chrome --profile-directory=Default\n"))
        self.assertEqual(err.count("left out"), 2)
        path = os.path.join(self.home, "new", "config.ini")
        code, out, err = self.main("--config", path, "--init-config")
        self.assertEqual(code, 0, err)
        self.assertEqual(list(bs.load_config(path)[0]["browsers"]), ["chrome-good"])

    def test_discover_prints_to_a_terminal_that_is_not_utf8(self):
        self.chrome({"Default": "Работа"})
        code, out, err = self.main("--discover", encoding="ascii")
        self.assertEqual(code, 0)
        self.assertIn("[browser chrome-", out)

    def test_an_entry_with_a_line_break_in_an_argument_is_left_out(self):
        self.entry("odd.desktop", r'Exec=odd-browser "a\n#b" %u')
        self.entry("cr.desktop", "Exec=cr-browser a\rb %u")
        self.entry("ok.desktop", "Exec=ok-browser %u")
        found, notes = self.found()
        self.assertEqual(found, {"ok-browser": "ok-browser"})
        self.assertEqual(len(notes), 2)

    def test_only_a_line_feed_ends_a_line_of_a_desktop_entry(self):
        # GLib reads the second Exec: the first one is the tail of the comment
        for char in LINE_BREAKS:
            with self.subTest(char=repr(char)):
                self.entry("a.desktop", "[Desktop Entry]\nType=Application\nName=A\n"
                                        f"Comment=a web browser{char}Exec=firefox --smuggled-command %u\n"
                                        "Exec=real-browser %u\nMimeType=x-scheme-handler/http;\n")
                self.assertEqual(self.found()[0], {"real-browser": "real-browser"})

    def test_a_desktop_entry_with_dos_line_ends(self):
        self.entry("a.desktop", "[Desktop Entry]\r\nName=DOS\r\nExec=dos-browser %u\r\n"
                                "MimeType=x-scheme-handler/http;\r\n")
        found = self.sections(self.env)
        self.assertEqual((found["dos-browser"]["name"], found["dos-browser"]["command"]), ("DOS", "dos-browser"))

    def test_a_field_code_at_the_end_of_a_word_is_where_the_link_goes(self):
        self.assertEqual(bs.exec_argv("firefox --new-tab --url=%u"), ["firefox", "--new-tab", "--url={url}"])
        self.assertEqual(bs.exec_argv("b --open=%U --x %i"), ["b", "--open={url}", "--x"])
        self.assertEqual(bs.exec_argv('firefox "%" x 100%x'), ["firefox", "%", "x", "100%x"])
        self.entry("tab.desktop", "Exec=firefox --new-tab --url=%u")
        found, notes = self.found()
        self.assertEqual((found, notes), ({"firefox": "firefox --new-tab --url={url}"}, []))
        self.assertEqual(bs.build_command(bs.shlex.split(found["firefox"]), "https://x/"),
                         ["firefox", "--new-tab", "--url=https://x/"])

    def test_a_field_code_inside_a_quoted_argument_leaves_the_entry_out(self):
        # The link would land in the text of a shell script: the entry is not for this tool
        for value in ('sh -c "exec chromium --foo %u"', "sh -c 'exec chromium %U'", 'b "--url=%u"',
                      r"sh -c exec\ chromium\ %u"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bs.exec_argv(value)
        self.entry("shell.desktop", 'Exec=sh -c "exec chromium --foo %u"')
        self.entry("ok.desktop", "Exec=ok-browser %u")
        found, notes = self.found()
        self.assertEqual(found, {"ok-browser": "ok-browser"})
        self.assertEqual(len(notes), 1)
        self.assertIn("shell.desktop", notes[0])

    def test_a_placeholder_in_foreign_data_is_not_the_placeholder(self):
        self.entry("p.desktop", "Exec=p-browser --name={url} %u")
        self.entry("firefox.desktop", "Exec=firefox %u")
        write_script(os.path.join(self.home, ".mozilla/firefox/profiles.ini"),
                     "[Profile0]\nName=My Work {url}\n[Profile1]\nName=plain\n")
        found, notes = self.found()
        self.assertEqual(found, {"firefox-plain": "firefox -P plain"})
        self.assertEqual(len(notes), 2)

    def test_firefox_gets_the_name_as_it_is(self):
        self.entry("firefox.desktop", "Exec=firefox %u")
        write_script(os.path.join(self.home, ".mozilla/firefox/profiles.ini"),
                     "[Profile0]\nName=My  Work\n[Profile1]\nName=a\x1bb\n[Profile2]\nName=a\rb\n")
        found = self.sections(self.env)
        self.assertEqual(list(found), ["firefox-my-work"])
        self.assertEqual((found["firefox-my-work"]["name"], found["firefox-my-work"]["command"]),
                         ("Chrome - My Work", 'firefox -P "My  Work"'))

    def test_a_link_is_not_an_application(self):
        self.entry("link.desktop", "[Desktop Entry]\nType=Link\nName=L\nExec=link-browser %u\n"
                                   "MimeType=x-scheme-handler/http;\n")
        self.assertEqual(self.found()[0], {})

    def test_a_program_under_snap_reads_the_data_of_the_snap(self):
        self.entry("chromium.desktop", "Exec=/snap/bin/chromium %U")
        self.local_state({"Default": "Config"}, ".config/chromium")
        self.local_state({"Default": "Snap"}, "snap/chromium/common/chromium")
        self.assertEqual(list(self.found()[0]), ["chromium-snap"])

    def test_a_browser_cannot_be_named_ask(self):
        self.entry("ask.desktop", "Exec=ask %u")
        self.assertEqual(self.found()[0], {"ask-2": "ask"})


class Words(unittest.TestCase):
    def test_slug(self):
        cases = {"Google Chrome": "google-chrome", "acme": "acme", "  Side ": "side",
                 "a--b__c": "a-b-c", "!!!": "", "": ""}
        for text, slug in cases.items():
            self.assertEqual(bs.slug(text), slug)

    def test_unique_name(self):
        self.assertEqual(bs.unique_name("chrome", set()), "chrome")
        self.assertEqual(bs.unique_name("chrome", {"chrome", "chrome-2"}), "chrome-3")
        self.assertEqual(bs.unique_name("ask", {"ask"}), "ask-2")

    def test_join_command_is_read_back_by_shlex(self):
        for argv in (["firefox"], ["google-chrome", "--profile-directory=Profile 6"], ["a b", "c"], ["x", ""],
                     ["x", 'say "hi"', "back\\slash", "it's"], ["env", "A=b c", "--flag=", "{url}"],
                     ["x", "-P", "a b"]):
            with self.subTest(argv=argv):
                self.assertEqual(shlex.split(bs.join_command(argv)), argv)

    def test_join_command_writes_like_the_example_config(self):
        self.assertEqual(bs.join_command(["google-chrome", "--profile-directory=Profile 6"]),
                         'google-chrome --profile-directory="Profile 6"')
        self.assertEqual(bs.join_command(["brave-browser", "--profile-directory=Default", "{url}"]),
                         "brave-browser --profile-directory=Default {url}")


if __name__ == "__main__":
    unittest.main()
