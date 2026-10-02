# browser-selector

A default web browser for Ubuntu/GNOME that opens each link in the browser and
profile a rule names, by where the link was clicked: the application, the
focused window, the URL, the output of a probe command. A handler in Python
(stdlib only), a picker and a settings window (GTK 4 + libadwaita), an
installer, unit tests and two end to end stands in docker.

Remote: `git@github.com:elkh510/browser-selector.git`, branch `main`.

**Docs: [docs/README.md](docs/README.md)** - read it, then the topic file you need.

## Rules

- Never commit or push without an explicit go for that step.
- Never touch the desktop of the user without an explicit go: no `install.sh` or
  `uninstall.sh` against the real home, no `xdg-settings set`, no `xdg-mime default`, no edit
  of `~/.config/browser-selector/config.ini`. The stands and a home under `$TMPDIR` are for
  that.
- Never let the handler start a real browser. `--explain`, `--discover` and `--check` start
  nothing; any other run needs a `PATH` that holds only stub browsers (the unit tests inject
  exec, the stands ship stubs). An unset or default `PATH` finds the real Chrome.
- The handler sits on the path of every click and reads what other programs wrote (URLs,
  window titles, desktop entries, browser profile files). No shell anywhere, the URL is always
  one argument, and a click always opens something: see
  [docs/design.md](docs/design.md#a-click-always-opens-something).
- `browser_selector.py` stays stdlib only and runs on Python 3.10. `browser_selector_gui.py`
  uses only API that exists in GTK 4.6 and libadwaita 1.1 and is not gone in Ubuntu 26.04. A
  click a rule decides must not import `gi`.
- A change is not done until the tests pass and `docs/` says so:
  [docs/docs-guide.md](docs/docs-guide.md). Add missing facts and fix stale ones in `docs/`
  yourself as you go, and list the doc edits in the report.
- Nothing of the user goes into a tracked file: no real name of a workspace, an organization,
  a browser profile or a person, no home path. Code, tests, stands and docs use the
  placeholders `Acme`, `Globex`, `Initech`. What is real lives in `local/`, which is in
  `.gitignore`: read [local/README.md](local/README.md) when the real names are needed.
- Docs and comments in English, no em dashes (use `-`). No comments in INI files.

## Commands

```
python3 -m unittest discover -s tests
python3 browser_selector.py --config config.example.ini --check
bash stand/x11/run.sh [scenario.sh]       # Ubuntu 22.04, X11; needs docker
bash stand/gnome50/run.sh [scenario.sh]   # GNOME Shell 50, Wayland; needs docker
browser-selector --explain URL            # what the installed handler sees and would run
```

The docker socket is refused inside the agent sandbox: the stand commands run with the
sandbox off, nothing else needs that.
