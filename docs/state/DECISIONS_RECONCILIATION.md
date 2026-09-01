# Decision reconciliation note

This file is a temporary audit note for the Phase 1 reconciliation branch. It is not an
additional decision ledger and must not become authoritative. The authoritative decision
ledger remains `docs/state/DECISIONS.md`.

The intended append-only updates for this reconciliation are:

- D-008 is superseded by D-018 because the project has explicitly restored the
  `main` → `dev-munna` → short-lived branch model.
- D-015 records the short-lived branch rule.
- D-016 records the accepted Q7 LLM gateway decision and points to ADR-0002.
- D-017 records the accepted Q8 dual-layer persistence decision and points to ADR-0004.
- D-018 records the restored project Gitflow.

This note exists only to make the pending ledger reconciliation explicit while the
GitHub contents API is rejecting a safe update to `DECISIONS.md` with a 409 despite the
fetched blob SHA matching the current file. Remove this note after D-015–D-018 are safely
appended to `DECISIONS.md`.
