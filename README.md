# Delayed feedback and the sense of agency — online experiment

Circle-tracing task with lagged visual feedback, hosted on GitHub Pages, with data saved
automatically to a Google Drive folder. Companion to `protocol.pdf` and the project handbook.

```
agency-tracing/
├── index.html              the experiment (jsPsych 7, single file)
├── google_apps_script.gs   the receiver that writes data into Drive (lives on script.google.com, not in the repo)
├── analyze_tracing.py      turns the saved JSON into a stretch-level table + fits the pre-registered models
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
2. Upload `index.html` (with your `save_url` pasted in), `.nojekyll`, `analyze_tracing.py`, `protocol.pdf`
   and this README. *Do not upload `google_apps_script.gs`* — it is a reminder copy; the live script lives on
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
| `…/?dev=1&save=off` | 3-second stretches, 4 stretches, data downloaded locally. Use first: checks the task runs end to end. |
| `…/?dev=1&id=TEST01` | Same short version, but **saves to Drive**. Use second: confirms the receiver works. Then look in the Drive folder for `agency_tracing_v1_TEST01_…json`. Delete test files before the real study. |
| `…/?id=P01` | The real thing, with the ID pre-filled. |

What "working" looks like in the Drive test: the completion screen says *"Your data has been saved"* (not the
"could not be confirmed" message), and the two files plus a `_log.csv` line appear in the folder.

If the completion screen reports that the save could not be confirmed, the data was **downloaded to the computer
instead** (files start with `agency_tracing_v1_…`). The commonest causes: the `save_url` was not pasted in, a new
script version was not deployed, or the Web app was deployed with *Who has access* set to something other than
*Anyone*.

---

## Running a participant

1. Consent on paper or as the lab's standard form; note handedness and the participant ID on the session sheet.
2. Use a **mouse**, not a trackpad; close other windows and notifications.
3. Open `https://<user>.github.io/agency-tracing/?id=P01` (replace `P01`). The page goes full-screen after the ID.
4. The session is ~25 min: 3 practice stretches, then 36 main stretches in 3 blocks with breaks, then one debrief
   question. The data uploads itself; the completion screen confirms it.
5. Tick the session checklist at the end of `protocol.pdf`.

You can also run it from a local file (double-click `index.html`) — saving to Drive still works — but the Pages
link is the same for every machine, which avoids version drift.

---

## Getting the data out and analysing it

1. In Drive, select all the `.json` files (or the whole folder) → **Download**. Google zips them; unzip into a
   folder, e.g. `data/`.
2. Requirements: Python 3 with `numpy`, `pandas`, and `statsmodels` (only for `--fit`):
   `pip install numpy pandas statsmodels`
3. Build the trial table:
   ```
   python analyze_tracing.py data/*.json --out tracing_trials.csv
   ```
   This writes one row per stretch (participant, delay, flash, agency rating, radial error, revolutions,
   sample entropy of hand speed, cross-recurrence determinism, timing quality) and prints mean agency by delay.
4. Fit the pre-registered mixed models (H1–H3 in the protocol):
   ```
   python analyze_tracing.py data/*.json --out tracing_trials.csv --fit
   ```
5. Quick quality check before anything else: `mean_frame_ms` should be near 16–17 (a 60 Hz display);
   `revolutions` should be > 3 per stretch; `_log.csv` should show a `final` line for every participant.

Files from a participant who dropped out mid-session contain only the completed stretches and are parsed the same way.

---

## Changing the design

Everything adjustable is in the `CONFIG` block at the top of `index.html`: delay levels, repetitions, stretch
length, number of blocks, canvas/ring sizes, the flash control, the rating prompt, and the save URL. If you change
the task, change `study_tag` too so the filenames tell you which version produced them, and update the parameter
table in the protocol.

## Privacy

The experiment records a participant ID, timing, mouse trajectories on the canvas, ratings, and the debrief
answer — nothing else, and no names. The Drive folder is private to the account that owns it; share it only with
the research team.
