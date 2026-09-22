"""Read access to the DM Market Update knowledge base for the trading bot ("the box").

Zero dependencies. Typical use:

    from knowledge.loader import Knowledge
    kb = Knowledge()                       # loads knowledge/knowledge.json
    kb.current("btc")                      # latest belief for a label (+ cite)
    kb.history("btc")                      # superseded rail, newest first
    kb.levels("BTC")                       # latest support/resistance for an asset
    kb.snapshot()                          # latest market snapshot
    kb.series("btc")                       # [(date, value), ...] across all snapshots
    kb.search("Hormuz")                    # grep across weekly digests + source text
    kb.context_pack()                      # compact text block for an LLM system prompt
    kb.source_text("[DM memo 2026-09-21]") # full extracted text behind a cite

CLI:  python3 -m knowledge.loader current btc
      python3 -m knowledge.loader pack
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

ROOT = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_JSON = os.path.join(ROOT, "knowledge.json")
MANIFEST_JSON = os.path.join(ROOT, "manifest.json")
WEEKLY_DIR = os.path.join(ROOT, "weekly")
TEXT_DIR = os.path.join(ROOT, "sources", "text")
STATE_CARD = os.path.join(ROOT, "state_card.md")

_CITE_RE = re.compile(r"\[DM (memo|slides) (\d{4}-\d{2}-\d{2})\]")


class Knowledge:
    def __init__(self, path: str = KNOWLEDGE_JSON):
        with open(path) as fh:
            self.data: dict[str, Any] = json.load(fh)
        self.manifest: list[dict[str, Any]] = []
        if os.path.exists(MANIFEST_JSON):
            with open(MANIFEST_JSON) as fh:
                self.manifest = json.load(fh).get("sources", [])

    # ---- meta -------------------------------------------------------------
    @property
    def as_of(self) -> str:
        return self.data["meta"]["current_as_of"]

    def labels(self) -> list[str]:
        """'I can talk about...'"""
        return list(self.data["labels"].keys())

    def rules(self) -> list[str]:
        return list(self.data["meta"]["rules"])

    def gaps(self) -> list[str]:
        return list(self.data["meta"].get("gaps", []))

    # ---- labels -----------------------------------------------------------
    def current(self, label: str) -> dict[str, Any]:
        """Latest belief for a label. Raises KeyError for unknown labels."""
        entry = self.data["labels"][label]
        cur = dict(entry["current"])
        cur["label"] = label
        cur["title"] = entry["title"]
        cur["has_history"] = bool(entry.get("superseded"))
        return cur

    def history(self, label: str) -> list[dict[str, Any]]:
        """Superseded rail, newest first. Every item is dead; do not promote."""
        return [dict(x, status="superseded") for x in self.data["labels"][label].get("superseded", [])]

    def locate(self, query: str) -> list[str]:
        """Labels whose key or title match a free-text query."""
        q = query.lower()
        return [k for k, v in self.data["labels"].items() if q in k or q in v["title"].lower()]

    # ---- numbers ----------------------------------------------------------
    def snapshot(self, date: str | None = None) -> dict[str, Any]:
        snaps = self.data["snapshots"]
        if date is None:
            return snaps[-1]
        for s in snaps:
            if s["date"] == date:
                return s
        raise KeyError(date)

    def series(self, field: str) -> list[tuple[str, Any]]:
        return [(s["date"], s[field]) for s in self.data["snapshots"] if s.get(field) is not None]

    def levels(self, asset: str, date: str | None = None) -> dict[str, Any] | None:
        rows = [r for r in self.data["levels"] if r["asset"].upper() == asset.upper()]
        if date:
            rows = [r for r in rows if r["date"] == date]
        return rows[-1] if rows else None

    def levels_history(self, asset: str) -> list[dict[str, Any]]:
        return [r for r in self.data["levels"] if r["asset"].upper() == asset.upper()]

    def frameworks(self) -> list[dict[str, Any]]:
        return list(self.data["frameworks"])

    def timeline(self, since: str | None = None) -> list[dict[str, Any]]:
        rows = self.data["timeline"]
        return [r for r in rows if not since or r["date"] >= since]

    def upcoming(self) -> list[dict[str, Any]]:
        return list(self.data["upcoming"])

    def conflicts(self) -> list[dict[str, Any]]:
        return list(self.data["conflicts"])

    # ---- text -------------------------------------------------------------
    def weekly(self, date: str) -> str:
        with open(os.path.join(WEEKLY_DIR, f"{date}.md")) as fh:
            return fh.read()

    def weeks(self) -> list[str]:
        return sorted(f[:-3] for f in os.listdir(WEEKLY_DIR) if f.endswith(".md"))

    def state_card(self) -> str:
        with open(STATE_CARD) as fh:
            return fh.read()

    def source_text(self, cite: str) -> str:
        """Full extracted text behind a cite like '[DM memo 2026-09-21]'."""
        m = _CITE_RE.fullmatch(cite.strip())
        if not m:
            raise ValueError(f"bad cite: {cite!r}")
        kind, date = m.group(1), m.group(2)
        with open(os.path.join(TEXT_DIR, f"{date}_{kind}.txt")) as fh:
            return fh.read()

    def search(self, term: str, where: str = "weekly", limit: int = 50) -> list[dict[str, Any]]:
        """Case-insensitive line search. where = 'weekly' | 'sources' | 'all'."""
        dirs = {"weekly": [WEEKLY_DIR], "sources": [TEXT_DIR], "all": [WEEKLY_DIR, TEXT_DIR]}[where]
        pat = re.compile(re.escape(term), re.I)
        hits: list[dict[str, Any]] = []
        for d in dirs:
            for name in sorted(os.listdir(d)):
                with open(os.path.join(d, name)) as fh:
                    for n, line in enumerate(fh, 1):
                        if pat.search(line):
                            hits.append({"file": os.path.relpath(os.path.join(d, name), ROOT), "line": n, "text": line.strip()})
                            if len(hits) >= limit:
                                return hits
        return hits

    # ---- prompt helpers ---------------------------------------------------
    def context_pack(self, labels: list[str] | None = None, with_history: bool = False) -> str:
        """Compact block for an LLM system prompt: rules, latest snapshot, current lines, levels, upcoming."""
        labels = labels or self.labels()
        out = [f"DM MARKET UPDATE KNOWLEDGE — current as of {self.as_of}", "Rules: " + " ".join(self.rules()), ""]
        snap = self.snapshot()
        out.append(f"Latest snapshot ({snap['as_of']}) {snap['cite']}: " +
                   ", ".join(f"{k}={v}" for k, v in snap.items() if k not in ("date", "as_of", "cite", "note") and v is not None))
        out.append("")
        for lb in labels:
            cur = self.current(lb)
            out.append(f"[{lb}] {cur['title']} — current ({cur['as_of']}) {cur['cite']}: {cur['summary']}")
            if with_history:
                for h in self.history(lb):
                    out.append(f"    superseded ({h['as_of']}) {h['cite']}: {h['summary']}")
        out.append("")
        out.append("Latest levels:")
        seen: set[str] = set()
        for row in reversed(self.data["levels"]):
            if row["asset"] in seen:
                continue
            seen.add(row["asset"])
            out.append(f"  {row['asset']} ({row['date']}): current={row.get('current')} support={row['support']} resistance={row['resistance']} bias={row['bias']} {row['cite']}")
        out.append("")
        out.append("Upcoming: " + "; ".join(f"{u['date']} {u['event']}" + (f" ({u['watch']})" if u.get('watch') else "") for u in self.upcoming()))
        out.append("Known gaps (no briefing): " + ", ".join(self.gaps()))
        out.append("Conflicts on file: " + ", ".join(c["id"] for c in self.conflicts()) + " — see knowledge.json['conflicts'].")
        return "\n".join(out)


def _main(argv: list[str]) -> int:
    kb = Knowledge()
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]
    if cmd == "labels":
        print("\n".join(kb.labels()))
    elif cmd == "current":
        print(json.dumps(kb.current(args[0]), indent=2))
    elif cmd == "history":
        print(json.dumps(kb.history(args[0]), indent=2))
    elif cmd == "levels":
        print(json.dumps(kb.levels(args[0]), indent=2))
    elif cmd == "snapshot":
        print(json.dumps(kb.snapshot(args[0] if args else None), indent=2))
    elif cmd == "series":
        for d, v in kb.series(args[0]):
            print(d, v)
    elif cmd == "search":
        for h in kb.search(" ".join(args), where="all"):
            print(f"{h['file']}:{h['line']}: {h['text']}")
    elif cmd == "pack":
        print(kb.context_pack(with_history="--history" in args))
    elif cmd == "conflicts":
        print(json.dumps(kb.conflicts(), indent=2))
    else:
        print(f"unknown command {cmd!r}; see --help", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
