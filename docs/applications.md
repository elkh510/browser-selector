# Applications

_verified: 2026-10-02_

How each application shows up to the handler, and the rule that matches it. Seen on Ubuntu
22.04, GNOME 42, X11, unless a line says otherwise. For a new application:

    sleep 5; browser-selector --explain https://example.com/

and switch to it within the five seconds. The `app`, `window` and `title` lines are what a
rule can match.

| Application | Packaging | `app` | `window` | Workspace or profile comes from |
|---|---|---|---|---|
| Slack | deb 4.52 | `slack` | `slack`, `slack` | window title, or its state file |
| ClickUp | unpacked AppImage | `desktop` | `clickup`, `ClickUp` | window title |
| VS Code | deb | `com.microsoft.VSCode` | `com.microsoft.vscode`, `com.microsoft.VSCode` | window title |
| NetBird | deb | `netbird` | none of its own | `netbird profile list` |
| Cloudflare One | deb `cloudflare-warp` | `warp-taskbar` | none of its own | the URL |
| Telegram | snap, strict | not known, see below | `telegram-desktop`, `TelegramDesktop` | all of it by `window`, no account |

## Slack

Unit `app-slack-<pid>.scope`. All workspaces live in one process, so `app` alone cannot tell
them apart.

Title: `<view> - <Workspace> - Slack`, for example `Threads - Acme - Slack` or
`<person> (DM) - Globex - Slack`.

    [rule slack-globex]
    app = slack
    title = - Globex - Slack$

Without the window (Wayland, where the title of a native window cannot be read): the selected
workspace is in `~/.config/Slack/storage/root-state.json`
(`workspaces[workspacesMeta.selectedWorkspaceId].name`), the built-in probe reads it:

    probe = @slack-workspace
    probe_match = ^Globex$

How soon Slack writes that file after a switch is not measured, see
[known-issues.md](known-issues.md).

## ClickUp

Unit `app-desktop-<pid>.scope`: the binary of the AppImage is called `desktop`, and so is the
app id. The window class keeps other apps with that id out.

Title: `<view> | <Workspace>`, with an optional ` (<view>)` after the workspace, for example
`Overview | Project Management | Initech (Overview)`.

    [rule clickup-initech]
    app = desktop|clickup
    title = \| Initech( \([^|]*\))?$

ClickUp keeps no state file like Slack does (`~/.config/ClickUp` is only the Chromium
profile), the title is the only signal.

## VS Code

Unit `app-com.microsoft.VSCode-<pid>.scope`, `CHROME_DESKTOP=com.microsoft.VSCode.desktop`.
All windows are one process.

Title with the default `window.title`:
`<tab> - <workspace> (Workspace) - <profile> - Visual Studio Code`. A folder opened without
a workspace file has no ` (Workspace)`, and a window of the default profile has no profile
part.

    [rule vscode-personal]
    app = com\.microsoft\.VSCode|code
    title = - personal( \(Workspace\))? - ([^-]* - )?Visual Studio Code$

A link VS Code opens by itself (the login of an extension) is routed by whatever window has
the focus at that moment.

## NetBird

`netbird-ui` runs in `app-gnome-netbird-<pid>.scope`. The login page it opens has nothing to
do with the focused window, so no `title` here.

`netbird profile list` prints a table, the active profile has a check mark:

    NAME     ACTIVE
    default
    globex   ✓

    [rule netbird-globex]
    app = netbird
    probe = netbird profile list
    probe_match = ^globex\s+✓

## Cloudflare One client

`warp-taskbar` runs as `warp-taskbar.service`. `warp-cli registration organization` prints
the team. The enrollment page is `https://<team>.cloudflareaccess.com/warp`, so a rule on the
URL is enough (the URL form is from the Cloudflare docs, not seen on this desktop):

    [rule cloudflare-team]
    url = ^https://<team>\.cloudflareaccess\.com/

The page hands the token back through `com.cloudflare.warp://`, which has its own handler and
never reaches this one.

## Telegram

The snap opens links through the portal, the handler then sits in the cgroup of the portal
and does not see who asked. Only `window` and `title` are left, and the title holds the chat
name and unread counters, not the account. So one rule for the whole of Telegram is all
there is, by the window class:

    [rule telegram]
    window = TelegramDesktop
    browser = brave-home

It reads the focused window, so on Wayland it works only while Telegram is an X11 client.
