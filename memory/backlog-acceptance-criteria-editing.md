---
name: backlog-acceptance-criteria-editing
description: Backlog CLI gotchas for editing acceptance criteria + sections; the safe AC-replace recipe
metadata:
  type: feedback
---

Editing Backlog tasks must go through the `backlog` CLI (never edit the task
`.md` directly — project CRITICAL rule), but the CLI's editors are coarse and
have sharp edges learned the hard way (2026-06-21, the TASK-5 re-baseline):

- **`--acceptance-criteria` does NOT replace in place.** It silently appends /
  no-ops, producing **duplicate ACs** (it corrupted a task this way). Do not use
  it to rewrite an existing criterion.
- **`--remove-ac N` renumbers** the criteria after N, and **`--ac` appends** at
  the end. So remove+add for one AC **reorders** the list (and breaks any prose
  that references "AC #N").
- **To replace AC text while preserving numbering:** extract all current ACs,
  apply the edit, then **remove ALL ACs (highest index → lowest in one call) and
  re-add ALL in order** via repeated `--ac`. Verify count + no duplicates after.
- **Sections (`--description`, `--plan`, `--notes`) only replace wholesale** — no
  partial/in-place edits. For a token/line fix, extract the section body (between
  its `<!-- SECTION:*:BEGIN/END -->` markers), transform, and set the whole thing.
- **A stale string can live in several places at once** — frontmatter (incl.
  `references`, fixed via `--ref`, which replaces the whole list), description, AC,
  and plan are independent; grep the *whole file* and fix each section's tool.
- **Always verify with `git diff` after** — the CLI bumps `updated_date` and may
  normalize blank lines; confirm only the intended text changed and nothing was
  dropped.

**Why:** the CLI tooling is lossy/surprising, and these tasks are long and
detailed — a careless edit silently drops or duplicates content.

**How to apply:** for any non-trivial AC/section edit, prefer a scripted
extract→transform→set with assertions (match-count == 1), then a `git diff`
review; budget for it being fiddly rather than a quick one-liner. See
[[respect-repo-boundary]] for the don't-touch-md-directly constraint's sibling.
