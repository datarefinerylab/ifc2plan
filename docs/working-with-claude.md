# Working on ifc2plan with Claude Code

A practical handout: how to plan work, turn it into GitHub issues, and close them.
Repo context Claude loads automatically lives in [`../CLAUDE.md`](../CLAUDE.md) — this file is for you.

---

## 0. One-time setup

```bash
cd ~/Projects/ifc2plan
claude
```

Two things worth doing before the first real session:

**A working Python env.** Nothing is installed for the system `python3` right now. Ask Claude:

> Set up a `.venv` here from requirements.txt, then run the geometry engine self-test and the `--overview` command on the Schependomlaan example to confirm the toolchain works. Report what breaks.

**Issue labels.** The repo carries GitHub's *default* label set (`bug`, `enhancement`,
`documentation`, `question`, `duplicate`, `invalid`, `wontfix`, `help wanted`,
`good first issue`), so don't try to create `bug` — it already exists and the command
fails. `geometry` has been added. The rest are still missing:

```bash
gh label create infra   --color 5319e7 --description "Env, packaging, CI, tests"
gh label create paper   --color fbca04 --description "Needed for publication"
# `feature` is redundant with the built-in `enhancement` — pick one and stick to it.
```

`gh repo set-default datarefinerylab/ifc2plan` is per-clone (it lives in `.git/config`,
which isn't committed), so run it once in a fresh clone. The repo is no longer a fork and
has a single remote, so there's nothing for `gh` to mis-resolve after that.

---

## 1. The loop

```
   plan ──────► issue ──────► branch ──────► fix ──────► review ──────► PR
 (plan mode)    (gh)         (git)        (Claude)   (/code-review)   (gh)
```

Each stage is one prompt. Don't try to do all five in a single message — you lose the chance to correct course, and Claude does its worst work when the target is vague.

### Stage 1 — Plan (use plan mode)

Press **Shift+Tab** until the prompt shows `plan mode`. Claude will investigate and propose, but not edit files. This is the right mode for anything you haven't fully specified yet.

> Read `ifc_processor.py` and `geometry_engine.py` and work out why door polygons come out non-rectangular while spaces are fine. Give me the two or three most likely causes, ranked, with the evidence for each and how I'd confirm which one it is. Don't change anything yet.

When the plan looks right, approve it and Claude switches to executing. If it's wrong, say what's wrong — the plan gets revised, not thrown away.

For a bigger sweep, ask for a parallel investigation:

> Use the Explore subagent to find every place in the codebase where a length or elevation value is scaled by 1000 or 2000, or where a unit is assumed. I want the full list before we touch anything.

### Stage 2 — Turn it into issues

> Based on that analysis, open GitHub issues on `datarefinerylab/ifc2plan`. One issue per independently-fixable problem. Each needs: a one-line title, observed vs expected behaviour, the exact command to reproduce on the Schependomlaan example, the file:line where you think it originates, and a definition of done. Label them appropriately. Show me the bodies before creating anything.

Always ask to see the bodies first — issues on this repo are visible to the lab.

Good issue hygiene here, given there are no tests:

- **Reproduce command in every issue.** `cd src/ifc2plan && python extract_floor_plans.py … --storey 0`
- **Definition of done is an observable output**, not "code is fixed". e.g. *"every IfcDoor polygon in `02 tweede verdieping_floor_plan.csv` has exactly 5 WKT coordinate pairs (4 corners + closure)"*.
- **Output filenames come from the storey name, not an index.** The output directory is
  `{--output}/{ifc file stem}` (`extract_floor_plans.py:51`) and the formatters append
  `{storey name}_floor_plan.csv` (`formatters.py:555`) or `_floor_plan{style}.png`
  (`formatters.py:370`). So real paths contain spaces —
  `output/IFC Schependomlaan/02 tweede verdieping_floor_plan.csv`. Quote them.
- **Attach the evidence.** `gh issue create … ` then drag the bad PNG into the web UI, or reference the output path.

### Stage 3 — Fix one issue

> Work on issue #3. Read it, check out a branch `fix/door-geometry`, make the smallest change that satisfies the definition of done, then run it on storey 0 of the Schependomlaan example and show me the door polygons before and after.

Keep one issue per branch. When Claude starts drifting into adjacent problems, stop it (**Esc**) and say so — the drift is usually a real finding, so ask for it as a new issue instead of a bigger diff.

### Stage 4 — Review before you trust it

```
/code-review
```

Reviews your working diff. For a heavier multi-agent pass on the whole branch, `/code-review ultra`.

Then verify yourself — this codebase has no safety net:

> Run the full extraction on all storeys of the example file, both `--formatter image wkt`, and tell me what changed versus main. Diff the CSVs, don't just eyeball the PNGs.

### Stage 5 — PR

> Commit with a message referencing #3, push the branch, and open a PR against main summarising what changed and how it was verified.

---

## 2. Ready-to-paste prompts for the current backlog

**Door and window geometry — done, see #1 and #2**

Both are fixed. The cause was not either of the two suspects originally listed
here: `trimesh.Trimesh(verts, faces)` welds vertices shared between separate solids,
fusing a door's leaf and frame into one torn surface, after which the section tracer
traced chains that hopped between parts and had to be force-closed with invented
edges. Fixed by `process=False` plus sectioning each solid on its own.

Windows had the same defect (they were never separately broken) — 63% → 78%
rectangular. That closes the "windows, unconfirmed" question.

Worth knowing for future geometry work: **"rectangular" is a bad success metric.**
A real door section legitimately contains L-shaped frame profiles and folded sheet
channels. Verify correctness instead — every polygon should come from a watertight
solid, and areas can be checked independently by ray casting.

**Section height (issue #3 — the biggest remaining defect)**

> Storey `[0]` of the example produces no intersections at all, and 45 of 205 doors never reach their storey's cutting plane. `process_storeys` hard-codes millimetre elevations and never reads the model's `IfcUnitAssignment`. Make the cut height derive from the declared unit plus a documented CLI offset, and report every element that misses the plane rather than dropping it silently.

**Per-unit output instead of per-floor**

> New feature: output grouped per dwelling unit rather than per storey. Before proposing an implementation, tell me how unit membership could be determined from IFC in this file — IfcZone, IfcGroup, spatial containment, space naming? Show me what's actually present in the example model. Then propose the CLI surface.

**Units / elevation handling**

> `process_storeys` hard-codes millimetre elevations and never reads the model's IfcUnitAssignment. Confirm this is a real bug for a metre-based IFC file, then open an issue.

**Making it testable**

> We have no test suite and every fix is verified by hand. Propose the minimum viable test setup: a few pytest cases over a small synthetic IFC (or fixtures extracted from the example) covering section-height calculation, polygon validity, and door corner count. Keep it lightweight — this is a research tool, not a product.

**Paper support (abstract due Sep 15)**

> I'm writing an abstract on this tool. Summarise the actual technical contribution from the code as it stands: what the pipeline does, what's novel about the approach, and what its current limitations are. Be honest about the limitations — I'd rather know now than have a reviewer find them.

---

## 3. gh cheat sheet

```bash
gh issue list --label geometry              # what's open
gh issue create --title "…" --body-file /tmp/body.md --label bug,geometry
gh issue view 3 --comments
gh issue close 3 --comment "Fixed in #7"
gh pr create --fill                         # after pushing a branch
gh pr checks
```

Claude can run all of these. Your token has `repo` scope, so issue and PR creation works without extra setup.

---

## 4. Things worth knowing

| Thing | Why it matters here |
|---|---|
| **Shift+Tab** | Cycles plan mode / auto-accept. Use plan mode for anything geometry-related — the reasoning is the valuable part. |
| **`@src/ifc2plan/ifc_processor.py`** | Drops a file into context directly instead of making Claude hunt for it. |
| **`!` prefix** | `!git log --oneline -5` runs it in-session and the output lands in the conversation. Use for anything interactive (`gh auth login`, activating an env). |
| **`#` prefix** | Appends a fact to `CLAUDE.md`. When you discover a gotcha mid-session, `#` it immediately so the next session knows. |
| **Esc, Esc** | Rewind to an earlier message and take a different path — cheaper than arguing with a bad direction. |
| **`/clear`** | Between unrelated tasks. Stale context is the main cause of Claude "forgetting" what you just told it. |
| **Background bash** | A full-model extraction on the 47 MB example is slow. Ask Claude to run it in the background and keep working. |
| **`/code-review`** | Your working diff, before you commit. |
| **Subagents** | Only worth it for genuine fan-out searches ("find every place X happens"). For normal work they just re-derive context you already have. |

### A custom `/issue` command (optional)

Create `.claude/commands/issue.md` in the repo if you find yourself repeating the issue-creation prompt:

```markdown
Turn the following into a GitHub issue on datarefinerylab/ifc2plan: $ARGUMENTS

Required sections: Observed / Expected / Reproduce (exact command against
examples/data/Shependomlaan) / Suspected origin (file:line) / Definition of done
(an observable property of the output, not "code is fixed").
Pick labels from the existing set. Show me the body before creating it.
```

Then: `/issue doors come out as 6-point polygons on storey 2`

---

## 5. Guardrails

- **Never let a fix land unverified against the example file.** No tests means Claude cannot self-check, and geometry bugs are invisible in a diff.
- **Ask before pushing.** `origin` is the lab's repo, not a personal fork.
- **Watch for silent failures.** `process_ifc_element` returns `None` on any exception; a "successful" run can quietly drop half the doors. If element counts change after a fix, that's a finding, not noise.
- **Don't let scope grow.** This codebase has real structural problems (no packaging, flat imports, no tests). Fixing them is legitimate work — but as its own issue, not smuggled into a door-geometry PR before a deadline.
