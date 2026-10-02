# browser-selector

A default browser for Linux that opens a link in the browser and profile that
fits where the link was clicked: Slack workspace A in one Chrome profile,
Slack workspace B in Brave, the login page of a VPN client in the profile of
its organization.

It is registered as the default web browser. Inside it are the browsers and
profiles of the machine and a list of rules. For every link the first rule
that matches names the browser, a picker asks when a rule says so, and a
click always opens something.

Built for Ubuntu with GNOME: 22.04 (GNOME 42, X11) and 26.04 (GNOME 50,
Wayland). Python 3.10 or newer, GTK 4 and libadwaita for the windows, all of
it already on a stock Ubuntu desktop. No daemon, no GNOME Shell extension.

## Install

    bash install.sh                 # into ~/.local, the default browser stays
    browser-selector --settings     # or "Browser Selector" in the app grid

The first config is written from the browsers and profiles found, with the
current default browser as the default and no rules. Making it the default
browser of the system is a separate step: the button at the bottom of the
settings window, or

    bash install.sh --set-default

`bash uninstall.sh` puts the previous default browser back and removes what
was installed. The config and the log stay.

## Rules

A rule can look at:

| Key | What |
|---|---|
| `app` | the application the link came from: its systemd unit (`slack`, `netbird`, `warp-taskbar`) or the `CHROME_DESKTOP` of an Electron app |
| `window` | the class of the focused window |
| `title` | the title of the focused window |
| `url` | the link |
| `probe`, `probe_match` | a command and a regex for its output |

Every condition is optional, all given ones must hold, the first matching
rule wins. `app` and `window` must match in full and ignore case, the others
are searched for and case sensitive.

The config is `~/.config/browser-selector/config.ini`. The settings window
edits it, and it can be edited by hand; comments in it are lost the first
time the window saves.

    [settings]
    default = chrome-main

    [browser chrome-main]
    name = Google Chrome - main
    command = google-chrome --profile-directory="Profile 6"

    [browser brave-home]
    name = Brave - home
    command = brave-browser --profile-directory="Profile 1"

    [rule slack-globex]
    app = slack
    title = - Globex - Slack$
    browser = brave-home

    [rule netbird-globex]
    app = netbird
    probe = netbird profile list
    probe_match = ^globex\s+✓
    browser = brave-home

    [rule cloudflare-team]
    url = ^https://myteam\.cloudflareaccess\.com/
    browser = chrome-main

`browser = ask` (or `default = ask`) shows the picker instead.
[config.example.ini](config.example.ini) has more.

To write a rule for a new application, see what the handler sees:

    sleep 5; browser-selector --explain https://example.com/

Switch to the application within the five seconds. The `app`, `window` and
`title` lines are what a rule can match. The "Recent" page of the settings
window shows the same for the last real clicks.

    browser-selector --check       # validate the config
    browser-selector --discover    # print the browsers and profiles found

## Wayland

`app`, `url` and `probe` work the same on X11 and Wayland. `window` and
`title` are read with `xprop`, which on a Wayland session sees X11 windows
only: a rule with `title` does not match a native Wayland window, the link
then goes on to the next rule or the default. For Slack use its own state
instead of the title:

    [rule slack-globex]
    app = slack
    probe = @slack-workspace
    probe_match = ^Globex$
    browser = brave-home

Applications from snap or flatpak open links through the portal. The handler
then cannot tell who the link came from by `app`, only `window` and `title`
are left for them.

## What a click does when something is wrong

No config, a config that is not valid, a browser that is not installed, a
window that cannot be shown: the link opens in the default browser of the
config, else in the first of `google-chrome`, `brave-browser`, `firefox`,
`chromium` found. The reason is in `~/.local/state/browser-selector/log`,
which records every decision with the host of the link, never the full URL.

## Tests

    python3 -m unittest discover -s tests
    bash stand/x11/run.sh        # end to end, Ubuntu 22.04 container
    bash stand/gnome50/run.sh    # end to end, GNOME Shell 50 on Wayland

The stands need docker. They run fake applications that open links through
the real `xdg-open` path and stub browsers that record what was started;
nothing touches the host. See [stand/README.md](stand/README.md).

How it works and why: [docs/design.md](docs/design.md),
[docs/design-gui.md](docs/design-gui.md).
