import json, os, tempfile, unittest
from dm_desk.circle import CircleUnavailable, Gatekeeper, Scout, capture, sync

SPACES = {"records": [{"id": 11, "name": "Market Updates"}, {"id": 12, "name": "Chat"}]}
POSTS_P1 = {"records": [
    {"id": 1, "name": "DM Market Update Sep 21", "created_at": "2026-09-21T12:00:00Z", "updated_at": "2026-09-21T12:00:00Z",
     "url": "https://x/1", "body_html": "<p>memo</p><a href='https://cdn.x/DM_Market_Update_Memo_Sep21_2026.pdf'>pdf</a>",
     "attachments": [{"url": "https://cdn.x/DM_Market_Update_Slides_Sep21_2026.pdf"}]},
    {"id": 2, "name": "Older", "created_at": "2026-08-31T12:00:00Z", "updated_at": "2026-08-31T12:00:00Z", "url": "https://x/2", "body_html": "<p>no files</p>"},
]}


def fake_transport(calls):
    def t(url, headers):
        calls.append((url, headers))
        if url.endswith("/api/admin/v2/spaces"):
            return 200, json.dumps(SPACES).encode()
        if "/api/admin/v2/posts" in url:
            return 200, json.dumps(POSTS_P1 if "page=1" in url else {"records": []}).encode()
        if url.endswith(".pdf"):
            return 200, b"%PDF-1.4 fake " + os.path.basename(url).encode()
        return 404, b"{}"
    return t


class CircleTests(unittest.TestCase):
    def test_token_required(self):
        os.environ.pop("CIRCLE_API_TOKEN", None)
        with self.assertRaises(CircleUnavailable):
            Gatekeeper()

    def test_scout_newest_first_and_attachments(self):
        calls = []
        gk = Gatekeeper(token="SECRET-TOKEN-XYZ", transport=fake_transport(calls), min_interval_s=0)
        sc = Scout(gk, os.path.join(tempfile.mkdtemp(), "wm.json"))
        spaces = sc.spaces(["market updates"])
        self.assertEqual([s["id"] for s in spaces], [11])
        posts = sc.posts(spaces[0])
        self.assertEqual([p.id for p in posts], ["1", "2"])
        self.assertEqual(len(posts[0].attachments), 2)
        self.assertTrue(all(h["Authorization"] == "Token SECRET-TOKEN-XYZ" for _, h in calls))
        self.assertNotIn("SECRET-TOKEN-XYZ", json.dumps([u for u, _ in calls]))     # token never in URLs

    def test_sync_captures_once_and_watermarks(self):
        calls = []
        gk = Gatekeeper(token="SECRET-TOKEN-XYZ", transport=fake_transport(calls), min_interval_s=0)
        out = tempfile.mkdtemp()
        r1 = sync(["Market Updates"], out, ingest=False, gk=gk)
        self.assertEqual(r1["created"], 2); self.assertEqual(len(r1["files"]), 2)
        self.assertTrue(all(os.path.exists(f) for f in r1["files"]))
        downloads = sum(1 for u, _ in calls if u.endswith(".pdf"))
        r2 = sync(["Market Updates"], out, ingest=False, gk=gk)
        self.assertEqual(r2["created"], 0); self.assertEqual(r2["files"], [])
        self.assertEqual(sum(1 for u, _ in calls if u.endswith(".pdf")), downloads)   # no re-download

    def test_auth_rejected_is_unavailable(self):
        gk = Gatekeeper(token="bad", transport=lambda u, h: (401, b"{}"), min_interval_s=0)
        with self.assertRaises(CircleUnavailable):
            Scout(gk, os.path.join(tempfile.mkdtemp(), "wm.json")).spaces()
