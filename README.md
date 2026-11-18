# Delayed feedback and the sense of agency — online experiment

Circle-tracing task with lagged visual feedback, hosted on GitHub Pages, with data saved
automatically to a Google Drive folder. Companion to `protocol.pdf` and the project handbook.

**Current task version: v2** (`study_tag: agency_tracing_v2`). What changed after the two pilot sessions,
and why, is in [`CHANGELOG.md`](CHANGELOG.md). v1 files are still read by the analysis script.

```
delayed-tracing/
├── index.html              the experiment (jsPsych 7, single file)
├── google_apps_script.gs   the receiver that writes data into Drive (lives on script.google.com, not in the repo)
├── analyze_tracing.py      JSON files -> trials.csv, participants.csv, report.txt and figures/
├── requirements.txt        Python packages for the analysis
├── CHANGELOG.md            v1 -> v2 changes and the reasons for them
├── .nojekyll               tells GitHub Pages to serve the files as-is
└── README.md               this file
```

Setting up takes about 20 minutes and happens in three parts: **Drive receiver → GitHub Pages → test**.
Do them in this order, because the Pages site needs the receiver's URL.

---

## Part 1 — the Drive receiver (Google Apps Script)

1. In Google Drive, create a folder for the data (e.g. `agency_tracing_data`). Open it. The **folder ID** is the last
   part of the address bar: `https://drive.google.com/drive/folders/`**`1AbC…xyz`**. Copy it.
2. Go to <https://script.google.com> → **New project**. Delete the default code, paste the whole of
   `google_apps_script.gs`, and replace `PASTE_YOUR_DRIVE_FOLDER_ID_HERE` with your folder ID. Save (Ctrl/Cmd+S)
   and give the project a name.
3. **Deploy → New deployment**. Click the gear next to "Select type" → **Web app**. Set
   - *Execute as:* **Me**
   - *Who has access:* **Anyone**

   Click **Deploy**. Google will ask you to authorise the script (it needs permission to create files in your Drive).
   If you see "Google hasn't verified this app", click *Advanced → Go to … (unsafe)* — it is your own script.
4. Copy the **Web app URL** (it ends in `/exec`). Paste it into `index.html` where it says
   `save_url: 'PASTE_YOUR_APPS_SCRIPT_WEB_APP_URL_HERE'`.
5. Check it is alive: open the Web app URL in a browser tab. You should see `{"status":"ok","message":"receiver is up"}`.

> **Every time you edit the script** you must publish a new version, or the live URL keeps running the old code:
> *Deploy → Manage deployments → ✎ (edit) → Version: New version → Deploy.* The URL stays the same.

The receiver writes, per participant session, `<study>_<ID>_<timestamp>.json` (full data with trajectories) and
`<study>_<ID>_<timestamp>_summary.csv` (one row per stretch, no trajectories), and appends a line to `_log.csv`.
The experiment posts at every block break and at the end, overwriting the same two files, so a participant who
closes the browser mid-way still leaves a partial file.

---

## Part 2 — hosting on GitHub Pages

1. On GitHub, create a new **public** repository (e.g. `agency-tracing`). Public is required for free Pages.
2. Upload `index.html` (with your `save_url` pasted in), `.nojekyll`, `analyze_tracing.py`, `requirements.txt`,
   `CHANGELOG.md`, `protocol.pdf` and this README. **Updating from v1:** replace these files in the existing repository
   (*Add file → Upload files*, drag them in, commit). The Pages link stays the same, and your `save_url` is
   already in the new `index.html`. *Do not upload `google_apps_script.gs`* — it is a reminder copy; the live script lives on
   script.google.com, and there is nothing secret in it anyway.
   (Either drag-and-drop in the browser via *Add file → Upload files*, or `git add . && git commit && git push`.)
3. **Settings → Pages**. Under *Build and deployment*, set *Source:* **Deploy from a branch**,
   *Branch:* **main**, folder **/ (root)**. Save.
4. After a minute or two the page reports the address:
   `https://<your-username>.github.io/agency-tracing/`. That is the experiment link.

Whenever you change `index.html`, push the new version; Pages updates automatically within a couple of minutes
(hard-refresh with Ctrl/Cmd+Shift+R if you see the old one).

---

## Part 3 — test before any participant

Three URL switches exist for this. **Never send participants a link with `save=off` or `dev=1`.**

| Link | What it does |
|---|---|
| `…/?dev=1&save=off` | 3-second stretches, 6 main stretches, data downloaded locally. Use first: checks the task runs end to end. |
| `…/?dev=1&id=TEST01` | Same short version, but **saves to Drive**. Use second: confirms the receiver works. Then look in the Drive folder for `agency_tracing_v2_TEST01_…json`. Delete test files before the real study (the analysis also drops `dev=1` sessions automatically). |
| `…/?id=P01` | The real thing, with the ID pre-filled. |

What "working" looks like in the Drive test: the completion screen says *"Your data has been saved"* (not the
"could not be confirmed" message), and the two files plus a `_log.csv` line appear in the folder.

If the completion screen reports that the save could not be confirmed, the data was **downloaded to the computer
instead** (files start with `agency_tracing_v2_…`). The commonest causes: the `save_url` was not pasted in, a new
script version was not deployed, or the Web app was deployed with *Who has access* set to something other than
*Anyone*.

---

## Running a participant

1. Consent on paper or as the lab's standard form; note the participant ID on the session sheet
   (handedness and input device are now also asked on screen).
2. Use a **mouse**, not a trackpad; close other windows and notifications.
3. Open `https://<user>.github.io/agency-tracing/?id=P01` (replace `P01`). The page goes full-screen after the ID.
4. The session is ~25 min: two set-up questions, a pacing demo (one lap every ~3 s), 3 practice stretches,
   36 main stretches in 3 blocks with breaks, then a two-question debrief. If a stretch is off the ring, reversing,
   too slow or too fast, a short note appears *after* the rating. The data uploads itself; the completion screen
   confirms it.
5. Tick the session checklist at the end of `protocol.pdf`.

You can also run it from a local file (double-click `index.html`) — saving to Drive still works — but the Pages
link is the same for every machine, which avoids version drift.

---

## Getting the data out and analysing it

1. In Drive, select all the `.json` files (or the whole folder) → **Download**. Google zips them; unzip into a
   folder, e.g. `data/`. (`_log.csv` and the `_summary.csv` files can stay; only `.json` files are read.)
2. Install the requirements once (Python 3.9+):
   ```
   pip install -r requirements.txt
   ```
3. Run the whole analysis with one command:
   ```
   python analyze_tracing.py data/ --out results
   ```
   It takes about 5–10 s per session (the complexity measures are the slow part; add `--no-shadows` for a
   quick look). Everything lands in `results/`:

   | File | What it is |
   |---|---|
   | `trials.csv` | **The working table.** One row per stretch: participant, block, stretch number, delay, flash, agency rating, tracing error, pace (laps/s), share off the ring, backward share, hand–dot gap, sample entropy, RQA determinism, QC flags, and whether the stretch and participant are included. Open in Excel/R/JASP. |
   | `participants.csv` | One row per session: device, hand, refresh rate, debrief answers, QC summary, include/exclude with the reason, mean agency at each delay, psychometric fit (PSE with bootstrap CI, slope), Spearman ρ, drift per stretch. |
   | `report.txt` | Everything printed on screen, including the H1–H3 models. |
   | `figures/fig1_agency_by_delay.png` | Group curve (mean ± 95% CI, pooled logistic fit) over every included participant. |
   | `figures/fig2_participant_curves.png` | One panel per participant with their fit and PSE; excluded people in orange with the reason. |
   | `figures/fig3_quality.png` | Tracing error, pace and off-ring share for every stretch of every session. |
   | `figures/fig4_session_drift.png` | Agency at the intermediate delays across the session (adaptation / drift). |
   | `figures/fig5_shadows.png` | Sample entropy and RQA determinism by delay, and against pace. |
   | `figures/trajectories/<ID>.png` | Every stretch's hand path for that participant: the fastest compliance check. |

4. **Look at `fig3_quality.png` and the trajectory sheets first**, before any result.

### Exclusion rules (pre-register these)

| Level | Rule (default) | Option to change it |
|---|---|---|
| Stretch | more than 25% of frames over 40 px from the ring | `--max-off-ring`, `--ring-tol` |
| Stretch | more than 15% of the path travelled backwards | `--max-backward` |
| Stretch | faster than 0.75 laps/s (scribbling) | `--max-laps-per-s` |
| Stretch | slower than 0.15 laps/s: **flagged, kept** | `--exclude-slow` to drop |
| Participant | fewer than 70% of main stretches usable | `--min-kept` |
| Participant | stayed on a trackpad after the prompt | `--keep-trackpad` |
| Participant | `?dev=1` / test session, or did not finish | `--include-dev` |

### Models

With 6 or more included participants the script fits mixed models with a random intercept and a random
delay slope per participant (falling back to a random intercept if that does not converge). The models
adjust for tracing error, pace and stretch number:

* **H1** `agency ~ delay + error + pace + stretch`
* **H2** `shadow ~ delay + error + pace + stretch`, for `sampen_speed` and `rqa_det`
* **H3** `agency ~ shadow (person-centred) + delay + error + pace + stretch`

With fewer participants, mixed models cannot be estimated (the random-effect variance collapses to zero),
so the script fits one ordinary regression per participant instead. Change the threshold with `--min-mixed`.

`python analyze_tracing.py --help` lists every option.

## Changing the design

Everything adjustable is in the `CONFIG` block at the top of `index.html`: delay levels, repetitions, stretch
length, number of blocks, canvas/ring sizes, the flash control, the rating prompt, and the save URL. If you change
the task, change `study_tag` too so the filenames tell you which version produced them, and update the parameter
table in the protocol. The pacing target and feedback limits are in `pace_lap_s` and `qc`; set `feedback: false`
to switch the feedback screens off.

## Privacy

The experiment records a participant ID, timing, mouse trajectories on the canvas, ratings, input device,
hand used, screen size and browser user-agent string (to diagnose display problems), and the debrief
answers — nothing else, and no names. The Drive folder is private to the account that owns it; share it only with
the research team.
