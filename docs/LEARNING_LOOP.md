# Learning loop

The learning processor consumes raw events in chronological order. It applies
lazy decay before each update:

```text
w_eff = w * 0.97 ^ days_since_last_update
```

## Signals

| Event | Signal |
|---|---:|
| click | +1.0 |
| long read (return after at least 30 seconds) | +0.5 |
| bounce (return within 8 seconds) | -0.4 |
| expand summary | +0.3 |
| save / like | +2.0 |
| dislike | -2.0 |
| less topic | -3.0 |
| seen without click after the edition day | -0.1 × position factor |

Positive click-type signals use `min(2.5, s / e(p))`, where
`e(p) = 1 / (1 + 0.25 × (p - 1))`. Primary topics receive the adjusted
signal, secondary topics receive half, and the source receives 0.3 times the
adjusted signal. Topic weights are clamped to `[-5, 10]`; source weights use
the same clamp. PDF clicks do not create impression penalties.

Positive events also update long and short interest vectors, using rates 0.04
and 0.20 respectively, capped at signal 2 and normalized after each update.
Updates are skipped when the article embedding is missing or uses another
embedder.

## Exploration

The exploration share is:

```text
max(user_exploration_floor, 0.40 - 0.05 × editions_read)
```

For topics outside the reader's top three, the recommender draws
`Beta(1 + clicks, 1 + max(views - clicks, 0))` with a deterministic seed made
from the user ID and edition date. The best eligible story from the highest
drawn topics fills exploration slots.

## Worked example

For a position-3 save, `e(3) = 0.615`. The adjusted signal is
`min(2.5, 2.0 / 0.615) = 2.5`. A primary topic increases by 2.5, a secondary
topic by 1.25, and the source by 0.75, subject to clamping and decay.

Raw events remain in SQLite with `processed_at` until consumed. Use
`python -m app.cli process-events --user-id USER_ID` to process them, or add
`--dry-run` to inspect before/after topic weights.
