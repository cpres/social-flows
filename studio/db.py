"""
The studio's library: one SQLite file at ~/Footage/.studio/studio.db.

    media       every clip and photo found in ~/Footage/<shoot>/
    reels       a reel concept and its render settings
    reel_items  a part of a media file used in a reel (start + length).
                One file can appear in many reels, or several times in one.

Files are never moved or copied. Each media row remembers size and capture
time, so a file that is renamed or moved to another shoot folder is relinked
instead of dropping out of its reels.
"""

import json
import sqlite3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import montage  # the engine; reused for its file-type lists

SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
    id          INTEGER PRIMARY KEY,
    path        TEXT UNIQUE NOT NULL,   -- relative to the footage root
    folder      TEXT NOT NULL,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,          -- video | photo
    size        INTEGER NOT NULL,
    mtime       REAL NOT NULL,
    captured_at REAL NOT NULL,
    duration    REAL NOT NULL DEFAULT 0,
    width       INTEGER NOT NULL DEFAULT 0,   -- as viewed, rotation applied
    height      INTEGER NOT NULL DEFAULT 0,
    missing     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS media_folder ON media(folder);
CREATE INDEX IF NOT EXISTS media_fingerprint ON media(size, captured_at);

CREATE TABLE IF NOT EXISTS reels (
    id         INTEGER PRIMARY KEY,
    name       TEXT UNIQUE NOT NULL,
    settings   TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS reel_items (
    id       INTEGER PRIMARY KEY,
    reel_id  INTEGER NOT NULL REFERENCES reels(id) ON DELETE CASCADE,
    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    position REAL NOT NULL,
    start    REAL NOT NULL DEFAULT 0,
    length   REAL NOT NULL,
    keep     INTEGER NOT NULL DEFAULT 1,
    focus_x  REAL NOT NULL DEFAULT 0.5,     -- where the 9:16 window sits in the frame
    focus_y  REAL NOT NULL DEFAULT 0.5,     -- (0 = left/top, 1 = right/bottom)
    transition TEXT NOT NULL DEFAULT '',    -- into the next part; '' = reel default
    lighten  REAL NOT NULL DEFAULT 0,       -- 0..1, lifts shadows and midtones
    beats    INTEGER NOT NULL DEFAULT 0     -- with beat sync: beats long; 0 = reel default
);
CREATE INDEX IF NOT EXISTS items_reel ON reel_items(reel_id, position);
CREATE INDEX IF NOT EXISTS items_media ON reel_items(media_id);
"""

DEFAULT_SETTINGS = {
    "defaultLength": 2.0,   # seconds per video cut
    "defaultHold": 1.6,     # seconds per photo
    "music": "",            # a track on the music shelf (or a path)
    "musicStart": 0.0,      # where in the song the reel starts (seconds)
    "musicVolume": 0.8,
    "musicInVideo": True,   # False: cut to the song but leave it out (add it in Instagram)
    "beatSync": False,      # when on, parts are whole beats long
    "beatsPerCut": 4,       # default beats per part
    "fit": "fill",
    "transition": "cut",    # between parts, unless a part picks its own
    "originalAudio": False,  # glasses audio off unless a reel turns it on
    "originalVolume": 0.35,
}


class Library:
    def __init__(self, root):
        self.root = Path(root)
        self.home = self.root / ".studio"
        self.path = self.home / "studio.db"
        if self.root.is_dir():
            self.home.mkdir(exist_ok=True)
            with self.connect() as db:
                db.executescript(SCHEMA)
                migrate(db)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
            db.commit()
        finally:
            db.close()

    # ------------------------------------------------------------ scanning

    @staticmethod
    def kind_of(path):
        ext = path.suffix.lower()
        if ext in montage.VIDEO_EXTS:
            return "video"
        if ext in montage.IMAGE_EXTS:
            return "photo"
        return None

    def shoot_folders(self):
        if not self.root.is_dir():
            return []
        return [d for d in self.root.iterdir() if d.is_dir() and not d.name.startswith(".")]

    def media_files(self, folder):
        return [p for p in folder.iterdir()
                if p.is_file() and not p.name.startswith(".") and self.kind_of(p)]

    def scan(self, folders=None):
        """Bring the media table in line with what's on disk.

        Only new or changed files are probed. A file that vanished from one
        place and appears in another (same size and capture time) keeps its
        id, so its reel items follow it.
        """
        folders = self.shoot_folders() if folders is None else folders
        with self.connect() as db:
            known = {r["path"]: r for r in db.execute("SELECT * FROM media")}
            on_disk = {}
            for folder in folders:
                for p in self.media_files(folder):
                    on_disk[p.relative_to(self.root).as_posix()] = p

            todo = []
            for rel, p in on_disk.items():
                st = p.stat()
                row = known.get(rel)
                if (row and row["size"] == st.st_size and row["mtime"] == st.st_mtime
                        and row["width"]):
                    if row["missing"]:
                        db.execute("UPDATE media SET missing = 0 WHERE id = ?", (row["id"],))
                    continue
                todo.append((rel, p, st))

            with ThreadPoolExecutor(max_workers=8) as pool:
                probed = list(pool.map(lambda t: probe(t[1]), todo))

            for (rel, p, st), info in zip(todo, probed):
                values = dict(path=rel, folder=p.parent.name, name=p.name, kind=self.kind_of(p),
                              size=st.st_size, mtime=st.st_mtime, **info)
                if rel in known:
                    db.execute("""UPDATE media SET size=:size, mtime=:mtime, captured_at=:captured_at,
                                  duration=:duration, width=:width, height=:height, missing=0
                                  WHERE path=:path""", values)
                    continue
                moved = self._moved_from(db, values, on_disk)
                if moved:
                    db.execute("""UPDATE media SET path=:path, folder=:folder, name=:name,
                                  mtime=:mtime, width=:width, height=:height, missing=0
                                  WHERE id=:id""", {**values, "id": moved})
                else:
                    db.execute("""INSERT INTO media (path, folder, name, kind, size, mtime,
                                  captured_at, duration, width, height)
                                  VALUES (:path, :folder, :name, :kind, :size, :mtime,
                                  :captured_at, :duration, :width, :height)""", values)

            # Anything we used to know in these folders that's gone is missing.
            names = {f.name for f in folders}
            for rel, row in known.items():
                if row["folder"] in names and rel not in on_disk and not row["missing"]:
                    if not (self.root / rel).exists():
                        db.execute("UPDATE media SET missing = 1 WHERE id = ?", (row["id"],))

    def _moved_from(self, db, values, on_disk):
        for row in db.execute("SELECT id, path FROM media WHERE size = ? AND kind = ? "
                              "AND abs(captured_at - ?) < 0.001",
                              (values["size"], values["kind"], values["captured_at"])):
            if row["path"] not in on_disk and not (self.root / row["path"]).exists():
                return row["id"]
        return None

    def original_of(self, db, media_id):
        """For a file that's a copy of one in another folder, the original's id."""
        m = db.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
        row = db.execute("""SELECT id FROM media WHERE id != ? AND folder != ? AND size = ?
                            AND kind = ? AND abs(captured_at - ?) < 0.001 AND missing = 0
                            ORDER BY id LIMIT 1""",
                         (m["id"], m["folder"], m["size"], m["kind"], m["captured_at"])).fetchone()
        return row["id"] if row else media_id


def migrate(db):
    """Add columns introduced after a library was first created."""
    have = {t: {r["name"] for r in db.execute(f"PRAGMA table_info({t})")}
            for t in ("media", "reel_items")}
    for table, col, decl in [("media", "width", "INTEGER NOT NULL DEFAULT 0"),
                             ("media", "height", "INTEGER NOT NULL DEFAULT 0"),
                             ("reel_items", "focus_x", "REAL NOT NULL DEFAULT 0.5"),
                             ("reel_items", "focus_y", "REAL NOT NULL DEFAULT 0.5"),
                             ("reel_items", "transition", "TEXT NOT NULL DEFAULT ''"),
                             ("reel_items", "lighten", "REAL NOT NULL DEFAULT 0"),
                             ("reel_items", "beats", "INTEGER NOT NULL DEFAULT 0")]:
        if col not in have[table]:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def probe(path):
    """Duration, capture time and on-screen size in one ffprobe call.

    Phones often store portrait video as sideways pixels plus a rotation
    flag; width/height here are as it's actually seen.
    """
    info = {"duration": 0.0, "captured_at": None, "width": 0, "height": 0}
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "format=duration:format_tags=creation_time:stream=width,height"
             ":stream_tags=rotate:stream_side_data=rotation",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30).stdout
        data = json.loads(out or "{}")
        fmt = data.get("format", {})
        if Library.kind_of(path) == "video":
            info["duration"] = round(float(fmt.get("duration") or 0), 3)
        stamp = (fmt.get("tags") or {}).get("creation_time")
        if stamp:
            info["captured_at"] = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
        stream = (data.get("streams") or [{}])[0]
        w, h = int(stream.get("width") or 0), int(stream.get("height") or 0)
        rotation = (stream.get("tags") or {}).get("rotate")
        for sd in stream.get("side_data_list") or []:
            if "rotation" in sd:
                rotation = sd["rotation"]
        if rotation is not None and abs(int(float(rotation))) % 180 == 90:
            w, h = h, w
        info["width"], info["height"] = w, h
    except Exception:
        pass
    info["captured_at"] = info["captured_at"] or path.stat().st_mtime
    return info


def default_start(duration, length):
    """Same rule the engine uses for folder sources: 30% in, not in the first 2s."""
    if duration <= 0:
        return 0.0
    start = duration * 0.3
    start = max(min(start, duration - 0.5), min(2.0, duration / 3))
    return round(max(0.0, min(start, duration - length)), 2)


def now():
    return time.time()


def settings_of(row):
    return {**DEFAULT_SETTINGS, **json.loads(row["settings"] or "{}")}
