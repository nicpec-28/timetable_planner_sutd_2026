# SUTD Term 7 Timetable Planner

A Streamlit app for planning a Term 7 timetable from the ESD and HASS/TE
timetable PDFs, checking for clashes, and exporting the result as a `.ics`
file for Google/Outlook/Apple Calendar.

## Setup

```bash
cd timetable
pip install -r requirements.txt
streamlit run app.py
```

## Deploying on Streamlit Community Cloud

This repo is ready to deploy as-is:

1. Push it to a GitHub repo (see commands below).
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with
   GitHub, and click **New app**.
3. Pick this repo/branch, and set **Main file path** to `app.py`.
4. Deploy. No secrets or extra config are needed — everything the app reads
   (`data/sessions.csv`, `data/exams.csv`) is committed in the repo.

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<your-username>/<repo-name>.git
git push -u origin main
```

(Create the empty GitHub repo first at github.com/new, or with
`gh repo create <repo-name> --public --source=. --remote=origin --push`
if you have the GitHub CLI installed.)

## Data

- `data/sessions.csv` — one row per weekly recurring class session (module
  code, name, day, start/end time, which weeks it runs, faculty, venue).
- `data/exams.csv` — final exam schedule per module code, extracted from the
  Term 7 pillar exam PDF.

Both files were extracted from grid-style TimeEdit PDF exports:

- `2630 Term 7 ESD_180826 (002).pdf`
- `2630 Term 7 HASS  TE_260826 (002).pdf`
- `2630 pillar midterm  final exams_students_31Aug26.pdf`

Grid PDFs like these are lossy to parse automatically — dense/overlapping
cells (especially in the HASS & TE sheet) can't always be read with full
confidence. Every row in `sessions.csv` has a `confidence` column:

- **high** — read directly off a clear, unambiguous cell.
- **medium** — time or room inferred from surrounding layout; likely correct.
- **low** — cell was visually crowded/overlapping in the source PDF; verify
  against the original document before relying on it.

The app's "Review / correct session details" table is editable — fix any
row directly in the browser before exporting your `.ics` file. Mid-terms are
not included since the source PDF has no confirmed mid-term dates yet
(subject leads communicate these later in the term).

## Week numbering

The app uses the same week numbers SUTD communicates to students, not the
raw week numbers printed in the source PDFs:

- **Week 1** — 14 Sep 2026 (term start)
- **Week 7** — 26 Oct 2026 — recess, no lessons
- **Week 8** — 2 Nov 2026 (lessons resume)
- **Week 14** — 14 Dec 2026 — finals week

Expand "Term calendar" at the top of the app to see the full Week 1–14 →
date mapping. Every session's `weeks` value (in `sessions.csv` and the
in-app editor) uses this numbering, e.g. `1-6,8-13` means every teaching
week except recess.

## Notes

- Some modules run only in specific weeks (e.g. `40.302` weeks 1–6 only,
  `40.305` weeks 8–13 only) — these are alternative options for the same
  slot and will not be flagged as clashing with each other.
- `01.107` and `01.101` appear on both source sheets (cross-listed pillar
  electives) and are de-duplicated to a single entry.
- Times are exported to the `.ics` file assuming Singapore time (UTC+8, no
  DST).

## Updating with a new timetable PDF

Re-extract the relevant table and edit `data/sessions.csv` /
`data/exams.csv` directly (plain CSV, easy to hand-edit or regenerate). No
code changes needed unless the sheet structure changes.
