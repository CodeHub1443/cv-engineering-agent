# D-043 video research: small stratum, datasets, VIRAT agreement

Evidence for ADR-0025 and decisions D-122 to D-126. Research only: no dataset was downloaded, and no video or frame was opened. All web pages were accessed 2026-11-16. Anything not verified against a primary source is marked **UNVERIFIED**. This is not legal advice; counsel must confirm the VIRAT reading.

## 1. The small stratum in pixels

ADR-0015 §3.4 uses normalised box area: small is `w*h < 0.0025`, medium is `< 0.023` (`detection_metrics.py:32-33`). Person aspect w:h of 0.4 is an **assumption**.

| Frame | Pixels | Small below | Person box (assumed) | Medium below | Person box |
|---|---|---|---|---|---|
| 640×360 (test video metadata, ffprobe) | 230,400 | 576 px² (about 24×24) | about 15×38 | 5,299 px² | about 46×115 |
| 1920×1080 | 2,073,600 | 5,184 px² (72×72) | about 46×114 | 47,693 px² | about 138×345 |
| 640×480 (MOT17-05) | 307,200 | 768 px² | about 18×44 | 7,066 px² | about 53×133 |

- At imgsz 768 a 16:9 frame becomes 768×432, so small means under 829 px² at the network input for every 16:9 source.
- COCO small is an absolute 32² = 1,024 px²: ADR-0015 small is stricter at 640×360 and 5 times larger at 1080p.
- How many persons in a 640×360 frame are small is **UNKNOWN**: the video has no labels and no frame was viewed. A histogram of EXP-20260929-01 detection boxes (detections, not persons) is the only proxy, and those files are on the Linux PC.
- MEVA per-camera resolution and fps: **UNVERIFIED** (1920×1080 is only the maximum in the paper's comparison table).

## 2. Datasets

### MEVA: rejected

- Licence: "All MEVA data is available for use under a CC BY-4.0 license" (mevadata.org); the licence file says "licensed under a Creative Commons Attribution 4.0 International License". Exception: drop-4-hadcv22 "may not be used for training any submissions to the NIST ActEV leaderboards".
- Size: 328 hours, 516 GB, 4,259 clips (site, AWS registry); the README says about 330 hours, 4,001 clips, 470 GB (**the sources conflict**). Annotated: 64 hours (769 five-minute clips) evaluation-level and 120.2 hours (1,443 clips) training-level. H.264 in AVI. Access is S3 `mevadata-public-01`, no account.
- Annotation format: **UNVERIFIED** (gitlab.kitware.com returned 403).
- **Disqualifying:** paper §4.2, "objects were tracked with bounding boxes for the duration of their involvement in the activity". Person boxes are not exhaustive, so precision, the D-077 floor and HOTA false positives would be biased by an unknown amount.

### MOT17: verified, non-commercial (CC BY-NC-SA 3.0)

- Licence text: "published under the Creative Commons Attribution-NonCommercial-ShareAlike 3.0 License (CC BY-NC-SA 3.0)"; for third-party sequences "the conditions of the original source may apply in addition". D-122 allows it for internal evaluation only.
- Train: 7 sequences, **5,316 frames** (600, 1,050, 837, 525, 654, 900, 750), 546 tracks and 112,297 boxes (my sum of the page rows). The page total 15,948 is 3 detector variants of 5,316; MOT16 paper Table 2 also gives 5,316. MOT17.zip 5.5 GB, MOT17Labels.zip 9.7 MB. Six sequences are 1920×1080 (five at 30 fps, MOT17-13 at 25 fps); MOT17-05 is 640×480 at 14 fps.
- The earlier "292,733 boxes, 1,342 tracks" are MOT16 totals, not MOT17.
- Format (verified for MOT16, paper §3.3 Tables 5 and 6): nine columns (frame, id, left, top, width, height, consider flag, class, visibility), 1-based. Classes 7, 8 and 12 are neutral (§4.1.3). That MOT17 uses the same format is **UNVERIFIED**. Exhaustive annotation: "annotate all moving or standing (upright) pedestrians".
- **Availability risk:** the motchallenge.net root returned HTTP 410 Gone and the MOT17 page was an archived copy. Whether it can still be downloaded is **UNVERIFIED**.

### VIRAT Ground: commercial use allowed, revocable

- Agreement (VIRAT Video Dataset Usage Agreement): "You may use the Dataset for lawful research and commercial purposes." "All individuals with access to the Dataset must sign this Agreement." "You agree to protect against the disclosure of Personally Identifiable Information ("PII")." "You shall not distribute any portion of the Dataset to any third party, except those parties who have agreed to the terms ... provided, however, that you may publish a few video frames or short video clips in scientific publications or lectures."
- Termination: "Kitware has the right to terminate this Agreement and your rights to use the Dataset, or any portion of the Dataset, at any time, without notice. In the event that Kitware terminates this Agreement you must immediately cease use of the Dataset and return or destroy all copies, derivatives and related documentation of the Dataset." It also ends immediately "if in Kitware's sole discretion you fail to comply".
- The agreement date and version are **UNVERIFIED** (filename "1-4-11"; PDF created 2018-11-05).
- viratdata.org: Release 2.0 ground data is about 8.5 hours of HD video, "2-30Hz frame rates and 10-200 pixels in person-height"; annotations have "full tracks on all movers", 46 activity types and 7 object types.
- **UNVERIFIED:** number of videos, resolutions, download size, `objects.txt` columns and person type code, annotation licence, and whether static persons are labelled (gitlab 403; release PDF unreadable).

## 3. Is revocation without notice a blocker? (D-123)

- Not for evaluation-only use: commercial use is explicit. The cost of revocation is reproducibility `[P§25]`: baselines on VIRAT could no longer be re-run, and derived files must be destroyed.
- Open question: whether ledger metrics count as "derivatives" (Q74).
- It is a blocker for training or shipping models on VIRAT (weights may be derivatives) and for giving frames to any unsigned party, including a hosted LLM.
- Conditions: everyone with access to the Linux PC signs; the data stays on that PC; derived files are tracked so they can be destroyed; no training. Counsel must accept the agreement first (Q73).

## 4. Estimates (none measured on video)

| Item | Estimate | Assumption |
|---|---|---|
| COCO replication R1, about 1 min, 0.017 GPU-h | measured anchor | 55.7 to 61.1 s wall for the same workload (EXPERIMENTS.md L375, L451, L487) |
| Inference 8.8 ms per frame | measured, inference only | EXP-20260929-01 (EXPERIMENTS.md:80) |
| R2 on MOT17 train, 2 to 4 min | estimate | 5,316 frames at 20 to 40 ms; 1080p decode and conf 0.001 NMS dominate |
| R2 on VIRAT, 4 to 7 min per 10k frames | estimate | same per-frame assumption; subset not chosen |
| Frames on disk, 3 to 5 GB per 10k frames | estimate | 0.3 to 0.5 MB per 1080p JPEG |
| End-to-end tracking FPS | unmeasured | floor set from R3 |

ByteTrack determinism is **untested until R3**.

## 5. The smoke-test video

The owner's test video has the same size (3,580,076 bytes) and header as `tests/fixtures/person_detection_sample.mp4`, which is tracked in git (D-085). The owner confirmed the two are identical by sha256 (D-126), so smoke run S1 is skipped. No frame was viewed.

## 6. Sources (accessed 2026-11-16)

- MEVA: [mevadata.org](https://mevadata.org/) (official); [licence file](https://mevadata.org/resources/MEVA-data-license.txt); [README](https://mevadata.org/resources/README-meva-kf1-data.html); [transcoding FAQ](https://mevadata.org/transcoding-faq.html); [AWS registry](https://registry.opendata.aws/mevadata/); [Corona et al., arXiv 2012.00914](https://arxiv.org/html/2012.00914) (peer-reviewed). gitlab.kitware.com returned 403.
- MOT: [motchallenge.net/data/MOT17](https://motchallenge.net/data/MOT17/) (official, archived copy); [Milan et al., MOT16, arXiv 1603.00831](https://arxiv.org/abs/1603.00831) (peer-reviewed).
- VIRAT: [usage agreement PDF](https://actev.kitware.com/pub/VIRAT-Video-Data-Set-Protection-Agreement-1-4-11.pdf) (official); [viratdata.org](https://viratdata.org/) (official). gitlab.kitware.com viratannotations returned 403.
- Tooling (read in the first planning round): [TrackEval](https://github.com/JonathonLuiten/TrackEval) (MIT); [Luiten et al., IJCV 2021](https://link.springer.com/article/10.1007/s11263-020-01375-2); [Ultralytics track docs](https://docs.ultralytics.com/modes/track).
