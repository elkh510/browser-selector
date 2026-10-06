# browser-selector docs (hub)

_verified: 2026-10-02_

Working docs for the `browser-selector` repo: the handler, discovery, the picker and the
settings window, the installer, the stands. Read this file, then the topic file you need. What
the tool is for and how to use it is in the [README](../README.md) of the repo.

**Paths.** A bare path like `stand/x11/run.sh` is relative to the repo root.

## Keeping these docs current

- **A change is not done until the docs say so.** Rules, layout and the done-checklist:
  [docs-guide.md](docs-guide.md).
- **These docs extend themselves.** Whenever work turns up a fact that is missing here - an
  application and how it shows up, a trap that cost time, a command that worked - add it to
  the topic file it belongs to (or a new file + a row below) in the same piece of work. No
  need to ask first; list every doc edit in the final report so the user sees it in the diff
  before committing.
- **Fix what is wrong, in place.** When something written here turns out stale or incorrect,
  correct that line where it is: do not append a second, contradicting version next to it, do
  not leave the old one "for history" (git has it). Move `_verified` only if the whole file
  was re-checked.
- **Write only what is verified** against the code, a stand or the desktop. Mark the rest as
  unverified, with what would confirm it.
- **One fact, one home.** Link instead of copying.
- **Split at ~150 lines**: a topic file that outgrows itself becomes `docs/<topic>/README.md`
  plus one file per subject.

## Files by topic

| File | Read it when you need |
|---|---|
| [docs-guide.md](docs-guide.md) | How docs are kept: the change rule, which kind of doc goes where, decision entries, the done-checklist |
| [design.md](design.md) | The handler: command line, what a rule can look at (`app`, `window`, `title`, `url`, `probe`), the config format, what a click does when something is wrong, the log, known limits |
| [design-gui.md](design-gui.md) | Discovery of browsers and profiles, the picker, the settings window, what `install.sh` puts where and what it refuses |
| [applications.md](applications.md) | How each application shows up to the handler (unit, `CHROME_DESKTOP`, window class, title format) and the rule that matches it |
| [known-issues.md](known-issues.md) | Open problems, limits and things not verified yet, each with what removes it |
| [../stand/README.md](../stand/README.md) | The two stands: what each piece is, how to run, what each scenario showed |
