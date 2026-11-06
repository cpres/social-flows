"""
The studio's library: one SQLite file at ~/Footage/.studio/studio.db.

    media       every clip and photo found in ~/Footage/<shoot>/
    reels       a reel concept and its render settings
    reel_items  a part of a media file used in a reel (start + length).
                One file can appear in many reels, or several times in one.
    picks       the part of a file picked in its shoot before it's in any
                reel (start, length, framing): where it starts out when it's
                added to a reel, woven, or opened again
    weave_drafts  the Weave wizard's progress, one per shoot (or per reel
                being re-woven), until it's made into a reel
    songs       a name, artist and categories given to a song in the music
                folder (by file name), over what the file itself says

Files are only moved when asked (Import, Move files). Each media row remembers size and capture
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
    updated_at REAL NOT NULL,
    archived_at REAL            -- set: put away, off the home page (kept, not deleted)
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
    beats    INTEGER NOT NULL DEFAULT 0,    -- with beat sync: beats long (½, ¼ too); 0 = reel default
    zoom     REAL NOT NULL DEFAULT 1,       -- >1 crops tighter than the full 9:16 window
    layout   TEXT NOT NULL DEFAULT '',      -- fill | blur; '' = the reel's framing
    pane     TEXT NOT NULL DEFAULT '',      -- Stack: solo = fills the frame on its own; '' = split
    top_after REAL NOT NULL DEFAULT 0,      -- (before scenes) then the top clip alone for this many beats
    frames   TEXT                           -- framing per slot shape, JSON {half: {x, y, zoom}, square: ...};
                                            -- NULL: parts from before slots, one framing everywhere
);
CREATE INDEX IF NOT EXISTS items_reel ON reel_items(reel_id, position);
CREATE INDEX IF NOT EXISTS items_media ON reel_items(media_id);

CREATE TABLE IF NOT EXISTS picks (
    media_id   INTEGER PRIMARY KEY REFERENCES media(id) ON DELETE CASCADE,
    start      REAL NOT NULL DEFAULT 0,
    length     REAL NOT NULL,
    focus_x    REAL NOT NULL DEFAULT 0.5,
    focus_y    REAL NOT NULL DEFAULT 0.5,
    zoom       REAL NOT NULL DEFAULT 1,
    layout     TEXT NOT NULL DEFAULT '',   -- fill | blur; '' = the reel's framing
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS weave_drafts (
    key        TEXT PRIMARY KEY,   -- 'shoot:<folder>' (new weave) or 'reel:<id>' (re-weave)
    folder     TEXT NOT NULL,
    reel_id    INTEGER REFERENCES reels(id) ON DELETE CASCADE,
    state      TEXT NOT NULL,      -- the Weave wizard's choices, as JSON
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS songs (
    name       TEXT PRIMARY KEY,   -- the file's name in the music folder
    title      TEXT,               -- NULL: what the file says
    artist     TEXT,
    categories TEXT                -- a JSON list; NULL: the file's genre
);
"""

DEFAULT_SETTINGS = {
    "defaultLength": 2.0,   # seconds per video cut
    "defaultHold": 1.6,     # seconds per photo
    "music": "",            # a track on the music shelf (or a path)
    "musicStart": 0.0,      # where in the song the reel starts (seconds)
    "musicVolume": 0.8,
    "musicInVideo": True,   # False: cut to the song but leave it out (add it in Instagram)
    "beatSync": False,      # when on, parts are whole beats long
    "beatsPerCut": 4,       # beats per part when beatsFit is "fixed"
    "beatsFit": "nearest",  # parts without their own beats: the whole beats nearest their length
    "fit": "fill",
    "look": "",             # the reel's look on every clip: "" (as shot) | vivid | rich
    "shape": "tall",        # tall (9:16) | wide (16:9, YouTube) | portrait (4:5) | square (1:1); a wide Stack is side by side
    "transition": "cut",    # between parts, unless a part picks its own
    "originalAudio": False,  # glasses audio off unless a reel turns it on
    "originalVolume": 0.35,
    # Lanes and scenes (see scenes.py): laneA lists the parts that are lane A,
    # scenes what's on screen when. None: worked out from the settings below
    # (from before scenes) when the reel is opened.
    "laneA": None,
    "scenes": None,
    # Before scenes, a Stack reel: one clip (a timelapse, say) in the top pane
    # for the whole reel while the parts play one after another underneath.
    "format": "standard",   # standard | stack
    "topItemId": None,      # the reel_items row pinned on top; still a normal row
    "stackSplit": 0.5,      # the top pane's share of the height
    "dividerPx": 4,         # the line between the panes (0 = none)
    "dividerColor": "#f7f1e3",
    "fitTop": True,         # make the top clip end with the parts underneath...
    "fitTopBy": "speed",    # ... by speeding it up or slowing it down | by cutting out its quiet stretches (quiet)
    "topSpeed": 1.0,        # with fit off: the top clip's own speed (2 = twice as fast)
    "stackIntro": 0,        # beats the top clip plays alone before the parts come in (0 = split from the start)
    # A part can fill the frame on its own (pane: solo) and be followed by the
    # top clip alone for a few beats (top_after); the panes slide between.
    # In a wide (16:9) reel the panes are side by side.
    # A reel made with Weave: the shoot it came from, its clips in order and the
    # pace, so the wizard can reopen it ({folder, clips, splitOver, between, ...}).
    "weave": None,
    # Text over the opening shots and a card over the last ones: a dark,
    # see-through layer with cream text. Logos come from brand/ in the repo.
    "titleText": "",        # e.g. "3rd Sundays" ('' = no title)
    "titleSub": "",         # e.g. "October Edition"
    "titleLogo": "",        # '' | oufp | garden-steward | both
    "endCard": False,
    "endLines": "",         # one line each; the first is the big one
    "endLogo": "oufp",
    "endPresentedBy": "garden-steward",   # "presented by" + this logo, small, underneath
    "endBeats": 4,          # how much longer the last part holds for the card
    # A voice track: a reading laid over the footage, made of pieces of takes
    # (audio files or videos in the shoot folders), one after another. Each
    # piece: {id, folder, file, start, end (in the take), gap (the breath
    # before it), lines: [{s, e, text, br (a stanza starts here), words}],
    # fx: [{id, s, e, effect, amount}]: a phrase (in the take) played through
    # echo | hall | waver | pulse | doubled, amount 0.6 / 1 / 1.4}.
    "voice": [],
    "voiceFit": True,       # the last part holds until the voice has finished
    "voiceClean": True,     # cut low rumble and hiss
    "voiceSongUnder": 0.15, # the song's volume while the voice speaks
    "voiceSongBetween": 0.3,  # ... and around it
    # Captions: the voice's lines on screen as they're said.
    "captions": True,
    "captionStyle": "breath",   # stanza | unfold | breath | page
    "captionFont": "cormorant-italic",
    "captionBg": "shadow",      # scrim | band | paper | blur | shadow
    "captionSize": 1.0,
    "captionTitle": "",         # Page: a small title over the words
    "captionFx": True,          # words with a voice effect show it too
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
            for t in ("media", "reel_items", "reels")}
    for table, col, decl in [("media", "width", "INTEGER NOT NULL DEFAULT 0"),
                             ("media", "height", "INTEGER NOT NULL DEFAULT 0"),
                             ("reel_items", "focus_x", "REAL NOT NULL DEFAULT 0.5"),
                             ("reel_items", "focus_y", "REAL NOT NULL DEFAULT 0.5"),
                             ("reel_items", "transition", "TEXT NOT NULL DEFAULT ''"),
                             ("reel_items", "lighten", "REAL NOT NULL DEFAULT 0"),
                             ("reel_items", "beats", "INTEGER NOT NULL DEFAULT 0"),
                             ("reel_items", "zoom", "REAL NOT NULL DEFAULT 1"),
                             ("reel_items", "layout", "TEXT NOT NULL DEFAULT ''"),
                             ("reel_items", "pane", "TEXT NOT NULL DEFAULT ''"),
                             ("reel_items", "top_after", "REAL NOT NULL DEFAULT 0"),
                             ("reel_items", "frames", "TEXT"),
                             ("reels", "archived_at", "REAL")]:
        if col not in have[table]:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    # v1: photo sizes now honour EXIF rotation; re-measure photos once.
    if db.execute("PRAGMA user_version").fetchone()[0] < 1:
        db.execute("UPDATE media SET width = 0 WHERE kind = 'photo'")
        db.execute("PRAGMA user_version = 1")
    # v2: "on top" was a per-part layout; it's now the reel's Stack format.
    if db.execute("PRAGMA user_version").fetchone()[0] < 2:
        for row in db.execute("SELECT id, reel_id FROM reel_items WHERE layout = 'stack' "
                              "ORDER BY position DESC").fetchall():
            reel = db.execute("SELECT settings FROM reels WHERE id = ?", (row["reel_id"],)).fetchone()
            s = {**json.loads(reel["settings"] or "{}"), "format": "stack", "topItemId": row["id"]}
            db.execute("UPDATE reels SET settings = ? WHERE id = ?", (json.dumps(s), row["reel_id"]))
        db.execute("UPDATE reel_items SET layout = '' WHERE layout = 'stack'")
        db.execute("PRAGMA user_version = 2")
    # v3: lane A plays at real speed unless a speed is picked; scenes that
    # were fitted by speed (the default until now) play at real speed.
    if db.execute("PRAGMA user_version").fetchone()[0] < 3:
        for row in db.execute("SELECT id, settings FROM reels").fetchall():
            s = json.loads(row["settings"] or "{}")
            changed = False
            for sc in s.get("scenes") or []:
                a = sc.get("a") if isinstance(sc, dict) else None
                if isinstance(a, dict) and a.get("timing") in ("fit", "range", None):
                    a["timing"] = "real"
                    a["out"] = None
                    changed = True
            if changed:
                db.execute("UPDATE reels SET settings = ? WHERE id = ?", (json.dumps(s), row["id"]))
        db.execute("PRAGMA user_version = 3")


def photo_rotation(path):
    """A phone photo's EXIF orientation, as degrees. ffprobe only reports it
    on the decoded frame, not the stream, but ffmpeg (thumbnails, render)
    applies it, so the size we store has to as well."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
             "-read_intervals", "%+#1", "-show_entries", "frame_side_data=rotation:frame_tags=Orientation",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30).stdout
        frame = (json.loads(out or "{}").get("frames") or [{}])[0]
        for sd in frame.get("side_data_list") or []:
            if "rotation" in sd:
                return sd["rotation"]
        orient = str((frame.get("tags") or {}).get("Orientation", "")).strip()
        if orient in ("5", "6", "7", "8"):   # EXIF: the four sideways orientations
            return 90
    except Exception:
        pass
    return None


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
        if rotation is None and Library.kind_of(path) == "photo":
            rotation = photo_rotation(path)
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
