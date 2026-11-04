# Annotation-label review: EXP-20261004-01 primary-sample candidates

**Descriptive review only.** No production decision is made. Q30 (operating point and precision floor)
stays **OPEN**. D-069 stays **OPEN**. Q27 (official size-stratified mAP and crowd status) stays **OPEN**.

## Scope and objective

The 63 candidates come from the primary-run review sample of the failure analysis (`docs/experiments/FAILURE-ANALYSIS-EXP-20261004.md`, ADR-0015 §9.9). The review asks whether each candidate is an annotation error, a valid annotation, or cannot be decided from the evidence. It is the check that EVALUATION §27 requires before a model is blamed.

**This review does not test the small-box bottleneck directly.** None of the 63 candidates is a missed GT box.
**The 63 candidates are not a representative sample** for estimating population annotation-error rates. They were selected by fixed rules and a seeded draw, not at random from the population.

- Rubric version: `annotation-review-rubric/v1 (2026-10-06)`
- Reviewer(s): Tanvir
- Candidate selection: unchanged from the failure analysis (seed 20261004).

## Candidate counts by class

- high_conf_fp: 50
- near_dup_gt_pair: 2
- degenerate_gt: 11
- total: 63

## Human label counts

- valid_annotation: 34
- annotation_error: 5
- ambiguous: 8
- not_reviewable: 0
- crowd_region_unresolved: 0
- unlabelled: 16

## Crowd status (Q27)

- Candidates with crowd status `q27_unresolved`: 63 of 63.
- `instances_val2017.json` has not been downloaded. Crowd status is unknown for every candidate.
- No candidate is labelled as a crowd exclusion. A crowd-like region is recorded as `crowd_region_unresolved`, and it is never scored as an annotation error.

## Rubric

- **High-confidence FP:** `annotation_error` = a visible person at the predicted box that no GT covers. `valid_annotation` = no person is visible there.
- **Near-duplicate GT pair:** `annotation_error` = both boxes mark the same person. `valid_annotation` = two visibly distinct people.
- **Degenerate GT (a side < 2 px):** `annotation_error` = no person is visible at the box. `valid_annotation` = a person is visible and the small box is valid. A box is never erroneous merely because it is small.
- `ambiguous` = the visual evidence cannot decide. `not_reviewable` = the evidence provided is insufficient.

## Limitations

- Single reviewer, no inter-rater check.
- 63 candidates from fixed rules and a seeded draw. Not a representative sample of the population.
- Review views are 2D image context. They cannot establish occlusion or depth.
- Q27 unresolved: crowd-region candidates cannot be separated from missed persons.

## Interpretation: what the review can and cannot establish

- It can say how many of these 63 candidates are annotation errors, valid annotations, or undecidable. Counts cover only the reviewer-labelled candidates (47 of 63); 16 are unlabelled.
- If most sampled high-confidence FPs are `annotation_error`, the labels undercount persons in that sample. The FP counts in the failure analysis then need that caveat.
- It cannot establish whether the 1,863 small-box misses at 0.25 are label errors or model errors. None is in the sample. Testing that needs a separate sample of fully missed small GT, which is out of scope here.
- It makes no production decision. It sets no operating point, precision floor, tolerance or winner.

## Status

- Ranks 001–050 (high_conf_fp) were reviewed by Tanvir on 2026-10-13.
- Ranks 011, 013, and 027 have observation notes but no assigned label.
- Ranks 051–063 (near_dup_gt_pair and degenerate_gt) remain unreviewed and unlabelled.
- Rank 025 (`annotation_error`, mapped from the owner's original `invalid_annotation` term) and rank 041 (`ambiguous`) were resolved by explicit owner confirmation.
- Q30, D-069, and Q27 remain open.

Nothing in this report was entered by the agent. The counts above change only when the reviewer enters labels.
