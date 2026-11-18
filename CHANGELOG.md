# Changelog

## v2 — November 2026 (`study_tag: agency_tracing_v2`)

Changes made after two pilot sessions (IDs `003` and `sam`, 26 Oct 2026). The agency effect behaved as
expected in both (PSE ≈ 125–130 ms), but the pilots exposed problems with tracing compliance, the debrief,
and one of the complexity measures.

### Experiment (`index.html`)

| Change | Why |
|---|---|
| **Pacing demo** before practice: a grey dot circles the ring at one lap every 3 s (`pace_lap_s`), and the instructions ask for one direction and staying on the ring. | `003` traced at ~10 s per lap, so a 120-ms lag moved the dot only ~15 px. `sam` scribbled at up to 2.4 laps/s. Pace sets how *visible* a given delay is, so it needs to be kept similar across people. |
| **Feedback screen after a stretch** when tracing was off the ring (>25% of frames beyond ±40 px), reversing (>15% of the path backwards), too slow (<0.15 laps/s) or too fast (>0.75 laps/s). It appears only **after** the agency rating, so it cannot colour that rating. `feedback: false` turns it off. | `sam` drifted from tracing into scribbling within 4 stretches and never recovered. Nothing in v1 told them. |
| **New per-stretch fields:** `laps_per_s`, `off_ring_frac`, `backward_frac`, `direction`, `ring_tol_px`, `canvas_px`, `ring_radius_px`, `stretch_index`, `qc_feedback`. | Tracing quality is visible in the data without reprocessing, and the analysis no longer has to assume the geometry. |
| **Set-up questions:** input device (with a prompt to switch to a mouse) and hand used. Screen size, pixel ratio and user-agent string are added to every row. | `sam`'s data looks like a trackpad or a fast flick style; there was no way to tell. `sam` also ran at 120 Hz and `003` at 60 Hz. |
| **Debrief:** the single 4-option question is replaced by *"Did the dot ever change colour?"* (yes/no/not sure) plus an optional free-text comment. | The instructions already tell people the dot sometimes lags, so "did it lag?" carried no information (`003` chose "changed colour" only despite rating 300 ms near 0). The colour flash is the actual attention check. |
| Dev mode: flash window scaled to the 3-s stretch (it never fired in v1 dev runs); shorter pacing demo. | Testing. |

The trial structure is unchanged: 5 delays × 6 repetitions + 6 flash controls at 0 ms, 3 blocks, 20-s
stretches, the same rating prompt and slider.

### Analysis (`analyze_tracing.py`)

* Takes a folder or a list of files; reads **v1 and v2** files; runs sessions in parallel.
* Writes `trials.csv`, `participants.csv`, `report.txt` and five figures plus a trajectory sheet per
  participant (see README).
* **Exclusion rules** at stretch and participant level (see README), all adjustable from the command line.
  Slow tracing is flagged, not excluded, by default.
* **Per-participant psychometric fit**, `agency = 100 / (1 + exp((delay − PSE)/slope))`, with a
  bootstrap CI on the PSE, plus Spearman ρ and within-session drift (holding delay constant).
* **Models:** pace (laps/s) and stretch number are added as covariates. `003`'s agency at intermediate
  delays rose ~1.5 points per stretch, and `sam`'s sample entropy fell with delay only because they
  slowed down under lag. The models use a random delay slope when estimable. With fewer than 6 included
  participants the script fits one ordinary regression per participant, because a random intercept over
  2 people collapses to zero variance (as the v1 script's output did).
* **Complexity shadow 2 replaced:** `crqa_det` (hand × lagged dot, radius = 10% of the maximum distance)
  becomes `rqa_det`, the determinism of the hand's angular-velocity dynamics (embedding dimension 3, delay
  60 ms, z-scored) at a **fixed 5% recurrence rate**. The old measure sat at 0.996–0.999 in every condition
  for `003`. Because the dot replays the hand's own path, the hand × dot cross-recurrence plot is just the
  hand's own recurrence plot shifted by the delay, so it cannot respond to the delay. Fixing the recurrence
  rate keeps DET comparable across stretches of different speed and amplitude.
  **This is a deviation from the protocol's H2/H3 measure and should be recorded as such.**
* Sample entropy (shadow 1) is unchanged in definition, now computed with O(n) memory.

## v1 — September 2026 (`study_tag: agency_tracing_v1`)

Initial version.
