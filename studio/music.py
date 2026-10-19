"""
The music shelf: tracks in ~/Music/Reels (MUSIC_DIR), and their beats.

Beats are detected once per track with librosa and cached as JSON under
~/Footage/.studio/music/. The engine reads that same file (`beat_file:`), so
the studio's preview and the render cut on exactly the same beats.
"""

import hashlib
import json
import re
import subprocess
import threading
from pathlib import Path

AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".aiff", ".aif"}


class Shelf:
    def __init__(self, folder, cache_dir):
        self.folder = Path(folder).expanduser()
        self.cache_dir = Path(cache_dir)
        self._locks = {}
        self._guard = threading.Lock()
        self._probed = {}   # (path, size, mtime) -> what ffprobe found in the file

    def tracks(self):
        if not self.folder.is_dir():
            return []
        out = []
        for p in sorted(self.folder.iterdir(), key=lambda q: q.name.lower()):
            if p.is_file() and p.suffix.lower() in AUDIO_EXTS and not p.name.startswith("."):
                cached = self.cached(p)
                info = self.probed(p)
                out.append({"name": p.name, "duration": info["duration"],
                            "bpm": cached["bpm"] if cached else None, **describe(p.stem, info["tags"])})
        return out

    def probed(self, path):
        st = path.stat()
        key = (str(path), st.st_size, st.st_mtime)
        if key not in self._probed:
            self._probed[key] = probe(path)
        return self._probed[key]

    def path_of(self, value):
        """A reel's music setting: a shelf track name, or a path."""
        if not value:
            return None
        p = Path(value).expanduser()
        if not p.is_absolute():
            p = self.folder / value
        return p

    def cache_file(self, path):
        st = path.stat()
        key = hashlib.sha1(f"{path.resolve()}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()[:16]
        return self.cache_dir / f"{path.stem[:40]}-{key}.json"

    def cached(self, path):
        f = self.cache_file(path)
        return json.loads(f.read_text()) if f.exists() else None

    def analyze(self, path):
        """{bpm, beats (seconds into the song), duration}; detected once, then cached."""
        with self._guard:
            lock = self._locks.setdefault(str(path), threading.Lock())
        with lock:
            hit = self.cached(path)
            if hit:
                return hit
            import librosa  # imported late: it's slow to load and optional
            import numpy as np
            y, sr = librosa.load(str(path), sr=22050, mono=True)
            tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
            beats = [round(float(b), 4) for b in beats]
            data = {"bpm": round(float(np.atleast_1d(tempo)[0]), 1), "beats": beats,
                    "duration": round(len(y) / sr, 2), "file": str(path)}
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.cache_file(path).write_text(json.dumps(data))
            return data


def beat_detection_available():
    try:
        import librosa  # noqa: F401
        return True
    except Exception:
        return False


def probe(path):
    """{duration, tags}: the song's length and its tags (title, artist, genre, ...),
    with the tag names lower-cased."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags",
                              "-of", "json", str(path)],
                             capture_output=True, text=True, timeout=20).stdout
        fmt = json.loads(out or "{}").get("format", {})
        tags = {k.lower(): str(v).strip() for k, v in (fmt.get("tags") or {}).items() if str(v).strip()}
        return {"duration": round(float(fmt.get("duration") or 0), 2), "tags": tags}
    except Exception:
        return {"duration": 0.0, "tags": {}}


# Pixabay names its downloads <artist>-<title words>-<id>.mp3, e.g.
# pietix-bass-instrumental-soft-510326.mp3 (some older ones leave the artist out).
PIXABAY = re.compile(r"^(?P<slug>.+)-(?P<id>\d{5,})$")


def words(slug):
    """bass-instrumental_soft -> Bass Instrumental Soft"""
    return " ".join(w[:1].upper() + w[1:] for w in re.split(r"[-_\s]+", slug) if w)


def slugged(text):
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def describe(stem, tags):
    """A song's name and artist as its file gives them: the tags when they say
    something the file name doesn't, else read from a Pixabay file name, else
    the file name itself. Plus the tags worth showing, and its Pixabay id."""
    m = PIXABAY.match(stem)
    slug = m["slug"] if m else stem
    title, artist = words(slug), ""
    first, _, rest = slug.partition("-")
    tagged_artist = tags.get("artist") or tags.get("album_artist") or ""
    # The first word is the artist when the tags say so, or (no tags) when it
    # leaves a title of two words or more: good-night is a title, not "Night" by Good.
    if m and rest and (slugged(first) == slugged(tagged_artist) if tagged_artist else "-" in rest):
        title, artist = words(rest), words(first)
    tagged = tags.get("title", "")
    # A title tag that's just the file name again says nothing new.
    if tagged and slugged(tagged) != slugged(stem):
        title = tagged
    artist = tagged_artist or artist
    shown = {k: tags[k] for k in ("title", "artist", "album", "genre", "comment", "date") if k in tags}
    return {"fileTitle": title, "fileArtist": artist, "genre": tags.get("genre", ""),
            "fileTags": shown, "pixabayId": m["id"] if m else None}
