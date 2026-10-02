# Design: discovery, picker, settings window

_verified: 2026-10-02_

The second part of the contract, on top of [design.md](design.md). The shape
is taken from Browser Tamer: the tool is the default browser, and inside it
the user sees his browsers and profiles and writes the rules.

The handler stays what it is: a click that a rule decides never loads GTK.

## Files

    browser_selector.py        the handler and everything without a window
    browser_selector_gui.py    picker and settings window, GTK 4 + libadwaita
    browser-selector.desktop            the handler, hidden from the app grid
    browser-selector-settings.desktop   the settings window, shown in the app grid

`browser_selector_gui.py` is imported by the handler only when a window is
needed. It may use only API that exists in GTK 4.6 and libadwaita 1.1 (Ubuntu
22.04) and still exists in the versions of Ubuntu 26.04. Both typelibs are on
a stock Ubuntu desktop, nothing is installed for it.

## Browser sections get a name and an icon

    [browser chrome-acme]
    name = Google Chrome - acme
    icon = google-chrome
    command = google-chrome --profile-directory="Profile 15"

`name` and `icon` are optional and only used by the picker and the settings
window. `icon` is an icon name of the theme or an absolute path.

## Discovery

    browser-selector --discover

prints a `[browser ...]` section for every browser and profile found, in the
format above, and changes nothing. The settings window uses the same function
and adds what is missing to the config; it never removes or rewrites a
section that is already there.

Where it looks:

* desktop entries with `x-scheme-handler/http` in `MimeType`, in
  `$XDG_DATA_HOME/applications`, every `applications` directory of
  `$XDG_DATA_DIRS`, `/var/lib/snapd/desktop/applications` and the flatpak
  export directories. The own entries are skipped. The command is `Exec`
  without its field codes, the name is `Name`, the icon is `Icon`;
* Chromium family (Chrome, Brave, Chromium, Edge, Vivaldi): `Local State` in
  the data directory of the browser, `profile.info_cache`. The key is the
  profile directory, the display name is `shortcut_name`, else `name`. One
  section per profile: the command of the browser plus
  `--profile-directory=<directory>`, also when there is only one profile, so
  the section keeps meaning that profile when a second one appears. A browser
  without `Local State` gives one section without the flag;
* Firefox: `profiles.ini` in `~/.mozilla/firefox` and in
  `~/snap/firefox/common/.mozilla/firefox`, one section per profile with
  `-P <name>`.

Section names are slugs of browser and profile (`chrome-acme`,
`brave-home`, `firefox-default-release`), unique within one run.

Everything discovery reads was written by another program, and a snap or
flatpak browser owns its files. So what it finds is checked like a config
before it is used: a profile or an entry with a control character or a line
break in a name, with `{url}` in its own words, or with a field code inside a
quoted argument (`sh -c "... %u"`) is left out with a note, and the rest is
kept. A field code at the end of a word (`--url=%u`) becomes `{url}` there. A
desktop entry is split into lines the way GLib does it, on `\n` only.

## Picker

`ask` is a reserved browser name: `default = ask` or `browser = ask` in a
rule. It cannot be defined as a section.

The picker is one small window: the host of the link, the app it came from,
and the configured browsers as a list with icon and name. A click, `Enter` on
the selected row or the digit of a row opens the link there. `Esc` or closing
the window opens nothing, exit code 0.

When the window cannot be shown (no display, GTK missing), the last resort of
design.md applies. The window runs in a child process of the handler, so a
window that dies ends in the last resort as well.

## Settings window

    browser-selector --settings

Pages:

* Browsers: the list, add, edit, remove, and "Find browsers" (discovery,
  adds the missing ones). A browser a rule or the default still uses cannot
  be removed;
* Rules: the list in order, move up and down, add, edit, remove. The edit
  form has the fields of a rule in design.md and a browser dropdown that
  includes "Ask every time";
* Default: the browser for everything else, "Ask every time" included;
* Test: URL, app, window class and title typed in by hand, the answer is the
  rule that fires and the command, by the same code the handler uses;
* Recent: the last lines of the decision log, read only. This is where the
  app id of a new application is looked up when writing a rule for it;
* a status row: whether the handler is the default browser of the system,
  with a button for the switch and for the way back. Nothing is switched
  without that button.

Every change is saved at once, there is no Save for the whole window. The
file is read again before each change, a hand edit made meanwhile is kept.

Saving validates with the code of `--check` and refuses a config that is not
valid, naming the section and the key. A section or a key the tool does not
know stays in the file and blocks saving until it is fixed by hand. The file
is written to a temporary file and renamed over the old one, a new one with
mode 0600. Comments in a hand edited config are lost on the first save, the
README says so.

## Install

    browser_selector.py, browser_selector_gui.py
                               -> ${XDG_DATA_HOME:-~/.local/share}/browser-selector/
    ~/.local/bin/browser-selector
                               -> symlink to browser_selector.py there
    browser-selector.desktop, browser-selector-settings.desktop
                               -> ${XDG_DATA_HOME:-~/.local/share}/applications/
    config                     written from discovery when there is none
                               (`--init-config`): every browser found,
                               default = the browser that was the system
                               default, no rules

The installed `browser_selector.py` gets the shebang `#!/usr/bin/python3 -I`:
the handler runs in the environment of whatever app the link was clicked in,
and a `PYTHONPATH`, a `PYTHONHOME` or the `python3` of a virtualenv there
must not reach it. Isolated mode also keeps the directory of the script out
of `sys.path`, so the handler adds its own real directory before it imports
`browser_selector_gui`.

The desktop entries are written to a temporary file and renamed into place,
never through an existing symlink. The path in `Exec` is quoted and escaped
as the Desktop Entry specification asks, a home directory with a space in it
still gives a working entry. Such an entry cannot be made the default
through `xdg-settings` 1.1.3 though: it takes the first word of `Exec` with
the quote. `--set-default` and the button in the window say so instead of
failing silently. The data directory must be a real directory: a symlink
there, or the checkout itself, is refused by both scripts. A relative
`XDG_*` value counts as unset.

`uninstall.sh` removes all of it except the config and says that the log
stays. It only removes what the installer put there: a
`~/.local/bin/browser-selector` that is not the symlink into the data
directory is left alone. When the handler is the default browser and the
previous one cannot be put back, it removes nothing and exits non-zero;
`--force` removes anyway.
