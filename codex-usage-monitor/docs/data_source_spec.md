# Codex Usage Monitor data-source specification

## Scope and trust levels

The monitor uses these mutually exclusive source labels:

| Label | Meaning |
| --- | --- |
| Official | Data returned by the documented Codex App Server protocol. It is not automatically manually verified. |
| Verified Local | A local representation repeatedly matched by a person to Codex Settings → Usage. |
| Local Unverified | A local file or log with no confirmed schema or UI match. |
| Estimated | A disclosed heuristic; never shown as official usage. |
| Unknown | No usable data. |

`verified` is a separate boolean. It remains `false` until the user compares the values with Codex → Settings → Usage.

## Candidate A — documented Codex App Server (selected for manual verification)

### Access method

Start a local `codex app-server` child using its default stdio JSONL transport, complete the documented `initialize` / `initialized` handshake, then issue **only** this JSON-RPC request:

```json
{"method":"account/rateLimits/read","id":1,"params":{}}
```

This is a documented Codex local protocol, not an invented HTTP endpoint. No token, cookie, Authorization header, login request, token refresh, reset-consumption request, or credential is supplied, exported, or persisted by the monitor. The Codex service may require the existing managed sign-in and network availability to obtain current limits.

### Response semantics

OpenAI documents the following fields on a rate-limit window:

| App Server field | Type | Meaning | Monitor treatment |
| --- | --- | --- | --- |
| `limitId` | string | Metered quota-bucket identifier | Accept only `"codex"`; ignore unrelated buckets. |
| `primary` / `secondary` | object or `null` | Distinct quota windows | Do not infer solely from position. |
| `usedPercent` | number | Current usage in the quota window | Require an integer in `0..100`; map directly to `*_used`. |
| `windowDurationMins` | integer | Window length in minutes | Require exact duration for mapping. |
| `resetsAt` | integer | Next reset as Unix seconds | Convert to timezone-aware UTC `datetime`. |

`remaining` is derived as `100 - usedPercent` only after a valid numeric percentage is returned. `None`, rather than `0`, represents unknown data.

### Window mapping rule

The Phase-2 read returned a `codex` primary window of `300` minutes and a `codex` secondary window of `10080` minutes. These are candidates for 5-hour and weekly windows, respectively.

The future reader must map them only when all of the following hold:

1. `limitId == "codex"`;
2. `windowDurationMins == 300` for the five-hour field, or `10080` for the weekly field;
3. `usedPercent` and `resetsAt` have valid types and ranges.

If a duration changes, a window is missing, or more than one matching window exists, the affected fields are `None` and the snapshot is `malformed` or `unavailable`; no fallback guess is allowed.

### Freshness and updates

`account/rateLimits/read` obtains a point-in-time snapshot. The documented `account/rateLimits/updated` notification can indicate changes, but no subscription or background refresh is implemented in Phase 2. A future reader must timestamp each response and treat failed, missing, or stale reads as unavailable.

### Current confidence

Source label: **Official**. Verification: **pending manual verification**. The protocol and units are documented, but the mapping to the values rendered in this user's Desktop Usage screen must be confirmed manually.

## Candidate B — local files and Desktop logs (not selected)

`%USERPROFILE%\.codex` state/SQLite files and MSIX `LocalCache\Local\Codex\Logs` contain relevant keywords. Phase 1 did not establish their JSON/SQLite/log schema, account scope, update frequency, timestamp unit, or relationship to the Usage screen. They remain **Local Unverified** and must not supply `UsageSnapshot` values.

## Exceptions and status mapping

| Condition | Snapshot fields | Status | Source |
| --- | --- | --- |
| Valid official windows; awaiting UI comparison | Values populated | `pending_manual_verification` | Official |
| No signed-in Codex account, unavailable service, or network failure | `None` | `unavailable` | Unknown |
| Incorrect types, out-of-range percent, ambiguous/missing window | Affected fields `None` | `malformed` | Official |
| Future data exceeds its freshness threshold | Affected fields `None` | `stale` | Official |

## Manual verification procedure

1. Immediately after a Phase-2 read, open **Codex → Settings → Usage** for the same account/workspace.
2. Compare the 5-hour used percentage, weekly used percentage, and both reset times. Allow only ordinary UI rounding/timezone presentation differences.
3. Repeat on at least three reads, ideally including a changed percentage or reset boundary.
4. Report each comparison result to the monitor maintainer. Only then may `verified` become `true`.
