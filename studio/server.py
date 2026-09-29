#!/usr/bin/env python3
"""
Footage Studio — a small local server for browsing ~/Footage and choosing
where (and for how long) to cut each clip.

Selections are saved next to the footage in `<folder>/.studio.json`. Export
writes `<folder>/montage.yaml`, which montage.py renders on its own.

    pip install -r studio/requirements.txt
    (cd studio/web && npm install && npm run build)   # once
    python3 studio/server.py                          # http://localhost:8765

FOOTAGE_DIR overrides the footage root (default ~/Footage).
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent / "montage" / "montage.py"
sys.path.insert(0, str(ENGINE.parent))
import montage  # noqa: E402  (reuse the engine's probe / capture_time / exts)

ROOT = Path(os.environ.get("FOOTAGE_DIR", "~/Footage")).expanduser().resolve()
CACHE = Path("~/.cache/footage-studio").expanduser()
SIDECAR = ".studio.json"
EXPORT_NAME = "montage.yaml"

DEFAULT_SETTINGS = {
    "defaultLength": 1.5,   # seconds per video cut
    "defaultHold": 1.6,     # seconds per photo
    "music": "",
    "beatSync": False,      # when on, the engine uses beats and ignores lengths
    "beatsPerCut": 2,
    "fit": "fill",
    "originalVolume": 0.35,
}

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


def kind_of(path):
    ext = path.suffix.lower()
    if ext in montage.VIDEO_EXTS:
        return "video"
    if ext in montage.IMAGE_EXTS:
        return "photo"
    return None


def media_files(folder):
    return [p for p in folder.iterdir()
            if p.is_file() and not p.name.startswith(".") and kind_of(p)]


_meta_cache = {}


def meta(path):
    """Duration and capture time, cached on path + mtime."""
    key = (str(path), path.stat().st_mtime)
    if key not in _meta_cache:
        duration = 0.0
        if kind_of(path) == "video":
            try:
                duration, _ = montage.probe(path)
            except Exception:
                duration = 0.0
        _meta_cache[key] = {"duration": round(duration, 3),
                            "capturedAt": montage.capture_time(path)}
    return _meta_cache[key]


def default_start(duration, length):
    """Same rule the engine uses for folder sources: 30% in, not in the first 2s."""
    start = duration * 0.3
    start = max(min(start, duration - 0.5), min(2.0, duration / 3))
    return round(max(0.0, min(start, duration - length)), 2)


def load_sidecar(folder):
    path = folder / SIDECAR
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except ValueError:
            data = {}
    return {"settings": {**DEFAULT_SETTINGS, **data.get("settings", {})},
            "clips": data.get("clips", {})}


def folder_clips(folder):
    side = load_sidecar(folder)
    settings = side["settings"]
    clips = []
    for p in media_files(folder):
        m = meta(p)
        kind = kind_of(p)
        saved = side["clips"].get(p.name, {})
        if kind == "video":
            length = float(saved.get("length", min(settings["defaultLength"], m["duration"])))
            start = float(saved.get("start", default_start(m["duration"], length)))
        else:
            length = float(saved.get("length", settings["defaultHold"]))
            start = 0.0
        clips.append({"file": p.name, "kind": kind, "duration": m["duration"],
                      "capturedAt": m["capturedAt"], "size": p.stat().st_size,
                      "keep": bool(saved.get("keep", True)),
                      "start": round(start, 3), "length": round(length, 3)})
    clips.sort(key=lambda c: c["capturedAt"])
    return clips, settings


# ---------------------------------------------------------------- API

@app.get("/api/folders")
def list_folders():
    if not ROOT.is_dir():
        return {"root": str(ROOT), "folders": [], "error": f"{ROOT} does not exist"}
    folders = []
    for d in ROOT.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        files = media_files(d)
        videos = [f for f in files if kind_of(f) == "video"]
        ordered = sorted(files, key=lambda f: meta(f)["capturedAt"])
        cover = next((f for f in ordered if kind_of(f) == "video"), ordered[0] if ordered else None)
        cover_t = meta(cover)["duration"] * 0.3 if cover and kind_of(cover) == "video" else 0
        side = load_sidecar(d)
        folders.append({
            "name": d.name,
            "clipCount": len(videos),
            "photoCount": len(files) - len(videos),
            "totalDuration": round(sum(meta(f)["duration"] for f in videos), 1),
            "lastModified": d.stat().st_mtime,
            "cover": cover.name if cover else None,
            "coverTime": round(cover_t, 2),
            "edited": (d / SIDECAR).exists(),
            "keptCount": sum(1 for f in files if side["clips"].get(f.name, {}).get("keep", True)),
        })
    # Newest shoot first: date-named folders by name, the rest by last change.
    folders.sort(key=lambda f: (f["name"][:10] if f["name"][:4].isdigit() else "",
                                f["lastModified"]), reverse=True)
    return {"root": str(ROOT), "folders": folders}


@app.get("/api/folders/{name}")
def get_folder(name: str):
    folder = resolve(name)
    clips, settings = folder_clips(folder)
    exported = folder / EXPORT_NAME
    return {"name": name, "path": str(folder), "clips": clips, "settings": settings,
            "exported": str(exported) if exported.exists() else None}


@app.put("/api/folders/{name}/selections")
def save_selections(name: str, body: dict = Body(...)):
    folder = resolve(name)
    clips = {c["file"]: {"keep": bool(c["keep"]),
                         "start": round(float(c["start"]), 3),
                         "length": round(float(c["length"]), 3)}
             for c in body.get("clips", [])}
    settings = {**DEFAULT_SETTINGS, **body.get("settings", {})}
    (folder / SIDECAR).write_text(json.dumps({"settings": settings, "clips": clips}, indent=2))
    return {"ok": True, "savedAt": datetime.now().isoformat(timespec="seconds")}


def build_config(name, folder):
    clips, s = folder_clips(folder)
    sources = []
    for c in clips:
        if not c["keep"]:
            continue
        entry = {"id": Path(c["file"]).stem[:16], "file": c["file"]}
        if c["kind"] == "video":
            entry["times"] = [round(c["start"], 2)]
            entry["length"] = round(c["length"], 2)
        else:
            entry["hold"] = round(c["length"], 2)
            entry["in_round"] = "all"
        sources.append(entry)

    cfg = {"output": f"renders/{name}.mp4", "rounds": 1, "sources": sources}
    if s.get("music"):
        cfg["music"] = s["music"]
        cfg["beat_sync"] = bool(s.get("beatSync"))
        cfg["beats_per_cut"] = int(s.get("beatsPerCut", 2))
        cfg["music_volume"] = 0.7
        cfg["music_fade_out"] = 2.0
    cfg.update({
        "clip_length": s["defaultLength"],
        "transitions": {"within_round": "cut", "between_rounds": "dissolve",
                        "into_image": "dissolve", "out_of_image": "dissolve",
                        "duration": 0.3},
        "original_audio": True,
        "original_volume": s.get("originalVolume", 0.35),
        "fit": s.get("fit", "fill"),
        "photo_motion": "push",
        "photo_zoom": 0.06,
        "crf": 18,
        "preset": "veryfast",
    })
    return cfg


@app.post("/api/folders/{name}/export")
def export(name: str):
    folder = resolve(name)
    cfg = build_config(name, folder)
    if not cfg["sources"]:
        raise HTTPException(400, "No clips are kept — nothing to export.")
    header = (f"# Generated by Footage Studio from {SIDECAR} on "
              f"{datetime.now():%Y-%m-%d %H:%M}.\n"
              f"# Edit clips in the studio; hand edits here are overwritten on export.\n"
              f"#   python3 {ENGINE} {EXPORT_NAME} --dry-run\n\n")
    out = folder / EXPORT_NAME
    out.write_text(header + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    result = subprocess.run([sys.executable, str(ENGINE), str(out), "--dry-run"],
                            capture_output=True, text=True, timeout=300)
    return {"path": str(out), "ok": result.returncode == 0,
            "dryRun": (result.stdout + result.stderr).strip(),
            "command": f"python3 {ENGINE} {out}"}


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
        seek = ["-ss", f"{max(t, 0):.2f}"] if kind_of(path) == "video" else []
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
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="open the browser")
    args = ap.parse_args()
    if not DIST.is_dir():
        print("Front end not built yet: cd studio/web && npm install && npm run build")
    print(f"\n  Footage Studio — {ROOT}\n  http://localhost:{args.port}\n")
    if args.open:
        import webbrowser
        webbrowser.open(f"http://localhost:{args.port}")
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
