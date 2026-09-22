# Phase 2 — data-source conclusion

## Result

There is currently **no reliable, scriptable, documented local source confirmed for this Windows account** that can produce the following values:

| Field | Reliable now? | Source classification |
| --- | --- | --- |
| `five_hour_used` | No | Unknown |
| `five_hour_remaining` | No | Unknown |
| `five_hour_reset_at` | No | Unknown |
| `weekly_used` | No | Unknown |
| `weekly_remaining` | No | Unknown |
| `weekly_reset_at` | No | Unknown |

The monitor must therefore not show a percentage, reset timestamp, or an `Official` label at this stage. Its future UI should show **Unable to read usage** until a source passes verification. It must not silently substitute zero.

## Investigation result

1. **Official CLI surface — insufficient for automation.** The installed `codex-cli 0.154.0-alpha.6.2` exposes no `status` command in `codex --help`. OpenAI documentation describes `/status` only as an interactive command in an active CLI session, not a stable JSON or read-only command for external tools.
2. **Desktop UI — official display, no supported local export found.** OpenAI documentation directs the user to **Settings → Usage** for the current allowance and reset times. This is the authoritative comparison target, but no public local file/API contract was found for extracting the values.
3. **Local state and logs — possible, not verified.** Diagnostics found keyword hits in `%USERPROFILE%\.codex\.codex-global-state.json` and in MSIX `LocalCache` Codex logs. Keyword presence alone does not establish schema, freshness, account scope, field semantics, or a stable contract. These are `Local / Unverified`, never `Official`.
4. **Public API — not applicable.** Platform API rate limits are distinct from a ChatGPT-plan Codex allowance. This project will not use an API key, invent an endpoint, or make network requests.

## Required verification gate for a future parser

Before a candidate source can be promoted to `Official / Verified`:

1. Parse only specifically identified, non-credential fields.
2. Record no secrets and make no change to Codex data.
3. Compare five-hour and weekly remaining percentages plus reset times with **Codex → Settings → Usage** on at least three separate refreshes, including a value change or reset boundary.
4. Reject it if any field is stale, missing, ambiguous, or differs from the UI beyond normal timestamp rounding.

Until that gate is passed, a future implementation may provide only an explicitly labelled **Estimated Usage** mode, based on a separately documented local heuristic. Phase 2 does not implement such a heuristic.

## Reproduce Phase 1 diagnostics

```powershell
python .\diagnostics\diagnostics.py
```

The generated `diagnostics\diagnostics_report.txt` lists candidate paths and keyword labels only. It deliberately excludes files whose names indicate authentication material and never reports matched content.

## Tests

```powershell
python -m unittest discover -s tests -t . -v
```

The tests cover keyword detection, credential-like filename exclusion, root scanning, and source classification. They create only temporary test files.
