"""
The music shelf: tracks in ~/Music/Reels (MUSIC_DIR), and their beats.

Beats are detected once per track with librosa and cached as JSON under
~/Footage/.studio/music/. The engine reads that same file (`beat_file:`), so
the studio's preview and the render cut on exactly the same beats.
"""

import hashlib
import json
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

    def tracks(self):
        if not self.folder.is_dir():
            return []
        out = []
        for p in sorted(self.folder.iterdir(), key=lambda q: q.name.lower()):
            if p.is_file() and p.suffix.lower() in AUDIO_EXTS and not p.name.startswith("."):
                cached = self.cached(p)
                out.append({"name": p.name, "duration": duration(p),
                            "bpm": cached["bpm"] if cached else None})
        return out

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


def duration(path):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=20).stdout
        return round(float(out.strip() or 0), 2)
    except Exception:
        return 0.0
