## What and why

Closes #

**Derives from:** `[P§__]`
**Governed by ADR:** ADR-____ (or: `not architectural, because …`)

<!-- One paragraph. What changed, and what problem it solves. -->

## Responsibility check `[P§34]`

- **This change adds/modifies responsibility:**
- **Which layer owns it:**
- **Why it does not belong to an existing component:**

> If this introduces a module and you cannot answer cleanly, stop — the boundary is wrong.

## Evidence

<!-- Required for any performance, accuracy, or "this is better" claim [P§29.3][P§29.10] -->

- **Baseline compared against:** EXP-________ / n/a
- **Measured result:** <!-- accuracy AND system metrics AND target constraint -->
- **Conditions identical to baseline?** yes / no — if no, the comparison is void

## Checklist

- [ ] Linked issue exists and this PR closes it
- [ ] Acceptance test written **first** and shown failing before implementation
- [ ] `ruff` + `mypy` clean; full test suite passes
- [ ] No provider name / SDK outside the LLM gateway `[P§20]`
- [ ] No reasoning ↔ orchestration ↔ knowledge ↔ execution leakage `[P§19]`–`[P§22]`
- [ ] No reimplementation of existing NVIDIA / vendor capability `[P§15]`
- [ ] Any gated action has an approval record `[P§24]`
- [ ] Experiment rows complete per `[P§25]` (if any run was performed)
- [ ] `docs/state/STATUS.md` rewritten
- [ ] `docs/state/JOURNAL.md` appended
- [ ] `docs/state/DECISIONS.md` appended (if a decision was made)
- [ ] `docs/state/OPEN_QUESTIONS.md` updated
- [ ] Diff under ~400 lines, or the split was justified in the issue
- [ ] `docs/PROJECT.md` untouched

## Deliberately not done

<!-- Scope you saw and left alone, with the issue number if you filed one. -->

## Uncertain about

<!-- Where you want the reviewer to look hardest. -->
