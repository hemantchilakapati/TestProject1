---
name: healthcare-locations-refresh
description: Collects every location of Jefferson Health (jeffersonhealth.org), Lehigh Valley Health Network (lvhn.org), Quest Diagnostics and Labcorp into one Excel workbook - address, lat/long, phone, fax, hours, location type, services - with a tab showing what changed since last month. Use this whenever the user asks to refresh, update, pull, download, scrape or re-run the healthcare/lab location list, the monthly locations report, Jefferson/LVHN/Quest/Labcorp locations, patient service center lists, or "the locations spreadsheet", including when it runs as a scheduled monthly task.
---

# Healthcare & lab locations refresh

Produces `Healthcare_Lab_Locations_<YYYY-MM>.xlsx` with one tab per organization
(Jefferson Health ~447, LVHN ~843, Quest ~2,300, Labcorp ~2,270 locations),
plus Summary, Changes (vs. last month), Checks and Excluded tabs.

The scrapers in `scripts/` already know how each site publishes its locations.
Run them rather than re-investigating the websites - that is what keeps the
output consistent month to month. Only investigate a site when a scraper fails
or the Checks tab flags it (see "When something breaks").

## Steps

1. **Pick folders.** Ask the user once where reports should be saved if you don't
   already know (for scheduled runs, use the folder from the task instructions).
   - `OUT_DIR`: where the monthly workbooks live
   - `WORK_DIR`: a scratch folder for this month, e.g. `<OUT_DIR>/.work-<YYYY-MM>`.
     Use a new one each month so pages are freshly downloaded.

2. **Find last month's workbook** in `OUT_DIR` (the newest
   `Healthcare_Lab_Locations_*.xlsx`). If there is one, pass it as `--previous`
   so the Changes tab and the count checks compare against it.

3. **Run everything** (Python 3 with `openpyxl`; install with `pip install openpyxl` if missing):
   ```bash
   python3 scripts/run_all.py --work-dir "$WORK_DIR" \
       --output "$OUT_DIR/Healthcare_Lab_Locations_<YYYY-MM>.xlsx" \
       --previous "$OUT_DIR/<last month's file>.xlsx"
   ```
   It runs the four scrapers in parallel and takes roughly 5-15 minutes (LVHN is
   deliberately slow because the site drops connections under load). Run it in the
   background if your shell has a time limit, and check `WORK_DIR/logs/*.log`.
   **If it gets cut off, just run the same command again** - finished pages are
   cached in `WORK_DIR/cache`, so it resumes rather than restarting.
   - One source only: add `--sources lvhn` (comma-separated list).
   - Rebuild the workbook without re-downloading: add `--build-only`.

4. **Read the JSON summary** the run prints: counts per source, excluded rows,
   added/removed/changed counts and any warnings. The same warnings are on the
   workbook's Checks tab (highlighted rows).

5. **Deliver.** Save the workbook in `OUT_DIR`, then send a short summary in this shape
   (by email if the user set that up, otherwise in chat):

   > **Locations refresh - October 2026**
   > Jefferson 447 · LVHN 843 · Quest 2,302 · Labcorp 2,273 (total 5,865)
   > Since last month: +14 added, -6 removed, 31 changed (mostly hours).
   > Notable: Labcorp opened 9 Walgreens sites; LVHN closed 2 practices in Easton.
   > Checks: all OK. (Or: "LVHN count dropped 12% - see below.")

   Pull the "notable" lines from the Changes tab; keep them to what a reader
   would care about (openings, closures, moves), not every hours tweak.

6. Delete `WORK_DIR` after a successful run - it holds a few hundred MB of cached pages.

## When something breaks

A scraper exits with an error, a count drops more than 10%, or a key column
(name, address, phone, lat/long) is suddenly mostly empty: the website has
probably changed. Read `references/sources.md` for how that site works and
what usually changes, investigate the live page, then fix the scraper in place.
Run that source alone (`--sources <name>`) to verify, then `--build-only`.

Don't ship a workbook with a broken source silently. If you can't fix it,
deliver the rest and say clearly which organization is stale or incomplete and why.
Leaving the previous month's JSON out is better than mixing old and new data
without saying so.

## Output reference

- **Summary**: counts (live formulas), states covered, added/removed/changed per source, check status.
- **Checks**: count vs. last month (or the baseline in `references/baseline.json`), key-field fill rates, scraper warnings.
- **Changes**: Added / Removed / Changed rows (name, address, phone, fax, daily hours), keyed by each location's page URL.
- **Excluded**: pages listed by a site that had no data (e.g. ~49 closed Quest sites still in its sitemap).
- Every location row has `Location URL` linking to its source page.
