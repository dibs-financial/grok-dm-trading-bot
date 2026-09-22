"""Knowledge desk: the box. Owns knowledge/ — ingest (Circle or files), extract, index, status."""
from __future__ import annotations

import json
import os
import subprocess
import sys

from . import config as C
from .drive import KNOWLEDGE, DriveUnavailable, KnowledgeDrive

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class KnowledgeDesk:
    name = "knowledge"

    def __init__(self, data_dir: str = C.DATA_DIR):
        self.dir = data_dir

    def status(self) -> dict:
        try:
            d = KnowledgeDrive()
        except DriveUnavailable as e:
            return {"ok": False, "error": str(e)}
        kb = d.kb
        return {"ok": True, "as_of": kb["meta"]["current_as_of"], "sources": d.manifest["count"], "weeks": len(d.manifest["weeks"]),
                "labels": list(kb["labels"]), "gaps": kb["meta"].get("gaps", []), "conflicts_status": kb["meta"].get("conflicts_status", "")}

    def heartbeat(self) -> str:
        s = self.status()
        return f"KB | as_of:{s.get('as_of', 'UNREAD')} | sources:{s.get('sources', 0)} | gaps:{len(s.get('gaps', []))}"

    def ingest(self, path: str) -> str:
        """Files (PDF/PPTX) from anywhere -> knowledge/sources; then rebuild indexes."""
        r = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "extract_sources.py"), path], capture_output=True, text=True)
        b = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "build_manifest.py")], capture_output=True, text=True)
        return (r.stdout + b.stdout).strip()

    def sync_circle(self, spaces: list[str], out_dir: str | None = None, profile: str = "v2") -> dict:
        from .circle import sync
        return sync(spaces, out_dir or os.path.join(self.dir, "drive"), profile=profile)
