# grok-dm-trading-bot
Decentralized Masters Trained (Grok) Bot On Robinhood Agentic.

## Knowledge source

The bot's market context lives in [`knowledge/`](knowledge/README.md): a structured, cited knowledge base built from the weekly DM Market Update memos and slide decks (May 11 → Sep 21, 2026).

- Start with [`knowledge/state_card.md`](knowledge/state_card.md) for the current belief per label (BTC, ETH, HYPE, Fed, oil/Iran, gold, equities, regulation, ...) with superseded history and resolved disagreements.
- Load it from code with `knowledge/loader.py` (`from knowledge.loader import Knowledge`), which reads `knowledge/knowledge.json`.
- Add a new week with `scripts/extract_sources.py` then `scripts/build_manifest.py` (see the knowledge README for the full procedure).

## DM desk (advisory)

`dm_desk/` implements [`docs/DM_DAILY_PLAN_v2.md`](docs/DM_DAILY_PLAN_v2.md): the Decentralized Masters research desk. Advisory only. It never places trades, never ARMs LIVE, never APPLYs, and never rewrites CrashForge hard locks (VIX22 / CII0.08 / SPY5d−4% / ARM LIVE≠ADD / lag>20=STALE / front-run invalid).

- **Loop.** `scan` every 4 hours (silent unless a trigger fires; heartbeat to the desk log), weekday **6:45** `gameplan` (packet only if it clears the 13-item gate, else `PACKET: NONE — <reason>`), weekday **16:00** `eod` (12-line review, no new strategy). `run` drives all three on the wall clock in America/Chicago; holidays keep the 4h loop.
- **Drive.** The knowledge base in `knowledge/` is the indexed Drive folder (`--drive knowledge`, default). `--drive folder PATH` watches a synced folder and ingests new memos first.
- **Tape.** `--tape coinbase` (public, no key) or `--tape file --tape-file examples/tape.json` for offline runs.
- **Locks.** `--locks examples/locks.json` supplies VIX / CII / SPY 5d. Unknown inputs fail closed.
- **Advisor.** Candidates come from `--advisor null` (default, proposes nothing), `--advisor file --candidates PATH`, or `--advisor grok` (xAI, needs `XAI_API_KEY`). The gate decides; the advisor only proposes.
- **Outputs** land in `dm_desk/data/`: `user_thread.log` (READY / PROBLEM / SCHEDULED only), `desk.log` (heartbeats, P1/P2), `crashforge_handoff.log` (full packets only), `ledger.jsonl` (novelty and misses read this first).

```bash
python3 -m dm_desk scan     --tape file --tape-file examples/tape.json --locks examples/locks.json
python3 -m dm_desk gameplan --tape file --tape-file examples/tape.json --locks examples/locks.json --advisor file --candidates examples/candidates.json --force
python3 -m dm_desk eod      --tape file --tape-file examples/tape.json --locks examples/locks.json --force
python3 -m dm_desk check examples/candidates.json      # dry-run the gate
python3 -m dm_desk outcome DM-20260922-01 applied-by-user
python3 -m unittest discover -s tests
```

## KB strategy engine

`dm_desk/engine/` implements [`docs/KB_STRATEGY_ENGINE.md`](docs/KB_STRATEGY_ENGINE.md): KB-Scanner (hash-diff of `knowledge/`, triple store), Pattern-Miner (level recurrence and hold rates, regime motifs, extreme-fear forward returns, catalyst outcomes), Hybrid-Solver (classical candidates → QUBO → quantum-inspired simulated annealing → desk packets), Uniqueness-Guard (fingerprint, body hash, near-duplicate, at most one emission per day), Strategy-Emitter (daily template around the packet), Ledger-Keeper (fingerprints on the ledger). The engine only proposes; the desk gate decides, and `PACKET: NONE` remains a valid day.

```bash
python3 -m dm_desk engine mine  --data-dir /tmp/dm                       # scan + pattern atlas
python3 -m dm_desk engine solve --data-dir /tmp/dm --candidates examples/venues.json
python3 -m dm_desk gameplan --advisor engine --candidates examples/venues.json --tape file --tape-file examples/tape.json --locks examples/locks.json --force
```
`examples/venues.json` is operator-maintained; a rail missing from it leaves the DeFi checklist unknown and the gate fails it closed.
