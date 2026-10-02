# Docs guide

_verified: 2026-10-02_

How documentation is kept in this repo. The day-to-day rules (self-extend, fix in place,
verified only, one fact one home, split at ~150 lines) are in
[README.md](README.md#keeping-these-docs-current); this file adds what sits around them.

## Rule: a change is not done until the docs say so

Any change to behaviour - a new rule key or option, a different answer of the handler, a
change in what discovery finds or leaves out, in what the installer writes or refuses, in the
config format, in a stand - updates the docs **in the same piece of work**, before it is
reported done.

- Update the fact where it lives, not only a summary. `design.md` and `design-gui.md` are the
  contract: the code follows them, and when the code has to differ, the contract is changed
  with it.
- Something found out about an application on a real desktop (its unit name, its title
  format, how it opens links) goes into [applications.md](applications.md).
- A limit, a workaround or a thing nobody has checked goes into
  [known-issues.md](known-issues.md) with the date and what removes it.
- A change that turned out to be wrong gets its doc corrected too, not just reverted.
- If a doc update was skipped, say so in the report and why.
- Doc edits are working-tree changes like any other: the user commits and pushes.

## Language and style

- English only. No em dashes, use `-`.
- Plain, factual, short sentences: what is, then why.
- Commands and paths in backticks or code blocks, copy-pasteable.
- Window titles, profile names and workspace names of the user are fine as examples; tokens
  and full login URLs are not.
- Relative links between docs.

## Stamps

Each topic file carries `_verified: YYYY-MM-DD_` under its title. Move the date only when the
file's facts were actually re-checked against the code, a stand run or the desktop. Facts
about other programs rot fastest (title formats, unit names, what `xdg-open` does): mark where
they were seen and on which version.

## Which kind of doc goes where

| Kind | Answers | Where |
|---|---|---|
| **Usage** | How do I install it and write a rule? | [README](../README.md) of the repo |
| **Reference** | What does it do right now? | `design.md`, `design-gui.md`, `applications.md` |
| **Explanation** | Why is it like this? | The "why" sentences next to each fact; decisions as entries (below) |
| **How-to** | How do I run and extend the stands? | [stand/README.md](../stand/README.md) |
| **Status** | What is limited, open or not verified? | [known-issues.md](known-issues.md) |

A new file is not done until [README.md](README.md) has its row.

## Decisions

For a choice someone would otherwise re-litigate, add a section to the topic file it concerns:

```
## <Decision title> (YYYY-MM-DD)
Context: what forced the choice.
Decision: what was chosen.
Consequences: what it costs, what would make us revisit it.
```

## Checklist before reporting a change as done

- [ ] `python3 -m unittest discover -s tests` passes; the stand whose area was touched passes.
- [ ] A new behaviour has a test that fails without it.
- [ ] Topic files show the new behaviour; `_verified` moved on files re-checked.
- [ ] Limits and unverified things listed in [known-issues.md](known-issues.md) with what
      removes them.
- [ ] New files have a row in [README.md](README.md); links resolve.

## Sources

- Diataxis: https://diataxis.fr/
- AGENTS.md: https://agents.md/
