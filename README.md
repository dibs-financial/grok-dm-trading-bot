# grok-dm-trading-bot
Decentralized Masters Trained (Grok) Bot On Robinhood Agentic.

## Knowledge source

The bot's market context lives in [`knowledge/`](knowledge/README.md): a structured, cited knowledge base built from the weekly DM Market Update memos and slide decks (May 11 → Sep 21, 2026).

- Start with [`knowledge/state_card.md`](knowledge/state_card.md) for the current belief per label (BTC, ETH, HYPE, Fed, oil/Iran, gold, equities, regulation, ...) with superseded history and resolved disagreements.
- Load it from code with `knowledge/loader.py` (`from knowledge.loader import Knowledge`), which reads `knowledge/knowledge.json`.
- Add a new week with `scripts/extract_sources.py` then `scripts/build_manifest.py` (see the knowledge README for the full procedure).

## The four desks

See [`docs/DESKS.md`](docs/DESKS.md). One system, one clock (America/Chicago), one lock set, one ledger, one CLI: `python3 -m dm_desk <desk> <command>`.

| Desk | What it does | Commands |
|---|---|---|
| `knowledge` | the box: ingest (Circle or files), extract, index `knowledge/` | `status`, `ingest PATH`, `sync --spaces "A,B"` |
| `research` | DM desk (Daily Plan v2): 4h scan, 6:45 game plan, 16:00 EOD; advisory only | `scan`, `gameplan`, `eod`, `run`, `ledger`, `outcome ID X`, `check FILE` |
| `engine` | pattern atlas → QUBO selection → uniqueness guard → candidates for the research gate | `scan`, `mine`, `solve`, `links` |
| `execution` | CrashForge: operator-armed rows fire at 08:25 with zero per-trade clicks; locks outrank EV | `rows`, `arm`, `cancel ID`, `fire`, `manage`, `resolve` |
| `status` | one line per desk | |

```bash
python3 -m dm_desk status
python3 -m dm_desk knowledge status
python3 -m dm_desk research gameplan --advisor engine --candidates examples/venues.json --tape file --tape-file examples/tape.json --locks examples/locks.json --force
python3 -m dm_desk execution arm --from-packet DM-20260922-01 --size 5
python3 -m dm_desk execution fire --tape file --tape-file examples/tape.json --locks examples/locks.json --force
python3 -m dm_desk execution resolve --issue "venue lag 18s" --edge 50 --locks examples/locks.json
python3 -m unittest discover -s tests
```

Operating prompts: [`docs/DM_DAILY_PLAN_v2.md`](docs/DM_DAILY_PLAN_v2.md), [`docs/KB_STRATEGY_ENGINE.md`](docs/KB_STRATEGY_ENGINE.md), [`docs/DM_CIRCLE_BOT_TEAM.md`](docs/DM_CIRCLE_BOT_TEAM.md), [`docs/CRASHFORGE_EXECUTION.md`](docs/CRASHFORGE_EXECUTION.md).

Adapters: tape `coinbase` (public) or `file`; Drive `knowledge` (default) or `folder`; advisor `null` | `file` | `grok` (needs `XAI_API_KEY`) | `engine`; broker `paper` (default) or `robinhood` (stub, refuses without an approved integration). Circle access needs `CIRCLE_API_TOKEN` in the environment; see `dm_desk/circle.py`. Runtime outputs land in `dm_desk/data/` (git-ignored).
