#!/usr/bin/env python3
"""
Footage Studio — a small local server for browsing ~/Footage and building
reels out of parts of clips and photos.

Shoot folders stay as they are. Reels, and which part of which file each one
uses, live in ~/Footage/.studio/studio.db (see db.py). Exporting a reel writes
~/Footage/.studio/reels/<reel>.yaml, which montage.py renders on its own.

    ./studio/run.sh        # sets up on first run, then http://localhost:3009

FOOTAGE_DIR overrides the footage root (default ~/Footage).
RENDER_DIR sets where rendered videos go (default ~/Movies/Footage Studio).
DOWNLOADS_DIR is where AirDrop drops things, for Import (default ~/Downloads).
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

if sys.version_info < (3, 9):
    sys.exit(f"Footage Studio needs Python 3.9+ (this is {sys.version.split()[0]}).\n\n"
             f"Start it with  ./studio/run.sh  (it finds a newer Python), or install one:\n"
             f"  brew install python@3.12")

try:
    import uvicorn
    import yaml
    from fastapi import Body, FastAPI, HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
except ImportError as missing:
    sys.exit(f"Missing Python package: {missing.name}\n\n"
             f"Start the studio with  ./studio/run.sh  (it sets everything up), or:\n"
             f"  python3 -m venv .venv && source .venv/bin/activate\n"
             f"  pip install -r studio/requirements.txt")

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent / "montage" / "montage.py"
sys.path.insert(0, str(ENGINE.parent))
sys.path.insert(0, str(HERE))
from db import DEFAULT_SETTINGS, Library, default_start, now, settings_of  # noqa: E402
from music import Shelf, beat_detection_available  # noqa: E402
from share import Shares  # noqa: E402

ROOT = Path(os.environ.get("FOOTAGE_DIR", "~/Footage")).expanduser().resolve()
RENDERS = Path(os.environ.get("RENDER_DIR", "~/Movies/Footage Studio")).expanduser()
CACHE = Path("~/.cache/footage-studio").expanduser()
DOWNLOADS = Path(os.environ.get("DOWNLOADS_DIR", "~/Downloads")).expanduser().resolve()
SIDECAR = ".studio.json"
# What a part can lead into the next with ('' = the reel's default).
TRANSITIONS = ("", "cut", "flash", "whip", "zoom", "dissolve", "dip")   # per-folder trims from the first version of the studio

lib = Library(ROOT)
shelf = Shelf(os.environ.get("MUSIC_DIR", "~/Music/Reels"), lib.home / "music")
shares = Shares(port=int(os.environ.get("SHARE_PORT", 3010)),
                ttl=int(os.environ.get("SHARE_TTL", 3600)))
ITEM_COLUMNS = ("media_id", "position", "start", "length", "keep", "focus_x", "focus_y",
                "transition", "lighten", "beats", "zoom", "layout")
LAYOUTS = ("", "fill", "blur")   # per part; '' = the reel's framing
FORMATS = ("standard", "stack")
app = FastAPI(title="Footage Studio")


# ---------------------------------------------------------------- helpers

def resolve(*parts):
    """Resolve a path under ROOT, refusing anything that escapes it."""
    path = ROOT.joinpath(*parts).resolve()
    if path != ROOT and ROOT not in path.parents:
        raise HTTPException(404)
    if not path.exists():
        raise HTTPException(404, f"Not found: {'/'.join(parts)}")
    return path


def media_dict(row):
    return {"id": row["id"], "folder": row["folder"], "file": row["name"], "kind": row["kind"],
            "duration": row["duration"], "capturedAt": row["captured_at"],
            "width": row["width"], "height": row["height"], "missing": bool(row["missing"])}


def item_dict(row):
    return {"id": row["item_id"], "reelId": row["reel_id"], "mediaId": row["media_id"],
            "position": row["position"], "start": row["start"], "length": row["length"],
            "keep": bool(row["keep"]), "focusX": row["focus_x"], "focusY": row["focus_y"],
            "transition": row["transition"], "lighten": row["lighten"], "beats": row["beats"],
            "zoom": row["zoom"], "layout": row["layout"]}


def top_item(db, reel_id, s):
    """A Stack reel's top clip: its pinned row, if that's still a video here."""
    if s.get("format") != "stack" or not s.get("topItemId"):
        return None
    return db.execute("""SELECT i.id FROM reel_items i JOIN media m ON m.id = i.media_id
                         WHERE i.id = ? AND i.reel_id = ? AND m.kind = 'video'""",
                      (s["topItemId"], reel_id)).fetchone()


def clean_settings(db, reel_id, s):
    """Keep the Stack settings in range."""
    if s.get("format") not in FORMATS:
        raise HTTPException(400, f"Unknown format: {s.get('format')}")
    s["stackSplit"] = round(min(max(float(s.get("stackSplit") or 0.5), 0.3), 0.7), 3)
    s["dividerPx"] = min(max(int(round(float(s.get("dividerPx") or 0) / 2)) * 2, 0), 20)
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(s.get("dividerColor") or "")):
        s["dividerColor"] = DEFAULT_SETTINGS["dividerColor"]
    s["fitTop"] = bool(s.get("fitTop"))
    if s.get("topItemId") is not None:
        s["topItemId"] = int(s["topItemId"])
        if not top_item(db, reel_id, {**s, "format": "stack"}):
            s["topItemId"] = None   # removed, or not a video in this reel
    return s


def reel_row(db, reel_id):
    row = db.execute("SELECT * FROM reels WHERE id = ?", (reel_id,)).fetchone()
    if not row:
        raise HTTPException(404, "No such reel")
    return row


def touch(db, reel_id):
    db.execute("UPDATE reels SET updated_at = ? WHERE id = ?", (now(), reel_id))


def fit(start, length, duration):
    """Keep a part inside its clip: at least 0.2s, never past the end."""
    if duration <= 0:
        return max(0.0, start), max(0.2, length)
    length = min(max(0.2, length), duration)
    start = min(max(0.0, start), duration - length)
    return round(start, 3), round(length, 3)


def zoom_of(v):
    return round(min(max(float(v or 1), 1.0), 3.0), 3)


def unit(v):
    return round(min(max(float(v), 0.0), 1.0), 4)


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "reel"


def reel_summaries(db):
    rows = db.execute("""
        SELECT r.*, COUNT(i.id) AS items,
               COALESCE(SUM(CASE WHEN i.keep THEN i.length ELSE 0 END), 0) AS total
        FROM reels r LEFT JOIN reel_items i ON i.reel_id = r.id
        GROUP BY r.id ORDER BY r.updated_at DESC""").fetchall()
    out = []
    for r in rows:
        cover = db.execute("""
            SELECT m.folder, m.name, m.kind, i.start FROM reel_items i
            JOIN media m ON m.id = i.media_id
            WHERE i.reel_id = ? AND m.missing = 0 ORDER BY i.position LIMIT 1""",
                           (r["id"],)).fetchone()
        out.append({"id": r["id"], "name": r["name"], "itemCount": r["items"],
                    "totalLength": round(r["total"], 2), "updatedAt": r["updated_at"],
                    "cover": dict(cover) if cover else None})
    return out


# ---------------------------------------------------------------- shoots

@app.get("/api/folders")
def list_folders():
    if not ROOT.is_dir():
        return {"root": str(ROOT), "folders": [], "reels": [],
                "error": f"{ROOT} does not exist"}
    lib.scan()
    folders = []
    with lib.connect() as db:
        for d in lib.shoot_folders():
            rows = db.execute("SELECT * FROM media WHERE folder = ? AND missing = 0 "
                              "ORDER BY captured_at", (d.name,)).fetchall()
            videos = [r for r in rows if r["kind"] == "video"]
            cover = videos[0] if videos else (rows[0] if rows else None)
            used = db.execute("""SELECT COUNT(DISTINCT i.media_id) FROM reel_items i
                                 JOIN media m ON m.id = i.media_id WHERE m.folder = ?""",
                              (d.name,)).fetchone()[0]
            folders.append({
                "name": d.name,
                "clipCount": len(videos),
                "photoCount": len(rows) - len(videos),
                "totalDuration": round(sum(r["duration"] for r in videos), 1),
                "lastModified": d.stat().st_mtime,
                "cover": cover["name"] if cover else None,
                "coverTime": round(cover["duration"] * 0.3, 2) if cover else 0,
                "usedCount": used,
            })
        reels = reel_summaries(db)
    # Newest shoot first: date-named folders by name, the rest by last change.
    folders.sort(key=lambda f: (f["name"][:10] if f["name"][:4].isdigit() else "",
                                f["lastModified"]), reverse=True)
    return {"root": str(ROOT), "folders": folders, "reels": reels}


@app.get("/api/folders/{name}")
def get_folder(name: str):
    folder = resolve(name)
    lib.scan([folder])
    with lib.connect() as db:
        media = [media_dict(r) for r in db.execute(
            "SELECT * FROM media WHERE folder = ? AND missing = 0 ORDER BY captured_at", (name,))]
        items = [item_dict(r) for r in db.execute("""
            SELECT i.id AS item_id, i.* FROM reel_items i JOIN media m ON m.id = i.media_id
            WHERE m.folder = ? ORDER BY i.start""", (name,))]
        reels = reel_summaries(db)
    return {"name": name, "path": str(folder), "media": media, "items": items, "reels": reels,
            "hasSidecar": (folder / SIDECAR).exists()}


@app.post("/api/folders/{name}/to-reel")
def folder_to_reel(name: str, body: dict = Body(default={})):
    """Make a reel from a folder: its old studio trims if any, else every file.

    Files that are copies of originals in another shoot folder point at the
    original, so per-concept folders of copied files can be retired.
    """
    folder = resolve(name)
    lib.scan()
    side = {}
    if (folder / SIDECAR).exists():
        try:
            side = json.loads((folder / SIDECAR).read_text())
        except ValueError:
            side = {}
    saved = side.get("clips", {})
    settings = {**DEFAULT_SETTINGS, **side.get("settings", {})}
    reel_name = (body.get("name") or name).strip()
    with lib.connect() as db:
        if db.execute("SELECT 1 FROM reels WHERE name = ?", (reel_name,)).fetchone():
            raise HTTPException(409, f"A reel called '{reel_name}' already exists")
        cur = db.execute("INSERT INTO reels (name, settings, created_at, updated_at) "
                         "VALUES (?, ?, ?, ?)", (reel_name, json.dumps(settings), now(), now()))
        reel_id = cur.lastrowid
        rows = db.execute("SELECT * FROM media WHERE folder = ? AND missing = 0 "
                          "ORDER BY captured_at", (name,)).fetchall()
        for pos, m in enumerate(rows):
            s = saved.get(m["name"], {})
            if not s.get("keep", True):
                continue
            if m["kind"] == "video":
                length = float(s.get("length", min(settings["defaultLength"], m["duration"])))
                start = float(s.get("start", default_start(m["duration"], length)))
            else:
                length, start = float(s.get("length", settings["defaultHold"])), 0.0
            db.execute("INSERT INTO reel_items (reel_id, media_id, position, start, length) "
                       "VALUES (?, ?, ?, ?, ?)",
                       (reel_id, lib.original_of(db, m["id"]), pos, start, length))
    return {"id": reel_id}


# ---------------------------------------------------------------- reels

@app.get("/api/reels")
def list_reels():
    with lib.connect() as db:
        return reel_summaries(db)


@app.post("/api/reels")
def create_reel(body: dict = Body(...)):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "A reel needs a name")
    with lib.connect() as db:
        if db.execute("SELECT 1 FROM reels WHERE name = ?", (name,)).fetchone():
            raise HTTPException(409, f"A reel called '{name}' already exists")
        cur = db.execute("INSERT INTO reels (name, settings, created_at, updated_at) "
                         "VALUES (?, '{}', ?, ?)", (name, now(), now()))
        return {"id": cur.lastrowid, "name": name}


@app.get("/api/reels/{reel_id}")
def get_reel(reel_id: int):
    with lib.connect() as db:
        r = reel_row(db, reel_id)
        rows = db.execute("""
            SELECT i.id AS item_id, i.*, m.* FROM reel_items i JOIN media m ON m.id = i.media_id
            WHERE i.reel_id = ? ORDER BY i.position, i.id""", (reel_id,)).fetchall()
        items = [{**item_dict(row), "media": media_dict({**dict(row), "id": row["media_id"]})}
                 for row in rows]
        # Other reels' parts of the same files, to show alongside on the trim bar.
        others = [item_dict(row) for row in db.execute("""
            SELECT i.id AS item_id, i.* FROM reel_items i
            WHERE i.reel_id != ? AND i.media_id IN
                  (SELECT media_id FROM reel_items WHERE reel_id = ?)""", (reel_id, reel_id))]
        reels = reel_summaries(db)
        settings = settings_of(r)
        if settings["format"] == "stack" and not top_item(db, reel_id, settings):
            settings["topItemId"] = None   # its clip was removed: pick another
    return {"id": r["id"], "name": r["name"], "settings": settings, "items": items,
            "otherItems": others, "reels": reels}


@app.patch("/api/reels/{reel_id}")
def update_reel(reel_id: int, body: dict = Body(...)):
    with lib.connect() as db:
        r = reel_row(db, reel_id)
        if "name" in body:
            name = body["name"].strip()
            if not name:
                raise HTTPException(400, "A reel needs a name")
            clash = db.execute("SELECT 1 FROM reels WHERE name = ? AND id != ?",
                               (name, reel_id)).fetchone()
            if clash:
                raise HTTPException(409, f"A reel called '{name}' already exists")
            db.execute("UPDATE reels SET name = ? WHERE id = ?", (name, reel_id))
        if "settings" in body:
            settings = clean_settings(db, reel_id, {**settings_of(r), **body["settings"]})
            db.execute("UPDATE reels SET settings = ? WHERE id = ?", (json.dumps(settings), reel_id))
        touch(db, reel_id)
    return {"ok": True}


@app.delete("/api/reels/{reel_id}")
def delete_reel(reel_id: int):
    with lib.connect() as db:
        reel_row(db, reel_id)
        db.execute("DELETE FROM reels WHERE id = ?", (reel_id,))
    return {"ok": True}


@app.put("/api/reels/{reel_id}/order")
def reorder(reel_id: int, body: dict = Body(...)):
    with lib.connect() as db:
        reel_row(db, reel_id)
        for pos, item_id in enumerate(body.get("itemIds", [])):
            db.execute("UPDATE reel_items SET position = ? WHERE id = ? AND reel_id = ?",
                       (pos, item_id, reel_id))
        touch(db, reel_id)
    return {"ok": True}


# ---------------------------------------------------------------- items

@app.post("/api/reels/{reel_id}/items")
def add_item(reel_id: int, body: dict = Body(...)):
    with lib.connect() as db:
        r = reel_row(db, reel_id)
        s = settings_of(r)
        m = db.execute("SELECT * FROM media WHERE id = ?", (body.get("mediaId"),)).fetchone()
        if not m:
            raise HTTPException(404, "No such clip")
        if m["kind"] == "video":
            length = float(body.get("length") or min(s["defaultLength"], m["duration"]))
            start = body.get("start")
            start = float(start) if start is not None else default_start(m["duration"], length)
            start, length = fit(start, length, m["duration"])
        else:
            length, start = float(body.get("length") or s["defaultHold"]), 0.0
        fx, fy = unit(body.get("focusX", 0.5)), unit(body.get("focusY", 0.5))
        lighten = unit(body.get("lighten", 0))
        beats = max(0, min(int(body.get("beats") or 0), 64))
        zoom = zoom_of(body.get("zoom", 1))
        layout = body.get("layout") or ""
        if layout not in LAYOUTS:
            raise HTTPException(400, f"Unknown layout: {layout}")
        pos = db.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM reel_items "
                         "WHERE reel_id = ?", (reel_id,)).fetchone()[0]
        cur = db.execute("INSERT INTO reel_items (reel_id, media_id, position, start, length, "
                         "focus_x, focus_y, lighten, beats, zoom, layout) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (reel_id, m["id"], pos, start, length, fx, fy, lighten, beats, zoom, layout))
        touch(db, reel_id)
        row = db.execute("SELECT id AS item_id, * FROM reel_items WHERE id = ?",
                         (cur.lastrowid,)).fetchone()
        return item_dict(row)


@app.patch("/api/items/{item_id}")
def update_item(item_id: int, body: dict = Body(...)):
    fields = {k: body[k] for k in ("start", "length", "keep", "position") if k in body}
    if "transition" in body:
        if body["transition"] not in TRANSITIONS:
            raise HTTPException(400, f"Unknown transition: {body['transition']}")
        fields["transition"] = body["transition"]
    if "lighten" in body:
        fields["lighten"] = unit(body["lighten"])
    if "beats" in body:
        fields["beats"] = max(0, min(int(body["beats"]), 64))
    if "zoom" in body:
        fields["zoom"] = zoom_of(body["zoom"])
    if "layout" in body:
        if body["layout"] not in LAYOUTS:
            raise HTTPException(400, f"Unknown layout: {body['layout']}")
        fields["layout"] = body["layout"]
    for key, col in (("focusX", "focus_x"), ("focusY", "focus_y")):
        if key in body:
            fields[col] = unit(body[key])
    if not fields:
        return {"ok": True}
    with lib.connect() as db:
        row = db.execute("""SELECT i.reel_id, i.start, i.length, m.kind, m.duration
                            FROM reel_items i JOIN media m ON m.id = i.media_id
                            WHERE i.id = ?""", (item_id,)).fetchone()
        if not row:
            raise HTTPException(404, "No such item")
        if row["kind"] == "video" and ("start" in fields or "length" in fields):
            fields["start"], fields["length"] = fit(float(fields.get("start", row["start"])),
                                                    float(fields.get("length", row["length"])),
                                                    row["duration"])
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        db.execute(f"UPDATE reel_items SET {sets} WHERE id = :id", {**fields, "id": item_id})
        touch(db, row["reel_id"])
    return {"ok": True}


@app.delete("/api/items/{item_id}")
def delete_item(item_id: int):
    with lib.connect() as db:
        row = db.execute("SELECT reel_id FROM reel_items WHERE id = ?", (item_id,)).fetchone()
        if row:
            db.execute("DELETE FROM reel_items WHERE id = ?", (item_id,))
            touch(db, row["reel_id"])
    return {"ok": True}


# ---------------------------------------------------------------- duplicate

@app.post("/api/reels/{reel_id}/duplicate")
def duplicate_reel(reel_id: int, body: dict = Body(default={})):
    """A full copy of a reel (settings, parts, trims, framing) to experiment on."""
    with lib.connect() as db:
        r = reel_row(db, reel_id)
        name = (body.get("name") or "").strip()
        if not name:
            n = 1
            while True:
                name = f"{r['name']} (copy{'' if n == 1 else ' ' + str(n)})"
                if not db.execute("SELECT 1 FROM reels WHERE name = ?", (name,)).fetchone():
                    break
                n += 1
        elif db.execute("SELECT 1 FROM reels WHERE name = ?", (name,)).fetchone():
            raise HTTPException(409, f"A reel called '{name}' already exists")
        cur = db.execute("INSERT INTO reels (name, settings, created_at, updated_at) "
                         "VALUES (?, ?, ?, ?)", (name, r["settings"], now(), now()))
        new_id = cur.lastrowid
        cols = ", ".join(ITEM_COLUMNS)
        old = [row["id"] for row in db.execute(
            "SELECT id FROM reel_items WHERE reel_id = ? ORDER BY position, id", (reel_id,))]
        db.execute(f"INSERT INTO reel_items (reel_id, {cols}) "
                   f"SELECT ?, {cols} FROM reel_items WHERE reel_id = ? ORDER BY position, id",
                   (new_id, reel_id))
        # The copy's top clip is the copy of the original's.
        s = settings_of(r)
        if s.get("topItemId") in old:
            new = [row["id"] for row in db.execute(
                "SELECT id FROM reel_items WHERE reel_id = ? ORDER BY id", (new_id,))]
            s["topItemId"] = new[old.index(s["topItemId"])]
            db.execute("UPDATE reels SET settings = ? WHERE id = ?", (json.dumps(s), new_id))
    return {"id": new_id, "name": name}


# ---------------------------------------------------------------- music

@app.get("/api/music")
def music_shelf():
    return {"dir": str(shelf.folder), "exists": shelf.folder.is_dir(),
            "tracks": shelf.tracks(), "beatDetection": beat_detection_available()}


@app.get("/api/music/{name}/file")
def music_file(name: str):
    path = shelf.path_of(name)
    if not path or not path.exists() or path.parent != shelf.folder:
        raise HTTPException(404, "No such track")
    return FileResponse(path)


@app.get("/api/music/{name}/beats")
def music_beats(name: str):
    path = shelf.path_of(name)
    if not path or not path.exists() or path.parent != shelf.folder:
        raise HTTPException(404, "No such track")
    try:
        return shelf.analyze(path)
    except ImportError:
        raise HTTPException(503, "Beat detection isn't installed: start the studio "
                                 "with ./studio/run.sh --beat")


# ---------------------------------------------------------------- export

def build_config(reel, rows):
    s = settings_of(reel)
    # A Stack reel: the top clip plays in the top pane for the whole reel;
    # the kept parts play one after another underneath.
    top = None
    if s.get("format") == "stack":
        top = next((r for r in rows if r["id"] == s.get("topItemId") and r["kind"] == "video"), None)
        if not top or top["missing"]:
            raise HTTPException(400, "Pick a clip for the top of this Stack reel." if not top else
                                f"The top clip is missing: {top['path']}")
    kept = [r for r in rows if r["keep"] and not r["missing"] and r is not top]
    if top and not kept:
        raise HTTPException(400, "Add parts to play underneath the top clip.")
    track = shelf.path_of(s.get("music"))
    synced = bool(track and s.get("beatSync"))
    sources, seen = [], {}
    for n, row in enumerate(kept):
        stem = Path(row["name"]).stem[:14]
        seen[stem] = seen.get(stem, 0) + 1
        entry = {"id": stem if seen[stem] == 1 else f"{stem}-{seen[stem]}",
                 "file": str(ROOT / row["path"])}
        if (row["focus_x"], row["focus_y"]) != (0.5, 0.5):
            entry["focus"] = [round(row["focus_x"], 3), round(row["focus_y"], 3)]
        if row["lighten"]:
            entry["lighten"] = round(row["lighten"], 2)
        if row["zoom"] > 1.001:
            entry["zoom"] = round(row["zoom"], 3)
        if row["layout"] in ("fill", "blur"):
            entry["fit"] = row["layout"]
        if row["kind"] == "video":
            entry["times"] = [round(row["start"], 2)]
            entry["length"] = round(row["length"], 2)
        else:
            entry["hold"] = round(row["length"], 2)
            entry["in_round"] = "all"
        if synced:
            entry["hold_beats" if row["kind"] == "photo" else "beats"] = (
                row["beats"] or int(s.get("beatsPerCut", 4)))
        if n + 1 < len(kept):
            entry["transition"] = row["transition"] or s.get("transition") or "cut"
        sources.append(entry)

    cfg = {"output": str(RENDERS / f"{slug(reel['name'])}.mp4"), "rounds": 1, "sources": sources}
    if top:
        cfg["top"] = {"file": str(ROOT / top["path"]), "start": round(top["start"], 2),
                      "length": round(top["length"], 2)}
        if (top["focus_x"], top["focus_y"]) != (0.5, 0.5):
            cfg["top"]["focus"] = [round(top["focus_x"], 3), round(top["focus_y"], 3)]
        if top["zoom"] > 1.001:
            cfg["top"]["zoom"] = round(top["zoom"], 3)
        if top["lighten"]:
            cfg["top"]["lighten"] = round(top["lighten"], 2)
        cfg["stack"] = {"split": s["stackSplit"], "divider": s["dividerPx"],
                        "divider_color": s["dividerColor"], "fit": bool(s["fitTop"])}
    if track:
        if not track.exists():
            raise HTTPException(400, f"Music file not found: {track}")
        cfg["music"] = str(track)
        cfg["music_start"] = round(float(s.get("musicStart") or 0), 3)
        cfg["music_in_video"] = bool(s.get("musicInVideo", True))
        cfg["beat_sync"] = synced
        cfg["beats_per_cut"] = int(s.get("beatsPerCut", 4))
        cfg["music_volume"] = float(s.get("musicVolume", 0.8))
        cfg["music_fade_out"] = 2.0
        if synced:
            try:
                shelf.analyze(track)
                cfg["beat_file"] = str(shelf.cache_file(track))
            except ImportError:
                raise HTTPException(400, "Cutting on the beat needs beat detection: "
                                         "start the studio with ./studio/run.sh --beat")
    cfg.update({
        "clip_length": s["defaultLength"],
        "transitions": {"within_round": "cut", "between_rounds": "dissolve",
                        "into_image": "dissolve", "out_of_image": "dissolve",
                        "duration": 0.3},
        "original_audio": bool(s.get("originalAudio")),
        "original_volume": s.get("originalVolume", 0.35),
        "fit": s.get("fit", "fill"),
        "photo_motion": "push",
        "photo_zoom": 0.06,
        "crf": 18,
        "preset": "veryfast",
    })
    return cfg


def write_config(reel_id):
    """Write the reel's YAML for the engine; returns (path, config)."""
    with lib.connect() as db:
        reel = reel_row(db, reel_id)
        rows = db.execute("""SELECT i.*, m.path, m.name, m.kind, m.missing FROM reel_items i
                             JOIN media m ON m.id = i.media_id
                             WHERE i.reel_id = ? ORDER BY i.position, i.id""",
                          (reel_id,)).fetchall()
    cfg = build_config(reel, rows)
    if not cfg["sources"]:
        raise HTTPException(400, "Nothing is kept in this reel yet.")
    out_dir = lib.home / "reels"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{slug(reel['name'])}.yaml"
    header = (f"# Generated by Footage Studio for the reel '{reel['name']}' on "
              f"{datetime.now():%Y-%m-%d %H:%M}.\n"
              f"# Edit the reel in the studio; hand edits here are overwritten on export.\n\n")
    out.write_text(header + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    return out, cfg


@app.post("/api/reels/{reel_id}/export")
def export(reel_id: int):
    out, cfg = write_config(reel_id)
    result = subprocess.run([sys.executable, str(ENGINE), str(out), "--dry-run"],
                            capture_output=True, text=True, timeout=300)
    return {"path": str(out), "ok": result.returncode == 0,
            "dryRun": (result.stdout + result.stderr).strip(),
            "output": cfg["output"],
            "command": f'python3 "{ENGINE}" "{out}"'}


# ---------------------------------------------------------------- render

# One render at a time per reel, run in the background; the page polls.
jobs = {}           # job id -> job dict
latest = {}         # reel id -> job id
jobs_lock = threading.Lock()


def job_view(job):
    return {k: job.get(k) for k in ("id", "reelId", "status", "stage", "done", "total",
                                    "output", "startedAt", "finishedAt", "log", "note")}


def run_render(job, config_path):
    proc = subprocess.Popen([sys.executable, "-u", str(ENGINE), str(config_path)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    buf = b""
    while True:
        chunk = proc.stdout.read(256)
        if not chunk:
            break
        buf += chunk
        # The engine redraws its progress line with \r.
        *lines, buf = re.split(rb"[\r\n]", buf)
        for raw in lines:
            line = raw.decode(errors="replace").strip()
            if not line:
                continue
            m = re.match(r"cutting (\d+)/(\d+)", line)
            if m:
                job["stage"], job["done"], job["total"] = "cutting", int(m[1]), int(m[2])
            elif line.startswith("joining"):
                job["stage"] = "joining"
            elif line.startswith("mixing"):
                job["stage"] = "mixing"
            elif line.startswith("Song left out"):
                job["note"] = line
            else:
                job["log"] = (job["log"] + [line])[-60:]
    proc.wait()
    job["status"] = "done" if proc.returncode == 0 and Path(job["output"]).exists() else "failed"
    job["stage"] = job["status"]
    job["finishedAt"] = now()


@app.post("/api/reels/{reel_id}/render")
def start_render(reel_id: int):
    with jobs_lock:
        current = jobs.get(latest.get(reel_id))
        if current and current["status"] == "running":
            return job_view(current)
        out, cfg = write_config(reel_id)
        RENDERS.mkdir(parents=True, exist_ok=True)
        job = {"id": uuid.uuid4().hex[:12], "reelId": reel_id, "status": "running",
               "stage": "starting", "done": 0, "total": len(cfg["sources"]),
               "output": cfg["output"], "startedAt": now(), "finishedAt": None, "log": []}
        jobs[job["id"]] = job
        latest[reel_id] = job["id"]
    threading.Thread(target=run_render, args=(job, out), daemon=True).start()
    return job_view(job)


@app.get("/api/reels/{reel_id}/render")
def last_render(reel_id: int):
    job = jobs.get(latest.get(reel_id))
    return job_view(job) if job else None


@app.get("/api/renders/{job_id}")
def render_status(job_id: str):
    job = jobs.get(job_id) or {}
    if not job:
        raise HTTPException(404, "No such render")
    return job_view(job)


@app.get("/api/renders/{job_id}/video")
def render_video(job_id: str):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        raise HTTPException(404)
    return FileResponse(job["output"])


@app.post("/api/renders/{job_id}/reveal")
def reveal(job_id: str):
    """Show the rendered file in Finder (or the folder, elsewhere)."""
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        raise HTTPException(404)
    reveal_file(Path(job["output"]))
    return {"ok": True}


def reveal_file(path):
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------- finished videos
# Everything in the renders folder, whether rendered today or last week, so
# you can play it again, reveal it, or send it to your phone later.

def rendered_path(name):
    path = (RENDERS / name).resolve()
    if path.parent != RENDERS.resolve() or path.suffix.lower() != ".mp4" or not path.exists():
        raise HTTPException(404, "No such video")
    return path


@app.get("/api/rendered")
def list_rendered():
    if not RENDERS.is_dir():
        return {"dir": str(RENDERS), "videos": []}
    with lib.connect() as db:
        by_slug = {slug(r["name"]): {"id": r["id"], "name": r["name"]}
                   for r in db.execute("SELECT id, name FROM reels")}
    videos = []
    for p in RENDERS.iterdir():
        if p.suffix.lower() != ".mp4" or p.name.startswith("."):
            continue
        st = p.stat()
        videos.append({"name": p.name, "size": st.st_size, "modified": st.st_mtime,
                       "duration": duration_of(p), "reel": by_slug.get(p.stem)})
    videos.sort(key=lambda v: v["modified"], reverse=True)
    return {"dir": str(RENDERS), "videos": videos}


_durations = {}


def duration_of(path):
    key = (str(path), path.stat().st_mtime)
    if key not in _durations:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout
        try:
            _durations[key] = round(float(out.strip()), 1)
        except ValueError:
            _durations[key] = 0.0
    return _durations[key]


@app.get("/api/rendered/{name}/file")
def rendered_file(name: str):
    return FileResponse(rendered_path(name))


@app.get("/api/rendered/{name}/thumb")
def rendered_thumb(name: str):
    path = rendered_path(name)
    key = hashlib.sha1(f"render|{path}|{path.stat().st_mtime}".encode()).hexdigest()
    out = CACHE / f"{key}.jpg"
    if not out.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", "0.5", "-i", str(path),
                        "-frames:v", "1", "-vf", "scale=240:-2", "-q:v", "4", str(out)],
                       capture_output=True, timeout=60)
        if not out.exists():
            raise HTTPException(500, "Could not make a thumbnail")
    return FileResponse(out, headers={"Cache-Control": "max-age=86400"})


@app.post("/api/rendered/{name}/reveal")
def rendered_reveal(name: str):
    reveal_file(rendered_path(name))
    return {"ok": True}


@app.post("/api/rendered/{name}/share")
def rendered_share(name: str):
    """A QR-able link on your home network that downloads this one video."""
    path = rendered_path(name)
    with lib.connect() as db:
        titles = {slug(r["name"]): r["name"] for r in db.execute("SELECT name FROM reels")}
    try:
        url, expires = shares.add(path, titles.get(path.stem, path.stem))
    except OSError as e:
        raise HTTPException(503, f"Couldn't open the sharing port {shares.port}: {e}")
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    return {"url": url, "expiresAt": expires, "minutes": round(shares.ttl / 60)}


# ---------------------------------------------------------------- files

@app.get("/api/media/{name}/{file}")
def media(name: str, file: str):
    return FileResponse(resolve(name, file))


@app.get("/api/thumb/{name}/{file}")
def thumb(name: str, file: str, t: float = 0.0, w: int = 480):
    return make_thumb(resolve(name, file), t, w)


def make_thumb(path, t=0.0, w=480):
    w = max(64, min(w, 1280))
    key = hashlib.sha1(f"{path}|{path.stat().st_mtime}|{t:.2f}|{w}".encode()).hexdigest()
    out = CACHE / f"{key}.jpg"
    if not out.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() in HEIC_EXTS and sys.platform == "darwin":
            subprocess.run(["sips", "-s", "format", "jpeg", "-Z", str(w), str(path),
                            "--out", str(out)], capture_output=True, timeout=60)
        else:
            seek = ["-ss", f"{max(t, 0):.2f}"] if Library.kind_of(path) == "video" else []
            subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", *seek, "-i", str(path),
                            "-frames:v", "1", "-vf", f"scale={w}:-2", "-q:v", "4", str(out)],
                           capture_output=True, timeout=60)
        if not out.exists():
            raise HTTPException(500, "Could not make a thumbnail")
    return FileResponse(out, headers={"Cache-Control": "max-age=86400"})


# ---------------------------------------------------------------- import
# Things AirDropped from the phone land loose in ~/Downloads. Import moves a
# day's worth of them into a shoot folder (a new one, or one you already have).

HEIC_EXTS = {".heic", ".heif"}   # iPhone photos; converted to JPEG on the way in
IMPORT_DAYS = 30                 # how far back the import list looks


def importable(path):
    return (path.is_file() and not path.name.startswith(".")
            and (Library.kind_of(path) or path.suffix.lower() in HEIC_EXTS))


def arrived(st):
    """When a file landed in Downloads. AirDrop keeps the photo's own dates on
    some files, but the inode change time is when it was written here."""
    return max(st.st_mtime, st.st_ctime)


def download_path(name):
    path = (DOWNLOADS / name).resolve()
    if path.parent != DOWNLOADS or not path.exists() or not importable(path):
        raise HTTPException(404, f"Not in Downloads: {name}")
    return path


def folder_name_ok(name):
    return bool(name) and name not in (".", "..") and not name.startswith(".") \
        and "/" not in name and "\\" not in name and ":" not in name


@app.get("/api/import")
def import_list():
    """Photos and videos in Downloads from the last few weeks, grouped by the
    day they arrived, each marked if a shoot folder already has it."""
    if not DOWNLOADS.is_dir():
        return {"dir": str(DOWNLOADS), "days": [], "files": [],
                "error": f"{DOWNLOADS} does not exist"}
    since = datetime.combine(date.today() - timedelta(days=IMPORT_DAYS), datetime.min.time())
    files, seen = [], {}
    paths = sorted((p for p in DOWNLOADS.iterdir() if importable(p)), key=lambda p: arrived(p.stat()))
    with lib.connect() as db:
        for p in paths:
            st = p.stat()
            at = arrived(st)
            if at < since.timestamp():
                continue
            files.append({"name": p.name, "kind": Library.kind_of(p) or "photo",
                          "size": st.st_size, "arrived": at,
                          "day": datetime.fromtimestamp(at).strftime("%Y-%m-%d"),
                          "convert": p.suffix.lower() in HEIC_EXTS,
                          "importedTo": in_footage(db, p),
                          "copyOf": copy_in_batch(p, seen)})
    files.sort(key=lambda f: f["arrived"])
    days = {}
    for f in files:
        d = days.setdefault(f["day"], {"day": f["day"], "photos": 0, "videos": 0, "new": 0})
        d["videos" if f["kind"] == "video" else "photos"] += 1
        d["new"] += not (f["importedTo"] or f["copyOf"])
    return {"dir": str(DOWNLOADS), "today": date.today().isoformat(),
            "days": sorted(days.values(), key=lambda d: d["day"], reverse=True), "files": files}


@app.get("/api/import/thumb/{file}")
def import_thumb(file: str, w: int = 320):
    path = download_path(file)
    try:
        return make_thumb(path, 0.5, w)
    except HTTPException:
        return make_thumb(path, 0.0, w)   # a clip shorter than the seek


@app.post("/api/import")
def import_files(body: dict = Body(...)):
    """Move files from Downloads into a shoot folder.

    {files: [names], folder: "2026-10-06 garden", create: true}

    A file that's already in Footage (or the same as one earlier in this
    import) isn't copied again; it's deleted from Downloads, so there's only
    ever one of each.
    """
    name = (body.get("folder") or "").strip()
    if not folder_name_ok(name):
        raise HTTPException(400, "Give the folder a name (no slashes or colons)")
    if not ROOT.is_dir():
        raise HTTPException(400, f"{ROOT} does not exist")
    sources = sorted((download_path(f) for f in body.get("files") or []),
                     key=lambda p: arrived(p.stat()))
    if not sources:
        raise HTTPException(400, "Pick at least one file to import")
    dest = ROOT / name
    if body.get("create"):
        if dest.exists():
            raise HTTPException(409, f"There's already a folder called '{name}'")
        dest.mkdir()
    elif not dest.is_dir():
        raise HTTPException(404, f"No folder called '{name}'")

    lib.scan()   # so files dropped into Footage by hand count as already there
    seen = {}
    copies = {src: copy_in_batch(src, seen) for src in sources}   # before anything moves
    imported, removed, failed = [], [], []
    for src in sources:
        heic = src.suffix.lower() in HEIC_EXTS
        try:
            with lib.connect() as db:
                dup = in_footage(db, src)
            if dup or copies[src]:
                src.unlink()
                removed.append(src.name)
                continue
            target = dest / (src.with_suffix(".jpg").name if heic else src.name)
            if target.exists():
                target = free_name(target)   # a different file with the same name
            if heic:
                to_jpeg(src, target)
                src.unlink()
            else:
                shutil.move(str(src), str(target))
            imported.append(target.name)
        except Exception as e:   # one bad file shouldn't stop the rest
            failed.append({"name": src.name, "error": str(e)})
    lib.scan([dest])
    if not any(dest.iterdir()) and body.get("create"):
        dest.rmdir()   # everything was a duplicate: no empty folder left behind
    return {"folder": name, "imported": imported, "removed": removed, "failed": failed}


def fingerprint(path):
    """Size plus a hash of the start and end: enough to tell two copies of a
    phone photo or clip apart from different files, without reading a whole video."""
    size = path.stat().st_size
    h = hashlib.sha1(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(1 << 20))
        if size > 2 << 20:
            f.seek(-(1 << 20), os.SEEK_END)
            h.update(f.read())
    return h.hexdigest()


def in_footage(db, src):
    """The shoot folder that already has this file, if any.

    Matched on content, so a copy AirDrop renamed ('IMG_1234 2.MOV') still
    counts. A HEIC photo is converted on import, so it's matched by name.
    """
    if src.suffix.lower() in HEIC_EXTS:
        stems = {src.stem, re.sub(r" \d+$", "", src.stem)}
        rows = db.execute(f"SELECT folder FROM media WHERE missing = 0 AND kind = 'photo' AND name IN "
                          f"({','.join('?' * len(stems))})", [f"{s}.jpg" for s in stems]).fetchall()
        return rows[0]["folder"] if rows else None
    size, fp = src.stat().st_size, None
    for row in db.execute("SELECT path, folder FROM media WHERE size = ? AND missing = 0", (size,)):
        other = ROOT / row["path"]
        try:
            fp = fp or fingerprint(src)
            if fingerprint(other) == fp:
                return row["folder"]
        except OSError:
            continue
    return None


def copy_in_batch(src, seen):
    """The name of an earlier file in Downloads with the same content, if any
    (AirDrop the same thing twice and you get 'IMG_1234 2.MOV'). Records src.
    Only files of the same size are ever read."""
    size = src.stat().st_size
    group = seen.setdefault(size, [])
    fp = fingerprint(src) if group else None
    for entry in group:
        entry[1] = entry[1] or fingerprint(entry[0])
        if entry[1] == fp:
            return entry[0].name
    group.append([src, fp])
    return None


def free_name(path):
    n = 2
    while (candidate := path.with_name(f"{path.stem} ({n}){path.suffix}")).exists():
        n += 1
    return candidate


def to_jpeg(src, target):
    """HEIC -> JPEG, keeping the photo's dates (the studio sorts by them)."""
    if sys.platform == "darwin":
        cmd = ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "best",
               str(src), "--out", str(target)]
    else:
        cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(src), "-q:v", "2", str(target)]
    subprocess.run(cmd, capture_output=True, timeout=120)
    if not target.exists():
        raise RuntimeError("couldn't convert it to JPEG")
    st = src.stat()
    os.utime(target, (st.st_atime, st.st_mtime))


DIST = HERE / "web" / "dist"
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")


def main():
    ap = argparse.ArgumentParser(description="Footage Studio")
    ap.add_argument("--port", type=int, default=3009)
    ap.add_argument("--open", action="store_true", help="open the browser")
    args = ap.parse_args()
    if not DIST.is_dir():
        print("Front end not built yet: cd studio/web && npm install && npm run build")
    print(f"\n  Footage Studio — {ROOT}\n  http://localhost:{args.port}\n")
    if args.open:
        import webbrowser
        webbrowser.open(f"http://localhost:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
