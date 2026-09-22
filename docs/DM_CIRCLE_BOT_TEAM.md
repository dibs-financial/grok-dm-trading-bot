# DM Circle bot team — "login boxes"

Purpose: pull the most and best information out of the Decentralized Masters community on Circle (posts, memo/slide attachments, call recordings, Q&A threads) and turn it into the cited knowledge base in `knowledge/` that the DM desk (`dm_desk/`) reads. One specialty per box. No overlapping duties. Nothing reaches the state card unless the Auditor passes it.

Ground rules that apply to every box:
- One service login. Only the Gatekeeper holds credentials (`CIRCLE_EMAIL` / `CIRCLE_PASSWORD` or `CIRCLE_API_TOKEN` from the environment, never in the repo). Every other box receives a read-only fetch handle.
- Member-only content stays member-only. No member PII, no directory scraping, no reposting outside the owner's own systems. Respect Circle's terms and rate limits.
- Every output line carries a cite: `[DM memo|slides|call|post|comment YYYY-MM-DD]` that resolves to a stored source file.
- Boxes never talk to each other directly. They write to a queue folder and the next box reads it. Handoffs are files with a manifest, not chat.

## Team blueprint

| # | Box | Specialty (one job) | Input | Output | Success criterion |
|---|---|---|---|---|---|
| 0 | **Scope-Definer** | Frame each run: the sub-questions (one per knowledge label plus "what changed since `current_as_of`"), success criteria, source-priority list | operator request; current `knowledge.json` meta | run brief with sub-questions, thresholds, priority list; no research | every downstream output cites the sub-question it answers |
| 1 | **Gatekeeper** | Log in to Circle once, keep the session alive, enforce rate limits and ToS | credentials from env; robots/ToS policy | authenticated read-only fetch handle; session health log | zero credential exposure; session uptime ≥ 99%; no rate-limit bans |
| 2 | **Scout** | Enumerate what exists: spaces, posts, events, attachments, newest first; detect changes since the last watermark | fetch handle; last watermark | change manifest (new / edited / deleted items with ids, dates, authors, URLs) | 100% of new items found within one scan; no re-listing of unchanged items |
| 3 | **Capturer** | Download raw items exactly once: post body, attachments (PDF/PPTX), recordings, transcripts | change manifest | `sources/original/` files + MD5 + capture receipt | dedupe by content hash (the June 8 deck uploaded seven times counts once); byte-exact originals |
| 4 | **Transcriber** | Turn call recordings into timestamped transcripts | audio/video files | `sources/text/YYYY-MM-DD_call.txt` with timestamps and speaker labels where available | word error rate low enough that numbers and levels are exact; every number spot-checked against audio |
| 5 | **Reader** | Convert every source to plain text and one faithful digest per source | originals + transcripts | `sources/text/*.txt`; `weekly/YYYY-MM-DD.md` (snapshot, levels, crypto, macro, calendar, risks, bottom line) | nothing added, nothing dropped; a reviewer can find each digest line in the source |
| 6 | **Number-Miner** | Extract every price, level, date, probability, flow figure into structured rows | digests + text | `knowledge.json` rows: `snapshots`, `levels`, `timeline`, `upcoming` | every number has a cite and a unit; no free-text numbers left un-rowed |
| 7 | **Amendment-Miner** | Mine comments, Q&A threads and follow-up posts for author corrections that change a memo statement | post comments, Q&A, chat spaces | amendment list: original claim, corrected claim, cite, date | only author-sourced corrections; each linked to the memo line it amends |
| 8 | **Cross-Checker** | Compare the same fact across sources; flag disagreements; propose the resolution on weight of sources; never average | Number-Miner rows + amendments | `conflicts` rows with `resolved`, `resolution_note`, erratum labels | every disagreement has exactly one resolved value and the losing figure kept as erratum |
| 9 | **Synthesizer** | Maintain one current line per label plus the superseded rail; latest source supersedes on the same label | confirmed rows, amendments, resolutions | `state_card.md` labels section; `knowledge.json['labels']` | no label has two current lines; every superseded rail is newest-first |
| 10 | **Auditor** | Block publication unless every check passes | everything above | pass/fail report | 100% of cites resolve; ordering sound; gaps listed; no un-resolved conflict; no PII; no wrapper products promoted as rails |
| 11 | **Publisher** | Write the approved bundle to `knowledge/`, regenerate `manifest.json` / `snapshots.csv`, bump `current_as_of`, and post the P1 "new Drive doc" signal the desk scans for | Auditor-passed bundle | committed knowledge tree; desk notification | desk sees the new memo on its next 4h scan; nothing published that the Auditor failed |

Existing code that already implements a box: Capturer and Reader are `scripts/extract_sources.py`; Publisher is `scripts/build_manifest.py` plus the desk's `KnowledgeDrive`; Number-Miner, Cross-Checker and Synthesizer outputs are the current `knowledge.json` and `state_card.md` schemas; the Auditor's cite check is the loader's `source_text()` resolution.

## Mapping to the six-role blueprint

The operator's generic six-role team (Scope-Definer → Source-Hunter → Extractor → Fact-Checker → Gap-Analyst → Synthesizer) is the same pipeline at a higher altitude. The Circle boxes are the concrete versions; nothing here adds a duty the six-role design lacks, it only splits the Circle-specific mechanics out so no box touches two things.

| Six-role blueprint | Circle box(es) | What the split buys |
|---|---|---|
| Scope-Definer | **Scope-Definer** (new, box 0) | fixed sub-questions per run: the 15 knowledge labels + "what changed since `current_as_of`"; source-priority list: memo > slides > call transcript > author comment > other |
| Source-Hunter | Gatekeeper + Scout | login and rate limits kept away from discovery |
| Extractor | Capturer + Transcriber + Reader + Number-Miner | byte-exact capture, transcript fidelity, faithful digest, and atomic numeric rows are four different failure modes |
| Fact-Checker | Cross-Checker + Amendment-Miner | the Cross-Checker owns truth adjudication and confidence; the Amendment-Miner only supplies author corrections as evidence |
| Gap-Analyst | Auditor (gap and contradiction report) | surfaces missing weeks, unresolved rows, unresolvable cites; never resolves |
| Synthesizer | Synthesizer + Publisher | merge is separated from commit so a failed audit cannot publish |

Rules adopted from the six-role blueprint, now binding on every box:
- **Reject-and-return.** A receiver rejects an incomplete or ill-formed package and returns it upstream with a one-line defect note. It never patches it.
- **One truth owner.** The Cross-Checker adjudicates every disagreement and assigns a confidence score 0–1 to each atomic claim. The Auditor surfaces gaps and contradictions but never resolves them. The Synthesizer drops anything still unresolved or below the confidence threshold (default 0.8; an author correction in Circle scores 1.0 against the memo it corrects).
- **Atomic claims.** Number-Miner rows are `claim | exact quote or page/slide locator | source cite`, nothing interpretive. Interpretation lives only in the Reader's digest and is labeled as the author's framing.
- **No specialty crossing.** A box that needs another box's output waits for it; it does not do the work itself.



```
Scope-Definer ─(run brief)─> Gatekeeper ─(fetch handle)─> Scout ─(change manifest)─> Capturer ─(originals + receipts)─┬─> Transcriber ─┐
                                                                                        └────────────────┴─> Reader
Reader ─(text + digests)─> Number-Miner ─┐
Reader ─(comments/Q&A)──> Amendment-Miner ┴─> Cross-Checker ─(rows + resolved conflicts)─> Synthesizer ─> Auditor ─> Publisher ─> dm_desk scan
```

Handoff rules:
1. A box starts only when the upstream manifest says `complete`. Partial manifests are not consumed.
2. A box writes only to its own output folder and never edits an upstream file. Corrections go back as a new manifest entry, not an in-place edit.
3. Time-varying facts (price, moving averages, odds): latest dated source wins. Fixed facts (a date, a vote count, an ATH): weight of sources wins; an author comment in Circle outranks the memo it corrects.
4. Two sources that still disagree after rule 3 go to the Cross-Checker's `conflicts` table with a resolution; they never get averaged and never both stay "current".
5. Missing weeks are recorded as gaps, not filled by inference.
6. Any box that cannot read its input for two runs raises PROBLEM to the operator log. It does not guess.

## Aggregation rule

Only Auditor-passed items reach `state_card.md` and `knowledge.json`. The Synthesizer keeps one current line per label and pushes the prior line to the superseded rail. The Publisher commits the bundle and the desk's next 4h scan picks it up as a P1 "new Drive doc" event. Volume is never a goal: a scan that finds nothing new publishes nothing.

## Success metrics

| Metric | Target |
|---|---|
| Coverage: distinct Circle sources captured / sources posted | 100% per scan |
| Scope: sub-questions answered or explicitly marked unresolvable | all 15 labels + "what changed" every run |
| Precision: state-card lines that map to a Cross-Checker-verified claim ≥ 0.8 | ≥ 90% (target 100%) |
| Density: state card + JSON size vs raw extracted text | ≤ 40% of raw text, no loss of verified numbers |
| Zero overlap: audit finds a box doing another box's job | 0 findings |
| Dedupe: duplicate uploads stored | 0 |
| Cite resolution: claims whose cite opens a source file | 100% |
| Freshness: post time on Circle → visible to desk | ≤ one 4h scan |
| Conflicts: open (unresolved) at publish | 0 |
| Number fidelity: sampled numbers matching source | 100% on a 20-item sample per week |
| Gaps: weeks with no briefing listed in `meta.gaps` | all of them, explicitly |
| Privacy: member PII stored | 0 |
| Desk effect: P1 "new memo" raised on the first scan after publish | every publish |

## What the team is not
- Not a trading signal. Nothing here places trades, ARMs LIVE, or APPLYs.
- Not a summarizer of member chatter. Comment mining is limited to author corrections and clarifications.
- Not a second memory. If Circle is unreachable, the team reports it; it does not restate old content as new.
