# GTA VI Launch-Day Twitch Forecast

[![bounty](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/keyxdrop/gta6-twitch-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/keyxdrop/gta6-twitch-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)

Entry for the make.fun bounty
[gta6-twitch-ccu-forecast-01](https://make.fun/bounty/gta6-twitch-ccu-forecast-01):
a Python program (stdlib only, offline, deterministic) that reads one case
— a game launch's Twitch viewer counts up to the end of hour 1 of its
release day — and writes five quantiles (5/25/50/75/95%) of the viewer
count for each of hours 2 to 24.

## Method

A launch day's shape is borrowed from the comparable launches inside the
case, weighted two ways: by unlock pattern (a rolling midnight-local
console launch does not move like a single global PC unlock, and early
access shifts a curve) and by how closely each comparable's pre-release
ramp — the twelve hours ending at hour 1 — tracks the target's own ramp.
From that weighted pool, each hour blends two views: the weighted median
of the pool's log-ratios to their own hour 1, and a per-hour weighted
regression of log viewers on log hour-1 viewers with its slope shrunk
toward 1, so a huge or small first hour bends the curve instead of just
scaling it. Quantile widths come from the pool's spread at that hour,
rescaled, with the outer quantiles damped slightly.

## Validation

The kit's scorer is server-side, so the program was validated by
leave-one-out cross-validation over the 37 usable comparable launches in
the practice data: each launch in turn was rebuilt as a pseudo-case
(hour 1 known, the other launches as its comparables), forecast, and
scored with the competition's pinball loss on the log scale, with the
house baseline formula scored under the identical protocol.

| pool | this program | house baseline |
| --- | --- | --- |
| all 37 launches | 0.5975 | 0.9296 |
| rolling-unlock launches (12) | 0.2385 | 0.3568 |
| clean console single-player launches (9) | 0.2150 | 0.2994 |

Runtime is about 0.16 s per case locally, far under the 8 s limit, and
two runs of the same case produce byte-identical output.

## Layout

- `main.py` — the entry program. It reads every `*.in` file in
  `$MAKEFUN_INPUT_DIR` (else `/input`) and writes one `<id>.out` per case
  to `$MAKEFUN_OUTPUT_DIR` (else `/output`).

## License

MIT — see `LICENSE`.
