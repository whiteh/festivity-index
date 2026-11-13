# Is it Mariah time? 🎄

A tiny website that judges how festive the nation is by tracking Google searches
for Mariah Carey's *All I Want for Christmas Is You*.

- **Festivity Index** — the last 7 days of search interest as a percentage of an
  average past Christmas peak (100 = a typical Christmas week). It maps to a verdict,
  from *Bah humbug* to *IT'S TIIIIME*.
- Comparisons with the same date last year and with a 5-year average.
- **Festive lift-off** — the first day this season searches reached 10% of a typical peak.
- A chart overlaying every season since 2021.

## How it works

`scripts/fetch_trends.py` uses [pytrends](https://github.com/GeneralMills/pytrends)
to pull five years of weekly data and the last 90 days of daily data from Google
Trends. Because Trends normalises every request to 0–100, the daily series is rescaled
onto the weekly scale (least-squares fit over the weeks they share). The result
goes to `site/data/trends.json`; everything else happens in the browser (`site/app.js`).

## Run it locally

```sh
pip install -r requirements.txt
python scripts/fetch_trends.py           # refresh site/data/trends.json
python -m http.server -d site 8000       # open http://localhost:8000
```

Change region with `TRENDS_GEO` (`GB` by default; `US`, `IE`, or empty for worldwide).

## Hosting

`.github/workflows/update.yml` runs daily: fetches fresh data, commits it, and deploys
`site/` to GitHub Pages. To enable: push to GitHub, then in **Settings → Pages** set
the source to **GitHub Actions**. Set a repository variable `TRENDS_GEO` to change region.

Google Trends has no official public API and sometimes rate-limits (HTTP 429)
cloud IPs. The script retries with back-off; if a run still fails, the site keeps showing
the previous day's data.
