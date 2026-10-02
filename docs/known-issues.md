# Known issues

_verified: 2026-10-02_

Open problems, limits and things nobody has checked yet. Each with what removes it. A line
goes away when the thing is fixed or confirmed.

## Not verified on a real desktop

| What | Since | What confirms it |
|---|---|---|
| A click in Slack and in ClickUp reaching its rule. The titles of the real windows match the rules, and a real click from VS Code was routed, but no link was clicked in these two | 2026-10-02 | click a link in each, read `~/.local/state/browser-selector/log` |
| How soon Slack writes `root-state.json` after a workspace switch. `@slack-workspace` is only as fresh as that file | 2026-10-02 | switch the workspace, compare the mtime of the file with the clock |
| That `--profile-directory` lands the link in the named profile when Chrome already runs with a window of another profile in front | 2026-10-02 | click with two profiles open |
| The windows under GNOME 42 with Dash to Panel and ArcMenu, and with the Yaru theme | 2026-10-02 | open the picker and the settings window on the desktop |
| The window height and the line wrap on the Recent page, changed after the screenshots in `stand/out/gnome50/screenshots/` were taken | 2026-10-02 | run `bash stand/gnome50/run.sh screenshots.sh` and look |

## Limits

| What | Why | What would remove it |
|---|---|---|
| On Wayland a rule with `window` or `title` matches X11 clients only. A native Wayland window gives no window at all, the link goes to the next rule or the default | `xprop` sees Xwayland only, GNOME exports the focused window to nobody else | a small GNOME Shell extension that answers "which window has focus" over D-Bus, read as a second window source. Slack does not need it (`@slack-workspace`), ClickUp would |
| Snap and flatpak applications are not known by `app` | they open links through the portal, the handler sits in the cgroup of the portal | nothing on this side; `window` and `title` still work for them |
| A home directory with a space or another reserved character: the handler works, but it cannot be made the default browser | `xdg-settings` 1.1.3 takes the first word of `Exec` with its quote | registering the five MIME types with `gio mime` instead of `xdg-settings set` |
| A wrapper script that leads back to the handler passes `--check` | a script cannot be seen through | caught at run time: the second start within 5 seconds goes to the last resort |
| A probe is killed at its timeout, what it started is not | only the probe process is tracked | a process group for the probe |
| Units of D-Bus activated applications (`dbus-:1.2-org.gnome.Nautilus@0.service`) do not give the app id | not normalised | a case for it in the app id code, after seeing the real names |
| The settings window saves a form over a hand edit of the same section made while the form was open, and two settings windows do not lock each other | the file is re-read before a change, not while a form is open | not planned |
| Comments in a hand edited config are lost on the first save from the window | the file is rewritten from the model | not planned |

## Not covered by a stand

| What | Covered by |
|---|---|
| Settings window: edit and remove a browser or a rule, move a rule, the Test and Recent pages, the default browser button | unit tests of the functions behind them, no key press |
| Settings window on GNOME Shell 50: only opened for the screenshots | the X11 stand drives it on Ubuntu 22.04 |
| The picker coming up while the user keeps typing in another window | nothing |
| systemd: both stands build the cgroups by hand, the parent of the handler there is the init of the container | the launch path was measured once on the desktop, see `design.md` |
| The loop guard, log mode and rotation, the probe output cap, template units | unit and process tests only |
