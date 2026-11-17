#!/usr/bin/env python3
"""Forecast a game launch day's Twitch viewers, hours 2..24, as quantiles.

Method, in one paragraph: a launch day's shape is borrowed from the
comparable launches inside the case, but not all comparables are equal.
Each comparable is weighted by (a) whether its unlock pattern matches the
target's -- a rolling midnight-local console launch does not move like a
single global PC unlock -- and (b) how closely its pre-release ramp, the
twelve hours ending at hour 1, tracks the target's own ramp. From the
weighted pool two views of every hour are blended: the weighted median of
the pool's log-ratios to their own hour 1, and a per-hour weighted
regression of log viewers on log hour-1 viewers (its slope shrunk toward
1), which lets a huge or small first hour bend the curve. The quantile
widths come from the pool's spread at that hour, rescaled, with the two
outer quantiles damped a little because a few dozen launches cannot pin
a 5% tail exactly.

Reads every *.in case in $MAKEFUN_INPUT_DIR (else /input) and writes one
<id>.out per case to $MAKEFUN_OUTPUT_DIR (else /output). Stdlib only,
deterministic, offline.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone

LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
Z = (-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722)

# Calibration constants, tuned by leave-one-out cross-validation over the
# comparable launches themselves (see README).
W_ROLLING = 3.0        # unlock-pattern weight: rolling midnight local
W_GLOBAL = 0.3         # unlock-pattern weight: single global unlock
W_EARLY_ACCESS = 0.6   # extra factor when a launch had early access
TRAJ_SIGMA = 1.4       # width of the ramp-similarity kernel
TRAJ_FLOOR = 0.03      # a dissimilar launch never quite vanishes
REG_BLEND = 0.7        # centre: regression share (median gets the rest)
SLOPE_SHRINK = 0.2     # regression slope pulled this far toward 1
SPREAD_SCALE = 0.85    # multiplies the blended per-hour log spread
TAIL_DAMP = 0.85       # extra damping on the 5% and 95% quantiles
MIN_SPREAD = 0.10      # never claim a tighter hour than this
RAMP_OFFSETS = tuple(range(-11, 2))  # hours -11..1 frame the ramp


def parse_ts(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc)


def hourly_by_index(day_start_text, rows, stamp_key):
    """Mean viewers per hour index (1 = first hour of the day)."""
    try:
        start = parse_ts(day_start_text)
    except (KeyError, ValueError):
        return {}
    buckets = {}
    for row in rows or []:
        try:
            when = parse_ts(row[stamp_key])
            viewers = float(row["viewers"])
        except (KeyError, ValueError, TypeError):
            continue
        if viewers > 0:
            idx = int((when - start).total_seconds() // 3600) + 1
            buckets.setdefault(idx, []).append(viewers)
    return {h: sum(v) / len(v) for h, v in buckets.items()}


def unlock_class(text):
    t = (text or "").lower()
    if "midnight local" in t or "rolling" in t:
        return "rolling"
    if ("global unlock" in t or "single global" in t or "simultaneous" in t
            or "one global" in t):
        return "global"
    return "other"


def ramp_shape(series, base_idx=1):
    """Log viewers relative to hour 1 over the ramp window, if known."""
    if base_idx not in series:
        return {}
    base = math.log(series[base_idx])
    return {h: math.log(series[h]) - base
            for h in RAMP_OFFSETS if h in series}


def ramp_distance(shape_a, shape_b):
    common = [h for h in RAMP_OFFSETS if h in shape_a and h in shape_b]
    if len(common) < 6:
        return None
    return math.sqrt(
        sum((shape_a[h] - shape_b[h]) ** 2 for h in common) / len(common))


def weighted_quantile(pairs, tau):
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    acc = 0.0
    for i, (value, w) in enumerate(ordered):
        acc += w
        if acc >= tau * total:
            if i + 1 < len(ordered):
                return 0.5 * (value + ordered[i + 1][0])
            return value
    return ordered[-1][0]


def target_is_rolling(case, target_series):
    """Rolling launches are already ramping when the UTC day begins."""
    notes = (case.get("notes") or "").lower()
    if "midnight local" in notes or "rolling" in notes:
        return True
    if 1 not in target_series:
        return False
    v1 = target_series[1]
    seen = [target_series[h] for h in RAMP_OFFSETS
            if h < 1 and h in target_series]
    return len(seen) >= 6 and max(seen) >= 0.01 * v1


def build_pool(case, target_series):
    """Weighted comparable day series: [(series, weight, ramp_shape)]."""
    rolling_target = target_is_rolling(case, target_series)
    target_shape = ramp_shape(target_series)
    pool = []
    for comp in case.get("comparables") or []:
        series = hourly_by_index(comp.get("day_start"),
                                 comp.get("hourly"), "from")
        day = {h: v for h, v in series.items() if 1 <= h <= 24}
        if 1 not in day or len(day) < 12:
            continue
        weight = 1.0
        if rolling_target:
            cls = unlock_class(comp.get("unlock"))
            if cls == "rolling":
                weight *= W_ROLLING
            elif cls == "global":
                weight *= W_GLOBAL
            if "early access" in (comp.get("unlock") or "").lower():
                weight *= W_EARLY_ACCESS
        dist = ramp_distance(target_shape, ramp_shape(series))
        if dist is not None:
            weight *= math.exp(-((dist / TRAJ_SIGMA) ** 2)) + TRAJ_FLOOR
        pool.append((series, weight))
    return pool


def hour_forecast(log_p1, pool):
    """Blended centre and spread per hour, in absolute log space."""
    out = {}
    for hour in range(2, 25):
        ratios = []
        points = []
        for series, weight in pool:
            if hour in series and 1 in series:
                ratios.append((math.log(series[hour] / series[1]), weight))
                points.append((math.log(series[1]),
                               math.log(series[hour]), weight))
        if len(ratios) < 6:
            continue
        med_centre = weighted_quantile(ratios, 0.5)
        med_spread = (weighted_quantile(ratios, 0.75)
                      - weighted_quantile(ratios, 0.25)) / 1.349
        total_w = sum(w for _, _, w in points)
        mean_x = sum(w * x for x, _, w in points) / total_w
        mean_y = sum(w * y for _, y, w in points) / total_w
        sxx = sum(w * (x - mean_x) ** 2 for x, _, w in points)
        sxy = sum(w * (x - mean_x) * (y - mean_y) for x, y, w in points)
        slope = sxy / sxx if sxx > 1e-9 else 1.0
        slope = (1.0 - SLOPE_SHRINK) * slope + SLOPE_SHRINK
        reg_centre = mean_y + slope * (log_p1 - mean_x)
        var = sum(w * (y - (mean_y + slope * (x - mean_x))) ** 2
                  for x, y, w in points) / total_w
        centre = ((1.0 - REG_BLEND) * (log_p1 + med_centre)
                  + REG_BLEND * reg_centre)
        spread = ((1.0 - REG_BLEND) * med_spread
                  + REG_BLEND * math.sqrt(var))
        out[hour] = (centre, max(MIN_SPREAD, spread * SPREAD_SCALE))
    return out


def forecast_case(case):
    known = case.get("known") or []
    p1 = 1.0
    if known:
        try:
            p1 = max(1.0, float(known[0]["viewers"]))
        except (KeyError, ValueError, TypeError):
            p1 = 1.0
    log_p1 = math.log(p1)
    target_series = hourly_by_index(case.get("day_start"),
                                    case.get("history_hourly"), "from")
    target_series[1] = p1
    pool = build_pool(case, target_series)
    stats = hour_forecast(log_p1, pool) if pool else {}
    rows = []
    last = (log_p1, 0.35)
    for hour in range(2, 25):
        centre, width = stats.get(hour, last)
        last = (centre, width)
        qs = []
        for idx, z in enumerate(Z):
            damp = TAIL_DAMP if idx in (0, len(Z) - 1) else 1.0
            value = math.exp(centre + z * width * damp)
            qs.append(min(1e9, max(0.01, round(value, 2))))
        for i in range(1, len(qs)):
            if qs[i] < qs[i - 1]:
                qs[i] = qs[i - 1]
        rows.append({"hour": hour, "q": qs})
    return {"hours": rows}


def main():
    in_dir = os.environ.get("MAKEFUN_INPUT_DIR") or "/input"
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(out_dir, exist_ok=True)
    names = sorted(n for n in os.listdir(in_dir) if n.endswith(".in"))
    for name in names:
        with open(os.path.join(in_dir, name), encoding="utf-8") as fh:
            case = json.load(fh)
        result = forecast_case(case)
        out_name = str(case.get("id") or name[:-3]) + ".out"
        with open(os.path.join(out_dir, out_name), "w",
                  encoding="utf-8") as fh:
            json.dump(result, fh, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
