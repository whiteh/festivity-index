"""Fetch Google Trends interest for "All I Want for Christmas Is You" and write
site/data/trends.json for the static site to read.

Two series are fetched:
  * weekly, last 5 years: the long-term baseline (each past Christmas peak).
  * daily, last 90 days: up-to-date resolution for "how festive are we today".

Google Trends normalises every request to 0-100 independently, so the daily
series is rescaled onto the weekly series' scale using the weeks they share.

Each run also saves the raw responses to data/archive/YYYY-MM-DD.json. The
5-year window rolls forward, so weeks that have dropped out of it are pulled
back in from older archive files (rescaled the same way) and the site keeps
every season indefinitely.
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
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data" / "trends.json"
ARCHIVE = ROOT / "data" / "archive"
MIN_OVERLAP_WEEKS = 26


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


def fit_scale(target: pd.Series, source: pd.Series) -> float:
    """Factor that maps `source` onto `target`'s scale over their shared index.

    Least squares through the origin: weights the high-value points, where
    Google's integer rounding matters least.
    """
    shared = target.index.intersection(source.index)
    t, s = target.loc[shared].astype(float), source.loc[shared].astype(float)
    denom = float((s * s).sum())
    return float((t * s).sum()) / denom if denom > 0 else 0.0


def to_rows(df: pd.DataFrame) -> list:
    return [[d.strftime("%Y-%m-%d"), int(v), bool(p)]
            for d, v, p in zip(df.index, df[TERM], df["isPartial"])]


def from_rows(rows: list) -> pd.Series:
    """Complete (non-partial) points from an archived series."""
    kept = [(pd.Timestamp(d), float(v)) for d, v, partial in rows if not partial]
    return pd.Series(dict(kept), dtype=float).sort_index()


def save_archive(weekly: pd.DataFrame, daily: pd.DataFrame, today: str) -> None:
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "term": TERM,
        "geo": GEO,
        "weekly": to_rows(weekly),
        "daily": to_rows(daily),
    }
    (ARCHIVE / f"{today}.json").write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")


def extend_with_archive(weekly: pd.Series, today: str) -> pd.Series:
    """Prepend weeks that have rolled out of the 5-year window, newest archive first."""
    merged = weekly.astype(float)
    for path in sorted(ARCHIVE.glob("*.json"), reverse=True):
        if path.stem == today:
            continue
        snap = json.loads(path.read_text())
        if snap.get("term") != TERM or snap.get("geo") != GEO:
            continue
        old = from_rows(snap["weekly"])
        earlier = old[old.index < merged.index.min()]
        if earlier.empty:
            continue
        overlap = merged.index.intersection(old.index)
        if len(overlap) < MIN_OVERLAP_WEEKS:
            print(f"Skipping {path.name}: only {len(overlap)} overlapping weeks", file=sys.stderr)
            continue
        factor = fit_scale(merged, old)
        merged = pd.concat([earlier * factor, merged])
        print(f"Added {len(earlier)} older weeks from {path.name} (x{factor:.3f})")
    return merged


def main() -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
    scale = fit_scale(full_weeks, daily_weekly_mean)
    print(f"Rescaling daily by {scale:.4f} using {len(shared)} shared weeks")

    save_archive(weekly, daily, today)
    long_weekly = extend_with_archive(full_weeks, today)
    partial_weeks = weekly[weekly["isPartial"].astype(bool)][TERM].astype(float)
    all_weeks = pd.concat([long_weekly, partial_weeks])

    def rows(series, factor=1.0):
        return [[d.strftime("%Y-%m-%d"), round(float(v) * factor, 2)]
                for d, v in series.items()]

    payload = {
        "term": TERM,
        "geo": GEO or "Worldwide",
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "weekly": rows(all_weeks),
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
