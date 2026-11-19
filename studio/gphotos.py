"""
Google Photos, through the Photos Picker API: the one supported way for an
app to read someone's own photos and videos.

An album link can't be read by an app (the Library API only reaches what the
app itself uploaded), so the picker is the input: a session is opened, its
pickerUri opened in a browser tab, items are chosen in Google's own picker,
then they're listed and downloaded.

    1. OAuth (installed-app flow, loopback redirect, PKCE) for SCOPE.
    2. POST /v1/sessions                 -> {id, pickerUri, pollingConfig}
    3. GET  /v1/sessions/{id}            until mediaItemsSet
    4. GET  /v1/mediaItems?sessionId=..  (paged) -> baseUrl per item
       baseUrl + "=d" (photo) / "=dv" (video), with the access token.
       Base URLs last about an hour; a stale one is refreshed by listing again.
    5. DELETE /v1/sessions/{id}

Config comes from the environment (.env): GOOGLE_CLIENT_ID and
GOOGLE_CLIENT_SECRET of a Desktop-type OAuth client. The token is kept in the
studio's home (~/Footage/.studio/gphotos-token.json), never in the repo.

Only urllib: the HTTP layer is one function (`Http`), so tests swap it out.
"""

import base64
import hashlib
import json
import os
import re
import secrets
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCOPE = "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://photospicker.googleapis.com/v1"
EXPIRED = (401, 403, 404, 410)   # what a stale base URL answers with


class HttpError(Exception):
    def __init__(self, status, body=b""):
        super().__init__(f"HTTP {status}: {said(body)}")
        self.status = status
        self.body = body


def said(body):
    """What an error response says: Google's error and its description, if it's JSON."""
    try:
        e = json.loads(body)
        if isinstance(e.get("error"), dict):   # the API's {error: {code, message, status}}
            return f"{e['error'].get('status', '')} {e['error'].get('message', '')}".strip()
        return " ".join(str(e[k]) for k in ("error", "error_description") if e.get(k))
    except (ValueError, AttributeError, TypeError):
        return (body or b"")[:300].decode("utf-8", "replace")


def tls_context():
    """Certificates to check Google's with: certifi's when it's installed (the
    python.org Python on a Mac has none of its own until "Install
    Certificates" is run), else the system's."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def reason(e):
    """A network failure, said plainly."""
    text = str(getattr(e, "reason", e))
    if "CERTIFICATE_VERIFY_FAILED" in text:
        return ("This Python can't check Google's certificate. Run ./studio/run.sh again (it installs "
                "certifi), or run 'Install Certificates.command' from your Python's Applications folder.")
    return f"Couldn't reach Google: {text}"


class Http:
    """The network, as two calls. Tests replace it with a fake."""

    def __init__(self):
        self.tls = tls_context()

    def request(self, method, url, headers=None, data=None):
        """-> (status, body bytes). Never raises on an HTTP status."""
        req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=60, context=self.tls) as res:
                return res.status, res.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except urllib.error.URLError as e:
            raise OSError(reason(e)) from e

    def download(self, url, headers, target, on_bytes=None):
        """Stream url into the file at target. -> status (200 when written).
        on_bytes(0, size) once the response starts (size from Content-Length,
        or None), then on_bytes(n) per chunk, so progress moves within a file."""
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=120, context=self.tls) as res, open(target, "wb") as f:
                if on_bytes:
                    size = res.headers.get("Content-Length")
                    on_bytes(0, int(size) if size and size.isdigit() else None)
                while chunk := res.read(1 << 18):
                    f.write(chunk)
                    if on_bytes:
                        on_bytes(len(chunk))
                return res.status
        except urllib.error.HTTPError as e:
            return e.code


def seconds_of(text, default):
    """A Google duration ("5s", "1800s", "0.5s") as seconds."""
    try:
        return float(str(text).rstrip("s"))
    except (TypeError, ValueError):
        return default


# A Pixel names each shot for when it was taken, in UTC, to the millisecond:
# PXL_20261115_180430715.jpg (also .MP.jpg, .TS-000.jpg, .mp4).
PIXEL_NAME = re.compile(r"PXL_(\d{8})_(\d{6})(\d{3})")


def name_time(filename):
    """When a shot was taken, from its file name where that says (a Pixel's),
    epoch seconds; else None. Truer than Google's createTime, which an
    edit or a re-upload can move."""
    m = PIXEL_NAME.match(filename or "")
    if not m:
        return None
    try:
        t = datetime.strptime(m[1] + m[2], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return t.timestamp() + int(m[3]) / 1000


def parse_time(text):
    """RFC 3339 ("2026-10-06T14:22:01.123Z") -> epoch seconds, or None."""
    if not text:
        return None
    try:
        t = str(text).replace("Z", "+00:00")
        # Python before 3.11 takes at most 6 fraction digits; Google may send 9.
        if "." in t:
            head, rest = t.split(".", 1)
            frac = rest[:len(rest) - len(rest.lstrip("0123456789"))]   # the digits up to the zone
            tz = rest[len(frac):]
            t = f"{head}.{frac[:6]}{tz}"
        return datetime.fromisoformat(t).timestamp()
    except ValueError:
        return None


def item_view(item):
    """A picked item as the studio uses it."""
    f = item.get("mediaFile") or {}
    kind = "video" if item.get("type") == "VIDEO" or (f.get("mimeType") or "").startswith("video/") else "photo"
    return {"id": item.get("id"), "filename": f.get("filename") or f"{item.get('id')}",
            "kind": kind, "mimeType": f.get("mimeType") or "",
            "createTime": item.get("createTime"),
            "capturedAt": name_time(f.get("filename")) or parse_time(item.get("createTime")),
            "baseUrl": f.get("baseUrl")}


class GooglePhotos:
    def __init__(self, home, client_id=None, client_secret=None, http=None, clock=time.time):
        self.token_path = Path(home) / "gphotos-token.json"
        self.client_id = client_id if client_id is not None else os.environ.get("GOOGLE_CLIENT_ID", "")
        self.client_secret = client_secret if client_secret is not None else os.environ.get("GOOGLE_CLIENT_SECRET", "")
        self.http = http or Http()
        self.clock = clock
        self._pending = {}   # OAuth state -> (PKCE verifier, redirect_uri)
        self.last_error = ""  # why the last sign-in didn't work, for the dialog

    # ------------------------------------------------------------ OAuth

    @property
    def configured(self):
        return bool(self.client_id and self.client_secret)

    @property
    def signed_in(self):
        return self.configured and bool(self._token().get("refresh_token"))

    def _token(self):
        """The saved sign-in, unless another OAuth client made it: Google bills
        each call to the project of the client its token came from, so after
        GOOGLE_CLIENT_ID changes an old token would keep using the old project.
        (Tokens saved before the client was noted are taken as they are.)"""
        try:
            tok = json.loads(self.token_path.read_text())
        except (OSError, ValueError):
            return {}
        return tok if tok.get("client_id", self.client_id) == self.client_id else {}

    def _save_token(self, tok):
        tok = {**tok, "client_id": self.client_id}
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.token_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(tok))
        os.chmod(tmp, 0o600)
        tmp.replace(self.token_path)

    def sign_out(self):
        self.token_path.unlink(missing_ok=True)

    def auth_url(self, redirect_uri):
        """Where to send the browser to sign in (PKCE, offline access)."""
        state = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self._pending[state] = (verifier, redirect_uri)
        q = {"client_id": self.client_id, "redirect_uri": redirect_uri, "response_type": "code",
             "scope": SCOPE, "access_type": "offline", "prompt": "consent", "state": state,
             "code_challenge": challenge, "code_challenge_method": "S256"}
        return f"{AUTH_URL}?{urllib.parse.urlencode(q)}"

    def finish_sign_in(self, code, state):
        """Trade the code Google sent back for a token, and keep it. Whatever
        goes wrong is kept in last_error too, for the dialog to show."""
        try:
            if state not in self._pending:
                raise ValueError("That sign-in was started before the studio restarted; sign in again.")
            verifier, redirect_uri = self._pending.pop(state)
            try:
                tok = self._token_call({"grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                                        "redirect_uri": redirect_uri})
            except HttpError as e:
                raise ValueError(f"Google turned down the sign-in ({said(e.body)}).") from e
            if not tok.get("refresh_token"):
                tok["refresh_token"] = self._token().get("refresh_token")
            if not tok.get("refresh_token"):
                raise ValueError("Google signed in but gave no lasting access. Remove the app at "
                                 "myaccount.google.com/permissions and sign in again.")
            self._save_token(tok)
        except Exception as e:
            self.last_error = str(e)
            raise
        self.last_error = ""

    def _token_call(self, fields):
        data = urllib.parse.urlencode({"client_id": self.client_id, "client_secret": self.client_secret,
                                       **fields}).encode()
        status, body = self.http.request("POST", TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, data)
        if status != 200:
            raise HttpError(status, body)
        tok = json.loads(body)
        tok["expires_at"] = self.clock() + float(tok.get("expires_in", 3600)) - 60
        return tok

    def access_token(self):
        tok = self._token()
        if not tok.get("refresh_token"):
            raise PermissionError("Not signed in to Google Photos")
        if tok.get("access_token") and tok.get("expires_at", 0) > self.clock():
            return tok["access_token"]
        try:
            fresh = self._token_call({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
        except HttpError as e:
            if e.status in (400, 401):   # invalid_grant: revoked, or a testing-mode token past 7 days
                self.sign_out()
                raise PermissionError("Google sign-in has expired; sign in again") from e
            raise
        fresh.setdefault("refresh_token", tok["refresh_token"])
        self._save_token(fresh)
        return fresh["access_token"]

    # ------------------------------------------------------------ the API

    def _auth(self):
        return {"Authorization": f"Bearer {self.access_token()}"}

    def _call(self, method, path, body=None):
        headers = self._auth()
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        status, raw = self.http.request(method, f"{API}{path}", headers, data)
        if status == 401:   # a token revoked under us: refresh once
            tok = self._token()
            tok["expires_at"] = 0
            self._save_token(tok)
            headers.update(self._auth())
            status, raw = self.http.request(method, f"{API}{path}", headers, data)
        if status >= 300:
            raise HttpError(status, raw)
        return json.loads(raw) if raw else {}

    def create_session(self):
        s = self._call("POST", "/sessions", {})
        return {"sessionId": s["id"], "pickerUri": s["pickerUri"],
                "pollSeconds": seconds_of((s.get("pollingConfig") or {}).get("pollInterval"), 5),
                "timeoutSeconds": seconds_of((s.get("pollingConfig") or {}).get("timeoutIn"), 1800)}

    def session(self, session_id):
        return self._call("GET", f"/sessions/{urllib.parse.quote(session_id)}")

    def delete_session(self, session_id):
        try:
            self._call("DELETE", f"/sessions/{urllib.parse.quote(session_id)}")
        except Exception:
            pass   # it expires by itself anyway

    def list_items(self, session_id):
        """Every picked item, all pages, as item_view dicts."""
        items, token = [], None
        while True:
            q = {"sessionId": session_id, "pageSize": 100}
            if token:
                q["pageToken"] = token
            page = self._call("GET", f"/mediaItems?{urllib.parse.urlencode(q)}")
            items += [item_view(i) for i in page.get("mediaItems") or []]
            token = page.get("nextPageToken")
            if not token:
                return items

    def download_url(self, item):
        return f"{item['baseUrl']}={'dv' if item['kind'] == 'video' else 'd'}"

    def download_all(self, session_id, items, target_of, done_with=None, on_bytes=None, should_stop=None):
        """Download items one by one; one bad file doesn't stop the rest.

        target_of(item) -> a path to write to. done_with(item, path or None,
        error or None) after each. A base URL that has gone stale (they last
        about an hour) gets the item list fetched again, once, for fresh
        ones; an item that still fails is reported and skipped.
        """
        refreshed = False
        for item in items:
            if should_stop and should_stop():
                return
            target = None
            try:
                target = target_of(item)
                status = self.http.download(self.download_url(item), self._auth(), target, on_bytes)
                if status in EXPIRED and not refreshed:
                    refreshed = True
                    fresh = {i["id"]: i for i in self.list_items(session_id)}
                    for it in items:
                        if it["id"] in fresh:
                            it["baseUrl"] = fresh[it["id"]]["baseUrl"]
                    status = self.http.download(self.download_url(item), self._auth(), target, on_bytes)
                if status != 200:
                    raise HttpError(status)
            except Exception as e:
                if target is not None:
                    Path(target).unlink(missing_ok=True)
                if done_with:
                    done_with(item, None, str(e))
                continue
            if done_with:
                done_with(item, target, None)


HEIC_EXTS = {".heic", ".heif"}


def names_of(item):
    """The names a picked item could have in Footage: Google's, and the JPEG
    a HEIC photo becomes on the way in."""
    name = Path(item["filename"]).name
    names = {name}
    if Path(name).suffix.lower() in HEIC_EXTS:
        names.add(Path(name).with_suffix(".jpg").name)
    return names


def already_in(db, item):
    """The shoot folder (db.py's library) that already has this picked item,
    if any: matched on the picker's id (brought in from Google Photos before,
    wherever it's been moved since), else on name and capture time (the same
    clip sent over from the phone). Content can't be compared: Google's
    video is a transcode, not the original file."""
    row = db.execute("""SELECT m.folder FROM gphotos_items g JOIN media m ON m.id = g.media_id
                        WHERE g.picker_id = ? AND m.missing = 0""", (item["id"],)).fetchone()
    if row:
        return row["folder"]
    if item.get("capturedAt") is None:
        return None
    names = sorted(names_of(item))
    row = db.execute(f"""SELECT folder FROM media WHERE missing = 0 AND name IN ({','.join('?' * len(names))})
                         AND abs(captured_at - ?) < 2 LIMIT 1""", [*names, item["capturedAt"]]).fetchone()
    return row["folder"] if row else None
