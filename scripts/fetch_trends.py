"""Fetch Google Trends interest for "All I Want for Christmas Is You" and write
site/data/trends.json for the static site to read.

Two series are fetched:
  * weekly, last 5 years: the long-term baseline (each past Christmas peak).
  * daily, last 90 days: up-to-date resolution for "how festive are we today".

Google Trends normalises every request to 0-100 independently, so the daily
series is rescaled onto the weekly series' scale using the weeks they share.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from pytrends.request import TrendReq

TERM = os.environ.get("TRENDS_TERM", "all i want for christmas is you")
GEO = os.environ.get("TRENDS_GEO", "GB")  # "" = worldwide, "US", "GB", ...
OUT = Path(__file__).resolve().parent.parent / "site" / "data" / "trends.json"


def fetch(timeframe: str, attempts: int = 5):
    """Fetch one timeframe, backing off on Google's frequent 429s."""
    for i in range(attempts):
        try:
            client = TrendReq(hl="en-GB", tz=0, timeout=(10, 30))
            client.build_payload([TERM], timeframe=timeframe, geo=GEO)
            df = client.interest_over_time()
            if df.empty:
                raise RuntimeError(f"No data returned for {timeframe!r}")
            return df
        except Exception as exc:  # pytrends raises a mix of exception types
            wait = 30 * (i + 1)
            print(f"[{timeframe}] attempt {i + 1} failed: {exc}; retrying in {wait}s",
                  file=sys.stderr)
            time.sleep(wait)
    raise SystemExit(f"Giving up on {timeframe!r} after {attempts} attempts")


def main() -> None:
    weekly = fetch("today 5-y")
    time.sleep(5)
    daily = fetch("today 3-m")

    # Rescale daily -> weekly scale using complete weeks present in both.
    # Weekly rows are labelled by the Sunday the week starts on.
    full_weeks = weekly[~weekly["isPartial"].astype(bool)][TERM]
    daily_vals = daily[~daily["isPartial"].astype(bool)][TERM]
    week_start = daily_vals.index - pd.to_timedelta((daily_vals.index.day_of_week + 1) % 7, unit="D")
    counts = daily_vals.groupby(week_start).count()
    daily_weekly_mean = daily_vals.groupby(week_start).mean()[counts == 7]
    shared = full_weeks.index.intersection(daily_weekly_mean.index)
    # Least squares through the origin: weights the high-value weeks, where
    # Google's integer rounding matters least (low daily values are very noisy).
    w = full_weeks.loc[shared]
    d = daily_weekly_mean.loc[shared]
    denom = float((d * d).sum())
    scale = float((w * d).sum()) / denom if denom > 0 else 0.0
    print(f"Rescaling daily by {scale:.4f} using {len(shared)} shared weeks")

    def rows(series, factor=1.0):
        return [[d.strftime("%Y-%m-%d"), round(float(v) * factor, 2)]
                for d, v in series.items()]

    payload = {
        "term": TERM,
        "geo": GEO or "Worldwide",
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "weekly": rows(weekly[TERM]),
        "weeklyPartialFrom": next(
            (d.strftime("%Y-%m-%d") for d, p in weekly["isPartial"].items() if p), None),
        "daily": rows(daily[TERM], scale),
        "dailyPartialFrom": next(
            (d.strftime("%Y-%m-%d") for d, p in daily["isPartial"].items() if p), None),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"Wrote {OUT} ({len(payload['weekly'])} weeks, {len(payload['daily'])} days)")


if __name__ == "__main__":
    main()
