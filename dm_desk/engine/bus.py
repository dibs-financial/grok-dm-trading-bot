"""Tiny in-process event bus with an append-only JSONL trace."""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from typing import Callable

from .. import config as C


class Bus:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(C.DATA_DIR, "engine", "events.jsonl")
        self.subs: dict[str, list[Callable[[dict], None]]] = defaultdict(list)

    def on(self, topic: str, fn: Callable[[dict], None]) -> None:
        self.subs[topic].append(fn)

    def emit(self, topic: str, payload: dict) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "a") as fh:
            fh.write(json.dumps({"ts": time.time(), "topic": topic, **payload}) + "\n")
        for fn in self.subs.get(topic, []):
            fn(payload)
