"""Instant-ingest ranking + cross-link propagator over the knowledge sources.

priority(source) = novelty x linkage_density
  novelty          = 1 - max Jaccard similarity to any earlier source text
  linkage_density  = share of the corpus' recurring level ids / catalyst tags this source also mentions
Cross-links: each source gets edges to its top-k most similar sources (Jaccard on token sets).
Stdlib only; no embeddings. Output is written to data/engine/links.json.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from ..drive import KNOWLEDGE

_TOK = re.compile(r"[a-z0-9$%.\-]+")
_NUM = re.compile(r"\$?\b\d{1,3}(?:,\d{3})+\b|\$\d+(?:\.\d+)?[kK]?")


def tokens(text: str) -> set[str]:
    return {t for t in _TOK.findall(text.lower()) if len(t) > 2}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


@dataclass
class SourceNode:
    cite: str
    date: str
    kind: str
    novelty: float = 0.0
    linkage: float = 0.0
    priority: float = 0.0
    links: list[tuple[str, float]] = field(default_factory=list)   # (cite, similarity)
    aliases: list[str] = field(default_factory=list)                 # near-duplicate sources (>= dup_tau)


def build(text_dir: str = os.path.join(KNOWLEDGE, "sources", "text"), k: int = 3, dup_tau: float = 0.9) -> list[SourceNode]:
    files = sorted(f for f in os.listdir(text_dir) if f.endswith(".txt"))
    nodes, toks, nums = [], {}, {}
    for f in files:
        date, kind = f[:10], f[11:-4]
        cite = f"[DM {kind} {date}]"
        text = open(os.path.join(text_dir, f)).read()
        toks[cite], nums[cite] = tokens(text), set(_NUM.findall(text))
        nodes.append(SourceNode(cite, date, kind))
    # linkage density: numbers this source shares with the rest of the corpus (levels, prices, odds)
    all_nums: dict[str, int] = {}
    for s in nums.values():
        for n in s:
            all_nums[n] = all_nums.get(n, 0) + 1
    recurring = {n for n, c in all_nums.items() if c >= 2}
    for n in nodes:
        earlier = [m for m in nodes if m.date < n.date or (m.date == n.date and m.cite < n.cite)]
        n.novelty = 1.0 - max((jaccard(toks[n.cite], toks[m.cite]) for m in earlier), default=0.0)
        n.linkage = len(nums[n.cite] & recurring) / len(recurring) if recurring else 0.0
        n.priority = round(n.novelty * n.linkage, 4)
        sims = sorted(((m.cite, jaccard(toks[n.cite], toks[m.cite])) for m in nodes if m.cite != n.cite), key=lambda x: -x[1])
        n.links = [(c, round(s, 3)) for c, s in sims[:k]]
        n.aliases = [c for c, s in sims if s >= dup_tau]
    return nodes


def save(nodes: list[SourceNode], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump([n.__dict__ for n in nodes], open(path, "w"), indent=1)
