# EVALUATION CONTRACT

Derived from `[P§12]`, `[P§13]`, `[P§27]`, `[P§29.2]`, `[P§29.4]`, `[P§29.10]`.

> The agent must be measurement-driven, and **never optimize only one metric** `[P§12]`.

## The composite result rule

No result is reportable as a single number. Every evaluation reports, together:

```
ACCURACY  +  SYSTEM PERFORMANCE  +  TARGET CONSTRAINT  +  BASELINE DELTA
```

A model at **99% mAP** that yields **2 FPS** on the target when the application requires
**20 FPS** is a **failure**, not a success `[P§12]`. Report it as one.

## Metric sets `[P§12]`

**Detection** — Precision · Recall · F1 · mAP@0.5 · mAP@0.5:0.95 · IoU · AP per class.

**Classification** — accuracy · precision · recall · F1 · confusion matrix · ROC-AUC ·
PR-AUC.

**Tracking** — MOTA · IDF1 · HOTA · ID switches · track fragmentation.

**System** — FPS · end-to-end latency · inference latency · throughput · GPU util ·
CPU util · VRAM · RAM · power · thermal behavior.

Per-class and per-condition breakdowns are mandatory where the deployment has asymmetric
cost (a security application's recall on the rare event matters more than its mean).

## Operating point, not just curves

Every reported detection/classification result names the **operating threshold** and the
false-positive tolerance it was chosen against `[P§5]`. "High recall" without stating the
false-positive rate at that threshold is not a result.

## Baseline discipline `[P§29.2]`, `[P§11]`

Before any optimization the following must exist and be recorded in `EXPERIMENTS.md`:

```
baseline model → baseline accuracy → baseline latency → baseline memory
              → baseline power → identified bottleneck
```

Only then is optimization — quantization, pruning, NAS, kernel work — justifiable, and
the justification names the bottleneck it addresses.

## Failure analysis is mandatory `[P§27]`

An evaluation that stops at `mAP = 72%` is incomplete. It must ask **why the 28% fail**,
categorized:

small objects · occlusion · blur · low illumination · camera angle · compression ·
class confusion · localization error · false positives · domain shift · temporal
instability · tracking failure · **annotation error**

Then follow the chain, recording each step:

```
failure pattern → root-cause hypothesis → experiment → measurement → decision
```

Annotation error is listed deliberately: check the labels before blaming the model.

## Split integrity `[P§26]`

Every evaluation states how leakage was excluded — **temporal leakage** and **camera
leakage** especially, which are the standard way CCTV projects produce fake numbers.
Frames from one video, or one camera, must not straddle train and test.

## Comparison rules `[P§29.3]`, `[P§29.10]`

- Same dataset version, same split, same operating point, same target hardware — or the
  comparison is void.
- A newer model is not better because it is newer.
- A vendor benchmark is not a measurement on your data.
- Improvements are reported with the delta against the named baseline, not in isolation.
- No optimization is accepted without post-optimization accuracy re-measurement:
  quantization that gains 2× FPS and silently loses 6 points of recall is a regression.

## Reporting template

```
EXP-…  vs baseline EXP-…
Dataset <version>, split <name>, threshold <t>, target <hardware>

accuracy   mAP@.5:.95 __  (Δ __)   recall __ (Δ __)   FP/hour __
system     FPS __ (need __)  e2e latency __ ms  VRAM __  power __
verdict    meets / fails target constraint: <which one, by how much>
failures   top 3 categories with share of error
next       recommended experiment and what it tests
```
