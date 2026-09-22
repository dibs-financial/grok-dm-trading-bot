"""KB-Scanner: diff knowledge/ by content hash and normalize knowledge.json into a triple store."""
from __future__ import annotations

import glob
import hashlib
import json
import os
from dataclasses import dataclass, field

from .. import config as C
from ..drive import KNOWLEDGE
from .bus import Bus


@dataclass
class Triple:
    s: str
    p: str
    o: str
    date: str
    cite: str
    confidence: float = 1.0


@dataclass
class Store:
    triples: list[Triple] = field(default_factory=list)
    series: list[dict] = field(default_factory=list)      # snapshots
    levels: list[dict] = field(default_factory=list)
    timeline: list[dict] = field(default_factory=list)
    as_of: str = ""

    def to_json(self) -> dict:
        return {"as_of": self.as_of, "triples": [t.__dict__ for t in self.triples], "series": self.series,
                "levels": self.levels, "timeline": self.timeline}

    @classmethod
    def from_json(cls, d: dict) -> "Store":
        return cls([Triple(**t) for t in d["triples"]], d["series"], d["levels"], d["timeline"], d.get("as_of", ""))


class Scanner:
    def __init__(self, root: str = KNOWLEDGE, data_dir: str | None = None, bus: Bus | None = None):
        self.root = root
        self.dir = data_dir or os.path.join(C.DATA_DIR, "engine")
        self.bus = bus or Bus(os.path.join(self.dir, "events.jsonl"))
        os.makedirs(self.dir, exist_ok=True)
        self.ckpt_path = os.path.join(self.dir, "checkpoint.json")
        self.store_path = os.path.join(self.dir, "store.json")

    def _hashes(self) -> dict[str, str]:
        out = {}
        for p in sorted(glob.glob(os.path.join(self.root, "**", "*"), recursive=True)):
            if os.path.isfile(p) and not p.endswith((".pdf", ".pptx", ".pyc")):
                out[os.path.relpath(p, self.root)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
        return out

    def scan(self) -> dict:
        """Returns {'delta': {'created': [...], 'updated': [...], 'deleted': [...]}, 'store': Store}."""
        prev = json.load(open(self.ckpt_path)) if os.path.exists(self.ckpt_path) else {}
        cur = self._hashes()
        delta = {"created": [k for k in cur if k not in prev],
                 "updated": [k for k in cur if k in prev and prev[k] != cur[k]],
                 "deleted": [k for k in prev if k not in cur]}
        changed = any(delta.values())
        if changed or not os.path.exists(self.store_path):
            store = self.normalize()
            json.dump(store.to_json(), open(self.store_path, "w"))
            json.dump(cur, open(self.ckpt_path, "w"))
            from . import links as _links
            nodes = _links.build(os.path.join(self.root, "sources", "text"))
            _links.save(nodes, os.path.join(self.dir, "links.json"))
            self.bus.emit("kb.delta", {"delta": delta, "as_of": store.as_of, "triples": len(store.triples),
                                       "top_priority": [n.cite for n in sorted(nodes, key=lambda n: -n.priority)[:3]]})
        else:
            store = Store.from_json(json.load(open(self.store_path)))
        return {"delta": delta, "changed": changed, "store": store}

    def normalize(self) -> Store:
        kb = json.load(open(os.path.join(self.root, "knowledge.json")))
        st = Store(as_of=kb["meta"]["current_as_of"])
        for label, entry in kb["labels"].items():
            cur = entry["current"]
            st.triples.append(Triple(label, "current", cur["summary"], cur["as_of"], cur["cite"]))
            for h in entry.get("superseded", []):
                st.triples.append(Triple(label, "superseded", h["summary"], h["as_of"], h["cite"], 0.9))
        for r in kb["levels"]:
            for lv in r["support"]:
                if isinstance(lv, (int, float)):
                    st.triples.append(Triple(r["asset"], "support", str(lv), r["date"], r["cite"]))
            for lv in r["resistance"]:
                if isinstance(lv, (int, float)):
                    st.triples.append(Triple(r["asset"], "resistance", str(lv), r["date"], r["cite"]))
        for ev in kb["timeline"]:
            st.triples.append(Triple("timeline", "event", ev["event"], ev["date"], ev["cite"]))
        for c in kb["conflicts"]:
            st.triples.append(Triple(c["id"], "resolved", str(c.get("resolved", "")), c.get("resolved_on", ""), "; ".join(l["cites"][0] for l in c["lines"] if l.get("cites")), 1.0))
        st.series, st.levels, st.timeline = kb["snapshots"], kb["levels"], kb["timeline"]
        return st
