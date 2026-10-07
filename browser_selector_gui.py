"""browser-selector: the picker and the settings window.

GTK 4 and libadwaita. The handler loads this module only when a window is
needed, the picker in a child process of its own. Everything a window decides
is a function of browser_selector, this is the layer that shows it. The
contract is docs/design-gui.md.

Only API of GTK 4.6 and libadwaita 1.1 (Ubuntu 22.04) is used: rows with an
entry are an Adw.ActionRow around a Gtk.Entry, forms are an Adw.Window.
"""

import os
import shlex
import sys

import browser_selector as bs

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import GLib
    # WM_CLASS and the Wayland app id are taken from this name when Gtk opens the display.
    GLib.set_prgname("browser-selector")
    from gi.repository import Adw, Gdk, Gio, Gtk
except (ImportError, ValueError) as error:
    raise bs.NoWindow(f"GTK 4 and libadwaita are needed: {error}") from None

ASK_LABEL = "Ask every time"
PAGES = (("browsers", "Browsers", "web-browser-symbolic"),
         ("rules", "Rules", "view-list-symbolic"),
         ("default", "Default", "emblem-default-symbolic"),
         ("test", "Test", "system-search-symbolic"),
         ("logs", "Logs", "document-open-recent-symbolic"))
RECENT_HINT = "The last links opened: the rule, the browser, the app and the host of the link."
LIVE_HINT = ("Every link clicked from now on, with all that a rule can match: the app, the window, "
             "the title, the full URL. Nothing of it is kept.")
BROWSER_FIELDS = (
    ("id", "_Id", "The name the rules use"),
    ("name", "_Name", "What the picker shows"),
    ("icon", "I_con", "Icon name or an absolute path"),
    ("command", "C_ommand", "The link goes to the end or into {url}"),
)
RULE_FIELDS = (
    ("id", "_Name", "The name of the rule in the log"),
    ("app", "_App", "Regex for the whole id of the app"),
    ("window", "_Window class", "Regex for the whole class"),
    ("title", "_Title", "Regex searched in the window title"),
    ("url", "_URL", "Regex searched in the link"),
    ("probe", "_Probe", "A command, or @slack-workspace"),
    ("probe_match", "Probe _match", "Regex searched in its output"),
)


def run(build):
    """One application around one window, until the window is closed. Its exit code."""
    # Adw.Application leaves the whole process when the display cannot be opened: look first.
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        raise bs.NoWindow("the display cannot be opened")
    app = Adw.Application(flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.connect("activate", build)
    return app.run(None)


def markup(text):
    """Titles of rows and toasts are Pango markup."""
    return GLib.markup_escape_text(text)


def browser_icon(icon):
    image = Gtk.Image(pixel_size=32)
    if os.path.isabs(icon):
        image.set_from_file(icon)
    else:
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        image.set_from_icon_name(icon if icon and theme.has_icon(icon) else "web-browser-symbolic")
    return image


def icon_button(icon, tooltip, clicked):
    button = Gtk.Button(icon_name=icon, tooltip_text=tooltip, valign=Gtk.Align.CENTER)
    button.add_css_class("flat")
    button.connect("clicked", clicked)
    return button


def entry_row(title, text="", subtitle="", hint=""):
    """A row with an entry: (row, entry). The mnemonic of the title leads to the entry."""
    entry = Gtk.Entry(text=text, placeholder_text=hint, width_chars=32, valign=Gtk.Align.CENTER)
    row = Adw.ActionRow(title=title, subtitle=markup(subtitle), use_underline=True, activatable_widget=entry)
    row.add_suffix(entry)
    return row, entry


def error_label():
    label = Gtk.Label(wrap=True, xalign=0, selectable=True, visible=False,
                      margin_top=12, margin_start=12, margin_end=12)
    label.add_css_class("error")
    return label


def on_keys(window, keys):
    """Shortcuts of a window: {accelerator: function without arguments}."""
    controller = Gtk.ShortcutController()
    for accelerator, function in keys.items():
        def action(widget, args, function=function):
            function()
            return True

        controller.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string(accelerator),
                                                 Gtk.CallbackAction.new(action)))
    window.add_controller(controller)


# --- picker ---

def pick(link, apps, browsers):
    """Ask which browser opens the link: [(name, label, icon)]. The name, None when it was closed."""
    picked = []

    def build(app):
        window = Adw.ApplicationWindow(application=app, title="Open link", default_width=440, resizable=False)

        def choose(index):
            picked.append(browsers[index][0])
            window.close()

        def key_pressed(controller, keyval, keycode, state):
            if keyval == Gdk.KEY_Escape:
                window.close()
                return True
            digit = chr(Gdk.keyval_to_unicode(keyval))
            if digit in "123456789" and int(digit) <= len(browsers):
                choose(int(digit) - 1)
                return True
            return False

        rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.BROWSE,
                           margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        rows.add_css_class("boxed-list")
        for number, (name, label, icon) in enumerate(browsers, 1):
            row = Adw.ActionRow(title=markup(label), activatable=True)
            row.add_prefix(browser_icon(icon))
            if number < 10:
                digit = Gtk.Label(label=str(number))
                digit.add_css_class("dim-label")
                row.add_suffix(digit)
            rows.append(row)
        rows.connect("row-activated", lambda box, row: choose(row.get_index()))

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", key_pressed)
        window.add_controller(keys)

        title = Adw.WindowTitle(title=link, subtitle=f"from {', '.join(apps)}" if apps else "")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(Adw.HeaderBar(title_widget=title))
        box.append(Gtk.ScrolledWindow(child=rows, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                      propagate_natural_height=True, max_content_height=560))
        window.set_content(box)
        window.present()
        rows.select_row(rows.get_row_at_index(0))
        rows.get_row_at_index(0).grab_focus()

    run(build)
    return picked[0] if picked else None


# --- settings window ---

class Form:
    """A modal window with one row per field, Cancel and Save in its header."""

    def __init__(self, parent, title, fields, values, choices, save):
        """fields: (key, title, subtitle); choices: {key: [(value, label)]} for the rows
        that are a list; save(values) returns the error text or None."""
        self.save = save
        self.entries, self.lists = {}, {}
        self.window = Adw.Window(transient_for=parent, modal=True, title=title, default_width=640,
                                 default_height=130 + 56 * len(fields))
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda button: self.window.close())
        done = Gtk.Button.new_with_mnemonic("_Save")
        done.add_css_class("suggested-action")
        done.connect("clicked", self.done)
        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        header.pack_start(cancel)
        header.pack_end(done)

        group = Adw.PreferencesGroup()
        for key, label, subtitle in fields:
            if key in choices:
                row = Adw.ComboRow(title=label, subtitle=markup(subtitle), use_underline=True,
                                   model=Gtk.StringList.new([text for _, text in choices[key]]))
                known = [value for value, _ in choices[key]]
                row.set_selected(known.index(values[key]) if values.get(key) in known else 0)
                self.lists[key] = (row, known)
            else:
                row, self.entries[key] = entry_row(label, values.get(key, ""), subtitle)
                self.entries[key].connect("activate", self.done)
            group.add(row)
        page = Adw.PreferencesPage(vexpand=True)
        page.add(group)
        self.error = error_label()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for widget in (header, self.error, page):
            box.append(widget)
        self.window.set_content(box)
        on_keys(self.window, {"Escape": self.window.close})
        self.window.present()
        self.entries[fields[0][0]].grab_focus()

    def done(self, *args):
        values = {key: entry.get_text() for key, entry in self.entries.items()}
        values.update({key: known[row.get_selected()] for key, (row, known) in self.lists.items()})
        error = self.save(values)
        if error:
            self.error.set_label(error)
            self.error.set_visible(True)
        else:
            self.window.close()


class Settings:
    """The settings window. Every change is validated and written to the config file at once."""

    def __init__(self, app, path, env):
        self.path, self.env = path, env
        self.which = bs.path_which(env)
        self.model, self.problems = bs.empty_model(), []
        self.rows = []          # (group, row) of everything fill() put there
        self.filling = False    # fill() moves the list of the default: that is not a change
        self.is_default = False
        self.watching = 0       # the timer of the live log, 0 while it is off
        self.window = Adw.ApplicationWindow(application=app, title="Browser Selector",
                                            default_width=780, default_height=720)

        self.stack = Adw.ViewStack(vexpand=True)
        pages = (self.browsers_page(), self.rules_page(), self.default_page(), self.test_page(), self.logs_page())
        for (name, title, icon), page in zip(PAGES, pages):
            self.stack.add_titled(page, name, title).set_icon_name(icon)
        self.stack.connect("notify::visible-child", lambda *args: (self.live.set_active(False), self.reload()))
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        self.problem = error_label()
        self.toasts = Adw.ToastOverlay(child=self.stack)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for widget in (Adw.HeaderBar(title_widget=switcher), self.problem, self.toasts,
                       Gtk.Separator(), self.status_row()):
            box.append(widget)
        self.window.set_content(box)

        keys = {f"<Alt>{number}": lambda name=name: self.stack.set_visible_child_name(name)
                for number, (name, _, _) in enumerate(PAGES, 1)}
        on_keys(self.window, dict(keys, **{"<Control>q": self.window.close, "<Control>w": self.window.close}))
        # The config may be edited by hand next to the window: read it again when the window is back.
        self.window.connect("notify::is-active", lambda *args: self.window.is_active() and self.reload())
        self.window.connect("close-request", lambda *args: self.live.set_active(False))
        self.fill()
        self.reload()
        self.window.present()
        GLib.idle_add(self.fill_status)

    # --- pages ---

    def list_page(self, title, description, buttons):
        """A page with one list and the buttons of its header: (page, group)."""
        group = Adw.PreferencesGroup(title=title, description=description)
        box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        for label, clicked in buttons:
            button = Gtk.Button.new_with_mnemonic(label)
            button.connect("clicked", clicked)
            box.append(button)
        group.set_header_suffix(box)
        page = Adw.PreferencesPage()
        page.add(group)
        return page, group

    def browsers_page(self):
        page, self.browsers = self.list_page(
            "Browsers", "What a rule can open, and what the picker offers.",
            (("_Find browsers", self.find_browsers), ("Add _browser", lambda button: self.edit_browser(None))))
        return page

    def rules_page(self):
        page, self.rules = self.list_page(
            "Rules", "The first rule that matches a link decides.",
            (("Add _rule", lambda button: self.edit_rule(None)),))
        return page

    def default_page(self):
        self.default = Adw.ComboRow(title="Browser for _everything else", use_underline=True,
                                    subtitle="Opens every link no rule decides")
        self.default.connect("notify::selected", self.default_picked)
        self.default_names = []
        group = Adw.PreferencesGroup(title="Default")
        group.add(self.default)
        page = Adw.PreferencesPage()
        page.add(group)
        return page

    def test_page(self):
        page, click = self.list_page(
            "A click", "What a link would open, by the code of the handler. The probes of the rules run for real.",
            (("_Test", self.run_test),))
        self.click = {}
        for key, title, hint in (("url", "_URL", "https://example.com/"), ("app", "_App", "slack"),
                                 ("window", "_Window class", "Slack"), ("title", "T_itle", "Threads - Team - Slack")):
            row, self.click[key] = entry_row(title, hint=hint)
            self.click[key].connect("activate", self.run_test)
            click.add(row)
        answer = Adw.PreferencesGroup(title="Answer")
        self.answer = {}
        for key in ("Rule", "Browser", "Command", "Notes"):
            self.answer[key] = Adw.ActionRow(title=key, subtitle="-")
            answer.add(self.answer[key])
        self.answer["Notes"].set_visible(False)
        page.add(answer)
        return page

    def logs_page(self):
        self.live = Gtk.ToggleButton(label="_Live", use_underline=True, valign=Gtk.Align.CENTER)
        self.live.connect("toggled", self.watch)
        self.logs = Adw.PreferencesGroup(title="Log", description=RECENT_HINT)
        self.logs.set_header_suffix(self.live)
        self.log = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                top_margin=12, bottom_margin=12, left_margin=12, right_margin=12)
        self.logs.add(Gtk.Frame(child=self.log))
        page = Adw.PreferencesPage()
        page.add(self.logs)
        return page

    def watch(self, *args):
        """The live file is there exactly while Live is pressed: leaving the page releases it."""
        on = self.live.get_active()
        if on and not self.watching:
            try:
                bs.start_live(self.env)
            except OSError as error:
                self.say(f"Clicks cannot be watched: {error.strerror}")
                self.live.set_active(False)
                return
            self.watching = GLib.timeout_add(300, self.show_log)
        elif not on and self.watching:
            GLib.source_remove(self.watching)
            self.watching = 0
            bs.stop_live(self.env)
        self.logs.set_description(LIVE_HINT if on else RECENT_HINT)
        self.show_log()

    def show_log(self):
        if self.watching:
            text = "\n\n".join(bs.read_live(self.env)) or "Click a link in any app."
        else:
            # The newest line first: that is the click the user just made.
            text = "\n".join(reversed(bs.log_tail(self.env))) or "Nothing was opened yet."
        buffer = self.log.get_buffer()
        if text != buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False):
            buffer.set_text(text)
        return GLib.SOURCE_CONTINUE

    def status_row(self):
        self.status = Gtk.Label(xalign=0, hexpand=True, wrap=True)
        self.switch = Gtk.Button(label="Set as _default", use_underline=True, valign=Gtk.Align.CENTER,
                                 sensitive=False)
        self.switch.connect("clicked", self.switch_default)
        box = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        box.append(self.status)
        box.append(self.switch)
        return box

    # --- showing the config ---

    def label(self, name):
        if name == bs.ASK:
            return ASK_LABEL
        return self.model["browsers"].get(name, {}).get("name") or name

    def choices(self, current=None):
        """The browsers a rule or the default can name: [(name, label)], the picker last."""
        names = list(self.model["browsers"])
        if current and current != bs.ASK and current not in names:
            names.append(current)  # a config that is not valid: show what it says
        return [(name, self.label(name)) for name in names] + [(bs.ASK, ASK_LABEL)]

    def reload(self):
        """Read the config file and show it."""
        model, error = bs.load_model(self.path)
        if error:
            problems = [f"The config cannot be read, mend {self.path} by hand:", error]
        else:
            problems = bs.check_model(model, self.which) if any(model.values()) else []
        self.show_log()
        # Rows are only made again when something changed: a click on a row that was just replaced is lost.
        if (model or bs.empty_model(), problems) != (self.model, self.problems):
            self.model, self.problems = model or bs.empty_model(), problems
            self.problem.set_label("\n".join(problems))
            self.problem.set_visible(bool(problems))
            self.fill()

    def fill(self):
        for group, row in self.rows:
            group.remove(row)
        self.rows = []

        def add(group, row):
            group.add(row)
            self.rows.append((group, row))

        for name, items in self.model["browsers"].items():
            row = Adw.ActionRow(title=markup(items.get("name") or name), activatable=True, subtitle_lines=1,
                                subtitle=markup(f"{name}: {items.get('command', '')}"))
            row.add_prefix(browser_icon(items.get("icon", "")))
            row.add_suffix(icon_button("user-trash-symbolic", "Remove",
                                       lambda button, name=name: self.remove(bs.without_browser, name)))
            row.connect("activated", lambda row, name=name: self.edit_browser(name))
            add(self.browsers, row)
        if not self.model["browsers"]:
            add(self.browsers, Adw.ActionRow(title="No browsers yet", subtitle="Find browsers looks for them"))

        for name, items in self.model["rules"].items():
            conditions = ", ".join(f"{key} = {items[key]}" for key in bs.KEYS["rule"][:-1] if key in items)
            opens = self.label(items.get("browser", "-"))
            row = Adw.ActionRow(title=markup(name), activatable=True, subtitle_lines=2,
                                subtitle=markup(f"{conditions or 'every link'} -> {opens}"))
            for icon, tooltip, step in (("go-up-symbolic", "Up", -1), ("go-down-symbolic", "Down", 1)):
                row.add_suffix(icon_button(icon, tooltip,
                                           lambda button, name=name, step=step: self.move(name, step)))
            row.add_suffix(icon_button("user-trash-symbolic", "Remove",
                                       lambda button, name=name: self.remove(bs.without_rule, name)))
            row.connect("activated", lambda row, name=name: self.edit_rule(name))
            add(self.rules, row)
        if not self.model["rules"]:
            add(self.rules, Adw.ActionRow(title="No rules yet", subtitle="Every link goes to the default"))

        self.fill_default()

    def fill_default(self):
        self.filling = True
        default = self.model["settings"].get("default")
        choices = self.choices(default)
        self.default_names = [name for name, _ in choices]
        self.default.set_model(Gtk.StringList.new([label for _, label in choices]))
        self.default.set_selected(self.default_names.index(default) if default in self.default_names
                                  else Gtk.INVALID_LIST_POSITION)
        self.filling = False

    def fill_status(self):
        current = bs.system_default(self.env)
        self.is_default = current == bs.ENTRY
        if self.is_default:
            self.status.set_label("Browser Selector is the default browser of the system.")
        else:
            self.status.set_label(f"The default browser of the system is {current or 'not known'}.")
        self.switch.set_sensitive(not self.is_default)
        return GLib.SOURCE_REMOVE

    def say(self, text):
        self.toasts.add_toast(Adw.Toast(title=markup(text)))

    # --- changing the config ---

    def change(self, edit):
        """One edit of the config file. The error text when it is refused, None when it is written."""
        model, errors = bs.change_config(self.path, edit, self.which)
        self.reload()
        if errors:
            print(bs.printable("browser-selector: not saved: " + "; ".join(errors)), file=sys.stderr)
        return "\n".join(errors) or None

    def change_or_say(self, edit):
        """change() for a button: a refusal is shown, not returned to a form."""
        error = self.change(edit)
        if error:
            self.say(error)
        return error

    def remove(self, without, name):
        self.change_or_say(lambda model: without(model, name))

    def move(self, name, step):
        self.change_or_say(lambda model: bs.move_rule(model, name, step))

    def default_picked(self, *args):
        if not self.filling and self.default.get_selected() < len(self.default_names):
            # Not from inside notify::selected: the change fills the very row that tells about it.
            GLib.idle_add(self.set_default, self.default_names[self.default.get_selected()])

    def set_default(self, name):
        if self.change_or_say(lambda model: bs.with_default(model, name)):
            self.fill_default()  # the row goes back to what is saved
        return GLib.SOURCE_REMOVE

    def find_browsers(self, *args):
        added, left = [], []
        try:
            found = bs.discover(self.env, self.which, left.append)
        except Exception as error:  # foreign files: whatever is in them, the window stays
            self.say(f"Find browsers: {type(error).__name__}")
            return
        for message in left:
            print(f"browser-selector: {message}", file=sys.stderr)

        def edit(model):
            model, added[:] = bs.with_discovered(model, found, self.which)
            return model

        error = self.change(edit)
        self.say(error or (f"Added: {', '.join(added)}" if added else "Nothing new was found")
                 + (f". Left out: {len(left)}, see stderr" if left else ""))

    def edit_browser(self, old):
        values = dict(self.model["browsers"].get(old, {}), id=old or "")

        def save(values):
            name = values.pop("id").strip()
            return self.change(lambda model: bs.with_browser(model, name, bs.clean(values), old))

        Form(self.window, "Browser" if old else "New browser", BROWSER_FIELDS, values, {}, save)

    def edit_rule(self, old):
        values = dict(self.model["rules"].get(old, {}), id=old or "")
        fields = RULE_FIELDS + (("browser", "_Browser", "Opens what the rule matches"),)

        def save(values):
            name = values.pop("id").strip()
            return self.change(lambda model: bs.with_rule(model, name, bs.clean(values), old))

        Form(self.window, "Rule" if old else "New rule", fields, values,
             {"browser": self.choices(values.get("browser"))}, save)

    def switch_default(self, *args):
        error = bs.make_default(self.env)
        if error:
            self.say(error)
        self.fill_status()

    def run_test(self, *args):
        url = self.click["url"].get_text().strip()
        config, errors = bs.parse_config(bs.render_model(self.model), self.which)
        if not url or errors:
            self.say("\n".join(errors) if url else "A URL is needed")
            return

        def words(key):
            return [word.strip() for word in self.click[key].get_text().split(",") if word.strip()]

        seen = (words("window"), self.click["title"].get_text()) if words("window") else None
        rule, browser, argv, notes = bs.try_click(config, url, words("app"), seen, self.env, self.which)
        answer = {"Rule": rule or "- (no rule matches, the default)",
                  "Browser": self.label(browser) if browser else "- (the last resort)",
                  "Command": shlex.join(argv) if argv else "- (the picker)" if browser == bs.ASK else "-",
                  "Notes": "\n".join(notes)}
        for key, text in answer.items():
            self.answer[key].set_subtitle(markup("\n".join(bs.printable(line) for line in text.splitlines())))
        self.answer["Notes"].set_visible(bool(notes))


def settings(path, env):
    """The settings window for the config at `path`. The exit code."""
    return run(lambda app: Settings(app, path, env))
