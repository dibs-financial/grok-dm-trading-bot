"""Drive adapter: 'Your Google Drive DM folder (memos/slides; newest first)'.

Two implementations:
  * KnowledgeDrive  - reads this repo's knowledge/ base (manifest.json + knowledge.json). This is
                      the processed form of the Drive folder and the default.
  * FolderDrive     - watches a local folder (e.g. a synced Google Drive mount) for new PDF/PPTX,
                      ingests them with scripts/extract_sources.py, then defers to KnowledgeDrive.
If Drive cannot be read the adapter raises DriveUnavailable: no packet, PROBLEM ping.
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
from dataclasses import dataclass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KNOWLEDGE = os.path.join(REPO, "knowledge")


class DriveUnavailable(RuntimeError):
    pass


@dataclass
class DriveDoc:
    date: str
    kind: str
    title: str
    cite: str
    path: str


@dataclass
class WatchedLevel:
    asset: str
    level: float
    role: str          # support | resistance
    date: str
    cite: str


class KnowledgeDrive:
    name = "knowledge/"

    def __init__(self, root: str = KNOWLEDGE):
        self.root = root
        try:
            with open(os.path.join(root, "manifest.json")) as fh:
                self.manifest = json.load(fh)
            with open(os.path.join(root, "knowledge.json")) as fh:
                self.kb = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            raise DriveUnavailable(f"knowledge base unreadable: {e}") from e

    def docs(self) -> list[DriveDoc]:
        rows = [DriveDoc(r["date"], r["kind"], r["title"], r["cite"], r["original"]) for r in self.manifest["sources"]]
        return sorted(rows, key=lambda d: (d.date, d.kind), reverse=True)   # newest first

    def latest(self) -> DriveDoc:
        docs = self.docs()
        if not docs:
            raise DriveUnavailable("Drive folder is empty")
        return docs[0]

    def latest_line(self) -> str:
        d = self.latest()
        return f"Drive latest: {os.path.basename(d.path)} ({d.date}, {d.title})"

    def new_since(self, date: str | None) -> list[DriveDoc]:
        return [d for d in self.docs() if date is None or d.date > date]

    def watched_levels(self, assets: tuple[str, ...] = ("BTC", "ETH")) -> list[WatchedLevel]:
        """Latest memo levels per asset = the levels the 4h loop watches."""
        out: list[WatchedLevel] = []
        for asset in assets:
            rows = [r for r in self.kb["levels"] if r["asset"].upper() == asset.upper()]
            if not rows:
                continue
            r = rows[-1]
            for lv in r["support"]:
                if isinstance(lv, (int, float)):
                    out.append(WatchedLevel(asset.upper(), float(lv), "support", r["date"], r["cite"]))
            for lv in r["resistance"]:
                if isinstance(lv, (int, float)):
                    out.append(WatchedLevel(asset.upper(), float(lv), "resistance", r["date"], r["cite"]))
        return out

    def named_defi_rails(self) -> tuple[str, ...]:
        """Rails named in the latest memo beyond spot BTC/ETH/Aave. Extend when memos name venues."""
        text = self.kb["labels"].get("hype", {}).get("current", {}).get("summary", "")
        rails = []
        if "Hyperliquid" in text or "HYPE" in text:
            rails.append("Hyperliquid perps")
        return tuple(rails)

    def context_pack(self) -> str:
        sys.path.insert(0, REPO)
        from knowledge.loader import Knowledge  # local import keeps drive.py dependency-free
        return Knowledge(os.path.join(self.root, "knowledge.json")).context_pack()


class FolderDrive(KnowledgeDrive):
    """Local folder (synced Drive). New PDF/PPTX are ingested into knowledge/ before reading."""
    name = "folder"

    def __init__(self, folder: str, root: str = KNOWLEDGE, ingest: bool = True):
        if not os.path.isdir(folder):
            raise DriveUnavailable(f"Drive folder not readable: {folder}")
        self.folder = folder
        if ingest and glob.glob(os.path.join(folder, "*.pdf")) + glob.glob(os.path.join(folder, "*.pptx")):
            cmd = [sys.executable, os.path.join(REPO, "scripts", "extract_sources.py"), folder]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                raise DriveUnavailable(f"ingest failed: {r.stderr.strip()[:300]}")
            subprocess.run([sys.executable, os.path.join(REPO, "scripts", "build_manifest.py")], capture_output=True, text=True)
        super().__init__(root)


def make_drive(kind: str = "knowledge", folder: str | None = None):
    if kind == "knowledge":
        return KnowledgeDrive()
    if kind == "folder":
        if not folder:
            raise ValueError("folder drive needs --drive-folder")
        return FolderDrive(folder)
    raise ValueError(f"unknown drive kind {kind!r}")
