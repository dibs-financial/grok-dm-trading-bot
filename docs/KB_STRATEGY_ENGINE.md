# Multi-Bot KB Strategy Engine — System Spec (as implemented)

Implemented in `dm_desk/engine/`. The engine mines the knowledge base (`knowledge/`), builds a pattern atlas, generates and scores candidate strategies with a QUBO selection step, filters them for uniqueness against the ledger, and hands survivors to the DM desk. **The desk's 13-item qualification gate remains the only thing that decides whether a packet ships.** The engine proposes; the gate decides.

## 0. Reconciliation with DM Daily Plan v2 (binding)

| Engine spec says | Daily Plan v2 says | What is implemented |
|---|---|---|
| Strategy-Emitter emits one plan per day in a fixed window | A daily-strategy quota is a production bug; `PACKET: NONE` is a valid day | **At most one** accepted emission per day. If no candidate clears Uniqueness-Guard *and* the desk gate, the 6:45 game plan ends `PACKET: NONE — <reason>`. |
| "Never reuses a prior tactic; daily uniqueness is hard" | Novelty must not become invention; allowed variants exist | Exact/near-duplicate fingerprints are rejected. A same-family candidate passes only via the plan's four allowed-variant conditions. Novelty deficit never forces a synthetic candidate. |
| Quantum annealer / QAOA | (no position; ThreadWeaver rule: no "powered by quantum") | A QUBO is built exactly as specified and solved with a **quantum-inspired classical simulated annealer** (stdlib only). The solver is a pluggable interface; nothing claims quantum hardware. |
| Bots share an event bus | Boxes hand off by files, not chat | In-process event bus that appends to `data/engine_events.jsonl`; every stage is idempotent and checkpointed. |
| Emits "ready-to-implement plan" | Advisory only; user APPLYs; CrashForge never silent-fires | The emission is a desk packet plus implementation steps. It carries `USER ACTION: APPLY or ignore`. |

## 1. Bot roster

| Bot | Module | Cadence | Duty |
|---|---|---|---|
| KB-Scanner | `engine/scanner.py` | every 4h scan (or on demand) | Diff `knowledge/` by content hash; normalize `knowledge.json` into a triple store (subject, predicate, object, date, cite) plus a time series; checkpoint. |
| Pattern-Miner | `engine/patterns.py` | after each scan delta | Rebuild the **pattern atlas**: level recurrence and hold/fail rates, weekly regime sequences and motif counts, extreme-fear forward returns, catalyst→outcome pairs, hike-odds vs BTC direction. Compact, cited. |
| Hybrid-Solver | `engine/solver.py` | daily trigger (6:45 game plan) or on demand | Classical candidate generation from the atlas → feasibility pre-filter → QUBO (utility + novelty bonus − coverage/conflict penalties, one-slot constraint) → simulated annealing → decode top-k into desk `Packet` candidates. |
| Uniqueness-Guard | `engine/guard.py` | pre-emit | Fingerprint = canonical hash of (rail, asset, side, trigger family, entry bucket, invalidation bucket, pattern ids). Reject on exact fingerprint or body hash, on token-set near-duplicate (Jaccard ≥ τ) against the ledger, or if a strategy was already accepted today. Returns a novelty-deficit signal to the solver. |
| Strategy-Emitter | `engine/emitter.py` | at most 1×/day, inside the 6:45 game plan | Wrap the gate-passed packet in the daily strategy template (ID, fingerprint, pattern ids, KB citations, steps). |
| Ledger-Keeper | `dm_desk/ledger.py` (+ fingerprint fields) | always-on | Append-only ledger of every emitted strategy: id, fingerprint, body hash, citations, pattern ids, outcomes. |

## 2. Scan loop
```
on each desk scan (4h) or `python3 -m dm_desk engine scan`:
  1. hash every file under knowledge/; compare with checkpoint -> delta set
  2. normalize knowledge.json -> triples (labels, levels, timeline, conflicts) + series (snapshots)
  3. tag each triple with date, cite, confidence (1.0 memo/slides; conflicts carry 'resolved')
  4. publish delta event on the bus; Pattern-Miner rebuilds the atlas from the full store
  5. write data/engine/{store.json, atlas.json, checkpoint.json}
```
The atlas is the only input surface for the solver, which keeps the combinatorial layer bounded.

## 3. Uniqueness filter
- Ledger rows carry `fingerprint`, `body_hash`, `pattern_ids`, `kb_citations`.
- Check order: exact fingerprint → exact body hash → Jaccard near-duplicate (τ = 0.8 default) → one-per-day → the plan's allowed-variant test for same trigger family.
- Rejections carry a reason and feed back to the solver as a novelty deficit (raises λ_novelty and re-anneals once; if still nothing, `PACKET: NONE`).

## 4. Hybrid algorithm
- **Classical.** Features per candidate: level recurrence, held-rate, analog hit-rate (from tape candles when available), R:R, distance from current price, regime fit (fear/greed bucket, hike-odds bucket), Drive freshness. Candidate set S: LONG at recurring support with invalidation at the next lower level and target at the next resistance, for spot BTC/ETH; SHORT only on a Drive-named perp rail. Pre-filter: R:R ≥ 2, within 10% of last price, invalidation outside noise.
- **QUBO.** Binary x_i per candidate. Energy = −Σ (u_i + λ n_i) x_i + P (Σ x_i − 1)² + Σ_{i<j} c_ij x_i x_j, where u = utility, n = novelty (1 − max similarity to ledger), c_ij = conflict penalty for same asset+side. Solved by simulated annealing (`engine/qubo.py`); `Solver` is an interface so an external annealer can be plugged in.
- **Post-process.** Decode low-energy bitstrings → ranked candidates → fill DeFi checklist from the operator-maintained `venues.json` (unknown venue ⇒ fields stay unknown ⇒ the gate fails closed) → hand to the desk gate.

## 5. Daily strategy template (Strategy-Emitter output)
```
strategy_id: DM-YYYYMMDD-##            # same id as the packet
date_utc: YYYY-MM-DD
fingerprint: <sha256 prefix>
pattern_ids: [level:BTC:82400, regime:fear->neutral, catalyst:CPI-soft, ...]
kb_citations: [[DM memo 2026-09-21], ...]
thesis: one line, derived from the atlas, no adjectives
packet:
  <the full desk packet block, verbatim>
steps:
  1. precondition check (Drive latest, locks, live level)
  2. venue + custody (wallet / lending market), order type, size = % of DeFi sleeve
  3. trigger monitor (the observable if-then) and who watches it
  4. invalidation order placed with the entry
  5. time stop enforcement
  6. ledger update at EOD / T+5
novelty: nearest ledger id + fingerprint distance + which allowed-variant condition applies
```

## 6. Success metrics
| Metric | Target |
|---|---|
| Scan idempotence: re-running scan with no KB change produces no delta | always |
| Atlas freshness: rebuilt within the same scan that ingested a delta | always |
| Uniqueness: emitted fingerprints repeated | 0 |
| Emission discipline: days with more than one accepted strategy | 0 |
| Gate respect: engine candidates that reached CrashForge without passing the desk gate | 0 |
| Silence: days where nothing qualified and the game plan said `PACKET: NONE` | every such day |
