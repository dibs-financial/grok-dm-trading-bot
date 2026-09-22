# knowledge/ — the box's source of knowledge

This folder is the single place the trading bot ("the box") pulls its market context from. Everything here is derived from the Decentralized Masters weekly **DM Market Update** memos and slide decks written by Tyler Hubbard, Head of Research. Nothing is invented; every line traces to a dated source.

Coverage: 15 weekly briefings, **2026-05-11 → 2026-09-21** (27 distinct files; duplicate uploads were deduplicated by content hash).

## Layout

| Path | What it is | Who reads it |
|---|---|---|
| `state_card.md` | **Living State Card.** One *current* line per label plus a dated *superseded* rail, and a **Conflicts** section. Start here. | humans, LLM prompts |
| `knowledge.json` | Same knowledge, machine-readable: `snapshots`, `levels`, `labels` (current + superseded), `frameworks`, `timeline`, `upcoming`, `conflicts`, `meta.gaps`. | the bot, via `loader.py` |
| `snapshots.csv` | Flat time series of the weekly market snapshot (generated from `knowledge.json`). | backtests, spreadsheets |
| `weekly/YYYY-MM-DD.md` | One faithful digest per briefing: snapshot, key levels, crypto, macro, calendar, risks/catalysts, bottom line. | retrieval / RAG |
| `sources/text/` | Plain-text extraction of every source (`YYYY-MM-DD_memo.txt`, `YYYY-MM-DD_slides.txt`). Ground truth for cites. | retrieval, verification |
| `sources/original/` | The original PDF / PPTX files, renamed by date and kind. | provenance |
| `manifest.json` | Index of sources: date, kind, cite key, title, paths, md5, size. | tooling |
| `loader.py` | Zero-dependency Python API + CLI. | the bot |

## Cite convention

Every claim carries `[DM memo YYYY-MM-DD]` or `[DM slides YYYY-MM-DD]`. That key maps 1:1 to `sources/text/YYYY-MM-DD_memo.txt` / `_slides.txt` and to a `manifest.json` row (which carries the document title). Spoken or client-facing output should render a cite as *platform + date + title*, e.g. "DM memo, June 15, 2026, 'DM Market Update Research Memo'", never as a raw file id.

## Rules the box must follow

1. **Answer from `current` only.** Offer history in one sentence ("There is a superseded version. Ask if you want it.") and open the superseded rail only when asked how something *used* to be.
2. **A later source supersedes an earlier one on the same label.** "Similar" is not "current".
3. **Two current lines that disagree stay two lines.** They are listed in `conflicts`; say both, never blend into a fake average.
4. **Every live claim needs a cite.** If there is no cite, say there is none.
5. **Gaps are explicit.** No briefing exists for the weeks of May 25, Jun 22, Jul 6, Jul 20, Aug 24, Sep 7, Sep 14. Events in those weeks (e.g. the Sep 15 CLARITY cloture failure, the Sep 16 Fed hike, the Aug NFP and Aug CPI prints) are known only as *referenced* by later briefings.
6. **This is research context, not a signal.** The sources describe themselves as educational and not financial advice. Levels and scenario odds are the author's framing as of that date.

## Using it from code

```python
from knowledge.loader import Knowledge

kb = Knowledge()
kb.as_of                       # '2026-09-21'
kb.labels()                    # ['btc', 'btc_flows', 'eth', 'hype', 'zec', 'alts', 'fed', ...]
kb.current("btc")              # {'as_of', 'cite', 'summary', 'title', 'has_history', ...}
kb.history("fed")              # superseded rail, newest first
kb.levels("BTC")               # latest {support, resistance, bias, cite}
kb.snapshot()                  # latest weekly snapshot dict
kb.series("btc")               # [('2026-05-11', 80640), ..., ('2026-09-21', 86200)]
kb.upcoming()                  # dated catalysts as of the latest briefing
kb.conflicts()                 # disagreements kept as separate lines
kb.frameworks()                # the author's standing rules of thumb
kb.search("Hormuz", where="all")
kb.source_text("[DM memo 2026-09-21]")
kb.context_pack()              # compact text block to drop into an LLM system prompt
```

CLI equivalents: `python3 -m knowledge.loader current btc`, `... levels BTC`, `... series gold`, `... search "50-month EMA"`, `... pack --history`.

## Adding a new week

1. Drop the new memo/slides (PDF or PPTX) anywhere and run
   `python3 scripts/extract_sources.py <file-or-dir>` — it dedupes by hash, infers date/kind from the filename, copies the original to `sources/original/` and writes `sources/text/`.
2. Write `weekly/YYYY-MM-DD.md` from the extracted text (same section layout as the existing digests).
3. Update `knowledge.json`: append a `snapshots` row and `levels` rows; for each label touched, move the old `current` to the top of `superseded` and write the new `current`; add `timeline` / `upcoming` entries; record any new disagreement in `conflicts`; bump `meta.current_as_of`.
4. Update `state_card.md` the same way (current line + superseded rail + conflicts).
5. Run `python3 scripts/build_manifest.py` to regenerate `manifest.json` and `snapshots.csv`.

Extraction needs `pymupdf` (PDF) and `python-pptx` (PPTX); the loader needs nothing beyond the standard library.
