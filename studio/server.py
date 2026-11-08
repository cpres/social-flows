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
import asyncio
import logging
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
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
BRAND = HERE.parent / "brand"   # the logo PNGs, kept out of git
sys.path.insert(0, str(ENGINE.parent))
sys.path.insert(0, str(HERE))


def load_dotenv(*files):
    """KEY=value lines from .env files (the repo's, then studio's) into the
    environment, for API keys kept out of git. Never overrides what the shell
    already set to something; # comments, `export ` and quotes are allowed."""
    for f in files:
        if not f.is_file():
            continue
        for line in f.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.removeprefix("export ").split("=", 1)
            k, v = k.strip(), v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            elif " #" in v:
                v = v.split(" #", 1)[0].rstrip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) and not os.environ.get(k):   # unset, or set but empty
                os.environ[k] = v


load_dotenv(HERE.parent / ".env", HERE / ".env")
import looks  # noqa: E402
from db import VOICE_FOLDER, DEFAULT_SETTINGS, Library, default_start, now, settings_of  # noqa: E402
import audio  # noqa: E402
import beats as beats_mod  # noqa: E402
import compose  # noqa: E402
import relay as relay_mod  # noqa: E402
import scenes as scenes_mod  # noqa: E402
import montage  # noqa: E402
from music import AUDIO_EXTS, Shelf, beat_detection_available  # noqa: E402
from share import Shares  # noqa: E402
from voice import MODEL as VOICE_MODEL, Voice, align, lines_from_words, transcription_available  # noqa: E402

ROOT = Path(os.environ.get("FOOTAGE_DIR", "~/Footage")).expanduser().resolve()
RENDERS = Path(os.environ.get("RENDER_DIR", "~/Movies/Footage Studio")).expanduser()
CACHE = Path("~/.cache/footage-studio").expanduser()
DOWNLOADS = Path(os.environ.get("DOWNLOADS_DIR", "~/Downloads")).expanduser().resolve()
SIDECAR = ".studio.json"
# What a part can lead into the next with ('' = the reel's default).
TRANSITIONS = ("", "cut", "flash", "whip", "zoom", "dissolve", "dip")   # per-folder trims from the first version of the studio

lib = Library(ROOT)
shelf = Shelf(os.environ.get("MUSIC_DIR", "~/Music/Reels"), lib.home / "music")
voice = Voice(CACHE / "voice", lib.home / "voice")
shares = Shares(port=int(os.environ.get("SHARE_PORT", 3010)),
                ttl=int(os.environ.get("SHARE_TTL", 3600)))
ITEM_COLUMNS = ("media_id", "position", "start", "length", "keep", "focus_x", "focus_y",
                "transition", "lighten", "beats", "zoom", "layout", "pane", "top_after", "frames")
LAYOUTS = ("", "fill", "blur")   # per part; '' = the reel's framing
FORMATS = ("standard", "stack")
PANES = ("", "solo")   # a Stack part: split with the top clip, or the whole frame on its own
# The reel's shape: the size it renders at. A wide Stack is side by side.
SHAPES = {"tall": (1080, 1920), "wide": (1920, 1080), "portrait": (1080, 1350), "square": (1080, 1080)}
LOGOS = {"oufp": ["oufp.png"], "garden-steward": ["garden-steward.png"],
         "both": ["oufp.png", "garden-steward.png"]}
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
            "zoom": row["zoom"], "layout": row["layout"], "pane": row["pane"], "topAfter": row["top_after"],
            "frames": frames_of(row["frames"])}


def frames_of(text):
    """A part's framing per slot shape, or None for a part from before slots."""
    if text is None:
        return None
    try:
        f = json.loads(text)
    except ValueError:
        return {}
    return {k: {"x": unit(v.get("x", 0.5)), "y": unit(v.get("y", 0.5)), "zoom": zoom_of(v.get("zoom", 1))}
            for k, v in f.items() if k in ("half", "square") and isinstance(v, dict)} if isinstance(f, dict) else {}


def pick_dict(row):
    return {"start": row["start"], "length": row["length"], "focusX": row["focus_x"],
            "focusY": row["focus_y"], "zoom": row["zoom"], "layout": row["layout"]}


def pick_of(db, media_id):
    """The part of a file picked in its shoot (see db.py), or None."""
    row = db.execute("SELECT * FROM picks WHERE media_id = ?", (media_id,)).fetchone()
    return pick_dict(row) if row else None


def top_item(db, reel_id, s):
    """A Stack reel's top clip: its pinned row, if that's still a video here."""
    if s.get("format") != "stack" or not s.get("topItemId"):
        return None
    return db.execute("""SELECT i.id FROM reel_items i JOIN media m ON m.id = i.media_id
                         WHERE i.id = ? AND i.reel_id = ? AND m.kind = 'video'""",
                      (s["topItemId"], reel_id)).fetchone()


def frame_size(s):
    """Width and height a reel renders at."""
    return SHAPES.get(s.get("shape"), SHAPES["tall"])


MIX_KEYS = {"A": "mixA", "B": "mixB", "music": "mixMusic", "voice": "mixVoice"}


def mix_of(s, layer):
    """A layer's fader, 0..1.5 (1: as it comes)."""
    try:
        return round(min(max(float(s.get(MIX_KEYS[layer], 1)), 0.0), 1.5), 3)
    except (TypeError, ValueError):
        return 1.0


def glasses_of(s):
    """Which glasses audio a reel keeps: primary (the primary slot's lane), A
    (lane A only) or off. Reels from before say originalAudio true/false."""
    if s.get("glassesAudio") in ("primary", "A", "off"):
        return s["glassesAudio"]
    return "primary" if s.get("originalAudio") else "off"


def clean_settings(db, reel_id, s):
    """Keep the Stack settings in range."""
    if s.get("format") not in FORMATS:
        raise HTTPException(400, f"Unknown format: {s.get('format')}")
    if s.get("shape") not in SHAPES:
        raise HTTPException(400, f"Unknown shape: {s.get('shape')}")
    s["stackSplit"] = round(min(max(float(s.get("stackSplit") or 0.5), 0.3), 0.7), 3)
    s["dividerPx"] = min(max(int(round(float(s.get("dividerPx") or 0) / 2)) * 2, 0), 20)
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(s.get("dividerColor") or "")):
        s["dividerColor"] = DEFAULT_SETTINGS["dividerColor"]
    s["fitTop"] = bool(s.get("fitTop"))
    s["fitTopBy"] = "quiet" if s.get("fitTopBy") == "quiet" else "speed"
    s["topSpeed"] = round(min(max(float(s.get("topSpeed") or 1), 0.25), 16.0), 3)
    s["stackIntro"] = beats_of(s.get("stackIntro"))
    if s.get("laneA") is not None:
        ids = [int(i) for i in s["laneA"]]
        mine = {r["id"] for r in db.execute("""SELECT i.id FROM reel_items i JOIN media m ON m.id = i.media_id
                                              WHERE i.reel_id = ? AND m.kind = 'video'""", (reel_id,))}
        s["laneA"] = [i for i in dict.fromkeys(ids) if i in mine]
    if s.get("scenes") is not None:
        s["scenes"] = scenes_mod.clean(s["scenes"], s)
    if s.get("topItemId") is not None:
        s["topItemId"] = int(s["topItemId"])
        if not top_item(db, reel_id, {**s, "format": "stack"}):
            s["topItemId"] = None   # removed, or not a video in this reel
    if "glassesAudio" in s:
        s["glassesAudio"] = glasses_of(s)
        s["originalAudio"] = s["glassesAudio"] != "off"   # what older code reads
    s["look"] = s.get("look") if s.get("look") in ("vivid", "rich") else ""
    s["duckMusic"] = bool(s.get("duckMusic", True))
    s["beatsFit"] = "fixed" if s.get("beatsFit") == "fixed" else "nearest"
    for layer, k in MIX_KEYS.items():
        if k in s:
            s[k] = mix_of(s, layer)
    if "beat" in s:
        s["beat"] = beats_mod.clean(s["beat"])
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


def beats_of(v):
    """A part's beats: whole ones, or ½ and ¼ for quick photos (0 = the reel's)."""
    n = round(min(max(float(v or 0), 0.0), 2048.0) * 4) / 4
    return int(n) if n == int(n) else n


def nearest_beats(length, period, photo=False):
    """The whole number of beats nearest a part's length (at least one; a
    photo can be ½ or ¼). The same as nearestBeats in ReelView.vue."""
    v = float(length or 0) / period if period else 0
    if photo and v < 0.375:
        return 0.25
    if photo and v < 0.75:
        return 0.5
    return int(min(max(round(v), 1), 2048))


def beat_period(track, start):
    """One beat of a song, as the reel page measures it: the median gap
    between its beats from where the reel starts in it."""
    a = shelf.analyze(track)
    b = [x for x in a.get("beats") or [] if x >= start - 0.02]
    if len(b) >= 4:
        steps = sorted(y - x for x, y in zip(b, b[1:]))
        return steps[len(steps) // 2]
    return 60.0 / float(a["bpm"])


def pane_of(v):
    if (v or "") not in PANES:
        raise HTTPException(400, f"Unknown pane: {v}")
    return v or ""


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "reel"


def reel_summaries(db):
    rows = db.execute("""
        SELECT r.*, COUNT(i.id) AS items,
               COALESCE(SUM(CASE WHEN i.keep THEN i.length ELSE 0 END), 0) AS total
        FROM reels r LEFT JOIN reel_items i ON i.reel_id = r.id
        GROUP BY r.id ORDER BY r.archived_at IS NOT NULL, r.updated_at DESC""").fetchall()
    out = []
    for r in rows:
        cover = db.execute("""
            SELECT m.folder, m.name, m.kind, i.start FROM reel_items i
            JOIN media m ON m.id = i.media_id
            WHERE i.reel_id = ? AND m.missing = 0 ORDER BY i.position LIMIT 1""",
                           (r["id"],)).fetchone()
        out.append({"id": r["id"], "name": r["name"], "itemCount": r["items"],
                    "totalLength": round(r["total"], 2), "updatedAt": r["updated_at"],
                    "archivedAt": r["archived_at"],
                    "cover": dict(cover) if cover else None})
    return out


# ---------------------------------------------------------------- shoots

@app.get("/api/folders")
def list_folders():
    if not ROOT.is_dir():
        return {"root": str(ROOT), "folders": [], "reels": [], "drafts": [],
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
        drafts = draft_summaries(db)
    # Newest shoot first: date-named folders by name, the rest by last change.
    folders.sort(key=lambda f: (f["name"][:10] if f["name"][:4].isdigit() else "",
                                f["lastModified"]), reverse=True)
    return {"root": str(ROOT), "folders": folders, "reels": reels, "drafts": drafts}


@app.get("/api/folders/{name}")
def get_folder(name: str):
    folder = resolve(name)
    lib.scan([folder])
    with lib.connect() as db:
        media = [media_dict(r) for r in db.execute(
            "SELECT * FROM media WHERE folder = ? AND missing = 0 ORDER BY captured_at", (name,))]
        picks = {r["media_id"]: pick_dict(r) for r in db.execute(
            "SELECT p.* FROM picks p JOIN media m ON m.id = p.media_id WHERE m.folder = ?", (name,))}
        for m in media:
            m["pick"] = picks.get(m["id"])
        items = [item_dict(r) for r in db.execute("""
            SELECT i.id AS item_id, i.* FROM reel_items i JOIN media m ON m.id = i.media_id
            WHERE m.folder = ? ORDER BY i.start""", (name,))]
        reels = reel_summaries(db)
        draft_at = draft_time(db, draft_key(folder=name))
    return {"name": name, "path": str(folder), "media": media, "items": items, "reels": reels,
            "hasSidecar": (folder / SIDECAR).exists(), "draftAt": draft_at}


@app.post("/api/folders/{name}/to-reel")
def folder_to_reel(name: str, body: dict = Body(default={})):
    """Make a reel from a folder: its old studio trims if any, else every file.

    {name, style}: standard (one part after another), stack (the longest
    video is lane A, the rest play under it at real speed) or relay
    (relay.py: clips hand the frame on, photos come in under long clips as
    cameos; {dial: 1..10, photo: seconds, cap, most: stretches per long clip, quiet}; an old {mix} maps to
    the dial).

    Files that are copies of originals in another shoot folder point at the
    original, so per-concept folders of copied files can be retired.
    """
    folder = resolve(name)
    lib.scan()
    side = folder_sidecar(folder)
    settings = {**DEFAULT_SETTINGS, **side.get("settings", {})}
    reel_name = (body.get("name") or name).strip()
    with lib.connect() as db:
        if db.execute("SELECT 1 FROM reels WHERE name = ?", (reel_name,)).fetchone():
            raise HTTPException(409, f"A reel called '{reel_name}' already exists")
        cur = db.execute("INSERT INTO reels (name, settings, created_at, updated_at) "
                         "VALUES (?, ?, ?, ?)", (reel_name, json.dumps(settings), now(), now()))
        reel_id = cur.lastrowid
        for pos, m, start, length, pick in folder_parts(db, name, side):
            db.execute("INSERT INTO reel_items (reel_id, media_id, position, start, length, "
                       "focus_x, focus_y, zoom, layout, frames) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')",
                       (reel_id, lib.original_of(db, m["id"]), pos, start, length,
                        pick.get("focusX", 0.5), pick.get("focusY", 0.5), pick.get("zoom", 1),
                        pick.get("layout", "") if m["kind"] == "video" else ""))
        style = body.get("style") or "standard"
        if style in ("stack", "relay"):
            apply_style(db, reel_id, style, body)
    return {"id": reel_id}


def folder_sidecar(folder):
    """A shoot folder's old studio file (its trims and settings), or {}."""
    if (folder / SIDECAR).exists():
        try:
            return json.loads((folder / SIDECAR).read_text())
        except ValueError:
            pass
    return {}


def folder_parts(db, name, side):
    """A folder's files as a new reel's parts, in shot order: [(position,
    media row, start, length, pick)]. An old trim wins; else the part
    picked in the shoot; else the default. Files the old trims dropped are
    left out."""
    saved = side.get("clips", {})
    settings = {**DEFAULT_SETTINGS, **side.get("settings", {})}
    rows = db.execute("SELECT * FROM media WHERE folder = ? AND missing = 0 "
                      "ORDER BY captured_at", (name,)).fetchall()
    out = []
    for pos, m in enumerate(rows):
        s = saved.get(m["name"], {})
        if not s.get("keep", True):
            continue
        pick = pick_of(db, m["id"]) or {}
        if m["kind"] == "video":
            length = float(s.get("length", pick.get("length", min(settings["defaultLength"], m["duration"]))))
            start = float(s.get("start", pick.get("start", default_start(m["duration"], length))))
            start, length = fit(start, length, m["duration"])
        else:
            length, start = float(s.get("length", pick.get("length", settings["defaultHold"]))), 0.0
        out.append((pos, m, start, length, pick))
    return out


def relay_opts(body):
    """The Relay settings asked for: the dial (or an old Single or split
    choice), how long photos stay, the long-clip cap, quiet moments."""
    return {"dial": relay_mod.dial_of(body.get("dial"), body.get("mix")),
            "photo_seconds": min(max(float(body.get("photo") or body.get("solo") or relay_mod.PHOTO_SECONDS), 0.5), 30),
            "cap": float(body["cap"]) if body.get("cap") else None,
            "most": int(min(max(int(body.get("most") or relay_mod.MOST_DEFAULT), 1), relay_mod.MOST_MAX)),
            "quiet": bool(body.get("quiet"))}


def relay_items(db, parts, opts, cached_only=False):
    """What the relay planner needs: [{kind, duration, start, length, avail,
    shot_at, keep, clip, match, _row}], _row: which of `parts` it's from.
    parts: dicts with kind, duration, start, length, media_id, path,
    captured_at. A long clip plays the long stretch picked in its shoot, or
    the clip less a little breathing room at each end; with a cap it's
    several stretches of up to the cap spread evenly through that (at most
    `most`, all of them from two minutes up), one item each
    (relay.stretches). A short clip plays all of itself, or the
    stretch picked. With quiet moments skipped, `keep` is a stretch with its
    lulls out. cached_only: use only movement already measured (for a quick
    estimate). Also returns whether any was missing."""
    items, missing = [], False
    for row_i, p in enumerate(parts):
        it = {"kind": p["kind"], "duration": float(p["duration"] or 0), "start": float(p["start"]),
              "length": float(p["length"]), "shot_at": float(p["captured_at"] or 0), "_row": row_i}
        if p["kind"] == "video" and it["duration"] >= relay_mod.LONG_THRESHOLD:
            pick = pick_of(db, p["media_id"])
            if pick and pick["length"] >= relay_mod.LONG_THRESHOLD:   # the stretch picked: just as picked
                st = relay_mod.stretches(float(pick["start"]), float(pick["length"]), opts.get("cap"), breath=0, most=opts["most"])
            else:
                st = relay_mod.stretches(0.0, it["duration"], opts.get("cap"), most=opts["most"])
            act = None
            if opts.get("quiet"):
                path = ROOT / p["path"]
                try:
                    act = activity_cached(path) if cached_only else activity_of(path)
                except Exception:
                    act = None
                missing = missing or not act
            # each stretch claims the photos shot up to halfway to its neighbours
            bounds = [0.0] + [(a + la + b) / 2 for (a, la), (b, _) in zip(st, st[1:])] + [it["duration"]]
            for k, (s, ln) in enumerate(st):
                one = {**it, "start": s, "avail": ln, "clip": row_i, "match": (bounds[k], bounds[k + 1])}
                if act:
                    one["keep"] = montage.quiet_cut([(float(a), float(b)) for a, b in act["points"]], s, ln)
                items.append(one)
            continue
        if p["kind"] == "video":   # a short clip plays all of itself, or the stretch picked in its shoot
            pick = pick_of(db, p["media_id"])
            it["start"], it["length"] = (float(pick["start"]), float(pick["length"])) if pick else (0.0, it["duration"])
        items.append(it)
    return items, missing


@app.post("/api/folders/{name}/relay-plan")
def relay_preview(name: str, body: dict = Body(default={})):
    """What a Relay reel from this folder would look like at each dial
    setting, for the New reel dialog: {plans: [{dial, stats, bar}] (dial 1
    to 10), approx: quiet moments not measured yet for some clips}."""
    folder = resolve(name)
    opts = relay_opts(body)
    side = folder_sidecar(folder)
    with lib.connect() as db:
        parts = [{"kind": m["kind"], "duration": m["duration"], "start": start, "length": length,
                  "media_id": lib.original_of(db, m["id"]), "path": m["path"], "captured_at": m["captured_at"]}
                 for _, m, start, length, _ in folder_parts(db, name, side)]
        items, missing = relay_items(db, parts, opts, cached_only=True)
    plans = []
    for d in range(relay_mod.DIAL_MIN, relay_mod.DIAL_MAX + 1):
        plan = relay_mod.plan_relay(items, {**opts, "dial": d})
        plans.append({"dial": d, "stats": plan["stats"], "bar": relay_mod.bar(plan)})
    return {"plans": plans, "approx": missing}


def apply_style(db, reel_id, style, body):
    """Lay a new reel out in a style (see folder_to_reel)."""
    rows = db.execute("""SELECT i.*, m.kind, m.duration, m.captured_at, m.path FROM reel_items i
                         JOIN media m ON m.id = i.media_id
                         WHERE i.reel_id = ? AND i.keep = 1 ORDER BY i.position, i.id""", (reel_id,)).fetchall()
    s = settings_of(db.execute("SELECT settings FROM reels WHERE id = ?", (reel_id,)).fetchone())
    if style == "stack":
        videos = [r for r in rows if r["kind"] == "video"]
        if len(rows) < 2 or not videos:
            return
        top = max(videos, key=lambda r: r["duration"])
        rest = [r for r in rows if r["id"] != top["id"]]
        s["laneA"] = [top["id"]]
        db.execute("UPDATE reel_items SET start = 0, length = ? WHERE id = ?", (top["duration"], top["id"]))
        s["scenes"] = [{"id": scenes_mod.new_id(), "layout": "stack", "from": rest[0]["id"], "split": 0.5, "into": "cut",
                        "a": {"item": top["id"], "in": None, "out": None, "timing": "real", "speed": 1}}]
    else:
        opts = relay_opts(body)
        items, _ = relay_items(db, rows, opts)
        plan = relay_mod.plan_relay(items, opts)
        db.execute("DELETE FROM reel_items WHERE reel_id = ?", (reel_id,))
        ids = []
        cols = [c for c in ITEM_COLUMNS if c not in ("position", "start", "length")]
        for pos, part in enumerate(plan["lanes"]["B"]):
            r = rows[items[part["item"]]["_row"]]
            cur = db.execute(f"INSERT INTO reel_items (reel_id, position, start, length, {', '.join(cols)}) "
                             f"VALUES (?, ?, ?, ?, {', '.join('?' * len(cols))})",
                             (reel_id, pos, part["start"], part["length"], *[r[c] for c in cols]))
            ids.append(cur.lastrowid)
        split = s.get("stackSplit") or 0.5
        s["laneA"] = []
        s["scenes"] = []
        for sc in plan["scenes"]:
            out = {"id": scenes_mod.new_id(), "layout": sc["layout"], "from": ids[sc["parts"][0]], "into": sc["into"]}
            if sc["layout"] == "stack":
                out.update(split=split, relay=True)
            if sc.get("grow"):
                out["grow"] = sc["grow"]
            s["scenes"].append(out)
        s["relay"] = {"dial": opts["dial"], "photo": opts["photo_seconds"], "cap": opts["cap"], "most": opts["most"], "quiet": opts["quiet"]}
    db.execute("UPDATE reels SET settings = ? WHERE id = ?", (json.dumps(s), reel_id))


@app.post("/api/folders/{name}/move")
def move_files(name: str, body: dict = Body(...)):
    """Move clips and photos from this shoot folder into another one.

    {files: [names], to: "2026-10-06 garden", create: true}

    Each file keeps its id, so its parts in reels follow it. A folder left
    with nothing in it is removed.
    """
    src = resolve(name)
    to = (body.get("to") or "").strip()
    if not folder_name_ok(to):
        raise HTTPException(400, "Give the folder a name (no slashes or colons)")
    if to == name:
        raise HTTPException(400, "That's the folder they're already in")
    paths = [resolve(name, f) for f in body.get("files") or []]
    if not paths:
        raise HTTPException(400, "Pick at least one file to move")
    dest = ROOT / to
    if body.get("create"):
        if dest.exists():
            raise HTTPException(409, f"There's already a folder called '{to}'")
        dest.mkdir()
    elif not dest.is_dir():
        raise HTTPException(404, f"No folder called '{to}'")

    lib.scan([src])   # so every file has its row before it moves
    moved, failed = [], []
    for p in paths:
        try:
            if p.parent != src or not lib.kind_of(p):
                raise ValueError("not a clip or photo in this folder")
            target = dest / p.name
            with lib.connect() as db:
                # A different file with the same name, or a row kept for one
                # that went missing (its reel parts wait for it): another name.
                taken = lambda t: t.exists() or db.execute(
                    "SELECT 1 FROM media WHERE path = ?", (t.relative_to(ROOT).as_posix(),)).fetchone()
                n = 2
                while taken(target):
                    target = dest / f"{p.stem} ({n}){p.suffix}"
                    n += 1
                shutil.move(str(p), str(target))
                db.execute("UPDATE media SET path = ?, folder = ?, name = ?, mtime = ?, missing = 0 "
                           "WHERE path = ?", (target.relative_to(ROOT).as_posix(), to, target.name,
                                              target.stat().st_mtime, p.relative_to(ROOT).as_posix()))
            moved.append(target.name)
        except Exception as e:   # one bad file shouldn't stop the rest
            failed.append({"name": p.name, "error": str(e)})
    lib.scan([src, dest])

    # Nothing left but Finder's .DS_Store: the folder was all a mistake.
    emptied = False
    if all(p.name == ".DS_Store" for p in src.iterdir()):
        for p in src.iterdir():
            p.unlink()
        src.rmdir()
        emptied = True
        with lib.connect() as db:
            db.execute("DELETE FROM weave_drafts WHERE key = ?", (draft_key(folder=name),))
    if not moved and body.get("create") and not any(dest.iterdir()):
        dest.rmdir()
    return {"folder": to, "moved": moved, "failed": failed, "emptied": emptied}


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
        settings = with_reading(db, settings_of(r))
        if settings["format"] == "stack" and not top_item(db, reel_id, settings):
            settings["topItemId"] = None   # its clip was removed: pick another
        if settings.get("scenes") is None:   # from before scenes: worked out once, saved on the next change
            settings["laneA"] = scenes_mod.lane_a(settings)
            settings["scenes"] = scenes_mod.migrated(settings, [{**item_dict(row), "id": row["item_id"],
                                                                  "missing": row["missing"],
                                                                  "top_after": row["top_after"]} for row in rows])
        settings["laneA"] = [i for i in scenes_mod.lane_a(settings) if any(it["id"] == i for it in items)]
        draft_at = draft_time(db, draft_key(reel=reel_id))
    return {"id": r["id"], "name": r["name"], "settings": settings, "items": items,
            "otherItems": others, "reels": reels, "draftAt": draft_at, "updatedAt": r["updated_at"],
            "archivedAt": r["archived_at"]}


@app.patch("/api/reels/{reel_id}")
def update_reel(reel_id: int, body: dict = Body(...)):
    with lib.connect() as db:
        r = reel_row(db, reel_id)
        if "archived" in body:
            # Put away or bring back; not an edit, so it doesn't count as a change.
            db.execute("UPDATE reels SET archived_at = ? WHERE id = ?",
                       (now() if body["archived"] else None, reel_id))
            if set(body) == {"archived"}:
                return {"ok": True}
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
            settings.pop("voice", None)   # it lives in the reading (PUT /api/readings/{id})
            db.execute("UPDATE reels SET settings = ? WHERE id = ?", (json.dumps(settings), reel_id))
        touch(db, reel_id)
    if "settings" in body:
        refresh_running_cards(reel_id)
    return {"ok": True}


def refresh_running_cards(reel_id):
    """A render of this reel under way: give it the title and end card as they
    are now. The engine reads them again just before laying them over."""
    job = jobs.get(latest.get(reel_id))
    if not job or job["status"] != "running" or not job.get("config"):
        return
    try:
        reel, rows = reel_and_rows(reel_id)
        fresh = build_config(reel, rows)
        path = Path(job["config"])
        cfg = yaml.safe_load(path.read_text()) or {}
    except (HTTPException, OSError, yaml.YAMLError):
        return
    for key in ("title", "end_card"):
        if fresh.get(key):
            cfg[key] = fresh[key]
        else:
            cfg.pop(key, None)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    tmp.replace(path)


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

def item_values(m, body, s, pick=None):
    """A part's columns from a request body, kept in range (m: its media row).
    What the body leaves out comes from the file's pick, if it has one."""
    body = {**(pick or {}), **{k: v for k, v in body.items() if v is not None}}
    if m["kind"] == "video":
        length = float(body.get("length") or min(s["defaultLength"], m["duration"]))
        start = body.get("start")
        start = float(start) if start is not None else default_start(m["duration"], length)
        start, length = fit(start, length, m["duration"])
    else:
        length, start = float(body.get("length") or s["defaultHold"]), 0.0
    layout = body.get("layout") or ""
    if layout not in LAYOUTS:
        raise HTTPException(400, f"Unknown layout: {layout}")
    transition = body.get("transition") or ""
    if transition not in TRANSITIONS:
        raise HTTPException(400, f"Unknown transition: {transition}")
    return {"media_id": m["id"], "start": start, "length": length,
            "focus_x": unit(body.get("focusX", 0.5)), "focus_y": unit(body.get("focusY", 0.5)),
            "lighten": unit(body.get("lighten", 0)),
            "beats": beats_of(body.get("beats")),
            "zoom": zoom_of(body.get("zoom", 1)), "layout": layout, "transition": transition,
            "pane": pane_of(body.get("pane")), "top_after": beats_of(body.get("topAfter")),
            "frames": json.dumps(frames_of(json.dumps(body["frames"])) if body.get("frames") else {}),
            "keep": int(bool(body.get("keep", True)))}


@app.post("/api/reels/{reel_id}/items")
def add_item(reel_id: int, body: dict = Body(...)):
    with lib.connect() as db:
        r = reel_row(db, reel_id)
        m = db.execute("SELECT * FROM media WHERE id = ?", (body.get("mediaId"),)).fetchone()
        if not m:
            raise HTTPException(404, "No such clip")
        values = item_values(m, body, settings_of(r), pick_of(db, m["id"]))
        values["position"] = db.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM reel_items "
                                        "WHERE reel_id = ?", (reel_id,)).fetchone()[0]
        cols = ", ".join(values)
        cur = db.execute(f"INSERT INTO reel_items (reel_id, {cols}) VALUES (:reel_id, "
                         f"{', '.join(':' + k for k in values)})", {**values, "reel_id": reel_id})
        touch(db, reel_id)
        row = db.execute("SELECT id AS item_id, * FROM reel_items WHERE id = ?",
                         (cur.lastrowid,)).fetchone()
        return item_dict(row)


@app.put("/api/reels/{reel_id}/items")
def set_items(reel_id: int, body: dict = Body(...)):
    """Replace a reel's parts with this list, in this order (what Weave saves).

    {items: [{id?, mediaId, start, length, ...}]}: a part with the id of one of
    this reel's parts updates it, so what was set on it elsewhere (lighten,
    zoom) stays; one without is added; the reel's other parts are removed.
    """
    with lib.connect() as db:
        r = reel_row(db, reel_id)
        s = settings_of(r)
        mine = {row["id"] for row in db.execute("SELECT id FROM reel_items WHERE reel_id = ?", (reel_id,))}
        keep = set()
        for pos, body_item in enumerate(body.get("items") or []):
            m = db.execute("SELECT * FROM media WHERE id = ?", (body_item.get("mediaId"),)).fetchone()
            if not m:
                raise HTTPException(404, f"No such clip: {body_item.get('mediaId')}")
            item_id = body_item.get("id")
            if item_id in mine:
                old = db.execute("SELECT * FROM reel_items WHERE id = ?", (item_id,)).fetchone()
                # Unsent fields keep what the part already had.
                base = {"focusX": old["focus_x"], "focusY": old["focus_y"], "lighten": old["lighten"],
                        "zoom": old["zoom"], "layout": old["layout"], "keep": bool(old["keep"]),
                        "pane": old["pane"], "topAfter": old["top_after"],
                        "frames": frames_of(old["frames"])}
                values = {**item_values(m, {**base, **body_item}, s), "position": pos}
                sets = ", ".join(f"{k} = :{k}" for k in values)
                db.execute(f"UPDATE reel_items SET {sets} WHERE id = :id", {**values, "id": item_id})
                keep.add(item_id)
            else:
                values = {**item_values(m, body_item, s, pick_of(db, m["id"])), "position": pos}
                cur = db.execute(f"INSERT INTO reel_items (reel_id, {', '.join(values)}) VALUES (:reel_id, "
                                 f"{', '.join(':' + k for k in values)})", {**values, "reel_id": reel_id})
                keep.add(cur.lastrowid)
        for gone in mine - keep:
            db.execute("DELETE FROM reel_items WHERE id = ?", (gone,))
        touch(db, reel_id)
    return get_reel(reel_id)


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
        fields["beats"] = beats_of(body["beats"])
    if "zoom" in body:
        fields["zoom"] = zoom_of(body["zoom"])
    if "layout" in body:
        if body["layout"] not in LAYOUTS:
            raise HTTPException(400, f"Unknown layout: {body['layout']}")
        fields["layout"] = body["layout"]
    for key, col in (("focusX", "focus_x"), ("focusY", "focus_y")):
        if key in body:
            fields[col] = unit(body[key])
    if "pane" in body:
        fields["pane"] = pane_of(body["pane"])
    if "topAfter" in body:
        fields["top_after"] = beats_of(body["topAfter"])
    if "frames" in body:
        fields["frames"] = json.dumps(frames_of(json.dumps(body["frames"] or {})))
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


@app.put("/api/media/{media_id}/pick")
def save_pick(media_id: int, body: dict = Body(...)):
    """Keep the part of a file picked in its shoot: {start, length, focusX, focusY, zoom, layout}."""
    with lib.connect() as db:
        m = db.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
        if not m:
            raise HTTPException(404, "No such clip")
        v = item_values(m, body, DEFAULT_SETTINGS)
        db.execute("INSERT OR REPLACE INTO picks (media_id, start, length, focus_x, focus_y, zoom, "
                   "layout, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (media_id, v["start"], v["length"], v["focus_x"], v["focus_y"], v["zoom"],
                    v["layout"] if m["kind"] == "video" else "", now()))
        return pick_of(db, media_id)


@app.delete("/api/media/{media_id}/pick")
def delete_pick(media_id: int):
    with lib.connect() as db:
        db.execute("DELETE FROM picks WHERE media_id = ?", (media_id,))
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
        # The copy's lane A, scenes (and top clip, from before scenes) point at
        # the copies of the original's parts.
        s = settings_of(r)
        new = [row["id"] for row in db.execute(
            "SELECT id FROM reel_items WHERE reel_id = ? ORDER BY id", (new_id,))]
        to_new = dict(zip(old, new)).get
        if s.get("topItemId") in old:
            s["topItemId"] = to_new(s["topItemId"])
        if s.get("laneA") is not None:
            s["laneA"] = [to_new(i) for i in s["laneA"] if to_new(i)]
        for sc in s.get("scenes") or []:
            if sc.get("from") is not None:
                sc["from"] = to_new(sc["from"])
            if isinstance(sc.get("a"), dict) and sc["a"].get("item") is not None:
                sc["a"]["item"] = to_new(sc["a"]["item"])
        db.execute("UPDATE reels SET settings = ? WHERE id = ?", (json.dumps(s), new_id))
    return {"id": new_id, "name": name}


# ---------------------------------------------------------------- weave drafts
# The Weave wizard saves its progress as you go: one draft per shoot for a new
# weave, one per reel being re-woven, until it's made into (or saved to) a reel.

def draft_key(folder="", reel=0):
    if reel:
        return f"reel:{int(reel)}"
    if folder:
        return f"shoot:{folder}"
    raise HTTPException(400, "Say which shoot (folder) or reel the draft is for")


def draft_time(db, key):
    row = db.execute("SELECT updated_at FROM weave_drafts WHERE key = ?", (key,)).fetchone()
    return row["updated_at"] if row else None


def draft_summaries(db):
    """Drafts in progress, newest first, for Home's cards."""
    out = []
    for d in db.execute("""SELECT w.*, r.name AS reel_name FROM weave_drafts w
                           LEFT JOIN reels r ON r.id = w.reel_id ORDER BY w.updated_at DESC"""):
        if not d["reel_id"] and not (ROOT / d["folder"]).is_dir():
            continue   # its shoot folder is gone
        state = json.loads(d["state"] or "{}")
        chosen = [c for c in state.get("clips", []) if c.get("on")]
        videos = [c for c in chosen if c.get("kind") == "video"]
        cover = None
        for c in chosen:
            m = db.execute("SELECT folder, name, kind FROM media WHERE id = ? AND missing = 0",
                           (c.get("mediaId"),)).fetchone()
            if m:
                parts = c.get("parts") or [{}]
                cover = {**dict(m), "start": parts[0].get("start", 0)}
                break
        out.append({"folder": d["folder"], "reelId": d["reel_id"], "reelName": d["reel_name"],
                    "step": int(state.get("step") or 0) + 1, "clips": len(videos),
                    "photos": len(chosen) - len(videos),
                    "parts": sum(len(c.get("parts") or []) for c in videos),
                    "updatedAt": d["updated_at"], "cover": cover})
    return out


@app.get("/api/weave/draft")
def get_draft(folder: str = "", reel: int = 0):
    with lib.connect() as db:
        row = db.execute("SELECT state, updated_at FROM weave_drafts WHERE key = ?",
                         (draft_key(folder, reel),)).fetchone()
    return {"state": json.loads(row["state"]), "updatedAt": row["updated_at"]} if row else None


@app.put("/api/weave/draft")
def save_draft(body: dict = Body(...)):
    """{folder, reelId?, state}: the wizard's choices so far."""
    folder = (body.get("folder") or "").strip()
    reel = int(body.get("reelId") or 0)
    if not folder:
        raise HTTPException(400, "A draft needs its shoot folder")
    at = now()
    with lib.connect() as db:
        if reel:
            reel_row(db, reel)
        db.execute("INSERT OR REPLACE INTO weave_drafts (key, folder, reel_id, state, updated_at) "
                   "VALUES (?, ?, ?, ?, ?)",
                   (draft_key(folder, reel), folder, reel or None, json.dumps(body.get("state") or {}), at))
    return {"updatedAt": at}


@app.delete("/api/weave/draft")
def delete_draft(folder: str = "", reel: int = 0):
    with lib.connect() as db:
        db.execute("DELETE FROM weave_drafts WHERE key = ?", (draft_key(folder, reel),))
    return {"ok": True}


# ---------------------------------------------------------------- music

def genres(text):
    """A genre tag as categories: "Beats; Lo-fi" -> ["Beats", "Lo-fi"]"""
    return [g.strip() for g in re.split(r"[;,/]", text or "") if g.strip()]


@app.get("/api/music")
def music_shelf():
    """The music folder's songs, each with its name, artist and categories: as
    given here, else as the file says."""
    with lib.connect() as db:
        given = {r["name"]: r for r in db.execute("SELECT * FROM songs")}
    tracks = shelf.tracks()
    for t in tracks:
        g = given.get(t["name"])
        t["title"] = (g and g["title"]) or t["fileTitle"]
        t["artist"] = (g and g["artist"]) or t["fileArtist"]
        t["categories"] = json.loads(g["categories"]) if g and g["categories"] is not None else genres(t["genre"])
    return {"dir": str(shelf.folder), "exists": shelf.folder.is_dir(),
            "tracks": tracks, "beatDetection": beat_detection_available()}


@app.put("/api/music/{name}/info")
def music_info(name: str, body: dict = Body(...)):
    """Name a song and put it in categories: {title, artist, categories}. An
    empty title or artist goes back to what the file says."""
    path = shelf.path_of(name)
    if not path or not path.exists() or path.parent != shelf.folder:
        raise HTTPException(404, "No such track")
    seen = set()
    cats = []
    for c in body.get("categories") or []:
        c = " ".join(str(c).split())
        if c and c.lower() not in seen:
            seen.add(c.lower())
            cats.append(c)
    with lib.connect() as db:
        db.execute("INSERT OR REPLACE INTO songs (name, title, artist, categories) VALUES (?, ?, ?, ?)",
                   (name, (body.get("title") or "").strip() or None,
                    (body.get("artist") or "").strip() or None, json.dumps(cats)))
    return music_shelf()


@app.get("/api/music/{name}/file")
def music_file(name: str):
    path = shelf.path_of(name)
    if not path or not path.exists() or path.parent != shelf.folder:
        raise HTTPException(404, "No such track")
    return FileResponse(path)


@app.get("/api/music/{name}/envelope")
def music_envelope(name: str):
    path = shelf.path_of(name)
    if not path or not path.exists() or path.parent != shelf.folder:
        raise HTTPException(404, "No such track")
    return audio.envelope(path, CACHE)


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


# ---------------------------------------------------------------- voice
# Takes of a reading, in the Voice folder (or the sound of a video in a shoot
# folder): their sound, what's said in them (transcribed once, in the
# background), and lines for the captions.

VOICE_DIR = ROOT / VOICE_FOLDER


def with_reading(db, s):
    """A reel's settings with its reading's pieces as settings.voice."""
    row = db.execute("SELECT pieces FROM readings WHERE id = ?", (s.get("readingId"),)).fetchone() \
        if s.get("readingId") else None
    s["voice"] = json.loads(row["pieces"]) if row else []
    if not row:
        s["readingId"] = None
    return s


def reading_dict(db, row):
    """A reading, with the reels that use it."""
    pieces = json.loads(row["pieces"] or "[]")
    reels = [{"id": r["id"], "name": r["name"]} for r in db.execute("SELECT id, name, settings FROM reels")
             if json.loads(r["settings"] or "{}").get("readingId") == row["id"]]
    length = sum(max(0.0, float(p.get("end") or 0) - float(p.get("start") or 0)) + float(p.get("gap") or 0)
                 for p in pieces)
    return {"id": row["id"], "name": row["name"], "pieces": pieces, "length": round(length, 1),
            "reels": reels, "updatedAt": row["updated_at"]}


def reading_row(db, reading_id):
    row = db.execute("SELECT * FROM readings WHERE id = ?", (reading_id,)).fetchone()
    if not row:
        raise HTTPException(404, "No such reading")
    return row


@app.get("/api/readings")
def list_readings():
    with lib.connect() as db:
        return [reading_dict(db, r) for r in db.execute("SELECT * FROM readings ORDER BY updated_at DESC")]


@app.post("/api/readings")
def create_reading(body: dict = Body(...)):
    """A new reading: {name, copyOf?: id (start from that one's pieces), pieces?}."""
    name = " ".join(str(body.get("name") or "").split()) or "Reading"
    with lib.connect() as db:
        pieces = body.get("pieces") or []
        if body.get("copyOf"):
            pieces = json.loads(reading_row(db, int(body["copyOf"]))["pieces"])
        cur = db.execute("INSERT INTO readings (name, pieces, created_at, updated_at) VALUES (?, ?, ?, ?)",
                         (name, json.dumps(pieces), now(), now()))
        return reading_dict(db, reading_row(db, cur.lastrowid))


@app.put("/api/readings/{reading_id}")
def update_reading(reading_id: int, body: dict = Body(...)):
    """Save a reading: {name?, pieces?}. Every reel that uses it gets it."""
    with lib.connect() as db:
        reading_row(db, reading_id)
        if "name" in body:
            name = " ".join(str(body["name"] or "").split())
            if not name:
                raise HTTPException(400, "A reading needs a name")
            db.execute("UPDATE readings SET name = ? WHERE id = ?", (name, reading_id))
        if "pieces" in body:
            pieces = body["pieces"] if isinstance(body["pieces"], list) else []
            db.execute("UPDATE readings SET pieces = ? WHERE id = ?", (json.dumps(pieces), reading_id))
        db.execute("UPDATE readings SET updated_at = ? WHERE id = ?", (now(), reading_id))
        return reading_dict(db, reading_row(db, reading_id))


@app.delete("/api/readings/{reading_id}")
def delete_reading(reading_id: int):
    """Delete a reading no reel uses (its recordings stay in the Voice folder)."""
    with lib.connect() as db:
        r = reading_dict(db, reading_row(db, reading_id))
        if r["reels"]:
            raise HTTPException(409, f"{', '.join(x['name'] for x in r['reels'])} still use{'s' if len(r['reels']) == 1 else ''} this reading")
        db.execute("DELETE FROM readings WHERE id = ?", (reading_id,))
    return {"ok": True}

def take_path(folder, file):
    if folder == VOICE_FOLDER:
        VOICE_DIR.mkdir(exist_ok=True)
    path = resolve(folder, file)
    if path.suffix.lower() not in AUDIO_EXTS and Library.kind_of(path) != "video":
        raise HTTPException(404, "Not a recording")
    return path


@app.get("/api/voice/folders")
def voice_folders():
    """The Voice folder, then the shoot folders newest first, with how many
    recordings each has."""
    out = []
    for d in ([VOICE_DIR] if VOICE_DIR.is_dir() else []) + lib.shoot_folders():
        audio = video = 0
        for p in d.iterdir():
            if p.name.startswith(".") or not p.is_file():
                continue
            if p.suffix.lower() in AUDIO_EXTS:
                audio += 1
            elif Library.kind_of(p) == "video":
                video += 1
        out.append({"name": d.name, "audio": audio, "video": video})
    out.sort(key=lambda f: f["name"], reverse=True)
    out.sort(key=lambda f: f["name"] != VOICE_FOLDER)   # the Voice folder first
    if not VOICE_DIR.is_dir():
        out.insert(0, {"name": VOICE_FOLDER, "audio": 0, "video": 0})
    return {"folders": out, "voiceFolder": VOICE_FOLDER, "transcribe": transcription_available(),
            "model": VOICE_MODEL}


@app.get("/api/voice/takes/{folder}")
def voice_takes(folder: str):
    """A folder's recordings: audio files first, then videos (their sound).
    Each says which reading it was brought in for, if any."""
    if folder == VOICE_FOLDER:
        VOICE_DIR.mkdir(exist_ok=True)
    d = resolve(folder)
    with lib.connect() as db:
        tags = {r["path"]: (r["reading_id"], r["added_at"]) for r in db.execute("SELECT * FROM voice_takes")}
    takes = []
    for p in sorted(d.iterdir(), key=lambda q: q.name.lower()):
        if p.name.startswith(".") or not p.is_file():
            continue
        kind = "audio" if p.suffix.lower() in AUDIO_EXTS else "video" if Library.kind_of(p) == "video" else None
        if kind:
            reading_id, added = tags.get(f"{folder}/{p.name}", (None, None))
            takes.append({"folder": folder, "file": p.name, "kind": kind, "readingId": reading_id,
                          "added": added or p.stat().st_mtime,
                          "duration": voice.duration(p), **voice.status(p)})
    # audio first, the newest first among them
    takes.sort(key=lambda t: (t["kind"] != "audio", -t["added"] if t["kind"] == "audio" else 0))
    return {"folder": folder, "takes": takes, "transcribe": transcription_available()}


@app.get("/api/voice/audio/{folder}/{file}")
def voice_audio(folder: str, file: str):
    try:
        return FileResponse(voice.audio(take_path(folder, file)), media_type="audio/mp4")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/voice/peaks/{folder}/{file}")
def voice_peaks(folder: str, file: str):
    try:
        return voice.peaks(take_path(folder, file))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/voice/envelope/{folder}/{file}")
def voice_envelope(folder: str, file: str):
    try:
        return audio.envelope(voice.audio(take_path(folder, file)), CACHE)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/voice/transcribe/{folder}/{file}")
def voice_transcribe(folder: str, file: str, again: bool = False):
    """Transcribe a take (once; again=true throws away what it heard and listens again)."""
    path = take_path(folder, file)
    if (again or not voice.transcript(path)) and not transcription_available():
        raise HTTPException(503, "Transcribing isn't installed: quit the studio and start it again with ./studio/run.sh, which installs it")
    return voice.start(path, again=again)


@app.get("/api/voice/transcript/{folder}/{file}")
def voice_transcript(folder: str, file: str):
    """What's said in the take: its words and the lines made from them (once
    transcribed), or how far along transcribing is."""
    path = take_path(folder, file)
    data = voice.transcript(path)
    if not data:
        return {**voice.status(path), "duration": voice.duration(path)}
    return {"status": "done", "progress": 1.0, "duration": data["duration"] or voice.duration(path),
            "language": data.get("language"), "words": data["words"], "lines": lines_from_words(data["words"])}


@app.post("/api/voice/align")
def voice_align(body: dict = Body(...)):
    """Time pasted text to a stretch of a take: {folder, file, start, end, text} -> {lines}."""
    path = take_path(body["folder"], body["file"])
    data = voice.transcript(path) or {"words": []}
    start, end = float(body.get("start") or 0), float(body.get("end") or 0)
    words = [w for w in data["words"] if w["e"] > start and w["s"] < end]
    return {"lines": align(words, body.get("text") or "", start, end)}


@app.get("/api/voice/downloads")
def voice_downloads():
    """Recordings that arrived in Downloads lately (AirDropped voice memos),
    newest first, to bring into a shoot folder as takes."""
    if not DOWNLOADS.is_dir():
        return {"files": []}
    since = (datetime.now() - timedelta(days=IMPORT_DAYS)).timestamp()
    files = []
    for p in DOWNLOADS.iterdir():
        if is_song(p) and arrived(p.stat()) >= since:
            files.append({"name": p.name, "arrived": arrived(p.stat()), "duration": voice.duration(p)})
    files.sort(key=lambda f: f["arrived"], reverse=True)
    return {"files": files}


@app.post("/api/voice/import")
def voice_import(body: dict = Body(...)):
    """Move recordings from Downloads into the Voice folder:
    {files: [names] (or file), readingId?: the reading they're for}.
    Each starts transcribing straight away, when that's installed."""
    names = body.get("files") or ([body["file"]] if body.get("file") else [])
    sources = [download_path(n, is_song) for n in names]
    if not sources:
        raise HTTPException(400, "Pick at least one recording")
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    reading_id = body.get("readingId")
    moved, failed = [], []
    with lib.connect() as db:
        if reading_id:
            reading_row(db, reading_id)
        for src in sources:
            try:
                target = VOICE_DIR / src.name
                if target.exists():
                    target = free_name(target)
                shutil.move(str(src), str(target))
                db.execute("INSERT OR REPLACE INTO voice_takes (path, reading_id, added_at) VALUES (?, ?, ?)",
                           (f"{VOICE_FOLDER}/{target.name}", reading_id, now()))
                moved.append(target.name)
            except Exception as e:   # one bad file shouldn't stop the rest
                failed.append({"name": src.name, "error": str(e)})
    if transcription_available():
        for name in moved:
            voice.start(VOICE_DIR / name)
    return {"folder": VOICE_FOLDER, "file": moved[0] if moved else None, "moved": moved, "failed": failed,
            "transcribing": transcription_available()}


@app.put("/api/voice/tag")
def voice_tag(body: dict = Body(...)):
    """Mark a take as one of a reading's: {folder, file, readingId}."""
    take_path(body["folder"], body["file"])
    with lib.connect() as db:
        db.execute("INSERT OR REPLACE INTO voice_takes (path, reading_id, added_at) VALUES "
                   "(?, ?, COALESCE((SELECT added_at FROM voice_takes WHERE path = ?), ?))",
                   (f"{body['folder']}/{body['file']}", body.get("readingId"),
                    f"{body['folder']}/{body['file']}", now()))
    return {"ok": True}


@app.get("/api/fonts/{name}")
def font_file(name: str):
    """The caption fonts in brand/fonts, so the preview uses the render's."""
    path = (BRAND / "fonts" / name).resolve()
    if path.parent != (BRAND / "fonts").resolve() or path.suffix.lower() not in (".ttf", ".otf") or not path.exists():
        raise HTTPException(404, "No such font")
    return FileResponse(path, headers={"Cache-Control": "max-age=86400"})


# ---------------------------------------------------------------- export

def build_config(reel, rows, grid_bpm=None):
    """The engine's config for a reel. With grid_bpm, it's laid out for a
    song not made yet: on a steady grid at that tempo when cutting on the
    beat, and without music."""
    with lib.connect() as db:
        s = with_reading(db, settings_of(reel))
    # Lanes and scenes (scenes.py): lane A's clips and, one after another,
    # what's on screen; each kept part plays in its scene.
    a_ids = scenes_mod.lane_a(s)
    by_id = {r["id"]: r for r in rows}
    lane_rows = {i: by_id[i] for i in a_ids if i in by_id and by_id[i]["kind"] == "video"}
    for r in lane_rows.values():
        if r["missing"]:
            raise HTTPException(400, f"A clip in lane A is missing: {r['path']}")
    kept = [r for r in rows if r["keep"] and not r["missing"] and r["id"] not in lane_rows]
    scenes = scenes_mod.normalized(s.get("scenes") if s.get("scenes") is not None
                                   else scenes_mod.migrated(s, [{**dict(r), "top_after": r["top_after"]} for r in rows]),
                                   [r["id"] for r in kept], list(lane_rows))
    if not kept and not any(sc["layout"] == "soloA" for sc in scenes):
        raise HTTPException(400, "Add parts to this reel first.")
    track = shelf.path_of(s.get("music")) if grid_bpm is None else None
    synced = bool((track or grid_bpm) and s.get("beatSync"))
    period = None   # one beat, for rounding parts to their nearest whole beats
    if synced:
        try:
            period = 60.0 / grid_bpm if grid_bpm else beat_period(track, float(s.get("musicStart") or 0))
        except (ImportError, KeyError, OSError, ValueError, ZeroDivisionError):
            period = None
    sources, seen, scene_cfg = [], {}, []
    kept_ids = [r["id"] for r in kept]
    for k, sc in enumerate(scenes):
        entry_sc = {"layout": sc["layout"], "split": sc.get("split", 0.5),
                    "into": sc.get("into", "cut") if k else "cut", **({"fill": sc["fill"]} if sc.get("fill") else {}),
                    **({"handoff": sc.get("handoff", scenes_mod.HANDOFF_DEFAULT)} if sc.get("into") == "handoff" else {}),
                    **({"grow": "A"} if sc.get("grow") == "A" and sc["layout"] == "soloB" else {})}
        prev = scenes[k - 1] if k else None
        relay = (sc.get("relay") and sc["layout"] in ("stack", "swap") and sc.get("into") == "handoff"
                 and prev and prev["layout"] == "soloB" and prev["parts"])
        if relay:   # A's slot: the shot before carries on
            last = by_id[prev["parts"][-1]]
            fx, fy, zoom = scenes_mod.frame_for(last, "full", "B")
            entry_sc["relay"] = True
            entry_sc["carry"] = {"file": str(ROOT / last["path"]), "kind": last["kind"],
                                 "start": round(last["start"] + last["length"], 3) if last["kind"] == "video" else 0,
                                 "focus": [round(fx, 3), round(fy, 3)], "zoom": round(zoom, 3),
                                 **({"lighten": round(last["lighten"], 2)} if last["lighten"] else {}),
                                 **({"fit": last["layout"]} if last["layout"] in ("fill", "blur") else {})}
        elif sc["layout"] != "soloB" and not lane_rows:
            sc = {**sc, "layout": "soloB"}   # a relay that lost the shot before it, and no lane A
            entry_sc["layout"] = "soloB"
        # Which band of a full-frame shot a half slot shows as it moves in or
        # out: the shot handed into A's slot, and B's in a relay (its framing
        # there, the bottom until it's framed).
        if sc.get("into") == "handoff" and prev and prev["layout"] == "soloB" and prev["parts"]:
            entry_sc["band_a"] = scenes_mod.band_of(by_id[prev["parts"][-1]])
        if relay and sc.get("parts"):
            entry_sc["band_b"] = scenes_mod.band_of(by_id[sc["parts"][0]])
        if sc["layout"] != "soloB" and not relay:
            a, row = sc["a"], lane_rows[sc["a"]["item"]]
            fx, fy, zoom = scenes_mod.frame_for(row, scenes_mod.slot_shape(sc, "A"), "A")
            entry_sc["a"] = {"item": row["id"], "file": str(ROOT / row["path"]), "start": round(row["start"], 3),
                             "end": round(row["start"] + row["length"], 3), "in": a.get("in"), "out": a.get("out"),
                             "duration": round(row["duration"], 3),
                             "timing": a.get("timing", "real"), "speed": a.get("speed", 1),
                             "focus": [round(fx, 3), round(fy, 3)], "zoom": round(zoom, 3)}
            if row["lighten"]:
                entry_sc["a"]["lighten"] = round(row["lighten"], 2)
            if a.get("timing") == "quiet":
                entry_sc["a"]["activity"] = activity_of(ROOT / row["path"])["points"]
        scene_cfg.append(entry_sc)
        if sc["layout"] == "soloA":   # A alone: its range (or the scene's length) sets how long
            a = sc["a"]
            secs = ((a["out"] - a["in"]) / (a.get("speed") or 1) if a.get("in") is not None and a.get("out") is not None
                    else sc.get("len", scenes_mod.SOLO_A_DEFAULT))
            sources.append({"id": f"solo A {k + 1}", "gap": True, "length": round(max(secs, scenes_mod.SOLO_A_MIN), 3),
                            "scene": k})
            continue
        for pid in sc["parts"]:
            row = by_id[pid]
            n = kept_ids.index(pid)
            stem = Path(row["name"]).stem[:14]
            seen[stem] = seen.get(stem, 0) + 1
            entry = {"id": stem if seen[stem] == 1 else f"{stem}-{seen[stem]}",
                     "file": str(ROOT / row["path"]), "scene": k}
            fx, fy, zoom = scenes_mod.frame_for(row, "full" if relay else scenes_mod.slot_shape(sc, "B"), "B")
            if (fx, fy) != (0.5, 0.5):
                entry["focus"] = [round(fx, 3), round(fy, 3)]
            if row["lighten"]:
                entry["lighten"] = round(row["lighten"], 2)
            if zoom > 1.001:
                entry["zoom"] = round(zoom, 3)
            if row["layout"] in ("fill", "blur"):
                entry["fit"] = row["layout"]
            if row["kind"] == "video":
                entry["times"] = [round(row["start"], 2)]
                entry["length"] = round(row["length"], 2)
            else:
                entry["hold"] = round(row["length"], 2)
                entry["in_round"] = "all"
            if synced:
                # A part's own beats; else the whole beats nearest its length (or the reel's fixed count)
                fixed = s.get("beatsFit") == "fixed" or not period
                entry["hold_beats" if row["kind"] == "photo" else "beats"] = (
                    beats_of(row["beats"]) or (int(s.get("beatsPerCut", 4)) if fixed
                                               else nearest_beats(row["length"], period, row["kind"] == "photo")))
            if n + 1 < len(kept):
                entry["transition"] = row["transition"] or s.get("transition") or "cut"
            sources.append(entry)

    w, h = frame_size(s)
    cfg = {"output": str(RENDERS / f"{slug(reel['name'])}.mp4"), "rounds": 1, "sources": sources,
           "width": w, "height": h, "scenes": scene_cfg,
           "stack": {"divider": s["dividerPx"], "divider_color": s["dividerColor"]}}
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
    pieces, lines = voice_timeline(s)
    if pieces:
        for p in pieces:
            if not (ROOT / p["folder"] / p["file"]).exists():
                raise HTTPException(400, f"A voice take is missing: {p['folder']}/{p['file']}")
        cfg["voice"] = {"pieces": [{"file": str(ROOT / p["folder"] / p["file"]), "start": p["start"],
                                    "end": p["end"], "at": p["at"], **({"fx": p["fx"]} if p["fx"] else {})}
                                   for p in pieces],
                        "fit": bool(s.get("voiceFit", True)), "clean": bool(s.get("voiceClean", True)),
                        "song_under": float(s.get("voiceSongUnder", 0.15)),
                        "song_between": float(s.get("voiceSongBetween", 0.3))}
    if lines and s.get("captions", True):
        cfg["captions"] = {"style": s.get("captionStyle"), "font": s.get("captionFont"),
                           "background": s.get("captionBg"), "size": float(s.get("captionSize") or 1),
                           "title": (s.get("captionTitle") or "").strip(), "lines": lines}
    if (s.get("titleText") or "").strip() and s.get("titleCard", True) is not False:   # ticked (or from before the tick)
        cfg["title"] = {"text": s["titleText"].strip()}
        if (s.get("titleSub") or "").strip():
            cfg["title"]["sub"] = s["titleSub"].strip()
        if logos := logo_files(s.get("titleLogo")):
            cfg["title"]["logos"] = logos
    lines = [l.strip() for l in (s.get("endLines") or "").splitlines() if l.strip()]
    if s.get("endCard") and (lines or s.get("endLogo")):
        cfg["end_card"] = {"lines": lines}
        if logos := logo_files(s.get("endLogo")):
            cfg["end_card"]["logos"] = logos
        if s.get("endPresentedBy") in ("oufp", "garden-steward"):
            cfg["end_card"]["presented_by"] = {"text": "presented by",
                                               "logo": logo_files(s["endPresentedBy"])[0]}
        # The last part holds this much longer, with the card over it: beats
        # when cutting on the beat, else about the same at 120 bpm.
        extra = beats_of(s.get("endBeats")) or 4
        cfg["end_card"]["beats" if synced else "hold"] = extra if synced else round(extra * 0.5, 2)
    cfg.update({
        "clip_length": s["defaultLength"],
        "transitions": {"within_round": "cut", "between_rounds": "dissolve",
                        "into_image": "dissolve", "out_of_image": "dissolve",
                        "duration": 0.3},
        "original_audio": glasses_of(s) != "off",
        "glasses_audio": glasses_of(s),
        "duck_music": bool(s.get("duckMusic", True)),
        "mix": {layer: mix_of(s, layer) for layer in ("A", "B", "music", "voice")},
        "original_volume": s.get("originalVolume", 0.35),
        "fit": s.get("fit", "fill"),
        **({"look": s["look"]} if s.get("look") in ("vivid", "rich") else {}),
        "photo_motion": "push",
        "photo_zoom": 0.06,
        "crf": 18,
        "preset": "veryfast",
    })
    return cfg


def words_hit(line, start, end):
    """Which of a caption line's words (first, last index) are said between
    start and end in the take: by the transcript's word times while the text
    still matches them, else all of them. As captions.js."""
    text = " ".join(str(line["text"]).split())
    words = line.get("words") or []
    if words and " ".join(w[0] for w in words) == text:
        hit = [i for i, w in enumerate(words) if w[2] > start + 0.02 and w[1] < end - 0.02]
        if hit:
            return [hit[0], hit[-1]]
    return [0, len(text.split()) - 1]


def voice_timeline(s):
    """A reel's voice pieces placed one after another (each after its breath),
    and their caption lines, on the reel's clock. Same as captions.js."""
    pieces, lines, t = [], [], 0.0
    for p in s.get("voice") or []:
        start, end = float(p.get("start") or 0), float(p.get("end") or 0)
        if end - start < 0.1:
            continue
        t += max(0.0, float(p.get("gap") or 0))
        fx = [{"start": round(max(float(f["s"]), start), 3), "end": round(min(float(f["e"]), end), 3),
               "effect": f["effect"], "amount": float(f.get("amount") or 1)}
              for f in p.get("fx") or [] if f.get("effect") and min(float(f["e"]), end) - max(float(f["s"]), start) >= 0.1]
        pieces.append({"folder": p["folder"], "file": p["file"], "start": round(start, 3),
                       "end": round(end, 3), "at": round(t, 3), "fx": fx})
        for l in p.get("lines") or []:
            ls, le = max(float(l["s"]), start), min(float(l["e"]), end)
            if le - ls < 0.05 or not str(l.get("text", "")).strip():
                continue
            line = {"start": round(t + ls - start, 3), "end": round(t + le - start, 3),
                    "text": " ".join(str(l["text"]).split()), "stanza": bool(l.get("br"))}
            if s.get("captionFx", True):
                hits = [{**f, "start": round(t + f["start"] - start, 3), "end": round(t + f["end"] - start, 3),
                         "words": words_hit(l, f["start"], f["end"])}
                        for f in fx if min(f["end"], l["e"]) - max(f["start"], l["s"]) > 0.1]
                if hits:
                    line["fx"] = hits
            lines.append(line)
        t += end - start
    return pieces, lines


def logo_files(choice):
    """The logo PNGs for a title or end card choice, which must be in brand/."""
    paths = [BRAND / name for name in LOGOS.get(choice or "", [])]
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        raise HTTPException(400, f"Put {' and '.join(missing)} (transparent PNG) in {BRAND}")
    return [str(p) for p in paths]


def reel_and_rows(reel_id):
    with lib.connect() as db:
        reel = reel_row(db, reel_id)
        rows = db.execute("""SELECT i.*, m.path, m.name, m.kind, m.missing, m.duration FROM reel_items i
                             JOIN media m ON m.id = i.media_id
                             WHERE i.reel_id = ? ORDER BY i.position, i.id""",
                          (reel_id,)).fetchall()
    return reel, rows


def write_config(reel_id):
    """Write the reel's YAML for the engine; returns (path, config)."""
    reel, rows = reel_and_rows(reel_id)
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


@app.get("/api/reels/{reel_id}/card/{kind}")
def card_preview(reel_id: int, kind: str):
    """The title (over the first part) or end card (over the last), as the
    render will draw it, at half size."""
    from PIL import Image, ImageOps
    import montage
    if kind not in ("title", "end_card"):
        raise HTTPException(404, "No such card")
    reel, rows = reel_and_rows(reel_id)
    cfg = build_config(reel, rows)
    if kind not in cfg:
        raise HTTPException(400, "Type a title first." if kind == "title" else "Turn on the end card first.")
    kept = [r for r in rows if r["keep"] and not r["missing"]]
    if not kept:
        raise HTTPException(400, "Nothing is kept in this reel yet.")
    row = kept[0] if kind == "title" else kept[-1]
    w, h = cfg["width"], cfg["height"]
    card = next(c for c in montage.load_cards(cfg, ENGINE.parent) if c["kind"] == kind)
    CACHE.mkdir(parents=True, exist_ok=True)
    png = montage.render_card(card, cfg, ENGINE.parent, CACHE / f"card-{reel_id}-{kind}.png")
    t = row["start"] + (0 if kind == "title" else row["length"] / 2)
    frame = Image.open(thumb_file(ROOT / row["path"], t, 1280)).convert("RGBA")
    frame = ImageOps.fit(frame, (w, h), centering=(row["focus_x"], row["focus_y"]))
    frame.alpha_composite(Image.open(png))
    out = CACHE / f"card-{reel_id}-{kind}.jpg"
    frame.convert("RGB").resize((w // 2, h // 2), Image.LANCZOS).save(out, quality=88)
    return FileResponse(out, headers={"Cache-Control": "no-store"})


@app.get("/api/reels/{reel_id}/captions/preview")
def caption_preview(reel_id: int, item: int, src: float = 0.0, t: float = 0.0):
    """The captions at reel time t, drawn as the render will, over the frame
    of the part playing then (item, at src seconds into its clip), half size."""
    import tempfile
    from PIL import Image, ImageFilter, ImageOps
    import montage
    reel, rows = reel_and_rows(reel_id)
    cfg = build_config(reel, rows)
    if "captions" not in cfg:
        raise HTTPException(400, "Add a voice piece with lines first.")
    row = next((r for r in rows if r["id"] == item), None)
    if not row or row["missing"]:
        raise HTTPException(404, "No such part")
    cfg.update(fps=30)
    w, h = cfg["width"], cfg["height"]
    frame = Image.open(thumb_file(ROOT / row["path"], src, 1280)).convert("RGBA")
    frame = ImageOps.fit(frame, (w, h), centering=(row["focus_x"], row["focus_y"]))
    cap = cfg["captions"]
    with tempfile.TemporaryDirectory() as tmp:
        for l in montage.caption_layers(cap["lines"], cap, cfg, ENGINE.parent, Path(tmp), 1e9):
            a = layer_alpha(l, t)
            if l.get("pulse"):
                hz, t0 = l["pulse"]
                a *= 0.6 + 0.4 * math.sin(2 * math.pi * hz * (t - t0))
            if a <= 0.001:
                continue
            x, y = l["x"], l["y"]
            # an effect's moving copy: the same expressions the render uses
            move = {"cos": math.cos, "sin": math.sin, "PI": math.pi, "t": t, "__builtins__": {}}
            if l.get("xmove"):
                x += eval(l["xmove"], move)
            if l.get("ymove"):
                y += eval(l["ymove"], move)
            if l.get("drift"):
                up, away, ga, gb, fi, fo = l["drift"]
                y += up * max(0, 1 - (t - ga) / max(fi, 0.01)) - away * max(0, 1 - (gb - t) / max(fo, 0.01))
            if l["kind"] == "png":
                im = Image.open(l["path"]).convert("RGBA")
            elif l["kind"] == "color":
                rgb, alpha = l["color"].split("@")
                im = Image.new("RGBA", l["size"], (*bytes.fromhex(rgb[2:]), round(255 * float(alpha))))
            else:
                box = (round(x), round(y), round(x) + l["size"][0], round(y) + l["size"][1])
                im = frame.crop(box).filter(ImageFilter.GaussianBlur(l["sigma"]))
            im.putalpha(im.getchannel("A").point(lambda v: v * a))
            layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
            layer.paste(im, (round(x), round(y)))
            frame = Image.alpha_composite(frame, layer)
    out = CACHE / f"captions-{reel_id}.jpg"
    frame.convert("RGB").resize((w // 2, h // 2), Image.LANCZOS).save(out, quality=88)
    return FileResponse(out, headers={"Cache-Control": "no-store"})


def layer_alpha(l, t):
    """How visible a caption layer is at t, with its fades."""
    if t < l["t0"] or t > l["t1"]:
        return 0.0
    a = 1.0
    if l["fi"] > 0:
        a = min(a, (t - l["t0"]) / l["fi"])
    if l["fo"] > 0:
        a = min(a, (l["t1"] - t) / l["fo"])
    return max(0.0, min(a, 1.0))


@app.post("/api/reels/{reel_id}/export")
def export(reel_id: int):
    out, cfg = write_config(reel_id)
    result = subprocess.run([sys.executable, str(ENGINE), str(out), "--dry-run"],
                            capture_output=True, text=True, timeout=300)
    return {"path": str(out), "ok": result.returncode == 0,
            "dryRun": (result.stdout + result.stderr).strip(),
            "output": cfg["output"],
            "command": f'python3 "{ENGINE}" "{out}"'}


# ---------------------------------------------------------------- AI music
# A track made for the reel (see compose.py): as long as the reel runs at the
# tempo asked for, styled on songs from the shelf, building up and breaking
# down across it. It lands on the shelf like any other song.

measured = {}   # shelf cache file name -> compose.measure() of that song


def reel_length(reel_id, bpm):
    """How long the reel runs, in seconds, with a song at this tempo: the
    engine's own plan, so it matches the render."""
    import montage as engine
    reel, rows = reel_and_rows(reel_id)
    cfg = build_config(reel, rows, grid_bpm=bpm)
    if not cfg["sources"]:
        raise HTTPException(400, "Nothing is kept in this reel yet.")
    cfg.update({"fps": 30})
    try:
        top = engine.load_top(cfg, ROOT)
        voice = engine.load_voice(cfg, ROOT)
        beats = [i * 60.0 / bpm for i in range(4000)] if settings_of(reel).get("beatSync") else None
        plan, _ = engine.build_plan(cfg, ROOT, beats, voice)
    except SystemExit as e:
        raise HTTPException(400, str(e))
    under = sum(seg["length"] for seg in plan)
    return round(engine.top_length(top, under) if top else under, 2), bool(beats)


def reel_timeline(reel_id, bpm):
    """The reel at this tempo, as the engine plans it: (seconds, synced,
    [{layout, start, end}] per scene)."""
    import montage as engine
    reel, rows = reel_and_rows(reel_id)
    cfg = build_config(reel, rows, grid_bpm=bpm)
    if not cfg["sources"]:
        raise HTTPException(400, "Nothing is kept in this reel yet.")
    cfg.update({"fps": 30})
    try:
        voice = engine.load_voice(cfg, ROOT)
        beats = [i * 60.0 / bpm for i in range(4000)] if settings_of(reel).get("beatSync") else None
        plan, _ = engine.build_plan(cfg, ROOT, beats, voice)
    except SystemExit as e:
        raise HTTPException(400, str(e))
    scenes, t = [], 0.0
    layouts = [sc.get("layout", "soloB") for sc in cfg.get("scenes") or []]
    for seg in plan:
        k = seg.get("scene") or 0
        if not scenes or scenes[-1]["k"] != k:
            scenes.append({"k": k, "layout": layouts[k] if k < len(layouts) else "soloB", "start": round(t, 3)})
        t += seg["length"]
        scenes[-1]["end"] = round(t, 3)
    seconds, synced = reel_length(reel_id, bpm)
    if scenes:
        scenes[-1]["end"] = seconds
    return seconds, synced, [{k: v for k, v in sc.items() if k != "k"} for sc in scenes]


def reference(names):
    """The shelf songs to take the style from, measured, plus their categories."""
    shelf_now = {t["name"]: t for t in music_shelf()["tracks"]}
    refs, cats = [], []
    for name in names or []:
        path = shelf.path_of(name)
        if name not in shelf_now or not path.exists():
            raise HTTPException(404, f"No song called {name} on the shelf")
        try:
            k = shelf.cache_file(path).name
            if k not in measured:
                measured[k] = {**compose.measure(path, shelf.analyze(path)), "name": name,
                               "title": shelf_now[name]["title"]}
            refs.append(measured[k])
        except ImportError:
            raise HTTPException(400, "Taking the style from a song needs beat detection: "
                                     "start the studio with ./studio/run.sh --beat")
        cats += [c for c in shelf_now[name]["categories"] if c.lower() != "ai" and c not in cats]
    return refs, cats


def compose_plan(reel_id, body):
    refs, cats = reference(body.get("refs"))
    style = compose.blend(refs)
    bpm = float(body.get("bpm") or style.get("bpm") or 100)
    if not 50 <= bpm <= 200:
        raise HTTPException(400, "Pick a tempo between 50 and 200 bpm.")
    key = (body.get("key") or "").strip() or style.get("key")
    words = style.get("words", [])
    genre = (body.get("style") or "").strip() or ", ".join(cats)
    seconds, synced = reel_length(reel_id, bpm)
    model = "clip" if body.get("model") == "clip" else "pro"
    asked = min(seconds, compose.CLIP_SECONDS) if model == "clip" else seconds
    sections = compose.arc(asked, bpm)
    return {"seconds": seconds, "asked": asked, "synced": synced, "bpm": bpm, "key": key, "style": genre,
            "words": words, "model": model, "sections": sections,
            "refs": [{k: r[k] for k in ("name", "title", "bpm", "key", "words")} for r in refs],
            "prompt": compose.prompt(asked, bpm, key, genre, words, body.get("notes") or "", sections)}


@app.get("/api/reels/{reel_id}/beat/length")
def beat_length(reel_id: int, bpm: float = 100):
    """How long the reel runs with a beat at this tempo (its parts are whole
    beats when cutting on the beat): {seconds, synced}."""
    if not beats_mod.TEMPO_RANGE[0] <= bpm <= beats_mod.TEMPO_RANGE[1]:
        raise HTTPException(400, "Pick a tempo between 60 and 180 bpm.")
    seconds, synced, scenes = reel_timeline(reel_id, bpm)
    return {"seconds": seconds, "synced": synced, "bpm": bpm, "scenes": scenes}


@app.get("/api/music/{name}/style")
def music_style(name: str):
    """What a song sounds like, for the beat builder's Start from: {bpm, key,
    words}, or {measured: false} without beat detection installed."""
    try:
        refs, _ = reference([name])
    except HTTPException as e:
        if e.status_code == 400:
            return {"measured": False, "why": e.detail}
        raise
    r = refs[0]
    return {"measured": True, "bpm": r["bpm"], "key": r["key"], "words": r["words"]}


# ---------------------------------------------------------------- the beat studio

beat_jobs = {}   # job id -> beats.Job; and reel id -> its latest job id
beat_latest = {}


def beat_context(reel_id, beat, length=None, measure=True, say=None):
    """What a run of takes needs from the reel: the length and scene edges at
    the beat's tempo, and the style (the reference song measured, its
    categories, the levers' words, tempo and key)."""
    reel, _ = reel_and_rows(reel_id)
    ref, genres, ref_line = None, [], ""
    src = beat["from"]
    st = beats_mod.style_of(src) if src["kind"] == "style" else None
    if st:   # a built-in style: its words are the genre
        genres = list(st[1][1])
        ref_line = f"In a {st[1][0].lower()} style ({st[0].lower()}): {', '.join(st[1][1])}"
    if src["kind"] == "song" and measure:
        track = next((t for t in music_shelf()["tracks"] if t["name"] == src["name"]), None)
        genres = [c for c in (track or {}).get("categories", []) if c.lower() != "ai"]
        try:
            path = shelf.path_of(src["name"])
            if say and path and path.exists() and shelf.cache_file(path).name not in measured:
                say(f"Listening to {(track or {}).get('title') or src['name']} for its tempo, key and tone "
                    "(the first time takes a little while)…")
            ref = reference([src["name"]])[0][0]
            ref_line = (f"Taking the groove from {ref['title']}: "
                        + (f"{round(ref['bpm'])} BPM, " if ref["bpm"] >= 40 else "")
                        + f"{ref['key']}, {', '.join(ref['words'])}")
        except HTTPException:
            ref_line = f"Taking the style from {src.get('category') or src['name']} (its categories; measuring it needs --beat)"
    tempo = beats_mod.tempo_of(beat)
    key = beats_mod.key_of(beat, ref["key"] if ref else "")
    seconds, _, scenes = reel_timeline(reel_id, tempo)
    style = {"genres": genres, "words": ref["words"] if ref else [], "levers": beats_mod.lever_words(beat),
             "instruments": beats_mod.instrument_words(beat),
             "tempo": tempo, "key": key}
    return {"beat": beat, "length": length or seconds, "edges": [sc["start"] for sc in scenes[1:]],
            "style": style, "ref_line": ref_line, "reel_name": reel["name"]}


def beat_prompt_text(ctx):
    s = ctx["style"]
    head = f"{s['tempo']} BPM, {s['key']}"
    if s["genres"]:
        head += f", {', '.join(s['genres'])}"
    calm = (ctx["beat"].get("ceiling") or 1) <= 0.65
    tail = "Stays relaxed and steady the whole way, a gentle lift, no big drops" if calm else ""
    feat = f"Featuring {', '.join(s['instruments'])}" if s.get("instruments") else ""
    return ". ".join(x for x in [head, feat, ", ".join(s["levers"] + s["words"]), tail] if x) + "."


@app.get("/api/reels/{reel_id}/beat/preview")
def beat_preview(reel_id: int):
    """The beat as it would be asked for now: the reel's length and scenes at
    its tempo, and the sections the music is cut into (the same plan a run
    uses), for the studio's picture of it."""
    reel, _ = reel_and_rows(reel_id)
    beat = beats_mod.clean(settings_of(reel).get("beat"))
    if not beat:
        raise HTTPException(400, "No beat set up yet")
    tempo = beats_mod.tempo_of(beat)
    seconds, synced, scenes = reel_timeline(reel_id, tempo)
    try:
        secs = beats_mod.sections(beat, seconds, [sc["start"] for sc in scenes[1:]])
    except beats_mod.BeatError as e:
        secs, err = [], str(e)
    else:
        err = None
    return {"seconds": seconds, "synced": synced, "tempo": tempo, "scenes": scenes, "sections": secs, "error": err}


VIBE_NAMES = {"garden": "Garden morning", "ecstatic": "Ecstatic dance", "street": "Street grit", "lofi": "Lo-fi chill"}


def take_name(beat):
    """What a take is, in a few words: its style, the song it's from, or the vibe."""
    src = beat["from"]
    st = beats_mod.style_of(src) if src["kind"] == "style" else None
    if st:
        return st[1][0]
    if src["kind"] == "song":
        track = next((t for t in music_shelf()["tracks"] if t["name"] == src["name"]), None)
        return f"from {(track or {}).get('title') or src['name']}"
    return VIBE_NAMES.get(beat.get("vibe"), "your levers")


@app.post("/api/reels/{reel_id}/beat/generate")
def beat_generate(reel_id: int, body: dict = Body(default={})):
    """Make a take from the reel's beat settings (body.lean: one of LEANS to
    lean it a direction; body.count: 3 for three leaning each way); or one Adapted from a
    take (body.adapt: {take, tweaks: [ADAPTS keys], note}: its seed, tempo
    and plan, changed that way); or Rebuild to new length (body.rebuild: the
    take in use, at the reel's length now; it replaces that take in the reel
    when done). Takes are numbered on from the reel's last."""
    reel, _ = reel_and_rows(reel_id)
    s = settings_of(reel)
    beat = beats_mod.clean(s.get("beat"))
    if not beat:
        raise HTTPException(400, "Open the beat studio and set up a beat first.")
    running = beat_jobs.get(beat_latest.get(reel_id))
    if running and running.status == "running":
        return running.view()
    engine = body.get("engine") if body.get("engine") in beats_mod.ENGINES else beat["engine"]
    base, extra, label = None, [], ""
    adapt = body.get("adapt") if isinstance(body.get("adapt"), dict) else ({"take": body["like"]} if body.get("like") else None)
    tid = (adapt or {}).get("take") or body.get("rebuild")
    all_takes = beats_mod.list_takes(lib.home, reel_id)
    if tid:
        base = next((t for t in all_takes if t["id"] == str(tid)), None)
        if not base:
            raise HTTPException(404, "No such take")
        engine = base["engine"]
        if adapt:
            beat, extra, label = beats_mod.adapted(beats_mod.clean(base["beat"]), adapt.get("tweaks") or [], adapt.get("note"))
            beat["tempo"], beat["key"] = base["tempo"], base["key"]   # stays in time with the cut
            if beat.get("prompt") and extra:
                beat["prompt"] += " " + ", ".join(extra) + "."
        else:
            beat = beats_mod.clean(base["beat"])   # the same beat, only longer or shorter
            label = "rebuilt for the new cut"
    lean = body.get("lean") if body.get("lean") in beats_mod.LEANS else None
    n = 1 if base or body.get("count") != 3 else 3
    first = max([t.get("n") or 0 for t in all_takes] + [0]) + 1   # numbered on from the last take
    if engine == "elevenlabs":
        try:
            beats_mod.eleven_key()
        except beats_mod.BeatError as e:
            raise HTTPException(400, str(e))
    job = beats_mod.Job(reel_id, engine, n)
    for i, t in enumerate(job.takes):
        t["n"] = first + i
    if base:
        job.source = base["id"]
        job.takes[0]["label"] = label
    beat_jobs[job.id] = job
    beat_latest[reel_id] = job.id

    def lyria(text):
        try:
            audio, _ = compose.call(text, compose.MODELS["pro"], lib.home / "music" / "ai")
            return audio
        except compose.ComposeError as e:
            raise beats_mod.BeatError(str(e))

    def go():
        # Working out the reel and the song can take a while (measuring a song
        # the first time): the run has started, and says so, meanwhile.
        try:
            ctx = beat_context(reel_id, beat, say=job.say)
        except (beats_mod.BeatError, HTTPException) as e:
            job.status, job.error = "failed", getattr(e, "detail", None) or str(e)
            job.say(job.error, "error")
            job.finished = time.time()
            return
        ctx["prompt"] = beat_prompt_text(ctx)
        if base:
            ctx["seeds"] = [base.get("seed") or random.randrange(2 ** 31)]
            ctx["variations"] = [(base.get("variation") or []) + extra]
            ctx["labels"] = [label]
            ctx["from"], ctx["fromN"] = base["id"], base.get("n")
            job.say(f"{'Adapting' if adapt else 'Rebuilding'} take {base.get('n')} ({base.get('label')}): "
                    f"{label}, with its seed and tempo ({base['tempo']} BPM)")
        elif n == 3:
            name = take_name(beat)
            ctx["seeds"] = [random.randrange(2 ** 31) for _ in range(n)]
            ctx["variations"] = [v for _, v in beats_mod.VARIATIONS]
            ctx["labels"] = [f"{name} · {label}" for label, _ in beats_mod.VARIATIONS]
        else:   # one take: as set, or leaning one way
            name = take_name(beat)
            ctx["seeds"] = [random.randrange(2 ** 31)]
            ctx["variations"] = [beats_mod.LEANS[lean][1] if lean else []]
            ctx["labels"] = [f"{name} · {beats_mod.LEANS[lean][0]}" if lean and lean != "fresh" else name]
        beats_mod.run_job(job, ctx, lib.home, lyria)
        if body.get("rebuild") and job.status == "done":
            use_take(reel_id, job.takes[0]["take"])
            job.say("The rebuilt take is in the reel now.", "done")
    threading.Thread(target=go, daemon=True).start()
    return job.view()


@app.get("/api/beat/jobs/{job_id}")
def beat_job(job_id: str):
    job = beat_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "No such run (the studio restarted?)")
    return job.view()


@app.get("/api/reels/{reel_id}/beat/job")
def beat_last_job(reel_id: int):
    """The reel's latest run, if the studio has one (to pick it up after a reload)."""
    job = beat_jobs.get(beat_latest.get(reel_id))
    return job.view() if job else None


@app.get("/api/reels/{reel_id}/beat/takes")
def beat_takes(reel_id: int):
    keep = ("id", "run", "n", "label", "engine", "model", "seed", "length", "generated", "tempo", "key",
            "prompt", "sections", "created", "took", "from", "fromN", "starred", "beat")
    return [{k: t.get(k) for k in keep} for t in beats_mod.list_takes(lib.home, reel_id)]


def beat_take_path(reel_id, take_id):
    if not re.fullmatch(r"[\w-]{1,40}", take_id):
        raise HTTPException(404, "No such take")
    p = beats_mod.takes_dir(lib.home, reel_id) / f"{take_id}.mp3"
    if not p.exists():
        raise HTTPException(404, "No such take")
    return p


@app.get("/api/reels/{reel_id}/beat/takes/{take_id}/audio")
def beat_take_audio(reel_id: int, take_id: str):
    return FileResponse(beat_take_path(reel_id, take_id), media_type="audio/mpeg")


@app.get("/api/reels/{reel_id}/beat/takes/{take_id}/envelope")
def beat_take_envelope(reel_id: int, take_id: str):
    return audio.envelope(beat_take_path(reel_id, take_id), CACHE)


def use_take(reel_id, take_id):
    """Put a take on the reel: copied to the music shelf (category AI) and
    made the reel's song, from its start."""
    src = beat_take_path(reel_id, take_id)
    meta = json.loads(src.with_suffix(".json").read_text())
    reel, _ = reel_and_rows(reel_id)
    safe = re.sub(r"[^\w\- ]+", "", reel["name"]).strip()[:40] or "reel"
    name = f"Beat {safe} take {meta['n']} {take_id}.mp3"
    shelf.folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, shelf.folder / name)
    with lib.connect() as db:
        db.execute("INSERT OR REPLACE INTO songs (name, title, artist, categories) VALUES (?, ?, ?, ?)",
                   (name, f"Beat · {reel['name']} · {meta['label']}", "ElevenLabs" if meta["engine"] == "elevenlabs"
                    else "Lyria", json.dumps(["AI"])))
    s = settings_of(reel)
    beat = beats_mod.clean(s.get("beat")) or {}
    beat["inUse"] = {"take": take_id, "length": meta["length"], "tempo": meta["tempo"]}
    update_reel(reel_id, {"settings": {"music": name, "musicStart": 0, "beat": beat}})
    return name


@app.post("/api/reels/{reel_id}/beat/takes/{take_id}/use")
def beat_use(reel_id: int, take_id: str):
    return {"music": use_take(reel_id, take_id)}


@app.post("/api/reels/{reel_id}/beat/takes/{take_id}/star")
def beat_star(reel_id: int, take_id: str, body: dict = Body(default={})):
    """Star a take you like (body.starred: true/false)."""
    meta_path = beat_take_path(reel_id, take_id).with_suffix(".json")
    meta = json.loads(meta_path.read_text())
    meta["starred"] = bool(body.get("starred", True))
    meta_path.write_text(json.dumps(meta, indent=1))
    return {"starred": meta["starred"]}


@app.get("/api/beat/styles")
def beat_styles():
    """The styles to start from, by family: [{v, label, styles: [{v, label,
    words, levers, instruments, tempo}]}]."""
    return [{"v": f, "label": label, "styles": [
        {"v": k, "label": st[0], "words": st[1], "levers": st[2], "instruments": st[3], "tempo": st[4]}
        for k, st in styles.items()]} for f, (label, styles) in beats_mod.STYLES.items()]


@app.get("/api/beat/instruments")
def beat_instruments():
    """The instruments a beat can ask for by name: [{v, label}]."""
    return [{"v": k, "label": v[0], "words": v[1]} for k, v in beats_mod.INSTRUMENTS.items()]


@app.get("/api/beat/adapts")
def beat_adapts():
    """The ways a take can be adapted: [{v, label}]."""
    return [{"v": k, "label": v[0]} for k, v in beats_mod.ADAPTS.items()]


@app.delete("/api/reels/{reel_id}/beat/takes/{take_id}")
def beat_delete(reel_id: int, take_id: str):
    p = beat_take_path(reel_id, take_id)
    p.unlink()
    p.with_suffix(".json").unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/reels/{reel_id}/compose/plan")
def compose_preview(reel_id: int, body: dict = Body(default={})):
    """What would be asked for: the reel's length at the tempo, the arc, the
    prompt. {refs: [shelf names], bpm, key, style, notes, model: pro|clip}"""
    return compose_plan(reel_id, body)


@app.post("/api/reels/{reel_id}/compose")
def compose_track(reel_id: int, body: dict = Body(default={})):
    """Make the track (the same as /compose/plan, or body.prompt as edited)
    and put it on the shelf. Takes a minute or so."""
    plan = compose_plan(reel_id, body)
    reel, _ = reel_and_rows(reel_id)
    shelf.folder.mkdir(parents=True, exist_ok=True)
    try:
        done = compose.compose(plan["asked"], plan["bpm"], shelf.folder, reel["name"], plan["key"],
                               plan["style"], plan["words"], model=plan["model"],
                               text=(body.get("prompt") or "").strip() or plan["prompt"],
                               log_dir=lib.home / "music" / "ai")
    except compose.ComposeError as e:
        raise HTTPException(502, str(e))
    note = ""
    if beat_detection_available():
        got = shelf.analyze(Path(done["path"]))
        if abs(got["bpm"] - plan["bpm"]) > 1.5 and abs(got["bpm"] - 2 * plan["bpm"]) > 3 \
                and abs(got["bpm"] - plan["bpm"] / 2) > 1.5:
            note = (f"Asked for {plan['bpm']:.0f} bpm, it came out at about {got['bpm']:.0f}, so the "
                    f"build-ups may sit a little off the parts.")
    return {**done, "note": note, "reelSeconds": plan["seconds"], "shelf": music_shelf()}


# ---------------------------------------------------------------- render

# One render at a time per reel, run in the background; the page polls.
jobs = {}           # job id -> job dict
latest = {}         # reel id -> job id
jobs_lock = threading.Lock()


def job_view(job):
    return {k: job.get(k) for k in ("id", "reelId", "status", "stage", "done", "total",
                                    "output", "startedAt", "finishedAt", "log", "note", "steps")}


# The engine's progress lines that start a step of the render (each part cut,
# each scene, A moving, joining, captions, cards, mixing): kept with when they
# started, so the studio can show what took how long.
STEP_LINE = re.compile(r"(cutting \d+/\d+|scene \d+/\d+|moving A|joining|stacking|laying the|mixing|ducking|using the title)")


def note_step(job, line):
    label = re.sub(r"\.\.\.$", "", line).strip()
    steps = job.setdefault("steps", [])
    if not steps or steps[-1]["label"] != label:
        steps.append({"label": label, "at": now()})
        del steps[:-400]


def run_render(job, config_path):
    proc = subprocess.Popen([sys.executable, "-u", str(ENGINE), str(config_path)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    buf = b""
    while True:
        chunk = proc.stdout.read1(4096)   # what's there now: a full read would wait for 4 KB
        if not chunk:
            break
        buf += chunk
        # The engine redraws its progress line with \r.
        *lines, buf = re.split(rb"[\r\n]", buf)
        for raw in lines:
            line = raw.decode(errors="replace").strip()
            if not line:
                continue
            if STEP_LINE.match(line):
                note_step(job, line)
            m = re.match(r"cutting (\d+)/(\d+)", line)
            if m:
                job["stage"], job["done"], job["total"] = "cutting", int(m[1]), int(m[2])
            elif line.startswith("joining"):
                job["stage"] = "joining"
            elif line.startswith("scene "):
                job["stage"] = "scenes"
            elif line.startswith("laying the title"):
                job["stage"] = "cards"
            elif line.startswith("laying the captions"):
                job["stage"] = "captions"
            elif line.startswith("mixing"):
                job["stage"] = "mixing"
            elif line.startswith("Song left out"):
                job["note"] = line
            else:
                job["log"] = (job["log"] + [line])[-60:]
    proc.wait()
    note_step(job, "finished")
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
               "output": cfg["output"], "startedAt": now(), "finishedAt": None, "log": [],
               "steps": [], "config": str(out)}
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
def media(name: str, file: str, q: str = ""):
    """A file, as it is. q=low: a small copy of a video for a quicker
    preview (made once in the background; the original until it's ready).
    Renders always use the originals."""
    path = resolve(name, file)
    if q == "low" and Library.kind_of(path) == "video":
        low = low_copy(path)
        if low:
            return FileResponse(low, media_type="video/mp4")
        return FileResponse(path, headers={"Cache-Control": "no-store"})   # so the copy is picked up next time
    return FileResponse(path)


LOW_HEIGHT = 540   # a low-quality copy's shorter side, in pixels
_low_pool = ThreadPoolExecutor(max_workers=2)
_low_jobs = {}     # copy path -> its Future, while it's being made
_low_lock = threading.Lock()


def low_path(path):
    key = hashlib.sha1(f"low{LOW_HEIGHT}|{path}|{path.stat().st_mtime}".encode()).hexdigest()
    return CACHE / "low" / f"{key}.mp4"


def make_low(path, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f"{out.stem}.{uuid.uuid4().hex}.tmp.mp4")   # never served half-written
    s = LOW_HEIGHT   # the shorter side, never larger than it was
    scale = f"scale='if(gt(iw,ih),-2,min({s},iw))':'if(gt(iw,ih),min({s},ih),-2)'"
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(path),
                        "-vf", f"{montage.hdr_fix(path)}{scale},format=yuv420p",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-g", "15",
                        "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(tmp)],
                       check=True, capture_output=True, timeout=1800)
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
        with _low_lock:
            _low_jobs.pop(out, None)


def low_copy(path, start=True):
    """The low-quality copy of a video if it's made, else None (and, with
    start, it's queued to be made)."""
    out = low_path(path)
    if out.exists():
        return out
    if start:
        with _low_lock:
            if out not in _low_jobs:
                _low_jobs[out] = _low_pool.submit(make_low, path, out)
    return None


@app.post("/api/reels/{reel_id}/low-copies")
def reel_low_copies(reel_id: int):
    """Make low-quality copies of a reel's videos (those not made yet are
    queued): {ready, total, made (the folder/file of each one made)}. Call
    again to see how far it's got."""
    with lib.connect() as db:
        reel_row(db, reel_id)
        paths = sorted({r["path"] for r in db.execute(
            "SELECT DISTINCT m.path FROM reel_items i JOIN media m ON m.id = i.media_id "
            "WHERE i.reel_id = ? AND m.kind = 'video' AND m.missing = 0", (reel_id,))})
    made = [p for p in paths if low_copy(ROOT / p)]
    return {"ready": len(made), "total": len(paths), "made": made}


@app.get("/api/thumb/{name}/{file}")
def thumb(name: str, file: str, t: float = 0.0, w: int = 480):
    return make_thumb(resolve(name, file), t, w)


@app.get("/api/activity/{name}/{file}")
def activity(name: str, file: str):
    """How much happens along a clip: [[seconds, 0..1], ...], for Weave's
    movement lane and 'Suggest busy moments'. Cached per file."""
    path = resolve(name, file)
    if Library.kind_of(path) != "video":
        raise HTTPException(400, "Not a video")
    return activity_of(path)


def activity_of(path):
    """{points: [[seconds, 0..1], ...]} for a video, measured once and cached."""
    key = hashlib.sha1(f"activity|{path}|{path.stat().st_mtime}".encode()).hexdigest()
    out = CACHE / f"{key}.json"
    if not out.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f"{key}.{uuid.uuid4().hex}.tmp")   # never read half-written
        tmp.write_text(json.dumps({"points": movement(path)}))
        tmp.replace(out)
    return json.loads(out.read_text())


def activity_cached(path):
    """activity_of's result if it's been measured already, else None."""
    key = hashlib.sha1(f"activity|{path}|{path.stat().st_mtime}".encode()).hexdigest()
    out = CACHE / f"{key}.json"
    return json.loads(out.read_text()) if out.exists() else None


@app.post("/api/envelopes")
def envelopes(body: dict = Body(...)):
    """How loud each file is along its length (see audio.py), for the audio
    rows under a reel's timeline: {mediaId: {step, db, duration, hasAudio}}.
    Measured once per file and cached; photos have no sound."""
    ids = [int(i) for i in body.get("mediaIds") or []][:500]
    if not ids:
        return {}
    with lib.connect() as db:
        rows = db.execute(f"SELECT id, path FROM media WHERE kind = 'video' AND missing = 0 "
                          f"AND id IN ({', '.join('?' * len(ids))})", ids).fetchall()

    def one(r):
        path = ROOT / r["path"]
        try:
            return audio.envelope(path, CACHE) if path.exists() else None
        except (OSError, subprocess.SubprocessError):
            return None   # unreadable: drawn as silence

    with ThreadPoolExecutor(max_workers=4) as pool:
        return {r["id"]: e for r, e in zip(rows, pool.map(one, rows)) if e}


@app.post("/api/looks")
def photo_looks(body: dict = Body(...)):
    """What's in each photo, for Smart hold: {detects, looks: {mediaId:
    {people, animals, look}}} (see looks.py). people and animals are null
    where it can't tell; detects says whether it ever can. Cached per file."""
    ids = [int(i) for i in body.get("mediaIds") or []][:500]
    if not ids:
        return {"detects": looks.can_detect(), "looks": {}}
    with lib.connect() as db:
        rows = db.execute(f"SELECT id, path FROM media WHERE kind = 'photo' AND missing = 0 "
                          f"AND id IN ({', '.join('?' * len(ids))})", ids).fetchall()
    with ThreadPoolExecutor(max_workers=4) as pool:
        found = pool.map(lambda r: look_of(ROOT / r["path"]), rows)
        return {"detects": looks.can_detect(), "looks": {r["id"]: f for r, f in zip(rows, found)}}


def look_of(path):
    if not path.exists():
        return {"look": None, "people": None, "animals": None}
    key = hashlib.sha1(f"look|{looks.can_detect()}|{path}|{path.stat().st_mtime}".encode()).hexdigest()
    out = CACHE / f"{key}.json"
    if not out.exists():
        try:
            found = {"look": looks.look(thumb_file(path, 0.0, 320))}
        except HTTPException:
            found = {"look": None}
        try:
            found.update(looks.subjects(path) or {"people": None, "animals": None})
        except Exception:   # Vision couldn't read it; the photo just isn't known
            found.update(people=None, animals=None)
        tmp = out.with_name(f"{key}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(found))
        tmp.replace(out)
    return json.loads(out.read_text())


def movement(path):
    """The mean difference between successive keyframes (scdet's mafd), which
    is cheap: only keyframes are decoded. Clips with too few keyframes are
    sampled once a second instead. Smoothed and scaled to 0..1 against the
    95th percentile, so one big jump doesn't flatten the rest."""
    def measure(decode, vf):
        try:
            text = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", *decode, "-i", str(path),
                                   "-vf", f"{vf}scale=160:-2,scdet=threshold=100,metadata=print:file=-",
                                   "-an", "-f", "null", "-"],
                                  capture_output=True, text=True, timeout=300).stdout
        except subprocess.TimeoutExpired:
            return []
        points, t = [], None
        for line in text.splitlines():
            if m := re.search(r"pts_time:([\d.]+)", line):
                t = float(m[1])
            elif (m := re.match(r"lavfi\.scd\.mafd=([\d.]+)", line)) and t is not None:
                points.append([t, float(m[1])])
        return points[1:]   # the first frame has nothing to compare with

    points = measure(["-skip_frame", "nokey"], "")
    if len(points) < 4:
        points = measure([], "fps=1,")
    if not points:
        return []
    raw = [v for _, v in points]
    smooth = []
    for i in range(len(raw)):
        near = raw[max(0, i - 1):i + 2]
        smooth.append(sum(near) / len(near))
    top = sorted(smooth)[int(0.95 * (len(smooth) - 1))] or max(smooth) or 1
    return [[round(t, 2), round(min(v / top, 1.0), 3)] for (t, _), v in zip(points, smooth)]


def make_thumb(path, t=0.0, w=480):
    return FileResponse(thumb_file(path, t, w), headers={"Cache-Control": "max-age=86400"})


def thumb_file(path, t=0.0, w=480):
    """A cached JPEG of a photo, or of a video's frame at t, w pixels wide."""
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
    return out


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


VOICE_NAMES = re.compile(r"(new recording|recording|voice|memo|reading|take|poem)", re.I)


def looks_like_voice(path):
    """A guess at whether an audio file in Downloads is a voice recording (an
    iPhone Voice Memo: "New Recording 3.m4a", no artist) rather than a song."""
    if VOICE_NAMES.search(path.stem):
        return True
    tags = shelf.probed(path)["tags"]
    if tags.get("artist") or tags.get("album_artist") or tags.get("genre"):
        return False
    return path.suffix.lower() in (".m4a", ".aac", ".wav", ".caf") and not re.search(r"-\d{5,}$", path.stem)


def is_song(path):
    return path.is_file() and not path.name.startswith(".") and path.suffix.lower() in AUDIO_EXTS


def download_path(name, ok=importable):
    path = (DOWNLOADS / name).resolve()
    if path.parent != DOWNLOADS or not path.exists() or not ok(path):
        raise HTTPException(404, f"Not in Downloads: {name}")
    return path


def in_shelf(src):
    """The music-folder track with the same content as this download, if any."""
    if not shelf.folder.is_dir():
        return None
    size, fp = src.stat().st_size, None
    for p in shelf.folder.iterdir():
        try:
            if is_song(p) and p.stat().st_size == size:
                fp = fp or fingerprint(src)
                if fingerprint(p) == fp:
                    return p.name
        except OSError:
            continue
    return None


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
    # Songs downloaded for the music folder, listed apart from the footage.
    songs = []
    for p in DOWNLOADS.iterdir():
        if not is_song(p):
            continue
        at = arrived(p.stat())
        if at >= since.timestamp():
            songs.append({"name": p.name, "arrived": at,
                          "day": datetime.fromtimestamp(at).strftime("%Y-%m-%d"),
                          "inShelf": in_shelf(p), "voice": looks_like_voice(p),
                          "duration": voice.duration(p)})
    songs.sort(key=lambda f: f["arrived"])
    days = {}
    for f in files:
        d = days.setdefault(f["day"], {"day": f["day"], "photos": 0, "videos": 0, "songs": 0, "new": 0})
        d["videos" if f["kind"] == "video" else "photos"] += 1
        d["new"] += not (f["importedTo"] or f["copyOf"])
    for f in songs:
        d = days.setdefault(f["day"], {"day": f["day"], "photos": 0, "videos": 0, "songs": 0, "new": 0})
        d["songs"] += 1
    return {"dir": str(DOWNLOADS), "today": date.today().isoformat(), "musicDir": str(shelf.folder),
            "days": sorted(days.values(), key=lambda d: d["day"], reverse=True),
            "files": files, "songs": songs, "transcribe": transcription_available()}


@app.post("/api/import/music")
def import_music(body: dict = Body(...)):
    """Move songs from Downloads into the music folder. {files: [names]}

    A song the music folder already has is just deleted from Downloads.
    """
    sources = [download_path(f, is_song) for f in body.get("files") or []]
    if not sources:
        raise HTTPException(400, "Pick at least one song")
    shelf.folder.mkdir(parents=True, exist_ok=True)
    moved, removed, failed = [], [], []
    for src in sources:
        try:
            if in_shelf(src):
                src.unlink()
                removed.append(src.name)
                continue
            target = shelf.folder / src.name
            if target.exists():
                target = free_name(target)
            shutil.move(str(src), str(target))
            moved.append(target.name)
        except Exception as e:   # one bad file shouldn't stop the rest
            failed.append({"name": src.name, "error": str(e)})
    return {"dir": str(shelf.folder), "moved": moved, "removed": removed, "failed": failed}


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
    # Ctrl-C stops it at once: an open page keeps videos streaming, and
    # uvicorn would otherwise wait for those downloads to finish first. The
    # downloads it cuts off aren't errors, so they aren't reported.
    config = uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning", timeout_graceful_shutdown=1)
    logging.getLogger("uvicorn.error").addFilter(QuietShutdown())
    uvicorn.Server(config).run()
    print("  Stopped.")


class QuietShutdown(logging.Filter):
    """Drop uvicorn's reports of the downloads it cancels on shutdown."""
    def filter(self, record):
        if "graceful shutdown" in record.getMessage():
            return False
        err = record.exc_info[1] if record.exc_info else None
        while err is not None:
            if isinstance(err, asyncio.CancelledError):
                return False
            err = err.__context__
        return True


if __name__ == "__main__":
    main()
