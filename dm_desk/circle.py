"""Circle (circle.so) Gatekeeper + Scout + Capturer for the DM community.

Gatekeeper: the only code that touches credentials. Reads CIRCLE_API_TOKEN (admin/headless API token)
            and CIRCLE_BASE_URL (default https://app.circle.so) from the environment. Never logs the token.
Scout:      enumerates spaces and posts newest first, computes the change set since the last watermark.
Capturer:   downloads memo/slide attachments (pdf/pptx) once into a folder and hands them to
            scripts/extract_sources.py (hash-dedupe happens there).

Endpoints are configurable (`profile`) because Circle exposes two APIs:
  * "v1"   Data API:   GET {base}/api/v1/spaces, /api/v1/posts?space_id=..  header  Authorization: Token token=<key>
  * "v2"   Admin API:  GET {base}/api/admin/v2/spaces, /api/admin/v2/posts    header  Authorization: Token <key>
Untested against a live community from this sandbox (no token, network blocked); the transport is injectable
so the logic is covered by tests with a fake transport.

Usage:  CIRCLE_API_TOKEN=... python3 -m dm_desk.circle sync --spaces "Market Updates,Memos" --out /path/drive
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ATTACHMENT_RE = re.compile(r"https?://[^\s\"'<>]+?\.(?:pdf|pptx)(?:\?[^\s\"'<>]*)?", re.I)

PROFILES = {
    "v1": {"spaces": "/api/v1/spaces", "posts": "/api/v1/posts", "auth": "Token token={token}", "page_param": "page", "per_page": "per_page"},
    "v2": {"spaces": "/api/admin/v2/spaces", "posts": "/api/admin/v2/posts", "auth": "Token {token}", "page_param": "page", "per_page": "per_page"},
}


class CircleUnavailable(RuntimeError):
    pass


@dataclass
class Post:
    id: str
    space_id: str
    space_name: str
    title: str
    created_at: str
    updated_at: str
    url: str
    attachments: list[str] = field(default_factory=list)
    body_text: str = ""


class Gatekeeper:
    """Holds the credential; issues authenticated GETs with rate limiting. Nothing else sees the token."""

    def __init__(self, token: str | None = None, base_url: str | None = None, profile: str = "v2",
                 transport: Callable[[str, dict], tuple[int, bytes]] | None = None, min_interval_s: float = 0.5, timeout: float = 20.0):
        self._token = token or os.environ.get("CIRCLE_API_TOKEN", "")
        self.base = (base_url or os.environ.get("CIRCLE_BASE_URL", "https://app.circle.so")).rstrip("/")
        self.profile = PROFILES[profile]
        self.transport = transport or self._urllib
        self.min_interval_s, self.timeout = min_interval_s, timeout
        self._last = 0.0
        if not self._token:
            raise CircleUnavailable("CIRCLE_API_TOKEN not set")

    def _urllib(self, url: str, headers: dict) -> tuple[int, bytes]:
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except Exception as e:  # noqa: BLE001
            raise CircleUnavailable(f"network: {e}") from e

    def get(self, path: str, params: dict | None = None) -> object:
        wait = self.min_interval_s - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        status, body = self.transport(url, {"Authorization": self.profile["auth"].format(token=self._token),
                                            "Accept": "application/json", "User-Agent": "dm-desk-circle/1.0"})
        self._last = time.time()
        if status == 429:
            time.sleep(5)
            return self.get(path, params)
        if status in (401, 403):
            raise CircleUnavailable(f"auth rejected ({status}) — token invalid or lacks scope")
        if status >= 400:
            raise CircleUnavailable(f"HTTP {status} on {path}")
        try:
            return json.loads(body.decode())
        except json.JSONDecodeError as e:
            raise CircleUnavailable(f"non-JSON body on {path}") from e

    def download(self, url: str, dest: str) -> str:
        status, body = self.transport(url, {"User-Agent": "dm-desk-circle/1.0"})
        if status >= 400:
            raise CircleUnavailable(f"HTTP {status} downloading {url}")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(body)
        return dest


class Scout:
    def __init__(self, gk: Gatekeeper, watermark_path: str):
        self.gk, self.watermark_path = gk, watermark_path
        self.watermark = json.load(open(watermark_path)) if os.path.exists(watermark_path) else {"posts": {}, "last_sync": None}

    @staticmethod
    def _items(payload) -> list[dict]:
        if isinstance(payload, list):
            return payload
        for k in ("records", "data", "posts", "spaces", "results"):
            if isinstance(payload, dict) and isinstance(payload.get(k), list):
                return payload[k]
        return []

    def spaces(self, names: list[str] | None = None) -> list[dict]:
        out = self._items(self.gk.get(self.gk.profile["spaces"]))
        if names:
            wanted = {n.strip().lower() for n in names}
            out = [s for s in out if str(s.get("name", "")).strip().lower() in wanted]
        return out

    def posts(self, space: dict, max_pages: int = 20, per_page: int = 50) -> list[Post]:
        out: list[Post] = []
        for page in range(1, max_pages + 1):
            payload = self.gk.get(self.gk.profile["posts"], {"space_id": space["id"], self.gk.profile["page_param"]: page,
                                                             self.gk.profile["per_page"]: per_page, "sort": "latest"})
            rows = self._items(payload)
            if not rows:
                break
            for r in rows:
                html = str(r.get("body_html") or r.get("body") or r.get("tiptap_body") or "")
                atts = ATTACHMENT_RE.findall(html)
                for a in r.get("attachments", []) or []:
                    u = a.get("url") if isinstance(a, dict) else str(a)
                    if u and u.lower().split("?")[0].endswith((".pdf", ".pptx")):
                        atts.append(u)
                out.append(Post(str(r.get("id")), str(space["id"]), str(space.get("name", "")), str(r.get("name") or r.get("title") or ""),
                                str(r.get("created_at", "")), str(r.get("updated_at", "")), str(r.get("url", "")),
                                sorted(set(atts)), re.sub(r"<[^>]+>", " ", html)[:5000]))
            if len(rows) < per_page:
                break
        return sorted(out, key=lambda p: p.created_at, reverse=True)   # newest first

    def changes(self, posts: list[Post]) -> dict[str, list[Post]]:
        seen = self.watermark["posts"]
        created = [p for p in posts if p.id not in seen]
        updated = [p for p in posts if p.id in seen and seen[p.id] != p.updated_at]
        return {"created": created, "updated": updated}

    def commit(self, posts: list[Post]) -> None:
        for p in posts:
            self.watermark["posts"][p.id] = p.updated_at
        self.watermark["last_sync"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        os.makedirs(os.path.dirname(self.watermark_path) or ".", exist_ok=True)
        json.dump(self.watermark, open(self.watermark_path, "w"), indent=1)


def capture(gk: Gatekeeper, posts: list[Post], out_dir: str) -> list[str]:
    """Download every pdf/pptx attachment once (by URL basename); returns local paths."""
    paths = []
    for p in posts:
        for url in p.attachments:
            name = os.path.basename(urllib.parse.urlparse(url).path)
            dest = os.path.join(out_dir, f"{p.created_at[:10] or 'undated'}_{name}")
            if not os.path.exists(dest):
                gk.download(url, dest)
            paths.append(dest)
    return paths


def sync(space_names: list[str], out_dir: str, profile: str = "v2", ingest: bool = True, gk: Gatekeeper | None = None) -> dict:
    gk = gk or Gatekeeper(profile=profile)
    scout = Scout(gk, os.path.join(out_dir, ".circle_watermark.json"))
    spaces = scout.spaces(space_names)
    if space_names and not spaces:
        raise CircleUnavailable(f"none of the requested spaces found: {space_names}")
    all_posts: list[Post] = []
    for s in spaces:
        all_posts += scout.posts(s)
    ch = scout.changes(all_posts)
    new = ch["created"] + ch["updated"]
    files = capture(gk, new, out_dir)
    if ingest and files:
        subprocess.run([sys.executable, os.path.join(REPO, "scripts", "extract_sources.py"), out_dir], check=False)
        subprocess.run([sys.executable, os.path.join(REPO, "scripts", "build_manifest.py")], check=False)
    scout.commit(all_posts)
    return {"spaces": [s.get("name") for s in spaces], "posts": len(all_posts), "created": len(ch["created"]),
            "updated": len(ch["updated"]), "files": files}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="dm_desk.circle", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["spaces", "sync"])
    ap.add_argument("--spaces", default="", help="comma-separated space names to watch (default: all)")
    ap.add_argument("--out", default=os.path.join(REPO, "dm_desk", "data", "drive"))
    ap.add_argument("--profile", default="v2", choices=list(PROFILES))
    ap.add_argument("--no-ingest", action="store_true")
    a = ap.parse_args(argv)
    try:
        gk = Gatekeeper(profile=a.profile)
        if a.command == "spaces":
            for s in Scout(gk, os.path.join(a.out, ".circle_watermark.json")).spaces():
                print(s.get("id"), "|", s.get("name"))
        else:
            names = [s for s in a.spaces.split(",") if s.strip()]
            print(json.dumps(sync(names, a.out, a.profile, ingest=not a.no_ingest, gk=gk), indent=1))
    except CircleUnavailable as e:
        print(f"PROBLEM: Circle unavailable — {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
