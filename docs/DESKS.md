# The four desks — one system

Everything in this repo is one system of four desks that share a clock (America/Chicago), a lock set, a book, a bus, a ledger, a data directory, and one CLI: `python3 -m dm_desk <desk> <command>`.

| Desk | Module | Owns | Reads | Writes | Never |
|---|---|---|---|---|---|
| **Knowledge** (the box) | `knowledge_desk.py`, `circle.py`, `scripts/` | `knowledge/`: sources, digests, `state_card.md`, `knowledge.json`, indexes | Circle (via Gatekeeper) or dropped files | `knowledge/`; P1 "new Drive doc" signal | scores trades; invents missing weeks; stores member PII |
| **Research** (DM desk) | `desk.py`, `gate.py`, `packet.py`, `ledger.py`, `eod.py` | the game plan, the packet, the EOD, the ledger | `knowledge/`, tape, locks, ledger, advisor candidates | user thread (READY/PROBLEM/SCHEDULED), desk log, CrashForge handoff, ledger | places trades; ARMs LIVE; APPLYs; rewrites locks; hands off wrappers; fills the slot |
| **Engine** | `engine/` | pattern atlas, links, QUBO selection, uniqueness guard | knowledge store, ledger | `data/engine/`, candidate packets to the research gate | emits without the gate; more than one per day; quantum hardware claims |
| **Execution** (CrashForge) | `execution.py` | standing-order rows, fire receipts, EV resolutions | tape, locks, rows | `standing_orders.jsonl`, `fire_receipts.jsonl`, `resolutions.jsonl`, user thread on fires | fires from a packet with no ARMED row; overrides a lock with EV; ADDs to a LIVE row; touches HOLD VTI+IBIT |

## The one human action
The research desk posts a packet. The operator **arms** it once, in advance: `dm_desk execution arm --from-packet DM-YYYYMMDD-##`. That is the APPLY. From then on the execution desk fires it with zero per-trade clicks when tape enters the band and every lock passes. Nothing else in the system asks for confirmation.

## Clock
| Time (America/Chicago) | Desk | Action |
|---|---|---|
| every 4h, all days | knowledge | Circle/Drive sync when configured; ingest on arrival |
| every 4h, all days | engine | KB-Scanner delta → atlas → links (inside the research scan when `--advisor engine`) |
| every 4h, all days | research | scan; silent unless a trigger fires; heartbeat to desk log |
| every 4h, all days | execution | manage LIVE rows: target / invalidation / expiry → flatten, log |
| 06:45 weekdays | research | game plan to user thread; packet only if it clears the gate; else `PACKET: NONE` |
| 08:25 weekdays | execution | pre-bell fire window over ARMED rows |
| 16:00 weekdays | research | EOD review, 12 lines, no new strategy |
Holidays: 4h loop continues; the three weekday slots are marked HOLIDAY.

## Handoffs (files, not chat)
knowledge → research: `knowledge/knowledge.json` + `manifest.json` (Drive latest line) · engine → research: `Packet` candidates through the `Advisor` interface · research → execution: `ledger.jsonl` (packet body) → operator `arm` → `standing_orders.jsonl` · execution → research: `fire_receipts.jsonl` for the EOD `PACKET: applied-by-user` line · every desk → operator: `user_thread.log` (READY / PROBLEM / SCHEDULED only), `desk.log` (heartbeats, P1/P2).

## Locks (read-only for every desk)
VIX22 · CII0.08 · SPY5d−4% · ARM LIVE≠ADD · lag>20=STALE · front-run invalid. Unknown input = FAIL. A FAIL forces `DO NOT APPLY` on packets and HELD on rows. The EV resolver only ranks options that keep every lock intact; if none remain it flattens.

## Operating prompts
`docs/DM_DAILY_PLAN_v2.md` (research), `docs/KB_STRATEGY_ENGINE.md` (engine), `docs/DM_CIRCLE_BOT_TEAM.md` (knowledge ingest team), `docs/CRASHFORGE_EXECUTION.md` (execution). Where a prompt and this page disagree, this page and the code win.
