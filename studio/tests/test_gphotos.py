"""Google Photos import tests: python3 -m unittest discover studio/tests

The suggested reel length, the Picker client against a faked network, and
recognising items brought in before."""
import json
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(HERE), str(HERE.parent / "montage")]
import gphotos  # noqa: E402
import relay  # noqa: E402
from db import Library  # noqa: E402


class SuggestTarget(unittest.TestCase):
    def test_quarter_of_video_plus_3s_a_photo_to_15s(self):
        # 6m 40s of video and 12 photos: 100 + 36 = 136 -> 135
        self.assertEqual(relay.suggest_target(400, 12), 135)

    def test_at_least_a_minute(self):
        self.assertEqual(relay.suggest_target(70, 0), 60)
        self.assertEqual(relay.suggest_target(0, 16), 60)   # 64s of photos played whole

    def test_at_most_four_minutes(self):
        self.assertEqual(relay.suggest_target(3600, 40), 240)

    def test_under_a_minute_in_all_plays_everything(self):
        self.assertIsNone(relay.suggest_target(40, 2))    # 40 + 8 = 48s
        self.assertIsNone(relay.suggest_target(0, 0))
        self.assertIsNone(relay.suggest_target(None, None))

    def test_rounds_to_nearest_15(self):
        self.assertEqual(relay.suggest_target(4 * 97, 0), 90)    # 97 -> 90
        self.assertEqual(relay.suggest_target(4 * 98, 0), 105)   # 98 -> 105

    def test_always_on_the_grid(self):
        for v in range(0, 2000, 37):
            for p in range(0, 60, 7):
                t = relay.suggest_target(v, p)
                if t is not None:
                    self.assertTrue(60 <= t <= 240 and t % 15 == 0, (v, p, t))


def item(i, kind="PHOTO", t="2026-10-06T14:00:00Z", name=None):
    return {"id": f"id{i}", "createTime": t, "type": kind,
            "mediaFile": {"baseUrl": f"https://lh3.example/{i}/v1", "mimeType": "video/mp4" if kind == "VIDEO" else "image/jpeg",
                          "filename": name or f"IMG_{i:04d}.{'MOV' if kind == 'VIDEO' else 'JPG'}"}}


class FakeHttp:
    """Picker endpoints from a list of pages; downloads answer per base URL."""

    def __init__(self, pages, stale=(), broken=()):
        self.pages = pages          # [[items], [items], ...]
        self.stale = set(stale)     # base URLs that have expired
        self.broken = set(broken)   # item numbers that always fail
        self.lists = 0              # times the item list was fetched from the start
        self.version = 1
        self.calls = []

    def request(self, method, url, headers=None, data=None):
        self.calls.append((method, url))
        if url == gphotos.TOKEN_URL:
            return 200, json.dumps({"access_token": "tok", "expires_in": 3600}).encode()
        assert headers["Authorization"] == "Bearer tok"
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.path.endswith("/mediaItems"):
            n = int(q.get("pageToken", 0))
            if n == 0:
                self.lists += 1
                if self.lists > 1:
                    self.version += 1   # listing again hands out fresh base URLs
            page = [json.loads(json.dumps(i)) for i in self.pages[n]]
            for i in page:
                i["mediaFile"]["baseUrl"] = i["mediaFile"]["baseUrl"].rsplit("/", 1)[0] + f"/v{self.version}"
            body = {"mediaItems": page}
            if n + 1 < len(self.pages):
                body["nextPageToken"] = str(n + 1)
            return 200, json.dumps(body).encode()
        if u.path.endswith("/sessions") and method == "POST":
            return 200, json.dumps({"id": "s1", "pickerUri": "https://photos.google.com/picker/s1",
                                    "pollingConfig": {"pollInterval": "4s", "timeoutIn": "1800s"}}).encode()
        return 404, b"{}"

    def download(self, url, headers, target, on_bytes=None):
        base, suffix = url.rsplit("=", 1)
        n = int(base.split("/")[-2])
        if n in self.broken:
            return 500
        if base in self.stale and base.endswith("/v1"):
            return 403
        Path(target).write_bytes(f"{n}={suffix}".encode())
        if on_bytes:
            on_bytes(10)
        return 200


def client(tmp, http):
    gp = gphotos.GooglePhotos(tmp, "cid", "secret", http=http)
    gp._save_token({"refresh_token": "r", "access_token": "tok", "expires_at": 1e12})
    return gp


class PickerClient(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_all(self, gp, items):
        results, n = [], iter(range(1000))
        gp.download_all("s1", items, lambda i: self.dir / f"f{next(n)}",
                        lambda i, path, err: results.append((i["id"], path, err)))
        return results

    def test_lists_every_page(self):
        http = FakeHttp([[item(1), item(2)], [item(3, "VIDEO")], [item(4)]])
        items = client(self.dir, http).list_items("s1")
        self.assertEqual([i["id"] for i in items], ["id1", "id2", "id3", "id4"])
        self.assertEqual(items[2]["kind"], "video")
        self.assertEqual(items[0]["capturedAt"], 1791295200.0)

    def test_photos_download_with_d_and_videos_with_dv(self):
        http = FakeHttp([[item(1), item(2, "VIDEO")]])
        gp = client(self.dir, http)
        results = self.run_all(gp, gp.list_items("s1"))
        self.assertEqual([Path(p).read_text() for _, p, _ in results], ["1=d", "2=dv"])

    def test_expired_base_url_lists_again_once(self):
        http = FakeHttp([[item(1), item(2)], [item(3)]],
                        stale={"https://lh3.example/2/v1", "https://lh3.example/3/v1"})
        gp = client(self.dir, http)
        results = self.run_all(gp, gp.list_items("s1"))
        self.assertEqual([err for _, _, err in results], [None, None, None])
        self.assertEqual(http.lists, 2)   # the first listing and one refetch, not one per file

    def test_still_expired_after_a_refetch_fails_that_file_only(self):
        http = FakeHttp([[item(1), item(2), item(3)]], stale={"https://lh3.example/2/v1"})
        gp = client(self.dir, http)
        items = gp.list_items("s1")
        http.version = 0   # the refetch hands out stale URLs again: .../v1
        results = self.run_all(gp, items)
        self.assertEqual(http.lists, 2)
        self.assertEqual([(i, e is None) for i, _, e in results], [("id1", True), ("id2", False), ("id3", True)])

    def test_one_bad_file_does_not_stop_the_rest(self):
        http = FakeHttp([[item(1), item(2), item(3)]], broken={2})
        gp = client(self.dir, http)
        results = self.run_all(gp, gp.list_items("s1"))
        self.assertEqual([(i, e is None) for i, _, e in results], [("id1", True), ("id2", False), ("id3", True)])
        self.assertIn("500", results[1][2])
        self.assertEqual(sorted(p.name for p in self.dir.glob("f*")), ["f0", "f2"])   # nothing half-written left
        self.assertEqual(http.lists, 1)   # a server error isn't an expired URL

    def test_session(self):
        s = client(self.dir, FakeHttp([[]])).create_session()
        self.assertEqual((s["sessionId"], s["pollSeconds"]), ("s1", 4.0))

    def test_refreshes_an_expired_token(self):
        http = FakeHttp([[item(1)]])
        gp = client(self.dir, http)
        gp._save_token({"refresh_token": "r", "access_token": "old", "expires_at": 0})
        gp.list_items("s1")
        self.assertEqual(http.calls[0], ("POST", gphotos.TOKEN_URL))
        self.assertEqual(json.loads(gp.token_path.read_text())["refresh_token"], "r")   # kept

    def test_a_token_from_another_client_is_not_used(self):
        # GOOGLE_CLIENT_ID changed: the old token would bill the old project.
        client(self.dir, FakeHttp([[]]))
        gp = gphotos.GooglePhotos(self.dir, "new-cid", "secret", http=FakeHttp([[]]))
        self.assertFalse(gp.signed_in)
        with self.assertRaises(PermissionError):
            gp.access_token()
        self.assertTrue(client(self.dir, FakeHttp([[]])).signed_in)   # the old client still sees it

    def test_a_token_saved_before_clients_were_noted_still_works(self):
        gp = client(self.dir, FakeHttp([[]]))
        gp.token_path.write_text(json.dumps({"refresh_token": "r", "access_token": "tok", "expires_at": 1e12}))
        self.assertEqual(gp.access_token(), "tok")

    def test_not_configured(self):
        gp = gphotos.GooglePhotos(self.dir, "", "", http=FakeHttp([[]]))
        self.assertFalse(gp.configured)
        self.assertFalse(gp.signed_in)

    def test_nanosecond_times(self):
        self.assertAlmostEqual(gphotos.parse_time("2026-10-06T14:00:00.123456789Z"), 1791295200.123456, places=5)


class SigningIn(unittest.TestCase):
    """The code Google sends back, traded for a token; failures said plainly."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def sign_in(self, status, body):
        class Token:
            def request(self, method, url, headers=None, data=None):
                self.sent = dict(urllib.parse.parse_qsl(data.decode()))
                return status, json.dumps(body).encode()
        http = Token()
        gp = gphotos.GooglePhotos(self.dir, "cid", "secret", http=http)
        url = gp.auth_url("http://127.0.0.1:3009/api/gphotos/callback")
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))["state"]
        try:
            gp.finish_sign_in("the-code", state)
        except ValueError:
            pass
        return gp, http

    def test_signed_in(self):
        gp, http = self.sign_in(200, {"access_token": "a", "refresh_token": "r", "expires_in": 3599})
        self.assertTrue(gp.signed_in)
        self.assertEqual(gp.last_error, "")
        self.assertEqual(http.sent["redirect_uri"], "http://127.0.0.1:3009/api/gphotos/callback")
        self.assertTrue(http.sent["code_verifier"])

    def test_turned_down_says_why(self):
        gp, _ = self.sign_in(400, {"error": "invalid_client", "error_description": "Unauthorized"})
        self.assertFalse(gp.signed_in)
        self.assertIn("invalid_client Unauthorized", gp.last_error)

    def test_no_lasting_access(self):
        gp, _ = self.sign_in(200, {"access_token": "a", "expires_in": 3599})
        self.assertFalse(gp.signed_in)
        self.assertIn("no lasting access", gp.last_error)

    def test_stale_state(self):
        gp = gphotos.GooglePhotos(self.dir, "cid", "secret", http=FakeHttp([[]]))
        with self.assertRaises(ValueError):
            gp.finish_sign_in("code", "unknown")
        self.assertIn("restarted", gp.last_error)


class AlreadyInFootage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Library(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def add_media(self, db, folder, name, t, missing=0):
        return db.execute("INSERT INTO media (path, folder, name, kind, size, mtime, captured_at, missing) "
                          "VALUES (?, ?, ?, 'video', 1, ?, ?, ?)",
                          (f"{folder}/{name}", folder, name, t, t, missing)).lastrowid

    def test_matched_on_picker_id_even_renamed_and_moved(self):
        with self.lib.connect() as db:
            mid = self.add_media(db, "2026-10-06 garden", "IMG_0001 (2).MOV", 5.0)
            db.execute("INSERT INTO gphotos_items (picker_id, media_id, filename, create_time, imported_at) "
                       "VALUES ('id1', ?, 'IMG_0001.MOV', 1791295200, 0)", (mid,))
            got = gphotos.already_in(db, gphotos.item_view(item(1, "VIDEO")))
        self.assertEqual(got, "2026-10-06 garden")

    def test_a_missing_file_is_not_already_there(self):
        with self.lib.connect() as db:
            mid = self.add_media(db, "old", "IMG_0001.MOV", 1791295200, missing=1)
            db.execute("INSERT INTO gphotos_items (picker_id, media_id, filename, imported_at) "
                       "VALUES ('id1', ?, 'IMG_0001.MOV', 0)", (mid,))
            self.assertIsNone(gphotos.already_in(db, gphotos.item_view(item(1, "VIDEO"))))

    def test_fallback_on_name_and_capture_time(self):
        with self.lib.connect() as db:
            self.add_media(db, "from phone", "IMG_0001.MOV", 1791295200.6)
            self.assertEqual(gphotos.already_in(db, gphotos.item_view(item(1, "VIDEO"))), "from phone")
            # same name, another day: a different clip
            self.assertIsNone(gphotos.already_in(db, gphotos.item_view(item(1, "VIDEO", t="2026-10-07T14:00:00Z"))))

    def test_heic_matches_its_jpeg(self):
        with self.lib.connect() as db:
            self.add_media(db, "phone", "IMG_0009.jpg", 1791295200)
            self.assertEqual(gphotos.already_in(db, gphotos.item_view(item(9, name="IMG_0009.HEIC"))), "phone")


if __name__ == "__main__":
    unittest.main()
