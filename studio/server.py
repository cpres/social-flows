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
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime
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

ROOT = Path(os.environ.get("FOOTAGE_DIR", "~/Footage")).expanduser().resolve()
RENDERS = Path(os.environ.get("RENDER_DIR", "~/Movies/Footage Studio")).expanduser()
CACHE = Path("~/.cache/footage-studio").expanduser()
SIDECAR = ".studio.json"
# What a part can lead into the next with ('' = the reel's default).
TRANSITIONS = ("", "cut", "flash", "whip", "zoom", "dissolve", "dip")   # per-folder trims from the first version of the studio

lib = Library(ROOT)
shelf = Shelf(os.environ.get("MUSIC_DIR", "~/Music/Reels"), lib.home / "music")
ITEM_COLUMNS = ("media_id", "position", "start", "length", "keep", "focus_x", "focus_y",
                "transition", "lighten", "beats", "zoom")
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
            "zoom": row["zoom"]}


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
    return {"id": r["id"], "name": r["name"], "settings": settings_of(r), "items": items,
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
            settings = {**settings_of(r), **body["settings"]}
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
        pos = db.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM reel_items "
                         "WHERE reel_id = ?", (reel_id,)).fetchone()[0]
        cur = db.execute("INSERT INTO reel_items (reel_id, media_id, position, start, length, "
                         "focus_x, focus_y, lighten, beats, zoom) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (reel_id, m["id"], pos, start, length, fx, fy, lighten, beats, zoom))
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
        db.execute(f"INSERT INTO reel_items (reel_id, {cols}) "
                   f"SELECT ?, {cols} FROM reel_items WHERE reel_id = ? ORDER BY position, id",
                   (new_id, reel_id))
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
    kept = [r for r in rows if r["keep"] and not r["missing"]]
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
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", job["output"]])
    else:
        subprocess.Popen(["xdg-open", str(Path(job["output"]).parent)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True}


# ---------------------------------------------------------------- files

@app.get("/api/media/{name}/{file}")
def media(name: str, file: str):
    return FileResponse(resolve(name, file))


@app.get("/api/thumb/{name}/{file}")
def thumb(name: str, file: str, t: float = 0.0, w: int = 480):
    path = resolve(name, file)
    w = max(64, min(w, 1280))
    key = hashlib.sha1(f"{path}|{path.stat().st_mtime}|{t:.2f}|{w}".encode()).hexdigest()
    out = CACHE / f"{key}.jpg"
    if not out.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        seek = ["-ss", f"{max(t, 0):.2f}"] if Library.kind_of(path) == "video" else []
        subprocess.run(["ffmpeg", "-y", "-v", "error", *seek, "-i", str(path),
                        "-frames:v", "1", "-vf", f"scale={w}:-2", "-q:v", "4", str(out)],
                       capture_output=True, timeout=60)
        if not out.exists():
            raise HTTPException(500, "Could not make a thumbnail")
    return FileResponse(out, headers={"Cache-Control": "max-age=86400"})


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
