"""install.sh and uninstall.sh in a throwaway home.

Their PATH holds links to the tools they need, a fake xdg-settings and fake
browsers, and nothing else: no real browser can start and the default browser
of the machine cannot change.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, bs, read, write_script

TOOLS = ("bash", "cat", "chmod", "mv", "mktemp", "ln", "rm", "mkdir", "tail", "dirname", "readlink", "rmdir", "grep")
# `get` prints the file `default`, `set` changes it for an entry named in the file `known`.
XDG_SETTINGS = """\
#!/bin/bash
echo "$*" >> "$FAKE/calls"
case "$1 $2" in
    "get default-web-browser") cat "$FAKE/default" 2>/dev/null ;;
    "set default-web-browser")
        grep -qxF "$3" "$FAKE/known" || exit 2
        # Like xdg-settings 1.1.3: the first word of Exec is the program, a quote in front of it included
        file="${XDG_DATA_HOME:-$HOME/.local/share}/applications/$3"
        [ ! -f "$file" ] || ! grep -q '^Exec="' "$file" || exit 2
        echo "$3" > "$FAKE/default" ;;
    *) exit 1 ;;
esac
"""
BROWSER = "#!/bin/bash\necho \"$0 $*\" >> \"$FAKE/started\"\n"
ENTRY = ("[Desktop Entry]\nType=Application\nName={0}\nExec={0} %u\nIcon={0}\n"
         "MimeType=text/html;x-scheme-handler/http;\n")
MINE = "[settings]\ndefault = mine\n\n[browser mine]\ncommand = firefox -P mine\n"


@unittest.skipUnless(os.access("/usr/bin/python3", os.X_OK), "install.sh needs /usr/bin/python3")
class Install(unittest.TestCase):
    home_name = "home"

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = directory.name
        self.home = os.path.join(self.tmp, self.home_name)
        self.fake = os.path.join(self.tmp, "fake")
        self.tools = os.path.join(self.tmp, "tools")
        os.makedirs(self.home)
        os.makedirs(self.tools)
        for tool in TOOLS:
            os.symlink(shutil.which(tool), os.path.join(self.tools, tool))
        write_script(os.path.join(self.tools, "xdg-settings"), XDG_SETTINGS)
        for browser in ("firefox", "google-chrome"):
            write_script(os.path.join(self.tools, browser), BROWSER)
            write_script(os.path.join(self.tmp, "share", "applications", browser + ".desktop"), ENTRY.format(browser))
        write_script(os.path.join(self.fake, "default"), "firefox.desktop\n")
        write_script(os.path.join(self.fake, "known"),
                     "firefox.desktop\ngoogle-chrome.desktop\nbrowser-selector.desktop\n")
        self.env = {"HOME": self.home, "PATH": self.tools, "FAKE": self.fake,
                    "XDG_DATA_DIRS": os.path.join(self.tmp, "share"), "PYTHONDONTWRITEBYTECODE": "1"}
        self.lib = os.path.join(self.home, ".local/share/browser-selector")
        self.apps = os.path.join(self.home, ".local/share/applications")
        self.bin = os.path.join(self.home, ".local/bin/browser-selector")
        self.config = os.path.join(self.home, ".config/browser-selector/config.ini")
        self.previous = os.path.join(self.home, ".local/state/browser-selector/previous-default")

    def run_script(self, *argv, **env):
        # In the throwaway directory: a script that takes a relative path lands there, not in the checkout
        done = subprocess.run(argv, env={**self.env, **env}, timeout=120, stdin=subprocess.DEVNULL, cwd=self.tmp,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        return done.returncode, done.stdout, done.stderr

    def install(self, *args):
        return self.run_script("bash", os.path.join(ROOT, "install.sh"), *args)

    def uninstall(self, *args):
        return self.run_script("bash", os.path.join(ROOT, "uninstall.sh"), *args)

    def installed(self):
        """Every file and link under the home, relative to it."""
        found = []
        for directory, _, files in os.walk(self.home):
            found += [os.path.relpath(os.path.join(directory, file), self.home) for file in files]
        return sorted(found)

    def default(self):
        return read(os.path.join(self.fake, "default")).strip()

    def exec_line(self, entry="browser-selector.desktop"):
        return [line for line in read(os.path.join(self.apps, entry)).splitlines() if line.startswith("Exec=")][0][5:]

    def tearDown(self):
        self.assertFalse(os.path.exists(os.path.join(self.fake, "started")), "a browser was started")


class Layout(Install):
    def test_what_lands_where(self):
        code, out, err = self.install()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.installed(), [
            ".config/browser-selector/config.ini", ".local/bin/browser-selector",
            ".local/share/applications/browser-selector.desktop",
            ".local/share/browser-selector/browser_selector.py",
            ".local/share/browser-selector/browser_selector_gui.py"])
        self.assertEqual(read(os.path.join(self.lib, "browser_selector_gui.py")),
                         read(os.path.join(ROOT, "browser_selector_gui.py")))
        self.assertTrue(os.path.islink(self.bin))
        self.assertEqual(os.readlink(self.bin), os.path.join(self.lib, "browser_selector.py"))
        self.assertEqual(os.stat(self.bin).st_mode & 0o777, 0o755)

    def test_the_installed_handler_runs_isolated(self):
        self.install()
        source = read(os.path.join(ROOT, "browser_selector.py")).split("\n", 1)
        installed = read(os.path.join(self.lib, "browser_selector.py")).split("\n", 1)
        self.assertEqual(source[0], "#!/usr/bin/env python3")
        self.assertEqual(installed, ["#!/usr/bin/python3 -I", source[1]])

    def test_the_environment_of_the_app_does_not_reach_the_handler(self):
        self.install()
        # What a click in an app with a virtualenv of its own brings along
        poison = os.path.join(self.tmp, "poison")
        for module in ("configparser", "shlex", "json", "sitecustomize"):
            write_script(os.path.join(poison, module + ".py"),
                         "raise SystemExit('the PYTHONPATH of the app was used')\n")
        write_script(os.path.join(poison, "python3"), "#!/bin/sh\necho 'the python of the app was used' >&2\nexit 9\n")
        code, out, err = self.run_script(self.bin, "--check", PYTHONPATH=poison, PYTHONHOME="/nonexistent",
                                         PATH=poison + ":" + self.tools, PYTHONSTARTUP=os.path.join(poison, "json.py"))
        self.assertEqual((code, err), (0, ""))
        # The checkout started by hand has no such protection, which is why the shebang is rewritten
        code, out, err = self.run_script("/usr/bin/python3", os.path.join(ROOT, "browser_selector.py"), "--version",
                                         PYTHONPATH=poison)
        self.assertIn("the PYTHONPATH of the app was used", err)

    def test_the_handler_finds_its_windows_next_to_its_real_file(self):
        self.install()
        other = os.path.join(self.tmp, "other")
        write_script(os.path.join(other, "browser_selector_gui.py"), "raise SystemExit('not the installed windows')\n")
        # A display nobody answers on: the module is loaded, no window can come up
        code, out, err = self.run_script(self.bin, "--settings", DISPLAY="/nonexistent/x:0", PYTHONPATH=other)
        self.assertEqual(code, 1)
        self.assertRegex(err, "the settings window cannot be shown: "
                              "(the display cannot be opened|GTK 4 and libadwaita are needed)")
        self.assertNotIn("No module named", err)
        self.assertNotIn("not the installed windows", err)

    def test_the_launcher_of_the_package_starts_the_handler(self):
        # Without site (-S) and as an imported module: the windows still find PyGObject
        lib = os.path.join(self.tmp, "package")
        os.makedirs(lib)
        for name in ("browser_selector.py", "browser_selector_gui.py", "packaging/launcher"):
            shutil.copy(os.path.join(ROOT, name), lib)
        launcher = os.path.join(lib, "launcher")
        self.assertEqual(read(launcher).splitlines()[0], "#!/usr/bin/python3 -IS")
        code, out, err = self.run_script(launcher, "--version")
        self.assertEqual((code, out, err), (0, f"browser-selector {bs.VERSION}\n", ""))
        code, out, err = self.run_script(launcher, DISPLAY="/nonexistent/x:0")
        self.assertEqual(code, 1)
        self.assertRegex(err, "the settings window cannot be shown: "
                              "(the display cannot be opened|GTK 4 and libadwaita are needed)")
        self.assertNotIn("No module named", err)

    def test_desktop_entries(self):
        self.install()
        self.assertEqual(self.exec_line(), f"{self.bin} %u")
        entry = read(os.path.join(self.apps, "browser-selector.desktop"))
        self.assertNotIn("NoDisplay", entry)
        self.assertIn("x-scheme-handler/http;x-scheme-handler/https;", entry)
        self.assertNotIn("@BIN@", entry)
        self.assertEqual(os.stat(os.path.join(self.apps, "browser-selector.desktop")).st_mode & 0o777, 0o644)

    def test_the_settings_entry_of_an_older_install_is_removed(self):
        os.makedirs(self.apps)
        old = os.path.join(self.apps, "browser-selector-settings.desktop")
        write_script(old, "[Desktop Entry]\n")
        self.assertEqual(self.install()[0], 0)
        self.assertFalse(os.path.lexists(old))

    def test_the_first_config_comes_from_discovery(self):
        write_script(os.path.join(self.fake, "default"), "google-chrome.desktop\n")
        code, out, err = self.install()
        model = bs.read_model(read(self.config))
        self.assertEqual(model["settings"], {"default": "chrome"})
        self.assertEqual(model["browsers"]["chrome"], {"name": "google-chrome", "icon": "google-chrome",
                                                       "command": "google-chrome"})
        self.assertIn("firefox", model["browsers"])
        self.assertEqual(model["rules"], {})
        self.assertEqual(self.run_script(self.bin, "--check")[0], 0)
        self.assertIn("default = chrome", out)

    @unittest.skipIf(os.path.isdir(bs.FLATPAK_APPLICATIONS), "the flatpaks of this machine would be found")
    def test_no_browser_found_no_config(self):
        code, out, err = self.run_script("bash", os.path.join(ROOT, "install.sh"),
                                         XDG_DATA_DIRS=os.path.join(self.tmp, "nothing"))
        self.assertEqual(code, 0)
        self.assertIn("no browser found", err)
        self.assertIn("Config:       not written", out)
        self.assertFalse(os.path.exists(self.config))
        self.assertTrue(os.path.islink(self.bin))

    def test_a_config_that_is_there_is_kept(self):
        write_script(self.config, MINE)
        os.chmod(self.config, 0o600)
        code, out, err = self.install()
        self.assertEqual((code, read(self.config)), (0, MINE))
        self.assertIn("Config kept:", out)
        code, out, err = self.install()
        self.assertEqual((code, read(self.config)), (0, MINE))

    def test_the_default_browser_is_not_changed(self):
        code, out, err = self.install()
        self.assertEqual(self.default(), "firefox.desktop")
        self.assertEqual(read(os.path.join(self.fake, "calls")).replace("get default-web-browser\n", ""), "")
        self.assertFalse(os.path.exists(self.previous))
        self.assertIn("xdg-settings set default-web-browser browser-selector.desktop", out)
        self.assertIn("xdg-settings set default-web-browser firefox.desktop", out)

    def test_set_default(self):
        code, out, err = self.install("--set-default")
        self.assertEqual((code, self.default()), (0, "browser-selector.desktop"))
        self.assertEqual(read(self.previous), "firefox.desktop\n")
        self.assertEqual(self.install("--set-default")[0], 0)
        self.assertEqual(read(self.previous), "firefox.desktop\n")

    def test_arguments(self):
        for args in (["--help"], ["--set-default", "x"], ["--force"]):
            code, out, err = self.install(*args)
            self.assertEqual((code, self.installed()), (1, []))
            self.assertIn("usage: install.sh [--set-default]", err)

    def test_an_install_of_the_old_layout_is_replaced(self):
        write_script(self.bin, "#!/usr/bin/env python3\nprint('the handler of the first version')\n")
        self.assertEqual(self.install()[0], 0)
        self.assertEqual(os.readlink(self.bin), os.path.join(self.lib, "browser_selector.py"))
        self.assertEqual(os.listdir(os.path.dirname(self.bin)), ["browser-selector"])

    def test_a_desktop_entry_is_never_written_through_a_link(self):
        victim = os.path.join(self.tmp, "victim")
        write_script(victim, "precious\n")
        os.makedirs(self.apps)
        os.makedirs(self.lib)
        for path in (os.path.join(self.apps, "browser-selector.desktop"),
                     os.path.join(self.lib, "browser_selector.py"), os.path.join(self.lib, "browser_selector_gui.py")):
            os.symlink(victim, path)
        self.assertEqual(self.install()[0], 0)
        self.assertEqual(read(victim), "precious\n")
        self.assertEqual(os.stat(victim).st_mode & 0o777, 0o755)
        self.assertFalse(os.path.islink(os.path.join(self.apps, "browser-selector.desktop")))
        self.assertEqual(self.exec_line(), f"{self.bin} %u")
        self.assertEqual(os.listdir(self.apps), ["browser-selector.desktop"])

    def test_no_temporary_file_is_left(self):
        self.install()
        self.install()
        for directory in (self.lib, self.apps, os.path.dirname(self.bin), os.path.dirname(self.config)):
            self.assertFalse([name for name in os.listdir(directory) if name.startswith(".")], directory)


class OddHome(Install):
    """A home directory with everything in its name the Desktop Entry specification reserves."""

    home_name = "my home $HOME `x` \"q\" 'q' \\b 100% & ; * (x) #é"

    def test_exec_is_quoted_and_escaped(self):
        code, out, err = self.install()
        self.assertEqual((code, err), (0, ""))
        line = self.exec_line()
        self.assertTrue(line.startswith('"') and line.endswith('" %u'), line)
        quoted = (self.bin.replace("\\", "\\\\\\\\").replace('"', '\\\\"').replace("`", "\\\\`")
                  .replace("$", "\\\\$").replace("%", "%%"))
        self.assertEqual(line, f'"{quoted}" %u')

    def test_the_entry_is_read_back_as_the_path(self):
        self.install()
        # The reader of discovery follows the specification: escapes of a string, then the quoting
        self.assertEqual(bs.exec_argv(self.exec_line()), [self.bin])

    def test_glib_reads_it_back_too(self):
        self.install()
        # What gio does with the entry before it starts the handler, in a process of its own
        script = ("import json, sys\nfrom gi.repository import GLib\nkeys = GLib.KeyFile()\n"
                  "keys.load_from_file(sys.argv[1], GLib.KeyFileFlags.NONE)\n"
                  "value = keys.get_string('Desktop Entry', 'Exec').replace('%%', '%')\n"
                  "print(json.dumps(GLib.shell_parse_argv(value)[1]))\n")
        done = subprocess.run([sys.executable, "-c", script, os.path.join(self.apps, "browser-selector.desktop")],
                              env={"PATH": self.tools}, timeout=60, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if done.returncode != 0:
            self.skipTest("no GLib for python here")
        self.assertEqual(json.loads(done.stdout), [self.bin, "%u"])

    def test_set_default_says_why_it_cannot(self):
        code, out, err = self.install("--set-default")
        self.assertEqual(code, 1)
        self.assertIn("a home directory with a reserved character in its path cannot be registered", err)
        self.assertEqual(self.default(), "firefox.desktop")
        self.assertFalse(os.path.exists(self.previous))

    def test_it_works(self):
        self.install()
        code, out, err = self.run_script(self.bin, "--version")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.run_script(self.bin, "--check")[0], 0)
        code, out, err = self.uninstall()
        self.assertEqual(code, 0)
        self.assertEqual(self.installed(), [".config/browser-selector/config.ini"])


class ForeignHome(Install):
    """Letters that are not ASCII are not reserved: the entry is not quoted, and xdg-settings takes it."""

    home_name = "домой-été"

    def test_exec_is_not_quoted_and_set_default_works(self):
        code, out, err = self.install("--set-default")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.exec_line(), f"{self.bin} %u")
        self.assertEqual(self.default(), "browser-selector.desktop")
        self.assertEqual(read(self.previous), "firefox.desktop\n")


class OddPlaces(Install):
    def victim(self):
        """A directory that looks like a checkout: the files of the tool and their bytecode."""
        victim = os.path.join(self.tmp, "checkout")
        for name in ("browser_selector.py", "browser_selector_gui.py", "__pycache__/browser_selector_gui.pyc"):
            write_script(os.path.join(victim, name), "precious\n")
        return victim

    def tree(self, directory):
        return sorted((os.path.relpath(os.path.join(place, name), directory), read(os.path.join(place, name)))
                      for place, _, names in os.walk(directory) for name in names)

    def test_a_data_directory_that_is_a_link_is_refused(self):
        victim = self.victim()
        before = self.tree(victim)
        os.makedirs(os.path.dirname(self.lib))
        os.symlink(victim, self.lib)
        for script in (self.install, self.uninstall, lambda: self.uninstall("--force")):
            code, out, err = script()
            self.assertEqual(code, 1)
            self.assertIn("is a symbolic link", err)
            self.assertEqual(self.tree(victim), before)
        self.assertFalse(os.path.lexists(self.bin))

    def test_a_data_directory_that_is_the_checkout_is_refused(self):
        share = os.path.join(self.tmp, "share-home")
        checkout = os.path.join(share, "browser-selector")
        os.makedirs(checkout)
        for name in ("browser_selector.py", "browser_selector_gui.py", "browser-selector.desktop",
                     "install.sh", "uninstall.sh"):
            shutil.copy(os.path.join(ROOT, name), checkout)
        before = self.tree(checkout)
        for script in ("install.sh", "uninstall.sh"):
            code, out, err = self.run_script("bash", os.path.join(checkout, script), XDG_DATA_HOME=share)
            self.assertEqual(code, 1)
            self.assertIn("is the directory of this script", err)
            self.assertEqual(self.tree(checkout), before)

    def test_previous_default_is_never_written_through_a_link(self):
        victim = os.path.join(self.tmp, "victim")
        write_script(victim, "precious\n")
        os.makedirs(os.path.dirname(self.previous))
        os.symlink(victim, self.previous)
        self.assertEqual(self.install("--set-default")[0], 0)
        self.assertEqual(read(victim), "precious\n")
        self.assertFalse(os.path.islink(self.previous))
        self.assertEqual(read(self.previous), "firefox.desktop\n")

    def test_a_relative_xdg_directory_is_ignored(self):
        code, out, err = self.run_script("bash", os.path.join(ROOT, "install.sh"), XDG_DATA_HOME="relative/data",
                                         XDG_CONFIG_HOME="relative/config", XDG_STATE_HOME="relative/state")
        self.assertEqual((code, err), (0, ""))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "relative")))
        self.assertEqual(os.readlink(self.bin), os.path.join(self.lib, "browser_selector.py"))
        self.assertEqual(self.run_script(self.bin, "--check", XDG_CONFIG_HOME="relative/config")[0], 0)
        code, out, err = self.run_script("bash", os.path.join(ROOT, "uninstall.sh"), XDG_DATA_HOME="relative/data")
        self.assertEqual(code, 0)
        self.assertEqual(self.installed(), [".config/browser-selector/config.ini"])

    def test_uninstall_does_not_restore_the_handler_itself(self):
        self.install("--set-default")
        before = self.installed()
        os.remove(os.path.join(self.fake, "calls"))
        for text in ("browser-selector.desktop\n", "browser-selector-settings.desktop\n", "--help\n", "x y.desktop\n"):
            write_script(self.previous, text)
            code, out, err = self.uninstall()
            self.assertEqual(code, 1)
            self.assertIn("Nothing is removed", err)
            self.assertEqual(self.installed(), before)
            self.assertNotIn("set default-web-browser " + text.strip(), read(os.path.join(self.fake, "calls")))

    def test_uninstall_without_xdg_settings_removes_nothing(self):
        self.install("--set-default")
        before = self.installed()
        os.remove(os.path.join(self.tools, "xdg-settings"))
        code, out, err = self.uninstall()
        self.assertEqual(code, 1)
        self.assertIn("xdg-settings", err)
        self.assertEqual(self.installed(), before)
        code, out, err = self.uninstall("--force")
        self.assertEqual(code, 0)
        self.assertEqual(self.installed(), [".config/browser-selector/config.ini"])


class Uninstall(Install):
    def setUp(self):
        super().setUp()
        write_script(self.config, MINE)

    def test_removes_what_was_installed_and_keeps_the_config(self):
        self.install()
        code, out, err = self.uninstall()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.installed(), [".config/browser-selector/config.ini"])
        self.assertEqual(read(self.config), MINE)
        self.assertFalse(os.path.exists(self.lib))
        self.assertIn(f"Kept:    {self.config}", out)
        self.assertEqual(self.default(), "firefox.desktop")

    def test_says_that_the_log_stays(self):
        self.install()
        log = os.path.join(self.home, ".local/state/browser-selector/log")
        write_script(log, "a line\n")
        code, out, err = self.uninstall()
        self.assertIn(f"Kept:    {log}", out)
        self.assertEqual(read(log), "a line\n")

    def test_the_compiled_windows_module_goes_too(self):
        self.install()
        write_script(os.path.join(self.lib, "__pycache__", "browser_selector_gui.cpython-310.pyc"), "x")
        self.assertEqual(self.uninstall()[0], 0)
        self.assertFalse(os.path.exists(self.lib))

    def test_a_data_directory_with_something_else_in_it_stays(self):
        self.install()
        write_script(os.path.join(self.lib, "notes.txt"), "mine\n")
        code, out, err = self.uninstall()
        self.assertEqual(code, 0)
        self.assertEqual(os.listdir(self.lib), ["notes.txt"])
        self.assertIn("not empty", out)

    def test_the_previous_default_browser_is_put_back(self):
        self.install("--set-default")
        self.assertEqual(self.default(), "browser-selector.desktop")
        code, out, err = self.uninstall()
        self.assertEqual((code, self.default()), (0, "firefox.desktop"))
        self.assertIn("Default browser: firefox.desktop", out)
        self.assertEqual(self.installed(), [".config/browser-selector/config.ini"])

    def test_another_default_browser_is_left_alone(self):
        self.install("--set-default")
        write_script(os.path.join(self.fake, "default"), "google-chrome.desktop\n")
        self.assertEqual(self.uninstall()[0], 0)
        self.assertEqual(self.default(), "google-chrome.desktop")

    def test_a_handler_that_is_not_the_link_of_the_installer_is_left_alone(self):
        for make in (lambda: write_script(self.bin, "#!/bin/sh\necho mine\n"),
                     lambda: os.symlink("/usr/bin/true", self.bin),
                     lambda: os.symlink(os.path.join(self.tmp, "elsewhere", "browser_selector.py"), self.bin)):
            with self.subTest():
                self.install()
                os.remove(self.bin)
                make()
                code, out, err = self.uninstall()
                self.assertEqual(code, 0)
                self.assertTrue(os.path.lexists(self.bin))
                self.assertIn(f"Left:    {self.bin}", out)
                self.assertFalse(os.path.exists(self.lib))
                os.remove(self.bin)

    def test_default_browser_that_cannot_be_put_back_nothing_is_removed(self):
        self.install("--set-default")
        before = self.installed()
        for break_it in (lambda: os.remove(self.previous),
                         lambda: write_script(self.previous, "gone.desktop\n")):
            break_it()
            code, out, err = self.uninstall()
            self.assertEqual(code, 1)
            self.assertIn("Nothing is removed", err)
            self.assertIn("--force", err)
            self.assertEqual(self.default(), "browser-selector.desktop")
            self.assertEqual([path for path in self.installed() if "previous-default" not in path],
                             [path for path in before if "previous-default" not in path])
            self.assertEqual(self.run_script(self.bin, "--version")[0], 0)

    def test_force_removes_anyway(self):
        self.install("--set-default")
        os.remove(self.previous)
        code, out, err = self.uninstall("--force")
        self.assertEqual(code, 0)
        self.assertIn("could not be put back", err)
        self.assertEqual(self.installed(), [".config/browser-selector/config.ini"])

    def test_force_still_puts_the_previous_one_back_when_it_can(self):
        self.install("--set-default")
        self.assertEqual(self.uninstall("--force")[0], 0)
        self.assertEqual(self.default(), "firefox.desktop")

    def test_nothing_installed(self):
        code, out, err = self.uninstall()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(self.installed(), [".config/browser-selector/config.ini"])

    def test_arguments(self):
        self.install()
        before = self.installed()
        for args in (["--help"], ["--force", "x"], ["-f"]):
            code, out, err = self.uninstall(*args)
            self.assertEqual((code, self.installed()), (1, before))
            self.assertIn("usage: uninstall.sh [--force]", err)


if __name__ == "__main__":
    unittest.main()
