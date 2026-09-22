# Changelog

## 2026-09-22 — knowledge box, four desks, engine, Circle client (main @ 38a5f60)

Fast-forwarded to `main` from `claude/box-knowledge-source-0zua4d` (8 commits, 128 files).

### Knowledge (the box) — `knowledge/`
- 46 uploaded DM Market Update files deduplicated by content hash to 27 distinct sources covering 15 weekly briefings (2026-05-11 → 2026-09-21).
- `state_card.md`: one current line per label plus a dated superseded rail, every line cited `[DM memo|slides YYYY-MM-DD]`.
- `knowledge.json`: snapshots, 48 support/resistance rows, labels, frameworks, timeline, upcoming catalysts.
- Nine source disagreements resolved on weight of sources; losing figures kept as errata.
- `loader.py` (`Knowledge().current("btc")`, `levels("BTC")`, `search()`, `context_pack()`), `weekly/` digests, `sources/`, `manifest.json`, `snapshots.csv`.
- `scripts/extract_sources.py` (ingest PDF/PPTX, dedupe, date from filename) and `scripts/build_manifest.py`.

### Research desk — `dm_desk/` (docs/DM_DAILY_PLAN_v2.md)
- 4h scan (silent unless a trigger fires), weekday 06:45 game plan (`PACKET: NONE` when nothing clears), weekday 16:00 EOD (12-line cap).
- Hard-lock precheck (VIX22 / CII0.08 / SPY5d−4% / ARM LIVE≠ADD / lag>20=STALE / front-run), fail closed on unknown inputs.
- 13-item qualification gate + DeFi checklist; wrapper rails rejected first; any lock FAIL forces `DO NOT APPLY`.
- Packet schema, append-only ledger with novelty rules, analog history counter, Coinbase/file tape, knowledge/folder Drive, null/file/grok advisors.

### Engine — `dm_desk/engine/` (docs/KB_STRATEGY_ENGINE.md)
- KB-Scanner (hash-diff, triple store), Pattern-Miner (level recurrence and hold rates, regime motifs, extreme-fear forward returns, catalyst outcomes), ingest ranking and cross-link propagator, level aliases.
- Hybrid-Solver: candidates → QUBO → quantum-inspired simulated annealing (stdlib) → desk packets. Uniqueness-Guard: fingerprint, body hash, near-duplicate, at most one emission per day.

### Execution desk — `dm_desk/execution.py` (docs/CRASHFORGE_EXECUTION.md)
- Operator-ARMED standing-order rows (the one human action), 08:25 fire window with lock check on the firing quote, ARM LIVE≠ADD, stale tape never fires, 4h manage to target/invalidation/expiry, EV resolver over lock-compliant options only, paper broker, Robinhood stub that refuses without an approved integration.

### Circle — `dm_desk/circle.py` (docs/DM_CIRCLE_BOT_TEAM.md)
- Gatekeeper (token from env only), Scout (spaces, posts newest first, watermark), Capturer (attachments once, hand-off to the extractor). Untested live: no token and circle.so blocked from the build sandbox; covered by fake-transport tests.

### System — docs/DESKS.md
- One clock (America/Chicago), one lock set, one ledger, one bus, one CLI `python3 -m dm_desk <desk> <command>`, scheduler for all desks. 66 tests.
