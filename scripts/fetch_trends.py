"""Fetch Google Trends interest for "All I Want for Christmas Is You" and write
site/data/trends.json for the static site to read.

Two series are fetched:
  * weekly, last 5 years: the long-term baseline (each past Christmas peak).
  * daily, last 90 days: up-to-date resolution for "how festive are we today".

Google Trends normalises every request to 0-100 independently, so the daily
series is rescaled onto the weekly series' scale using the weeks they share.

Google samples searches, so the numbers vary between fetches made hours apart
(repeat requests within minutes return the same response), and occasionally a
daily response is plainly wrong (zeros in busy weeks). So responses that don't
agree with the weekly data are rejected, and each day's value is the median of
the last week of archived responses, all rescaled onto today's scale.

Each run also saves the raw responses to data/archive/YYYY-MM-DD.json. The
5-year window rolls forward, so weeks that have dropped out of it are pulled
back in from older archive files (rescaled the same way) and the site keeps
every season indefinitely.

Festive lift-off (the first day searches cross 10% of a typical Christmas peak
and stay there for a week) is locked into data/liftoff.json once that week has
passed, so it never changes afterwards.
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
LIFTOFF = ROOT / "data" / "liftoff.json"
MIN_OVERLAP_WEEKS = 26

SMOOTH_DAYS = 7          # median each day across this many daily snapshots
BUSY_WEEK = 5            # weekly value above which a zero day is impossible
MAX_WEEK_MISMATCH = 0.25 # allowed |weekly - rescaled daily mean| / weekly
PAST_SEASONS = 5
LIFTOFF_SHARE = 0.10     # lift-off threshold: share of an average past peak


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


def week_start(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Sunday that starts each date's week (Trends labels weeks by their Sunday)."""
    return index - pd.to_timedelta((index.day_of_week + 1) % 7, unit="D")


def check_daily(daily: pd.DataFrame, full_weeks: pd.Series) -> tuple[float | None, str]:
    """Rescale factor for a daily response, or None and the reason it's implausible."""
    vals = daily[~daily["isPartial"].astype(bool)][TERM].astype(float)
    weeks = week_start(vals.index)
    counts = vals.groupby(weeks).count()
    weekly_mean = vals.groupby(weeks).mean()[counts == 7]
    shared = full_weeks.index.intersection(weekly_mean.index)
    if len(shared) < 4:
        return None, f"only {len(shared)} weeks overlap the weekly data"
    scale = fit_scale(full_weeks, weekly_mean)

    busy = full_weeks.loc[shared][full_weeks.loc[shared] >= BUSY_WEEK]
    zeros = [d for d, v in vals.items() if v == 0 and week_start(pd.DatetimeIndex([d]))[0] in busy.index]
    if zeros:
        return None, "zero on " + ", ".join(d.strftime("%d %b") for d in zeros) + " in a busy week"
    if len(busy):
        mismatch = ((busy - weekly_mean.loc[busy.index] * scale).abs() / busy).max()
        if mismatch > MAX_WEEK_MISMATCH:
            return None, f"weekly totals off by {mismatch:.0%}"
    return scale, "ok"


def fetch_daily(full_weeks: pd.Series) -> tuple[pd.DataFrame, float]:
    """A plausible daily response and its rescale factor, or stop and keep the old data."""
    for attempt in (1, 2):
        df = fetch("today 3-m")
        scale, reason = check_daily(df, full_weeks)
        print(f"Daily response {attempt}: {reason}" + (f" (x{scale:.4f})" if scale else ""))
        if scale:
            return df, scale
        time.sleep(60)
    raise SystemExit("Google's daily data looks wrong today; keeping the previous data.")


def frame_from_rows(rows: list) -> pd.DataFrame:
    return pd.DataFrame({TERM: [float(v) for _, v, _ in rows], "isPartial": [p for *_, p in rows]},
                        index=pd.DatetimeIndex([d for d, *_ in rows]))


def smooth_with_archive(current: pd.Series, today: str) -> tuple[pd.Series, int]:
    """Median of each day across today's response and recent archived ones.

    Archived responses are checked against their own weekly data (bad ones are
    skipped), then rescaled onto today's scale using the days they share.
    """
    columns = [current]
    for path in sorted(ARCHIVE.glob("*.json"), reverse=True):
        if len(columns) == SMOOTH_DAYS:
            break
        if path.stem >= today:
            continue
        snap = json.loads(path.read_text())
        if snap.get("term") != TERM or snap.get("geo") != GEO or "daily" not in snap:
            continue
        old = frame_from_rows(snap["daily"])
        weekly = from_rows(snap["weekly"])
        ok, reason = check_daily(old, weekly)
        if not ok:
            print(f"Skipping {path.name}: {reason}")
            continue
        old_vals = old[~old["isPartial"].astype(bool)][TERM]
        columns.append(old_vals * fit_scale(current, old_vals))
    smoothed = pd.concat(columns, axis=1, sort=True).median(axis=1)
    return smoothed.loc[current.index], len(columns)


def season_of(ts: pd.Timestamp) -> int | None:
    """Christmas a date belongs to: Sep-Dec of that year, or the January after."""
    if ts.month >= 9:
        return ts.year
    return ts.year - 1 if ts.month == 1 else None


def season_window(season: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    return pd.Timestamp(season, 9, 1), pd.Timestamp(season + 1, 1, 10)


def average_past_peak(weekly: pd.Series, current: int) -> float:
    peaks = []
    for season in range(current - 1, current - 1 - PAST_SEASONS, -1):
        start, end = season_window(season)
        window = weekly[(weekly.index >= start) & (weekly.index <= end)]
        if len(window):
            peaks.append(float(window.max()))
    return sum(peaks) / len(peaks) if peaks else 0.0


def find_liftoff(weekly: pd.Series, daily: pd.Series, season: int,
                 threshold: float) -> tuple[pd.Timestamp, bool] | None:
    """First day searches reach the threshold and average above it for the next week.

    Returns (date, confirmed); confirmed once that whole week is in the data.
    Weeks before the daily data starts are checked with the weekly series.
    """
    start, end = season_window(season)
    first_daily = daily.index.min()
    early = weekly[(weekly.index >= start) & (weekly.index < first_daily)]
    for i in range(len(early)):
        if early.iloc[i] >= threshold and early.iloc[i:i + 2].mean() >= threshold:
            return early.index[i], True
    days = daily[(daily.index >= start) & (daily.index <= end)]
    for i in range(len(days)):
        week = days.iloc[i:i + 7]
        if days.iloc[i] >= threshold and week.mean() >= threshold:
            return days.index[i], len(week) == 7
    return None


def liftoff_for(weekly: pd.Series, daily: pd.Series) -> dict | None:
    """This season's lift-off, read from or locked into data/liftoff.json."""
    last = daily.index.max()
    season = season_of(last) or (last.year - 1 if last.month < 9 else last.year)
    key = GEO or "Worldwide"
    locked = json.loads(LIFTOFF.read_text()) if LIFTOFF.exists() else {}
    if str(season) in locked.get(key, {}):
        return {"date": locked[key][str(season)], "confirmed": True}

    threshold = LIFTOFF_SHARE * average_past_peak(weekly, season)
    found = find_liftoff(weekly, daily, season, threshold) if threshold > 0 else None
    if not found:
        return None
    date, confirmed = found
    if confirmed:
        locked.setdefault(key, {})[str(season)] = date.strftime("%Y-%m-%d")
        LIFTOFF.write_text(json.dumps(locked, indent=1, sort_keys=True) + "\n")
        print(f"Locked {season} lift-off at {date:%d %b}")
    return {"date": date.strftime("%Y-%m-%d"), "confirmed": confirmed}


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
    full_weeks = weekly[~weekly["isPartial"].astype(bool)][TERM].astype(float)
    time.sleep(5)
    daily_raw, scale = fetch_daily(full_weeks)
    save_archive(weekly, daily_raw, today)

    daily, used = smooth_with_archive(daily_raw[TERM].astype(float) * scale, today)
    print(f"Daily values are medians across {used} snapshots")
    partial = daily_raw.index[daily_raw["isPartial"].astype(bool)]
    daily_partial_from = partial.min().strftime("%Y-%m-%d") if len(partial) else None

    long_weekly = extend_with_archive(full_weeks, today)
    partial_weeks = weekly[weekly["isPartial"].astype(bool)][TERM].astype(float)
    all_weeks = pd.concat([long_weekly, partial_weeks])

    complete_daily = daily[daily.index < pd.Timestamp(daily_partial_from)] if daily_partial_from else daily
    liftoff = liftoff_for(long_weekly, complete_daily)

    def rows(series):
        return [[d.strftime("%Y-%m-%d"), round(float(v), 2)] for d, v in series.items()]

    payload = {
        "term": TERM,
        "geo": GEO or "Worldwide",
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "weekly": rows(all_weeks),
        "weeklyPartialFrom": next(
            (d.strftime("%Y-%m-%d") for d, p in weekly["isPartial"].items() if p), None),
        "daily": rows(daily),
        "dailyPartialFrom": daily_partial_from,
        "liftoff": liftoff,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"Wrote {OUT} ({len(payload['weekly'])} weeks, {len(payload['daily'])} days)")


if __name__ == "__main__":
    main()
