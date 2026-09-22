#!/usr/bin/env python3
"""Regenerate knowledge/manifest.json and knowledge/snapshots.csv.

manifest.json  - one row per distinct source file (date, kind, paths, md5, size, title line)
snapshots.csv  - flat time series from knowledge.json['snapshots']

Run after adding sources with scripts/extract_sources.py and after editing knowledge.json.
"""
import csv, glob, hashlib, json, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
K = os.path.join(ROOT, "knowledge")
ORIG, TEXT = os.path.join(K, "sources", "original"), os.path.join(K, "sources", "text")


TITLES = {
    "2026-05-11_memo": "Gems Uncovered — Weekly Market Memo",
    "2026-05-11_slides": "Gems Uncovered — Weekly Market Update",
    "2026-05-18_memo": "Decentralized Masters — Weekly Market Memo",
    "2026-05-18_slides": "Market Update — Crypto / Macro",
    "2026-06-01_memo": "DM Market Update (memo)",
    "2026-06-01_slides": "DM Market Update (slides)",
    "2026-06-08_memo": "DM Market Update — Research Memo",
    "2026-06-08_slides": "DM Market Update — Weekly markets briefing",
    "2026-06-15_memo": "DM Market Update — Research Memo",
    "2026-06-15_slides": "Weekly Market Update",
    "2026-06-21_memo": "DM Market Update — Weekly Research Supplement",
    "2026-06-21_slides": "Market Update — Weekly Research Briefing",
    "2026-06-29_slides": "DM Market Update — Weekly Research Briefing (NFP week)",
    "2026-07-13_memo": "DM Market Update — Weekly Research Supplement",
    "2026-07-13_slides": "Market Update — NFP shock / Warsh Tuesday / ETF reversal",
    "2026-07-27_slides": "Market Update — Iran pause / Oil -6% / FOMC Wed",
    "2026-08-03_memo": "DM Market Update — Weekly Research Supplement",
    "2026-08-03_slides": "Market Update — FOMC 9-3 / MSFT validates AI / KOSPI / Coldcard",
    "2026-08-10_memo": "DM Market Update — Weekly Research Supplement",
    "2026-08-10_slides": "Market Update — Monday Edition (NFP -23K, CPI Wed)",
    "2026-08-17_memo": "DM Market Update — Weekly Research Supplement",
    "2026-08-17_slides": "Market Update — Monday Edition (CPI 3.4%, Iran MOU expires)",
    "2026-08-20_slides": "Market Update — Thursday Extended Edition (BTC $69,500 breakout)",
    "2026-08-31_memo": "DM Market Update (memo)",
    "2026-08-31_slides": "Market Update — Oil & Iran pivot / Warsh at Jackson Hole",
    "2026-09-21_memo": "Weekly Market Update — Confidential Research Report",
    "2026-09-21_slides": "Market Update — Monday Edition (BTC $86.2K breakout)",
}


def title_of(text_path):
    """Curated title if known, else first non-empty line of the extracted text."""
    stem = os.path.basename(text_path)[:-4]
    if stem in TITLES:
        return TITLES[stem]
    with open(text_path) as fh:
        for line in fh:
            s = line.strip()
            if s and not s.startswith("====="):
                return s[:120]
    return ""


def build_manifest():
    rows = []
    for p in sorted(glob.glob(os.path.join(ORIG, "*"))):
        base = os.path.basename(p)
        m = re.match(r"(\d{4}-\d{2}-\d{2})_(memo|slides)(?:_v\d+)?\.(pdf|pptx)$", base)
        if not m:
            continue
        date, kind, ext = m.groups()
        stem = base.rsplit(".", 1)[0]
        text = os.path.join(TEXT, f"{stem}.txt")
        rows.append({
            "date": date,
            "kind": kind,
            "cite": f"[DM {kind} {date}]",
            "title": title_of(text) if os.path.exists(text) else "",
            "original": os.path.relpath(p, ROOT),
            "text": os.path.relpath(text, ROOT) if os.path.exists(text) else None,
            "format": ext,
            "bytes": os.path.getsize(p),
            "md5": hashlib.md5(open(p, "rb").read()).hexdigest(),
            "text_chars": os.path.getsize(text) if os.path.exists(text) else 0,
            "author": "Tyler Hubbard, Head of Research, Decentralized Masters",
        })
    weeks = sorted({r["date"] for r in rows})
    out = {"generated_for": weeks[-1] if weeks else None, "weeks": weeks, "count": len(rows), "sources": rows}
    with open(os.path.join(K, "manifest.json"), "w") as fh:
        json.dump(out, fh, indent=2)
    return out


def build_snapshots_csv():
    with open(os.path.join(K, "knowledge.json")) as fh:
        snaps = json.load(fh)["snapshots"]
    fields = ["date", "as_of"]
    for s in snaps:
        for k in s:
            if k not in fields and k not in ("cite", "note"):
                fields.append(k)
    fields += ["cite", "note"]
    with open(os.path.join(K, "snapshots.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for s in snaps:
            w.writerow({k: s.get(k, "") for k in fields})
    return len(snaps)


if __name__ == "__main__":
    m = build_manifest()
    n = build_snapshots_csv()
    print(f"manifest: {m['count']} sources over {len(m['weeks'])} weeks (latest {m['generated_for']}); snapshots.csv: {n} rows")
