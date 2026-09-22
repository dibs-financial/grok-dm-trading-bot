# grok-dm-trading-bot
Decentralized Masters Trained (Grok) Bot On Robinhood Agentic.

## Knowledge source

The bot's market context lives in [`knowledge/`](knowledge/README.md): a structured, cited knowledge base built from the weekly DM Market Update memos and slide decks (May 11 → Sep 21, 2026).

- Start with [`knowledge/state_card.md`](knowledge/state_card.md) for the current belief per label (BTC, ETH, HYPE, Fed, oil/Iran, gold, equities, regulation, ...) with superseded history and flagged conflicts.
- Load it from code with `knowledge/loader.py` (`from knowledge.loader import Knowledge`), which reads `knowledge/knowledge.json`.
- Add a new week with `scripts/extract_sources.py` then `scripts/build_manifest.py` (see the knowledge README for the full procedure).
