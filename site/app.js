// How festive is the nation? Reads data/trends.json and passes judgement.
(() => {
  "use strict";

  const DAY = 864e5;
  const SEASON_END = 131;      // days after 1 Sep (~10 Jan)
  const XMAS = 115;            // 25 Dec, days after 1 Sep
  const NOV_1 = 61;            // 1 Nov: when festive searches traditionally take off
  const PAST_SEASONS = 5;
  const DAILY_DAYS = 28;      // use daily resolution for the most recent four weeks

  // Festivity Index thresholds (100 = a typical Christmas-week peak).
  const TIERS = [
    { min: 0,  name: "Bah humbug",            short: "Humbug",
      blurb: "Autumn reigns. The decorations are still in the loft and the nation is having none of it." },
    { min: 3,  name: "Thawing out",           short: "Thawing",
      blurb: "The ice is cracking. A few early adopters have caved, and somewhere a garden centre has its lights up." },
    { min: 10, name: "Jingle bells, faintly", short: "Jingling",
      blurb: "The nation is warming up. Office party playlists are being quietly drafted." },
    { min: 25, name: "Tinsel’s going up",     short: "Tinsel",
      blurb: "Advent calendars are open and the festive mood is spreading fast. Resistance is weakening." },
    { min: 50, name: "Fully festive",         short: "Festive",
      blurb: "It’s in every shop, on every radio and at every party. There is no escape and nobody wants one." },
    { min: 80, name: "Peak Christmas",        short: "Peak",
      blurb: "Maximum festivity. The whole country is in full Christmas mode. Merry Christmas." },
  ];

  const GEO_NAMES = { GB: "the UK", US: "the US", IE: "Ireland", AU: "Australia", CA: "Canada", Worldwide: "the world" };
  const PAST_COLORS = ["--past-1", "--past-2", "--past-3", "--past-4", "--past-5"];

  const $ = (id) => document.getElementById(id);
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const parse = (s) => new Date(s + "T00:00:00Z");
  const fmtDate = (d) => d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
  const seasonOf = (d) => (d.getUTCMonth() >= 8 ? d.getUTCFullYear() : d.getUTCMonth() === 0 ? d.getUTCFullYear() - 1 : null);
  const dayOfSeason = (d, s) => Math.round((d - Date.UTC(s, 8, 1)) / DAY);
  const dateFromDay = (s, n) => new Date(Date.UTC(s, 8, 1) + n * DAY);
  const mean = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : NaN);

  // Linear interpolation of a season's {x,y} points at day x.
  function valueAt(points, x) {
    if (!points.length || x < points[0].x || x > points[points.length - 1].x) return null;
    for (let i = 1; i < points.length; i++) {
      const a = points[i - 1], b = points[i];
      if (x <= b.x) return a.y + (b.y - a.y) * ((x - a.x) / (b.x - a.x || 1));
    }
    return points[points.length - 1].y;
  }

  function buildSeasons(data) {
    const seasons = new Map();
    const add = (s, x, y, date) => {
      if (!seasons.has(s)) seasons.set(s, []);
      seasons.get(s).push({ x, y, date });
    };

    const daily = data.daily
      .filter(([d]) => !data.dailyPartialFrom || d < data.dailyPartialFrom)
      .map(([d, v]) => ({ date: parse(d), v }));
    // Daily values are integers on their own 0-100 scale, so quiet days round to
    // zero; only trust them for the recent weeks where they add resolution.
    // Use them from the latest unbroken run of non-zero days, at most DAILY_DAYS.
    let start = daily.length;
    while (start > 0 && daily[start - 1].v > 0 && daily.length - start < DAILY_DAYS) start--;
    const firstDaily = start < daily.length ? daily[start].date : null;

    for (const [d, v] of data.weekly) {
      if (data.weeklyPartialFrom && d >= data.weeklyPartialFrom) continue;
      const mid = new Date(parse(d).getTime() + 3 * DAY); // plot weeks at mid-week
      if (firstDaily && mid >= firstDaily) continue;      // daily data takes over
      const s = seasonOf(mid);
      if (s === null) continue;
      const x = dayOfSeason(mid, s);
      if (x <= SEASON_END) add(s, x, v, mid);
    }
    for (const { date, v } of daily) {
      if (!firstDaily || date < firstDaily) continue;
      const s = seasonOf(date);
      if (s === null) continue;
      const x = dayOfSeason(date, s);
      if (x <= SEASON_END) add(s, x, v, date);
    }
    for (const pts of seasons.values()) pts.sort((a, b) => a.x - b.x);
    return { seasons, daily };
  }

  function analyse(data) {
    const { seasons, daily } = buildSeasons(data);
    const lastDay = daily.length ? daily[daily.length - 1].date : parse(data.weekly[data.weekly.length - 1][0]);
    const current = seasonOf(lastDay) ?? (lastDay.getUTCMonth() < 8 ? lastDay.getUTCFullYear() - 1 : lastDay.getUTCFullYear());
    const inSeason = seasonOf(lastDay) !== null;

    const past = [...seasons.keys()].filter((s) => s < current).sort((a, b) => b - a).slice(0, PAST_SEASONS);
    const peaks = past.map((s) => {
      const top = seasons.get(s).reduce((m, p) => (p.y > m.y ? p : m));
      return { season: s, value: top.y, date: top.date };
    });
    const avgPeak = mean(peaks.map((p) => p.value));

    const last7 = daily.slice(-7);
    const now = mean(last7.map((p) => p.v));
    const index = avgPeak > 0 ? (now / avgPeak) * 100 : 0;

    // Compare like with like: the 7-day average sits ~3 days before the last day.
    const nowX = inSeason ? dayOfSeason(lastDay, current) - 3 : null;
    const sameTime = past
      .map((s) => ({ season: s, value: nowX === null ? null : valueAt(seasons.get(s), nowX) }))
      .filter((p) => p.value !== null);
    const lastYear = sameTime.find((p) => p.season === current - 1) || null;
    const typical = mean(sameTime.map((p) => p.value));

    // Lift-off: first day this season reaching 10% of a typical peak.
    const threshold = avgPeak * 0.1;
    const liftoff = (seasons.get(current) || []).find((p) => p.y >= threshold) || null;

    return { seasons, current, past, peaks, avgPeak, now, index, nowX, lastYear, typical, liftoff, lastDay, inSeason };
  }

  function tierFor(index) {
    let t = TIERS[0];
    for (const tier of TIERS) if (index >= tier.min) t = tier;
    return t;
  }
  const meterPos = (index) => Math.sqrt(Math.min(Math.max(index, 0), 100) / 100) * 100;

  function ratioText(now, then) {
    if (!(then > 0)) return { v: "—", s: "no comparison available" };
    const r = now / then;
    if (r >= 1.95) return { v: `${r.toFixed(1)}×`, s: "more festive", up: true };
    const pct = Math.round((r - 1) * 100);
    if (Math.abs(pct) < 5) return { v: "Level", s: "about the same" };
    return { v: `${pct > 0 ? "+" : "−"}${Math.abs(pct)}%`, s: pct > 0 ? "more festive" : "less festive", up: pct > 0 };
  }

  function renderVerdict(a, geoName) {
    const tier = tierFor(a.index);
    $("verdict-title").textContent = tier.name;
    $("index-value").textContent = Math.round(a.index);
    const heat = Math.min(Math.max(a.index / 80, 0), 1);
    document.documentElement.style.setProperty("--heat", heat.toFixed(3));
    $("eyebrow").textContent = `Festive conditions · ${geoName} · ${fmtDate(a.lastDay)}`;
    startSnow(a.index);

    let pace = "";
    if (a.inSeason && a.typical > 0) {
      const r = a.now / a.typical;
      pace = r > 1.15 ? ` ${cap(geoName)} is ahead of schedule — more festive than usual for the time of year.`
        : r < 0.85 ? ` ${cap(geoName)} is running late — less festive than usual for the time of year.`
        : ` Right on schedule for the time of year.`;
    }
    $("verdict-blurb").textContent = tier.blurb + pace;

    const pos = meterPos(a.index);
    const fill = $("meter-fill");
    // Keep the gradient pinned to the whole track so the fill reveals it rather than squashing it.
    fill.style.setProperty("--track-w", `${$("meter").clientWidth}px`);
    requestAnimationFrame(() => (fill.style.width = `${Math.max(pos, 1.5)}%`));
    $("meter").setAttribute("aria-label", `Festivity Index ${a.index.toFixed(0)} out of 100: ${tier.name}`);
    $("meter-ticks").innerHTML = TIERS.map((t) =>
      `<li class="${t === tier ? "on" : ""}" style="left:${t === TIERS[TIERS.length - 1] ? 100 : meterPos(t.min)}%">${t.short}</li>`).join("");
  }
  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

  function renderTiles(a) {
    const vsLast = ratioText(a.now, a.lastYear?.value);
    const vsTyp = ratioText(a.now, a.typical);
    const xmas = Date.UTC(a.lastDay.getUTCFullYear(), 11, 25);
    const sleeps = Math.round((xmas - a.lastDay) / DAY);
    const tiles = [
      { k: "vs this time last year", v: vsLast.v, s: vsLast.s, up: vsLast.up },
      { k: `vs ${a.past.length}-year average`, v: vsTyp.v, s: vsTyp.s, up: vsTyp.up },
      a.liftoff
        ? { k: "Festive lift-off", v: fmtDate(a.liftoff.date), s: "when searches first hit 10% of peak" }
        : { k: "Festive lift-off", v: "Not yet", s: "searches still under 10% of peak" },
      sleeps > 0
        ? { k: "Sleeps until Christmas", v: sleeps, s: "as of the latest data" }
        : { k: "Christmas", v: sleeps === 0 ? "Today!" : "Done", s: sleeps === 0 ? "Merry Christmas" : "see you next year" },
    ];
    $("tiles").innerHTML = tiles.map((t) =>
      `<div class="stat${t.up ? " up" : ""}"><div class="k">${t.k}</div><div class="v">${t.v}</div><div class="s">${t.s}</div></div>`).join("");
  }

  function seriesList(a) {
    const list = [{ season: a.current, points: a.seasons.get(a.current) || [], color: css("--red"), width: 3, now: true }];
    a.past.forEach((s, i) => list.push({ season: s, points: a.seasons.get(s), color: css(PAST_COLORS[i]), width: 2 }));
    return list;
  }

  function renderChart(a) {
    const host = $("chart");
    const W = Math.max(host.clientWidth, 280);
    const H = W < 500 ? 260 : 340;
    const m = { t: 12, r: W < 500 ? 12 : 64, b: 28, l: 32 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const series = seriesList(a);

    const maxV = Math.max(10, ...series.flatMap((s) => s.points.map((p) => p.y)));
    const yMax = Math.ceil(maxV / 20) * 20;
    const X = (x) => m.l + (x / SEASON_END) * iw;
    const Y = (y) => m.t + ih - (y / yMax) * ih;

    const months = [[0, "Sep"], [30, "Oct"], [61, "Nov"], [91, "Dec"], [122, "Jan"]];
    const yTicks = [];
    for (let v = 0; v <= yMax; v += yMax / 4) yTicks.push(v);

    const path = (pts) => pts.map((p, i) => `${i ? "L" : "M"}${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join("");
    const cur = series[0];
    const tail = cur.points[cur.points.length - 1];

    host.innerHTML = `
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Search interest by day of season, ${series.length} seasons overlaid">
        <g class="grid">${yTicks.map((v) => `<line x1="${m.l}" x2="${m.l + iw}" y1="${Y(v)}" y2="${Y(v)}"/>`).join("")}</g>
        <g class="axis">
          ${yTicks.map((v) => `<text x="${m.l - 8}" y="${Y(v) + 4}" text-anchor="end">${v}</text>`).join("")}
          ${months.map(([x, l]) => `<text x="${X(x) + 2}" y="${H - 8}">${l}</text>`).join("")}
        </g>
        <g class="marker"><line x1="${X(NOV_1)}" x2="${X(NOV_1)}" y1="${m.t}" y2="${m.t + ih}"/>
          <text x="${X(NOV_1) + 5}" y="${m.t + 10}">1 Nov</text></g>
        <g class="marker"><line x1="${X(XMAS)}" x2="${X(XMAS)}" y1="${m.t}" y2="${m.t + ih}"/>
          <text x="${X(XMAS) - 5}" y="${m.t + 10}" text-anchor="end">25 Dec</text></g>
        ${series.slice().reverse().map((s) =>
          `<path d="${path(s.points)}" fill="none" stroke="${s.color}" stroke-width="${s.width}" stroke-linejoin="round" stroke-linecap="round"/>`).join("")}
        ${tail ? `<circle cx="${X(tail.x)}" cy="${Y(tail.y)}" r="5" fill="${cur.color}" stroke="${css("--surface")}" stroke-width="2"/>
          <text class="label now" x="${X(tail.x) + 9}" y="${Y(tail.y) - 8}">Now</text>` : ""}
        <line class="crosshair" id="crosshair" y1="${m.t}" y2="${m.t + ih}" visibility="hidden"/>
        <rect id="hit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent"/>
      </svg>`;

    $("legend").innerHTML = series.map((s) =>
      `<span><i style="background:${s.color};height:${s.width}px"></i>${seasonLabel(s.season, a.current)}</span>`).join("");

    // Hover: crosshair + tooltip with every season's value on that date.
    const svg = host.querySelector("svg"), hit = $("hit"), xh = $("crosshair"), tip = $("tooltip");
    const move = (ev) => {
      const r = svg.getBoundingClientRect();
      const px = ((ev.clientX - r.left) / r.width) * W;
      const x = Math.round(Math.min(Math.max((px - m.l) / iw, 0), 1) * SEASON_END);
      xh.setAttribute("x1", X(x)); xh.setAttribute("x2", X(x)); xh.setAttribute("visibility", "visible");
      const rows = series.map((s) => ({ s, v: valueAt(s.points, x) })).filter((r) => r.v !== null);
      tip.innerHTML = `<div class="t">${fmtDate(dateFromDay(2001, x))}</div>` + (rows.length
        ? rows.map(({ s, v }) => `<div class="r"><span><i style="background:${s.color}"></i>${seasonLabel(s.season, a.current)}</span><b>${v.toFixed(1)}</b></div>`).join("")
        : `<div class="muted">No data</div>`);
      tip.hidden = false;
      const tw = tip.offsetWidth, th = tip.offsetHeight;
      let left = ev.clientX + 14, top = ev.clientY - th / 2;
      if (left + tw > innerWidth - 8) left = ev.clientX - tw - 14;
      tip.style.left = `${Math.max(8, left)}px`;
      tip.style.top = `${Math.min(Math.max(8, top), innerHeight - th - 8)}px`;
    };
    const leave = () => { tip.hidden = true; xh.setAttribute("visibility", "hidden"); };
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerdown", move);
    hit.addEventListener("pointerleave", leave);
  }

  // Snowfall proportional to the Festivity Index: a few stray flakes when
  // nobody cares, a blizzard in Christmas week.
  let snowStop = null;
  function startSnow(index) {
    if (snowStop) snowStop();
    const canvas = $("snow"), ctx = canvas.getContext("2d");
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let flakes = [], w = 0, h = 0, raf = 0;
    const size = () => {
      const dpr = Math.min(devicePixelRatio || 1, 2);
      w = canvas.clientWidth; h = canvas.clientHeight;
      canvas.width = w * dpr; canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const n = Math.round(Math.min(8 + index * 2.5, 260) * (w / 1000));
      flakes = Array.from({ length: Math.max(n, 4) }, () => ({
        x: Math.random() * w, y: Math.random() * h,
        r: 0.8 + Math.random() * 2.2, s: 0.25 + Math.random() * 0.7, d: Math.random() * Math.PI * 2,
      }));
    };
    const draw = () => {
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = css("--flake");
      for (const f of flakes) {
        ctx.globalAlpha = 0.35 + f.r / 5;
        ctx.beginPath(); ctx.arc(f.x, f.y, f.r, 0, Math.PI * 2); ctx.fill();
      }
    };
    const tick = () => {
      for (const f of flakes) {
        f.y += f.s; f.d += 0.01; f.x += Math.sin(f.d) * 0.3;
        if (f.y > h + 4) { f.y = -4; f.x = Math.random() * w; }
      }
      draw();
      raf = requestAnimationFrame(tick);
    };
    size();
    if (still) draw(); else tick();
    const onResize = () => { size(); if (still) draw(); };
    addEventListener("resize", onResize);
    snowStop = () => { cancelAnimationFrame(raf); removeEventListener("resize", onResize); };
  }

  const seasonLabel = (s, current) => (s === current ? `${s} (this year)` : `${s}`);

  function renderTable(a) {
    const rows = [a.current, ...a.past].map((s) => {
      const pts = a.seasons.get(s) || [];
      const top = pts.length ? pts.reduce((m, p) => (p.y > m.y ? p : m)) : null;
      const same = a.nowX === null ? null : valueAt(pts, a.nowX);
      return `<tr><td>${seasonLabel(s, a.current)}</td><td>${top ? top.y.toFixed(0) : "—"}</td>
        <td>${top ? fmtDate(top.date) : "—"}</td><td>${same === null ? "—" : same.toFixed(1)}</td></tr>`;
    }).join("");
    const nowLabel = a.nowX === null ? "This date" : fmtDate(dateFromDay(2001, a.nowX));
    $("table").innerHTML = `<table><thead><tr><th>Season</th><th>Peak</th><th>Peak date</th><th>On ${nowLabel}</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  function renderMeta(data) {
    const geoName = GEO_NAMES[data.geo] || data.geo;
    document.querySelectorAll("[data-geo]").forEach((el) => (el.textContent = geoName));
    $("brand").textContent = `How festive is ${geoName}?`;
    document.title = `How Festive Is ${geoName}?`;
    const updated = new Date(data.updated);
    $("stamp").textContent = `Updated ${updated.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" })} UTC`;
    const q = encodeURIComponent(data.term);
    $("source-link").href = `https://trends.google.com/trends/explore?q=${q}${data.geo && data.geo !== "Worldwide" ? `&geo=${data.geo}` : ""}`;
    return geoName;
  }

  async function main() {
    try {
      const res = await fetch("data/trends.json", { cache: "no-cache" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const geoName = renderMeta(data);
      const a = analyse(data);
      renderVerdict(a, geoName);
      renderTiles(a);
      renderChart(a);
      renderTable(a);
      let t;
      addEventListener("resize", () => { clearTimeout(t); t = setTimeout(() => {
        renderChart(a);
        $("meter-fill").style.setProperty("--track-w", `${$("meter").clientWidth}px`);
      }, 150); });
      matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => renderChart(a));
    } catch (err) {
      $("verdict-title").textContent = "No data yet";
      $("verdict-blurb").textContent = `Couldn't load data/trends.json (${err.message}). Run scripts/fetch_trends.py to fetch it.`;
      console.error(err);
    }
  }

  main();
})();
