"""The desk loop: 4h scan, weekday 6:45 game plan, weekday 16:00 EOD, escalation and sinks.

Everything the desk emits goes through one of three sinks:
  user   - the user thread. Only READY / PROBLEM / SCHEDULED.
  log    - desk log. Heartbeats and P2 notes. Never the user thread.
  cf     - CrashForge handoff. Only full packets that passed the gate. CrashForge must not
           silent-fire from these; the user must APPLY.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config as C
from . import eod as eod_mod
from .advisor import Advisor, NullAdvisor
from .drive import DriveUnavailable, KnowledgeDrive, WatchedLevel
from .gate import qualify
from .history import count_analogs
from .ledger import Ledger
from .locks import LockInputs, LockResult, check as lock_check
from .packet import Packet
from .tape import Quote, TapeError, TapeProvider

TZ = ZoneInfo(C.TZ)


# ---- sinks ------------------------------------------------------------------------------
class Sinks:
    def __init__(self, data_dir: str = C.DATA_DIR, echo: bool = True):
        self.dir = data_dir
        self.echo = echo
        os.makedirs(data_dir, exist_ok=True)

    def _append(self, name: str, text: str) -> None:
        with open(os.path.join(self.dir, name), "a") as fh:
            fh.write(text.rstrip() + "\n")

    def user(self, kind: str, text: str) -> None:
        """kind: READY | PROBLEM | SCHEDULED"""
        assert kind in ("READY", "PROBLEM", "SCHEDULED"), kind
        stamped = f"[{kind}] {text}"
        self._append("user_thread.log", stamped)
        if self.echo:
            print(stamped)

    def log(self, text: str) -> None:
        self._append("desk.log", text)
        if self.echo:
            print(f"(desk log) {text}")

    def cf(self, packet_text: str) -> None:
        self._append("crashforge_handoff.log", packet_text + "\n---")
        if self.echo:
            print("(-> CrashForge priority packet posted; CrashForge must not silent-fire)")


# ---- persistent scan state ---------------------------------------------------------------
@dataclass
class State:
    last_drive_date: str | None = None
    last_scan_iso: str | None = None
    last_lock_status: str | None = None
    last_prices: dict[str, float] = field(default_factory=dict)
    consecutive_failures: int = 0
    drive_down_since_iso: str | None = None
    scans_today: int = 0
    scans_day: str = ""
    gameplan_posted_day: str = ""
    silence_broken_without_trigger: bool = False

    @classmethod
    def load(cls, path: str) -> "State":
        if os.path.exists(path):
            with open(path) as fh:
                return cls(**json.load(fh))
        return cls()

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(self.__dict__, fh, indent=2)


@dataclass
class ScanReport:
    ts: datetime
    drive_latest: str | None
    quotes: dict[str, Quote]
    locks: LockResult
    triggers: list[str]                 # what broke silence (empty = silent success)
    problems: list[str]
    p1: list[str]
    heartbeat: str


class Desk:
    def __init__(self, drive: KnowledgeDrive | None = None, tape: TapeProvider | None = None,
                 advisor: Advisor | None = None, sinks: Sinks | None = None, ledger: Ledger | None = None,
                 lock_inputs: LockInputs | None = None, data_dir: str = C.DATA_DIR, book: C.Book | None = None):
        self.data_dir = data_dir
        self.drive_factory = drive
        self.tape = tape
        self.advisor = advisor or NullAdvisor()
        self.sinks = sinks or Sinks(data_dir)
        self.ledger = ledger or Ledger(os.path.join(data_dir, "ledger.jsonl"))
        self.lock_inputs = lock_inputs or LockInputs()
        self.book = book or C.Book()
        self.state = State.load(os.path.join(data_dir, "state.json"))
        if not self.ledger.present:
            self.ledger._write()          # creates an empty ledger; 'missing' is reserved for a lost file
            self.sinks.log("ledger initialized empty at " + self.ledger.path)

    # ---- helpers ------------------------------------------------------------------------
    def now(self) -> datetime:
        return datetime.now(TZ)

    def _save(self) -> None:
        self.state.save(os.path.join(self.data_dir, "state.json"))

    def _drive(self):
        return self.drive_factory if self.drive_factory is not None else KnowledgeDrive()

    @staticmethod
    def is_holiday(d: datetime) -> bool:
        return d.strftime("%Y-%m-%d") in C.US_MARKET_HOLIDAYS

    @staticmethod
    def is_weekday(d: datetime) -> bool:
        return d.weekday() < 5

    def _lock_inputs_with_lag(self, quotes: dict[str, Quote]) -> LockInputs:
        li = LockInputs(**self.lock_inputs.__dict__)
        if quotes:
            li.lag_seconds = max(q.lag_seconds for q in quotes.values())
        return li

    # ---- 4h scan --------------------------------------------------------------------------
    def scan(self) -> ScanReport:
        ts = self.now()
        st = self.state
        day = ts.strftime("%Y-%m-%d")
        if st.scans_day != day:
            st.scans_day, st.scans_today = day, 0
        st.scans_today += 1
        triggers: list[str] = []
        problems: list[str] = []
        p1: list[str] = []

        # Drive
        drive_latest = None
        new_docs = []
        try:
            drive = self._drive()
            latest = drive.latest()
            drive_latest = latest.date
            new_docs = drive.new_since(st.last_drive_date)
            watched = drive.watched_levels()
            st.drive_down_since_iso = None
        except DriveUnavailable as e:
            watched = []
            problems.append(f"Drive unread: {e}")
            st.drive_down_since_iso = st.drive_down_since_iso or ts.isoformat()
        if new_docs and st.last_drive_date is not None:
            triggers.append(f"new Drive doc(s): " + ", ".join(f"{d.kind} {d.date}" for d in new_docs[:3]))
            p1.append("newer memo than last study")
        if drive_latest:
            st.last_drive_date = max(st.last_drive_date or "", drive_latest)

        # Tape
        quotes: dict[str, Quote] = {}
        if self.tape is not None:
            for sym in ("BTC", "ETH"):
                try:
                    quotes[sym] = self.tape.quote(sym)
                except TapeError as e:
                    problems.append(f"tape {sym}: {e}")
        else:
            problems.append("no tape provider configured")

        # Watched levels touched / breached / inside 1%
        for w in watched:
            q = quotes.get(w.asset)
            if not q:
                continue
            prev = st.last_prices.get(w.asset)
            crossed = prev is not None and (min(prev, q.price) <= w.level <= max(prev, q.price))
            near = abs(q.price - w.level) / w.level <= C.LEVEL_PROXIMITY_P1
            if crossed:
                triggers.append(f"{w.asset} {w.role} {w.level:,.0f} touched/breached ({prev:,.0f} -> {q.price:,.0f}) {w.cite}")
            elif near:
                p1.append(f"{w.asset} inside 1% of {w.role} {w.level:,.0f} ({q.price:,.0f}) with no packet")
        for sym, q in quotes.items():
            st.last_prices[sym] = q.price

        # Locks
        locks = lock_check(self._lock_inputs_with_lag(quotes))
        if st.last_lock_status is not None and locks.status != st.last_lock_status:
            triggers.append(f"lock status {st.last_lock_status} -> {locks.status}: " + "; ".join(locks.reasons))
        elif locks.status in ("WARN", "FAIL") and st.last_lock_status is None:
            triggers.append(f"lock status {locks.status}: " + "; ".join(locks.reasons))
        st.last_lock_status = locks.status

        # Prior packet trigger / invalidation printed
        for e in self.ledger.open_packets():
            q = quotes.get(e.asset.upper())
            pk = Packet.from_dict(e.packet) if e.packet else None
            if not q or not pk:
                continue
            if pk.invalidation is not None and ((pk.side == "LONG" and q.price <= pk.invalidation) or (pk.side == "SHORT" and q.price >= pk.invalidation)):
                triggers.append(f"packet {e.id} INVALIDATION printed at {q.price:,.0f}")
                problems.append(f"live packet {e.id} printed invalidation")
                self.ledger.update(e.id, outcome_eod="INVALIDATED")
            elif pk.target is not None and ((pk.side == "LONG" and q.price >= pk.target) or (pk.side == "SHORT" and q.price <= pk.target)):
                triggers.append(f"packet {e.id} TARGET printed at {q.price:,.0f}")
                self.ledger.update(e.id, outcome_eod="HIT")
            elif pk.time_stop and datetime.fromisoformat(pk.time_stop) <= ts:
                triggers.append(f"packet {e.id} EXPIRED (time stop {pk.time_stop})")
                self.ledger.update(e.id, outcome_eod="EXPIRED")

        # Failures / escalation
        st.consecutive_failures = st.consecutive_failures + 1 if problems else 0
        tape_str = "/".join(f"{s}:{q.price:,.0f}" for s, q in quotes.items()) or "n/a"
        hb = (f"SCAN [{ts:%H:%M} {C.TZ}] | Drive:{drive_latest or 'UNREAD'} | tape:{tape_str} "
              f"| locks:{locks.status} | packet:none")
        self.sinks.log(hb)

        p0 = []
        if st.drive_down_since_iso and ts - datetime.fromisoformat(st.drive_down_since_iso) >= timedelta(hours=C.DRIVE_DOWN_P0_HOURS):
            p0.append(f"Drive down {C.DRIVE_DOWN_P0_HOURS}+ hours")
        if st.consecutive_failures >= C.DRIVE_FAIL_SCANS_PROBLEM:
            p0.append(f"{st.consecutive_failures} consecutive scans could not read Drive/tape")
        if any("lag>20=STALE: lag" in r for r in locks.reasons) and self.ledger.open_packets():
            p0.append("lag>20 on a packet already handed off")
        if any("front-run" in r for r in locks.reasons):
            p0.append("suspected front-run")
        if any("INVALIDATION printed" in t for t in triggers):
            p0.append("live packet printed invalidation")
        if p0:
            self.sinks.user("PROBLEM", "P0 " + " | ".join(p0) + (" | " + "; ".join(problems) if problems else ""))
        elif triggers:
            # Trigger events break 4h silence into the user thread only if they are READY/PROBLEM class;
            # level touches and Drive updates are P1 and ride the next scheduled post.
            self.sinks.log("P1 " + " | ".join(triggers + p1))
        else:
            self.sinks.log("P2 uneventful scan — silence kept")
        self._save()
        return ScanReport(ts, drive_latest, quotes, locks, triggers, problems, p1, hb)

    # ---- candidate -> packet ---------------------------------------------------------------
    def _complete_and_qualify(self, cand: Packet, quotes: dict[str, Quote], locks: LockResult,
                              drive_line: str, drive_rails: tuple[str, ...], scan_start: datetime) -> tuple[Packet, list[str]]:
        ts = self.now()
        cand.packet_id = cand.packet_id or self.ledger.next_id(ts.date())
        cand.drive_latest = drive_line
        cand.lock_check = dict(locks.results)
        # live check from tape
        q = quotes.get(cand.asset.upper())
        if q:
            e = cand.entry if cand.entry is not None else (sum(cand.entry_band) / 2 if cand.entry_band else None)
            cand.live.timestamp = ts.isoformat(timespec="seconds")
            cand.live.source = q.source
            if e is not None:
                cand.live.level_still_present = abs(q.price - e) / e <= 0.03
                if cand.live.traded_through_without_reload is None:
                    cand.live.traded_through_without_reload = (cand.side == "LONG" and q.price > e * 1.03) or (cand.side == "SHORT" and q.price < e * 0.97)
            if cand.live.liquidity_at_size is None and cand.defi.slippage_edge_fraction is not None:
                cand.live.liquidity_at_size = cand.defi.slippage_edge_fraction <= C.SLIPPAGE_MAX_EDGE_FRACTION
        # history from candles
        if self.tape is not None and cand.history.n == 0 and cand.entry is not None and cand.target is not None and cand.invalidation is not None:
            try:
                candles = self.tape.candles(cand.asset.upper(), 86400, 400)
                res = count_analogs(candles, cand.entry, cand.target, cand.invalidation, cand.side)
                cand.history.timeframe = cand.history.timeframe or "1D"
                cand.history.n, cand.history.hit_before_invalidate, cand.history.last_dates = res.n, res.hit_before_invalidate, res.dates
            except TapeError:
                pass
        # correlation vs book
        if not cand.correlation:
            cand.correlation = "doubles existing beta" if cand.asset.upper() == "BTC" and cand.side == "LONG" else ("add" if cand.asset.upper() in ("BTC", "ETH") else "independent")
            cand.correlation_note = cand.correlation_note or f"crypto beta vs BTC GTC @${C.BTC_GTC:,.0f} and HOLD {'+'.join(C.HOLD_BOOK)}"
        # novelty from ledger
        last = self.ledger.recent_sessions()
        nv = self.ledger.novelty(cand, live_level_new=all(e.entry != cand.entry_text() for e in last),
                                 regime_changed=(locks.status != self.state.last_lock_status),
                                 drive_evidence_newer=any(e.drive_date < (self.state.last_drive_date or "") for e in last),
                                 prior_miss_changes_plan=bool(self.ledger.misses()))
        cand.novelty_ledger_id, cand.novelty_reason = nv.nearest_id, nv.line
        cand.enforce_intent()
        g = qualify(cand, drive_rails=drive_rails, scan_start=scan_start, now=ts)
        return cand, g.failures

    # ---- 6:45 game plan ----------------------------------------------------------------------
    def gameplan(self, force: bool = False) -> str:
        ts = self.now()
        day = ts.strftime("%Y-%m-%d")
        if not force and (not self.is_weekday(ts) or self.is_holiday(ts)):
            text = f"GAME PLAN [{day}]: HOLIDAY/WEEKEND — 4h crypto loop continues; lock check: {lock_check(self._lock_inputs_with_lag({})).render()}"
            self.sinks.log(text)
            return text
        scan_start = ts - timedelta(hours=C.SCAN_INTERVAL_HOURS)
        rep = self.scan()
        lines = [f"GAME PLAN [{day} {ts:%H:%M} {C.TZ}]"]
        try:
            drive = self._drive()
            drive_line = drive.latest_line()
            drive_rails = drive.named_defi_rails()
            context = drive.context_pack()
        except DriveUnavailable as e:
            self.sinks.user("PROBLEM", f"Drive cannot be read at 6:45: {e}. No packet.")
            self.state.gameplan_posted_day = day
            self._save()
            return "PROBLEM: Drive unread"
        lines.append(drive_line)
        lines.append("Tape: " + ", ".join(f"{s} {q.price:,.0f} ({q.source}, lag {q.lag_seconds:.0f}s)" for s, q in rep.quotes.items()))
        lines.append("Locks: " + rep.locks.render())
        if rep.p1 or rep.triggers:
            lines.append("P1 since last post: " + " | ".join(rep.triggers + rep.p1))
        if self.ledger.misses():
            lines.append("Prior misses on ledger: " + ", ".join(f"{e.id} ({e.outcome_eod})" for e in self.ledger.misses()[-3:]))
        if not self.ledger.present:
            lines.append("Ledger: MISSING — novelty cannot be claimed.")

        shipped = None
        reasons: list[str] = []
        cands = self.advisor.propose(context + "\n\nTape: " + ", ".join(f"{s}={q.price}" for s, q in rep.quotes.items()))
        for cand in cands:
            pk, fails = self._complete_and_qualify(cand, rep.quotes, rep.locks, drive_line, drive_rails, scan_start)
            if not fails:
                shipped = pk
                break
            reasons.append(f"{pk.packet_id or 'cand'}: {fails[0]}" + (f" (+{len(fails)-1})" if len(fails) > 1 else ""))
            if len(fails) == 1:
                self.sinks.log(f"P1 qualification near-miss: {pk.packet_id or 'cand'} — {fails[0]}")

        if shipped:
            text = shipped.render()
            fp = bh = ""
            pids: list[str] = []
            m = re.search(r"fingerprint (\w+); patterns ([^;]+)", shipped.correlation_note)
            if m:
                from .engine.guard import body_hash as _bh
                from .engine import emitter as _em
                fp, pids, bh = m.group(1), m.group(2).split(","), _bh(shipped)
                text = _em.render(shipped, fp, pids, shipped.novelty_ledger_id, 0.0)
            self.ledger.add(shipped, self.state.last_drive_date or "", fingerprint=fp, body_hash=bh, pattern_ids=pids,
                            kb_citations=[c for c in shipped.correlation_note.split() if c.startswith("[DM")])
            lines.append("")
            lines.append(text)
            self.sinks.cf(text)
            self.sinks.user("READY", "\n".join(lines))
        else:
            why = reasons[0] if reasons else ("advisor proposed nothing; tape did not support a trade" if cands == [] else "no candidate cleared the gate")
            lines.append(f"PACKET: NONE — {why}")
            self.sinks.user("SCHEDULED", "\n".join(lines))
        self.state.gameplan_posted_day = day
        self._save()
        return "\n".join(lines)

    # ---- 16:00 EOD ------------------------------------------------------------------------------
    def eod(self, lesson: str | None = None, seed: str | None = None, force: bool = False) -> str:
        ts = self.now()
        day = ts.strftime("%Y-%m-%d")
        if not force and (not self.is_weekday(ts) or self.is_holiday(ts)):
            text = f"EOD [{day}]: HOLIDAY/WEEKEND — skipped; 4h loop continues"
            self.sinks.log(text)
            return text
        todays = [e for e in self.ledger.entries if e.date == day.replace("-", "")]
        # research <- execution handoff: a FIRED receipt for today's packet means the operator armed it
        rp = os.path.join(self.data_dir, "fire_receipts.jsonl")
        if todays and os.path.exists(rp):
            fired = {json.loads(l).get("packet_id") for l in open(rp) if l.strip() and '"FIRED"' in l}
            for e in todays:
                if e.id in fired and e.status == "posted":
                    self.ledger.update(e.id, status="applied-by-user")
        if todays:
            e = todays[-1]
            packet = e.status if e.status in ("applied-by-user", "ignored") else "posted"
            tape_vs_plan = e.outcome_eod
            p1 = "full packet, gate passed"
            applied = e.status == "applied-by-user"
            p2 = tape_vs_plan if applied else "n/a"
        else:
            packet, tape_vs_plan, p1, applied, p2 = "none", "none", "n/a", False, "n/a"
        expected = 24 // C.SCAN_INTERVAL_HOURS
        gp = self.state.gameplan_posted_day == day
        p0 = (not gp) or self.state.silence_broken_without_trigger
        inp = eod_mod.EodInput(date=day, gameplan_posted=gp, scans_done=self.state.scans_today, scans_expected=expected,
                               silence_kept=not self.state.silence_broken_without_trigger, packet=packet, tape_vs_plan=tape_vs_plan,
                               lesson=lesson or ("packet posted; outcome logged, not scored on P&L" if todays else "no packet; process only"),
                               seed=seed or self._seed(), p0_process_miss=p0, p1_packet_quality=p1, p2_outcome=p2, applied=applied)
        text = eod_mod.render(inp)
        if todays:
            self.ledger.update(todays[-1].id, lesson=inp.lesson)
        self.sinks.user("SCHEDULED", text)
        self._save()
        return text

    def _seed(self) -> str:
        try:
            w = self._drive().watched_levels(("BTC",))
        except DriveUnavailable:
            return "restore Drive read"
        if not w:
            return "no BTC levels on file"
        sup = [x for x in w if x.role == "support"]
        res = [x for x in w if x.role == "resistance"]
        parts = []
        if sup: parts.append(f"BTC support {max(s.level for s in sup):,.0f}")
        if res: parts.append(f"resistance {min(r.level for r in res):,.0f}")
        return "watch " + " / ".join(parts) + f" {w[0].cite}"
