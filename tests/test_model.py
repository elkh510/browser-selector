"""The config as the settings window edits it: reading, writing, every edit."""

import os
import stat
import unittest
from unittest import mock

from support import CONFIG, ROOT, HandlerCase, bs, read

EXAMPLE = os.path.join(ROOT, "config.example.ini")
SMALL = """\
[settings]
default = main

[browser main]
command = google-chrome

[browser fox]
name = Firefox
command = firefox

[rule one]
app = slack
browser = fox

[rule two]
url = ^https://two\\.example\\.com/
browser = main

[rule three]
title = Three$
browser = fox
"""


def small():
    return bs.read_model(SMALL)


class ReadAndRender(unittest.TestCase):
    def test_model_of_a_config(self):
        model = small()
        self.assertEqual(model["settings"], {"default": "main"})
        self.assertEqual(model["browsers"], {"main": {"command": "google-chrome"},
                                             "fox": {"name": "Firefox", "command": "firefox"}})
        self.assertEqual(list(model["rules"]), ["one", "two", "three"])
        self.assertEqual(model["rules"]["two"], {"url": r"^https://two\.example\.com/", "browser": "main"})
        self.assertEqual(model["unknown"], {})

    def test_round_trip_of_the_example_config(self):
        text = read(EXAMPLE)
        self.assertEqual(bs.render_model(bs.read_model(text)), text)
        self.assertEqual(bs.check_model(bs.read_model(text)), [])

    def test_round_trip_of_the_test_configs(self):
        for text in (SMALL, CONFIG):
            model = bs.read_model(text)
            self.assertEqual(bs.read_model(bs.render_model(model)), model)
            self.assertEqual([rule["name"] for rule in bs.parse_config(bs.render_model(model))[0]["rules"]],
                             [rule["name"] for rule in bs.parse_config(text)[0]["rules"]])

    def test_sections_are_written_settings_browsers_rules(self):
        text = "[rule r]\nbrowser = main\n[browser main]\ncommand = firefox\n[settings]\ndefault = main\n"
        self.assertEqual(bs.render_model(bs.read_model(text)),
                         "[settings]\ndefault = main\n\n[browser main]\ncommand = firefox\n\n"
                         "[rule r]\nbrowser = main\n")

    def test_comments_are_lost_values_are_not(self):
        text = "; a comment\n[settings]\n# another\ndefault = main\n[browser main]\ncommand = firefox  \n"
        self.assertEqual(bs.render_model(bs.read_model(text)),
                         "[settings]\ndefault = main\n\n[browser main]\ncommand = firefox\n")

    def test_values_the_regexes_need(self):
        items = {"url": r"^https://x\.com/#frag;%(y)s = [a:b]", "title": "- Team - Slack$", "browser": "main"}
        model = bs.with_rule(small(), "odd", items)
        self.assertEqual(bs.read_model(bs.render_model(model))["rules"]["odd"], items)
        self.assertEqual(bs.check_model(model), [])

    def test_an_empty_value_and_a_value_of_two_lines(self):
        model = bs.read_model("[browser main]\nname =\ncommand = firefox\n\t--new-tab\n")
        self.assertEqual(model["browsers"]["main"], {"name": "", "command": "firefox\n--new-tab"})
        self.assertEqual(bs.render_model(model), "[browser main]\nname =\ncommand = firefox\n\t--new-tab\n")

    def test_what_is_not_a_known_section_is_kept(self):
        text = ("[settings]\ndefault = main\n\n[browser main]\ncommand = firefox\n\n"
                "[bogus]\nkey = 1\n\n[browser]\nx = y\n")
        model = bs.read_model(text)
        self.assertEqual(model["unknown"], {"bogus": {"key": "1"}, "browser": {"x": "y"}})
        self.assertEqual(bs.render_model(model), text)
        self.assertTrue(bs.check_model(model)[0].startswith("[bogus]: unknown section"))
        model["unknown"]["bogus"] = {"key": " 1"}
        self.assertTrue(bs.check_model(model)[0].startswith("[bogus]: the name or a value cannot be written"))

    def test_not_ini(self):
        for text in ("default = main\n", "[settings]\n[settings]\n", "[rule r]\nnot a line\n"):
            with self.subTest(text=text), self.assertRaises(bs.configparser.Error):
                bs.read_model(text)

    def test_empty(self):
        self.assertEqual(bs.read_model(""), bs.empty_model())
        self.assertEqual(bs.render_model(bs.empty_model()), "")


class CheckModel(unittest.TestCase):
    def assertError(self, model, where):
        errors = bs.check_model(model)
        self.assertTrue(errors and errors[0].startswith(where), errors)

    def test_valid(self):
        self.assertEqual(bs.check_model(small()), [])

    def test_the_errors_are_the_ones_of_check(self):
        model = bs.with_rule(small(), "bad", {"url": "(", "browser": "nowhere"})
        self.assertEqual(bs.check_model(model), bs.parse_config(bs.render_model(model))[1])
        self.assertEqual([error.partition(":")[0] for error in bs.check_model(model)],
                         ["[rule bad] url", "[rule bad] browser"])

    def test_the_program_is_resolved_like_check_does(self):
        model = bs.with_browser(small(), "me", {"command": "my-browser"})
        self.assertEqual(bs.check_model(model), [])
        errors = bs.check_model(model, which=lambda program: bs.HANDLER)
        self.assertTrue(any(error.startswith("[browser me] command: ") for error in errors), errors)

    def test_names_and_values_an_ini_file_cannot_hold(self):
        self.assertError(bs.with_browser(small(), "a\nb", {"command": "firefox"}), "")
        self.assertError(bs.with_rule(small(), " padded", {"browser": "main"}), "[rule  padded]: ")
        self.assertError(bs.with_rule(small(), "r", {"title": " leading space", "browser": "main"}), "[rule r]: ")
        self.assertError(bs.with_rule(small(), "r", {"a = b": "x", "browser": "main"}), "[rule r]")
        self.assertError(bs.with_default(small(), "main\n[rule x]"), "")

    def test_a_value_of_the_settings_that_is_not_read_back(self):
        self.assertEqual(bs.check_model(dict(small(), settings={"default": " main"})),
                         ["[settings]: a value cannot be written to an INI file"])

    def test_a_value_cannot_add_a_section(self):
        # The lines of a value are written indented: they are read back as the value, not as a section
        model = bs.with_rule(small(), "r", {"title": "x\n[browser evil]\ncommand = evil", "browser": "main"})
        self.assertEqual(bs.read_model(bs.render_model(model)), model)
        self.assertEqual(list(bs.parse_config(bs.render_model(model))[0]["browsers"]), ["main", "fox"])

    def test_a_bracket_in_a_name_is_read_back(self):
        model = bs.with_browser(small(), "a]b", {"command": "firefox"})
        self.assertEqual(bs.read_model(bs.render_model(model)), model)


LINE_BREAKS = ("\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", " ", " ", "\x00", "\x1b", "\ud800")


class LineBreaks(HandlerCase):
    """What is validated is what is on disk: only a line feed ends a line, and nothing that
    another reader takes for a line end, and no control character, is ever written."""

    def assertRefused(self, model, where):
        errors = bs.check_model(model)
        self.assertTrue(errors and errors[0].startswith(where), errors)
        self.assertTrue(errors[0].isprintable(), errors)
        path = os.path.join(self.tmp, "refused.ini")
        self.assertEqual(bs.save_model(path, model), errors)
        self.assertFalse(os.path.exists(path))

    def test_a_value(self):
        for char in LINE_BREAKS:
            with self.subTest(char=repr(char)):
                self.assertRefused(bs.with_rule(small(), "r", {"title": f"a{char}b", "browser": "main"}),
                                   "[rule r] title: ")
                self.assertRefused(bs.with_browser(small(), "b", {"name": f"a{char}b", "command": "firefox"}),
                                   "[browser b] name: ")
                self.assertRefused(bs.with_default(small(), f"main{char}"), "[settings] default: ")

    def test_a_name(self):
        for char in LINE_BREAKS + ("\n",):
            with self.subTest(char=repr(char)):
                self.assertRefused(bs.with_browser(small(), f"a{char}b", {"command": "firefox"}), "[browser a")
                self.assertRefused(bs.with_rule(small(), f"a{char}b", {"browser": "main"}), "[rule a")
                self.assertRefused(dict(small(), unknown={f"a{char}b": {}}), "[a")

    def test_a_tab_and_a_value_of_two_lines_are_fine(self):
        model = bs.with_rule(small(), "r", {"title": "a\tb", "probe": "sh -c 'x\ny'", "probe_match": "x",
                                            "browser": "main"})
        self.assertEqual(bs.check_model(model), [])

    def test_a_carriage_return_in_a_file_is_not_a_line_end(self):
        path = self.write_config("")
        with open(path, "wb") as file:
            file.write(SMALL.encode() + b"[rule cr]\ntitle = a\rb\x0bc\nbrowser = main\n")
        config, errors = bs.load_config(path)
        self.assertEqual(errors, [])
        self.assertEqual(config["rules"][-1]["title"].pattern, "a\rb\x0bc")
        self.assertEqual(bs.load_model(path)[0]["rules"]["cr"], {"title": "a\rb\x0bc", "browser": "main"})

    def test_a_file_with_dos_line_ends(self):
        path = self.write_config("")
        with open(path, "wb") as file:
            file.write(SMALL.replace("\n", "\r\n").encode())
        self.assertEqual(bs.load_model(path), (small(), None))
        self.assertEqual(bs.load_config(path)[1], [])

    def test_a_path_that_cannot_be_written_is_an_error_not_a_crash(self):
        errors = bs.save_model(os.path.join(self.tmp, "a\0b", "config.ini"), small())
        self.assertEqual(len(errors), 1)


class TwoSpellings(HandlerCase):
    """[rule x] and [rule  x] are two sections for configparser and one name for the handler."""

    CASES = (("[rule  one]\nurl = second\nbrowser = main\n", "rule  one"),
             ("[browser  main]\ncommand = chromium\n", "browser  main"),
             ("[settings ]\ndefault = fox\n", "settings "))

    def test_check_reports_the_second_one(self):
        for extra, section in self.CASES:
            with self.subTest(section=section):
                config, errors = bs.parse_config(SMALL + extra)
                self.assertIsNone(config)
                self.assertEqual([error for error in errors if error.startswith(f"[{section}]: ")], errors)
                self.assertEqual(len(errors), 1)

    def test_the_model_keeps_both(self):
        for extra, section in self.CASES:
            with self.subTest(section=section):
                model = bs.read_model(SMALL + extra)
                self.assertEqual(list(model["unknown"]), [section])
                self.assertEqual({kind: model[kind] for kind in ("settings", "browsers", "rules")},
                                 {kind: small()[kind] for kind in ("settings", "browsers", "rules")})
                self.assertEqual(bs.render_model(model), SMALL + "\n" + extra)

    def test_a_save_is_refused_and_nothing_is_lost(self):
        for extra, section in self.CASES:
            with self.subTest(section=section):
                path = self.write_config(SMALL + extra)
                model, errors = bs.change_config(path, lambda model: bs.without_rule(model, "three"))
                self.assertIsNone(model)
                self.assertTrue(errors[0].startswith(f"[{section}]: "), errors)
                self.assertEqual(read(path), SMALL + extra)

    def test_one_odd_spelling_alone_is_fine(self):
        text = SMALL.replace("[rule one]", "[rule  one]").replace("[settings]", "[settings ]")
        self.assertEqual(bs.parse_config(text)[1], [])
        self.assertEqual(bs.read_model(text), small())


class UnknownKeys(unittest.TestCase):
    def test_an_edit_does_not_drop_a_key_it_does_not_know(self):
        model = bs.read_model(SMALL.replace("command = firefox", "command = firefox\nprofile = Work")
                              .replace("app = slack", "app = slack\nhost = x"))
        with self.assertRaisesRegex(ValueError, r"^\[browser fox\] profile: unknown key"):
            bs.with_browser(model, "fox", {"command": "firefox"}, old="fox")
        with self.assertRaisesRegex(ValueError, r"^\[rule one\] host: unknown key"):
            bs.with_rule(model, "uno", {"browser": "fox"}, old="one")
        self.assertEqual(bs.with_browser(model, "main", {"command": "chromium"}, old="main")["browsers"]["fox"],
                         {"name": "Firefox", "command": "firefox", "profile": "Work"})


class Save(HandlerCase):
    def setUp(self):
        super().setUp()
        self.path = self.write_config(SMALL)

    def test_valid_model_is_written(self):
        model = bs.with_rule(small(), "four", {"app": "netbird", "browser": "main"})
        self.assertEqual(bs.save_model(self.path, model), [])
        self.assertEqual(read(self.path), SMALL + "\n[rule four]\napp = netbird\nbrowser = main\n")
        self.assertEqual(self.handle("--check")[0], 0)

    def test_invalid_model_is_refused_and_the_file_is_untouched(self):
        before = os.stat(self.path)
        errors = bs.save_model(self.path, bs.with_rule(small(), "bad", {"url": "(", "browser": "main"}))
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith("[rule bad] url: bad regex"), errors)
        self.assertEqual(read(self.path), SMALL)
        self.assertEqual(os.stat(self.path), before)

    def test_through_a_temporary_file_and_a_rename(self):
        inode = os.stat(self.path).st_ino
        replaced = []
        real_replace = os.replace

        def replace(source, target):
            # At the moment of the rename the old file is whole and the new one is complete
            replaced.append((os.path.dirname(source), target, read(target), read(source)))
            real_replace(source, target)

        model = bs.with_default(small(), "fox")
        with mock.patch.object(bs.os, "replace", replace):
            self.assertEqual(bs.save_model(self.path, model), [])
        self.assertEqual(replaced, [(os.path.dirname(self.path), self.path, SMALL, bs.render_model(model))])
        self.assertNotEqual(os.stat(self.path).st_ino, inode)
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["config.ini"])

    def test_a_failed_write_leaves_the_file_and_no_temporary_one(self):
        with mock.patch.object(bs.os, "replace", side_effect=OSError(28, "No space left on device")):
            errors = bs.save_model(self.path, bs.with_default(small(), "fox"))
        self.assertEqual(len(errors), 1)
        self.assertIn("No space left on device", errors[0])
        self.assertEqual(read(self.path), SMALL)
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["config.ini"])

    def test_the_temporary_file_is_never_one_that_is_there(self):
        temporary = f"{self.path}.{os.getpid()}.tmp"
        victim = os.path.join(self.tmp, "victim")
        for make in (lambda: os.symlink(victim, temporary), lambda: os.link(victim, temporary)):
            with open(victim, "w") as file:
                file.write("precious\n")
            make()
            errors = bs.save_model(self.path, bs.with_default(small(), "fox"))
            self.assertEqual(len(errors), 1)
            self.assertEqual((read(victim), read(self.path)), ("precious\n", SMALL))
            self.assertTrue(os.path.lexists(temporary))
            os.remove(temporary)

    def test_new_file_and_new_directory(self):
        path = os.path.join(self.tmp, "new", "dir", "config.ini")
        self.assertEqual(bs.save_model(path, small()), [])
        self.assertEqual(read(path), SMALL)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_the_mode_of_the_file_is_kept(self):
        os.chmod(self.path, 0o640)
        self.assertEqual(bs.save_model(self.path, bs.with_default(small(), "fox")), [])
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o640)

    def test_a_config_that_is_a_link_stays_a_link(self):
        target = os.path.join(self.tmp, "dotfiles", "config.ini")
        os.makedirs(os.path.dirname(target))
        os.rename(self.path, target)
        os.symlink(target, self.path)
        self.assertEqual(bs.save_model(self.path, bs.with_default(small(), "fox")), [])
        self.assertTrue(os.path.islink(self.path))
        self.assertIn("default = fox", read(target))

    def test_a_directory_in_the_way(self):
        errors = bs.save_model(self.home, small())
        self.assertEqual(len(errors), 1)
        self.assertTrue(os.path.isdir(self.home))

    def test_load_model(self):
        self.assertEqual(bs.load_model(self.path), (small(), None))
        self.assertEqual(bs.load_model(os.path.join(self.tmp, "nothing.ini")), (bs.empty_model(), None))
        model, error = bs.load_model(self.write_config("default = main\n", "broken.ini"))
        self.assertIsNone(model)
        self.assertIn("no section headers", error)
        self.assertEqual(bs.load_model(self.home)[0], None)

    def test_load_model_reads_a_config_with_a_bom(self):
        with open(self.path, "w", encoding="utf-8-sig") as file:
            file.write(SMALL)
        self.assertEqual(bs.load_model(self.path), (small(), None))

    def test_load_model_reads_a_config_that_is_not_valid(self):
        model, error = bs.load_model(self.write_config(SMALL + "[rule bad]\ntitle = (\n", "invalid.ini"))
        self.assertEqual((model["rules"]["bad"], error), ({"title": "("}, None))


class ChangeConfig(HandlerCase):
    def setUp(self):
        super().setUp()
        self.path = self.write_config(SMALL)

    def test_an_edit_is_written(self):
        model, errors = bs.change_config(self.path, lambda model: bs.without_rule(model, "two"))
        self.assertEqual((list(model["rules"]), errors), (["one", "three"], []))
        self.assertEqual(list(bs.load_model(self.path)[0]["rules"]), ["one", "three"])

    def test_a_refused_edit_changes_nothing(self):
        for edit, where in ((lambda model: bs.without_browser(model, "fox"), "[browser fox]: still used by"),
                            (lambda model: bs.with_rule(model, "bad", {"url": "(", "browser": "main"}),
                             "[rule bad] url: bad regex"),
                            (lambda model: bs.with_default(model, "nowhere"), "[settings] default: browser nowhere")):
            model, errors = bs.change_config(self.path, edit)
            self.assertIsNone(model)
            self.assertTrue(errors[0].startswith(where), errors)
            self.assertEqual(read(self.path), SMALL)

    def test_the_file_is_read_again_for_every_edit(self):
        # Edited by hand while the window is open: the edit of the window lands on top of it
        self.write_config(SMALL + "\n[rule by-hand]\napp = x\nbrowser = main\n")
        model, errors = bs.change_config(self.path, lambda model: bs.without_rule(model, "one"))
        self.assertEqual(list(model["rules"]), ["two", "three", "by-hand"])

    def test_a_file_that_cannot_be_read_is_never_overwritten(self):
        self.write_config("this is not a config\n")
        model, errors = bs.change_config(self.path, lambda model: bs.with_browser(model, "new", {"command": "firefox"}))
        self.assertIsNone(model)
        self.assertEqual(read(self.path), "this is not a config\n")

    def test_no_file_yet(self):
        path = os.path.join(self.tmp, "new.ini")
        model, errors = bs.change_config(path, lambda model: bs.with_browser(model, "fox", {"command": "firefox"}))
        self.assertEqual(errors, [])
        self.assertEqual(read(path), "[settings]\ndefault = fox\n\n[browser fox]\ncommand = firefox\n")


class Browsers(unittest.TestCase):
    def test_add(self):
        model = bs.with_browser(small(), "brave", {"name": "Brave", "command": "brave-browser"})
        self.assertEqual(list(model["browsers"]), ["main", "fox", "brave"])
        self.assertEqual(bs.check_model(model), [])

    def test_an_edit_gives_a_new_model(self):
        before = small()
        bs.with_browser(before, "brave", {"command": "brave-browser"})
        bs.with_rule(before, "four", {"browser": "main"})
        bs.without_rule(before, "one")
        bs.move_rule(before, "one", 1)
        bs.with_default(before, "fox")
        bs.with_discovered(before, [{"section": "x", "name": "", "icon": "", "command": "x"}])
        self.assertEqual(before, small())

    def test_edit_in_place(self):
        model = bs.with_browser(small(), "main", {"command": "chromium", "icon": "chromium"}, old="main")
        self.assertEqual(list(model["browsers"]), ["main", "fox"])
        self.assertEqual(model["browsers"]["main"], {"command": "chromium", "icon": "chromium"})

    def test_a_new_name_is_followed_by_the_default_and_the_rules(self):
        model = bs.with_browser(small(), "chrome", {"command": "google-chrome"}, old="main")
        self.assertEqual(list(model["browsers"]), ["chrome", "fox"])
        self.assertEqual(model["settings"]["default"], "chrome")
        self.assertEqual([rule["browser"] for rule in model["rules"].values()], ["fox", "chrome", "fox"])
        self.assertEqual(bs.check_model(model), [])

    def test_a_name_that_is_taken(self):
        for old in (None, "main"):
            with self.assertRaisesRegex(ValueError, r"\[browser fox\]: there is one with this name already"):
                bs.with_browser(small(), "fox", {"command": "x"}, old=old)

    def test_a_name_is_needed(self):
        with self.assertRaisesRegex(ValueError, r"\[browser\]: a name is needed"):
            bs.with_browser(small(), "", {"command": "x"})

    def test_edit_of_a_browser_that_is_gone(self):
        with self.assertRaisesRegex(ValueError, r"\[browser gone\]: not in the config any more"):
            bs.with_browser(small(), "new", {"command": "x"}, old="gone")

    def test_a_default_that_is_empty_is_no_default(self):
        model = bs.read_model("[settings]\ndefault =\nprobe_timeout = 5\n")
        self.assertEqual(bs.with_browser(model, "fox", {"command": "firefox"})["settings"],
                         {"default": "fox", "probe_timeout": "5"})
        found = [{"section": "fox", "name": "", "icon": "", "command": "firefox"}]
        self.assertEqual(bs.with_discovered(model, found)[0]["settings"], {"default": "fox", "probe_timeout": "5"})

    def test_the_first_browser_becomes_the_default(self):
        model = bs.with_browser(bs.empty_model(), "fox", {"command": "firefox"})
        self.assertEqual(model["settings"], {"default": "fox"})
        self.assertEqual(bs.with_browser(model, "other", {"command": "chromium"})["settings"], {"default": "fox"})
        self.assertEqual(bs.check_model(model), [])

    def test_ask_cannot_be_a_browser(self):
        self.assertEqual(bs.check_model(bs.with_browser(small(), "ask", {"command": "firefox"})),
                         ["[browser ask]: ask is a reserved name"])

    def test_cannot_remove_a_browser_that_is_in_use(self):
        with self.assertRaisesRegex(ValueError, r"\[browser fox\]: still used by \[rule one\], \[rule three\]"):
            bs.without_browser(small(), "fox")
        with self.assertRaisesRegex(ValueError, r"\[browser main\]: still used by \[settings\] default, \[rule two\]"):
            bs.without_browser(small(), "main")
        self.assertEqual(bs.browser_users(small(), "nobody"), [])

    def test_remove_a_browser_nothing_uses(self):
        model = bs.without_rule(bs.without_rule(small(), "one"), "three")
        model = bs.without_browser(model, "fox")
        self.assertEqual(list(model["browsers"]), ["main"])
        self.assertEqual(bs.check_model(model), [])

    def test_clean(self):
        self.assertEqual(bs.clean({"name": "  Firefox ", "icon": "", "command": " firefox -P x ", "app": "   "}),
                         {"name": "Firefox", "command": "firefox -P x"})


class Rules(unittest.TestCase):
    def test_add_at_the_end(self):
        model = bs.with_rule(small(), "four", {"app": "netbird", "browser": bs.ASK})
        self.assertEqual(list(model["rules"]), ["one", "two", "three", "four"])
        self.assertEqual(bs.check_model(model), [])

    def test_edit_keeps_the_place(self):
        model = bs.with_rule(small(), "second", {"app": "x", "browser": "fox"}, old="two")
        self.assertEqual(list(model["rules"]), ["one", "second", "three"])
        self.assertEqual(model["rules"]["second"], {"app": "x", "browser": "fox"})

    def test_a_name_that_is_taken(self):
        with self.assertRaisesRegex(ValueError, r"\[rule one\]: there is one with this name already"):
            bs.with_rule(small(), "one", {"browser": "main"})
        with self.assertRaisesRegex(ValueError, r"\[rule one\]: there is one with this name already"):
            bs.with_rule(small(), "one", {"browser": "main"}, old="two")

    def test_remove(self):
        self.assertEqual(list(bs.without_rule(small(), "two")["rules"]), ["one", "three"])
        self.assertEqual(bs.without_rule(small(), "gone"), small())

    def test_move(self):
        self.assertEqual(list(bs.move_rule(small(), "three", -1)["rules"]), ["one", "three", "two"])
        self.assertEqual(list(bs.move_rule(small(), "one", 1)["rules"]), ["two", "one", "three"])
        model = bs.move_rule(bs.move_rule(small(), "three", -1), "three", -1)
        self.assertEqual(list(model["rules"]), ["three", "one", "two"])
        self.assertEqual(model["rules"]["three"], small()["rules"]["three"])

    def test_move_at_either_end_changes_nothing(self):
        self.assertEqual(list(bs.move_rule(small(), "one", -1)["rules"]), ["one", "two", "three"])
        self.assertEqual(list(bs.move_rule(small(), "three", 1)["rules"]), ["one", "two", "three"])

    def test_move_of_a_rule_that_is_gone(self):
        with self.assertRaisesRegex(ValueError, r"\[rule gone\]: not in the config any more"):
            bs.move_rule(small(), "gone", 1)

    def test_the_order_of_the_file_is_the_order_of_the_handler(self):
        model = bs.move_rule(small(), "three", -1)
        config = bs.parse_config(bs.render_model(model))[0]
        self.assertEqual([rule["name"] for rule in config["rules"]], ["one", "three", "two"])

    def test_default(self):
        self.assertEqual(bs.with_default(small(), "fox")["settings"], {"default": "fox"})
        self.assertEqual(bs.check_model(bs.with_default(small(), bs.ASK)), [])
        model = bs.read_model("[settings]\nprobe_timeout = 5\ndefault = main\n[browser main]\ncommand = x\n")
        self.assertEqual(bs.with_default(model, "ask")["settings"], {"probe_timeout": "5", "default": "ask"})


class Discovered(unittest.TestCase):
    FOUND = [
        {"section": "chrome-base", "name": "Google Chrome - base", "icon": "google-chrome",
         "command": '/usr/bin/google-chrome-stable --profile-directory="Profile 6"', "entries": [], "current": True},
        {"section": "fox", "name": "Firefox Web Browser", "icon": "", "command": "firefox", "entries": [],
         "current": True},
        {"section": "main", "name": "Chromium", "icon": "chromium", "command": "chromium", "entries": [],
         "current": True},
    ]

    def test_what_is_missing_is_added(self):
        model, added = bs.with_discovered(small(), self.FOUND)
        self.assertEqual(added, ["chrome-base", "main-2"])
        self.assertEqual(list(model["browsers"]), ["main", "fox", "chrome-base", "main-2"])
        self.assertEqual(model["browsers"]["chrome-base"], {
            "name": "Google Chrome - base", "icon": "google-chrome",
            "command": '/usr/bin/google-chrome-stable --profile-directory="Profile 6"'})
        self.assertEqual(model["browsers"]["main-2"], {"name": "Chromium", "icon": "chromium", "command": "chromium"})
        self.assertEqual(bs.check_model(model), [])

    def test_a_section_that_is_there_is_never_changed(self):
        model, added = bs.with_discovered(small(), self.FOUND)
        self.assertEqual({name: model["browsers"][name] for name in ("main", "fox")}, small()["browsers"])
        self.assertEqual((model["settings"], model["rules"]), (small()["settings"], small()["rules"]))

    def test_a_second_run_adds_nothing(self):
        model, added = bs.with_discovered(small(), self.FOUND)
        self.assertEqual(bs.with_discovered(model, self.FOUND), (model, []))

    def test_the_same_program_under_another_path_is_the_same_browser(self):
        def which(program):
            return {"google-chrome": "/usr/bin/google-chrome-stable"}.get(program, program)

        found = [dict(self.FOUND[0], command="/usr/bin/google-chrome-stable")]
        self.assertEqual(bs.with_discovered(small(), found)[1], ["chrome-base"])
        self.assertEqual(bs.with_discovered(small(), found, which)[1], [])

    def test_two_finds_that_start_the_same_thing_are_one_browser(self):
        found = [self.FOUND[0], dict(self.FOUND[0], section="chrome-again")]
        self.assertEqual(bs.with_discovered(small(), found)[1], ["chrome-base"])

    def test_another_profile_of_the_same_program_is_another_browser(self):
        model = bs.with_browser(small(), "chrome-main", {"command": 'google-chrome --profile-directory="Profile 9"'})
        which = {"google-chrome": "/usr/bin/google-chrome-stable"}.get
        self.assertEqual(bs.with_discovered(model, self.FOUND[:1], lambda program: which(program, program))[1],
                         ["chrome-base"])

    def test_ask_is_never_a_name(self):
        model, added = bs.with_discovered(small(), [dict(self.FOUND[0], section="ask")])
        self.assertEqual(added, ["ask-2"])

    def test_a_config_without_a_default_gets_the_first_one_found(self):
        model, added = bs.with_discovered(bs.empty_model(), self.FOUND)
        self.assertEqual(added, ["chrome-base", "fox", "main"])
        self.assertEqual(model["settings"], {"default": "chrome-base"})
        self.assertEqual(bs.check_model(model), [])
        self.assertEqual(bs.with_discovered(bs.empty_model(), []), (bs.empty_model(), []))

    def test_a_command_of_the_config_that_cannot_be_split(self):
        model = bs.read_model('[settings]\ndefault = x\n[browser x]\ncommand = firefox "open\n')
        self.assertEqual(bs.with_discovered(model, self.FOUND[1:2])[1], ["fox"])


if __name__ == "__main__":
    unittest.main()
