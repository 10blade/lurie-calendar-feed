# Lurie Calendar Feed

This project builds an unofficial iCalendar feed for professional education events from the public Robert H. Lurie Comprehensive Cancer Center event pages.

It looks for professional, clinical, research, and academic events such as Grand Rounds, seminar series, symposia, conferences, and CME-style programs. It skips patient/community events, wellness activities, fundraisers, support groups, and general public events unless the page clearly identifies the event as professional education.

The generated calendar is published from `docs/lurie-professional-events.ics`.

Residents, fellows and students in Chicago area, Welcome to subscribe to the ics calendar; Calendar updates daily

# ics link here: https://10blade.github.io/lurie-calendar-feed/lurie-professional-events.ics

## Run Locally

1. Install Python 3.13.
2. Open a terminal in this repository.
3. Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

4. Install the project:

```powershell
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

5. Run tests:

```powershell
pytest
```

6. Generate the feed:

```powershell
python -m lurie_calendar update --days-ahead 180
```

7. Validate generated event data:

```powershell
python -m lurie_calendar validate data/lurie_events.json
```

The update command writes:

- `data/lurie_events.json`
- `data/review_required.json`
- `data/stable_uids.json`
- `docs/lurie-professional-events.ics`
- `docs/index.html`
- `logs/last_run_summary.md`

Downloaded PDFs are cached under `.cache/` and are ignored by Git.

## Use GitHub Desktop

If you are new to Git, GitHub Desktop is the easiest way to connect this folder to GitHub.

1. Install GitHub Desktop.
2. Sign in.
3. Choose **File > Clone repository**.
4. Select `10blade/lurie-calendar-feed`.
5. Choose a local folder.
6. Copy or create these project files in the cloned folder.
7. In GitHub Desktop, review the changes.
8. Commit them with a message such as `Build Lurie calendar feed`.
9. Click **Push origin**.

## Run the GitHub Action Manually

1. Open the repository on GitHub.
2. Go to **Actions**.
3. Select **Update and publish calendar**.
4. Click **Run workflow**.
5. Choose the `main` branch.
6. Click **Run workflow** again.

The workflow runs tests first, then runs the scraper, commits generated data/log files, and deploys `docs/` to GitHub Pages.

## Enable GitHub Pages

1. Open the repository on GitHub.
2. Go to **Settings > Pages**.
3. Under **Build and deployment**, set **Source** to **GitHub Actions**.
4. Save the setting.

After a successful workflow run, GitHub will show the Pages site URL.

## Find the Public ICS URL

After GitHub Pages is enabled and the workflow succeeds, the ICS URL should be:

```text
https://10blade.github.io/lurie-calendar-feed/lurie-professional-events.ics
```

The status page should be:

```text
https://10blade.github.io/lurie-calendar-feed/
```

## Subscribe in Google Calendar

1. Open Google Calendar in a browser.
2. On the left, next to **Other calendars**, click **+**.
3. Choose **From URL**.
4. Paste the public ICS URL.
5. Click **Add calendar**.

Google Calendar refreshes subscribed ICS calendars on its own schedule, so updates may not appear immediately.

## Troubleshoot Missing Events

Check these files first:

- `logs/last_run_summary.md`
- `data/review_required.json`
- the latest folder under `artifacts/`

Common reasons an event may be missing:

- the event is outside the `--days-ahead` window,
- the page looks like a patient/community event,
- the page links to a PDF with no extractable text,
- the PDF and webpage have conflicting dates, times, or titles,
- the source page changed its layout.

The scraper fails safely if it loads the source pages but finds zero future professional events. In that case it does not overwrite a previously valid ICS file with an empty calendar.

## Add Fixtures When the Parser Misses an Event

When an event is missed, save a small static example so the parser can be improved without depending on the live website.

1. Copy the relevant public HTML into `tests/fixtures/`.
2. If the important details are in a PDF, copy the extracted text into a `.txt` fixture.
3. Add a pytest case that reproduces the missed event.
4. Update the parser until the test passes.

Do not add downloaded PDFs to the repository unless there is a clear reason and the file is safe to redistribute.

## Security Notes

- No Google Calendar API is used.
- No OpenAI keys or other secrets are required.
- Scraped HTML and PDF text are treated as untrusted input.
- The scraper parses public content locally and does not send scraped page or PDF contents to an external AI service.
