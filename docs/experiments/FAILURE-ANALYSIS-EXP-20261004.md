# Failure analysis: EXP-20261004-01..04 (IoU-matched, descriptive)

**Status: descriptive only.** No pass/fail criterion, no acceptance threshold, no operating point and no
production choice. Q30 (operating point and precision floor) stays **OPEN**. D-069 stays **OPEN**. Q27 stays
**OPEN**. The thresholds below are analysis parameters, not production criteria.

Source: ADR-0015 §9 (issue #75). Read-only, deterministic, from existing prediction artifacts and YOLO labels.
No GPU inference, no new ledger rows.

## Provenance

- EXP-20261004-01: predictions sha256 `2d00b55986646a87d941dab1c2951c1bc0f239058018f8eca74f1904223a8e59` (matches recorded provenance), commit `2463ee5bbef52203d5494ce7ccd99b7929fbb7a2`, images listed 5000, background images 48, GT persons 10777.
- EXP-20261004-02: predictions sha256 `fecf59ef69170de17efe61655a54ce80e6e0d5cc8ec16dc78584488b39a8f772` (matches recorded provenance), commit `2463ee5bbef52203d5494ce7ccd99b7929fbb7a2`, images listed 5000, background images 48, GT persons 10777.
- EXP-20261004-03: predictions sha256 `2c92cf7f917fed91ac4cfcf1294efae3fdce6aca3174e550b01c3d6c9b526bcf` (matches recorded provenance), commit `2463ee5bbef52203d5494ce7ccd99b7929fbb7a2`, images listed 5000, background images 48, GT persons 10777.
- EXP-20261004-04: predictions sha256 `8cc55342a3bb836f8f480ce7f1efff600e0543771a882afe5ac74e972a1f1608` (matches recorded provenance), commit `2463ee5bbef52203d5494ce7ccd99b7929fbb7a2`, images listed 5000, background images 48, GT persons 10777.

## Bottleneck ranking, EXP-20261004-01 (descriptive)

Share of **all GT persons** at the reference threshold 0.25. Ties break by name.

- no_overlap: 3059 (28.4%; 95% CI 27.0%–29.8%)
- near_miss: 443 (4.1%; 95% CI 3.7%–4.5%)
- competed: 53 (0.5%; 95% CI 0.4%–0.6%)

Fully missed (no prediction at any score overlaps at IoU >= 0.5): 933 (8.7%; 95% CI 7.8%–9.5%)

Missed at the reference threshold: 3555 (33.0%; 95% CI 31.6%–34.4%)

## Size and density strata (box-area bins; descriptive)

- small: GT 2552, fully missed 769, missed at 0.25 1863 (share of this stratum's GT 73.0%; 95% CI 70.6%–75.2%)
- medium: GT 3689, fully missed 126, missed at 0.25 1271 (share of this stratum's GT 34.5%; 95% CI 32.3%–36.5%)
- large: GT 4536, fully missed 38, missed at 0.25 421 (share of this stratum's GT 9.3%; 95% CI 8.3%–10.3%)
- sparse: GT 3908, fully missed 204, missed at 0.25 851 (share of this stratum's GT 21.8%; 95% CI 20.2%–23.4%)
- dense: GT 6869, fully missed 729, missed at 0.25 2704 (share of this stratum's GT 39.4%; 95% CI 37.5%–41.2%)

## Comparisons (descriptive, one run each)

- EXP-20261004-01: fully missed 933, missed at 0.25 3555, unmatched predictions at 0.25 2075, at 0.50 441.
- EXP-20261004-02: fully missed 542, missed at 0.25 2879, unmatched predictions at 0.25 2962, at 0.50 743.
- EXP-20261004-03: fully missed 468, missed at 0.25 2789, unmatched predictions at 0.25 4102, at 0.50 1226.
- EXP-20261004-04: fully missed 927, missed at 0.25 3559, unmatched predictions at 0.25 2079, at 0.50 442.

## Key descriptive findings (computed from the tables; no production decision)

- Descriptive bottleneck under the agreed definition (EXP-20261004-01): `no_overlap`, 3059 GT persons (28.4% of all GT at reference 0.25).
- Small boxes account for 1863 of 3555 misses at 0.25 (52.4%), from 2552 of 10777 GT (23.7%).
- Fully missed rate by box-area bin (share of that bin's GT): small 30.1% (769/2552), medium 3.4% (126/3689), large 0.8% (38/4536). By density: sparse 5.2% (204/3908), dense 10.6% (729/6869).
- Precision check, 640 FP16 vs 640 FP32 (one run each): fully missed 933 vs 927; missed at 0.25 3555 vs 3559; unmatched predictions at 0.50 441 vs 442. One run per condition: no run-to-run variance is estimated, so this comparison cannot show a precision effect either way.
- Resolution, 640 -> 960 -> 1280 (FP16, one run each): fully missed 933 -> 542 -> 468; unmatched predictions at 0.25 2075 -> 2962 -> 4102; unmatched at 0.50 441 -> 743 -> 1226. Descriptive only; no winner is declared.


## Method and accepted deviations (issue #75; owner decisions 2026-10-04)

- **Read-only ledger lookup.** Each run's expected predictions sha256 is read from its recorded ledger notes over a read-only connection (`mode=ro`). No ledger row is written or altered.
- **Strict label parsing.** A malformed GT line refuses the whole analysis. Nothing is skipped silently.
- **Q28 full-curve gate (input-integrity and protocol, not a production criterion).** A run whose lowest person score is above 0.002 is refused as truncated, because the reference thresholds and the bins would not be computed on a full PR curve.
- **Partition of GT boxes at the reference threshold 0.25.** Every GT box is exactly one of: matched at reference, competed, near-miss, or no-overlap. The `competed` category is a diagnostic sub-category of missed-at-reference: the box overlaps a score >= 0.25 prediction at IoU >= 0.5, but the greedy assignment went to another GT box. It does not replace fully-missed, missed-at-reference, near-miss or no-overlap.
- **Fully missed** is a separate definition: no prediction at any score (>= 0.001) overlaps the GT box at IoU >= 0.5.
- **Degenerate GT boxes (a side < 2 px)** are a descriptive review heuristic. They are not an annotation-quality standard.
- **Near-duplicate GT pairs (IoU >= 0.90)** are a review heuristic. They are not an annotation-quality standard.


## Limitations (required)

- Box-area bins are descriptive normalized box-area bins. They are not official COCO size categories: COCO uses absolute annotation area in pixels (32^2 and 96^2). The ADR-0015 §3.4 cut-offs approximate those for roughly 640x480 images only.
- Official COCO size-stratified mAP is Q27. It needs instances_val2017.json, which is not downloaded. Q27 remains open. Nothing here closes it or supports a published claim.
- Crowd (iscrowd) annotations cannot be identified without instances_val2017.json. Crowd-related error is reported as not measured, never as zero.
- Matching is the greedy IoU >= 0.5 rule of cv_agent.experiments.detection_metrics. It is not the COCO evaluator.
- All thresholds (IoU 0.30, score 0.25, score 0.50, side < 2 px, IoU 0.90) are descriptive analysis parameters, not production criteria. Q30 and D-069 remain OPEN.
- Human review labels are not assigned by this analysis. Any agent-proposed label is preliminary only.

## Not measured (reported as not measured, never as zero)

- occlusion and crowd (needs instances_val2017.json iscrowd): not measured
- blur: not measured
- illumination: not measured
- camera angle: not measured
- compression: not measured
- class confusion (runs are persons-only): not measured
- domain shift: not measured
- temporal instability: not measured

## Review candidates

Candidate counts only. Nothing here labels an annotation as wrong. Human review results are recorded separately.

- high-confidence false positives (score >= 0.50, unmatched): 441
- near-duplicate GT pairs (IoU >= 0.90): 2
- degenerate GT boxes (a side < 2 px): 11
