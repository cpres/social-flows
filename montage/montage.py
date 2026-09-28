#!/usr/bin/env python3
"""
Steward Montage — interleaved cut builder with beat sync and soft transitions.

Takes several long clips (and optional photos) and cuts them together in
rounds: a short piece of each clip, then jump forward in each clip and do
another round. The viewer watches several actions progress side by side.

    Round 1:  mulch @0:15  | shovel @1:00  | verge @0:20
    Round 2:  mulch @0:45  | shovel @1:20  | verge @0:55   (dissolve between rounds)
    Round 3:  mulch @1:15  | shovel @1:40  | verge @1:40  ~ photo (slow push-in)

Two styles, one engine:
  rounds  - a few clips revisited several times (montage.yaml)
  daylog  - a whole folder of clips, one cut each, in the order you shot
            them (daylog.yaml). Point a source at `folder:` instead of
            `file:` and it picks a moment inside each clip for you.

Sound: cuts can land on the beats of the music track, and the glasses audio
can sit quietly underneath as an ambient bed.

Usage:
    python3 montage.py montage.yaml            # render
    python3 montage.py montage.yaml --dry-run  # print the cut list only

Requires ffmpeg + ffprobe on PATH and PyYAML (pip install pyyaml).
Automatic beat detection also needs librosa (pip install librosa);
without it, set bpm: in the config instead.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mpg"}

# Garden Steward palette, used for the "pad" fit mode background.
BRAND_BG = {"forest": "0x344a34", "sage": "0x8aa37c", "cream": "0xf7f1e3"}

# Friendly transition names -> ffmpeg xfade names. Any other xfade name also works.
TRANSITIONS = {"dissolve": "fade", "dip": "fadeblack", "dip_white": "fadewhite"}

EDGE_FADE = 0.03  # tiny audio fade on every cut so hard cuts never click


# ---------------------------------------------------------------- helpers

def parse_time(value):
    """Accept 75, 75.5, '1:15', '0:01:15.5' -> seconds (float)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    seconds = 0.0
    for p in str(value).strip().split(":"):
        seconds = seconds * 60 + float(p)
    return seconds


def fmt(seconds):
    m, s = divmod(max(seconds, 0), 60)
    return f"{int(m)}:{s:04.1f}"


def probe(path):
    """Return (duration_seconds, has_audio) for a video file."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    duration = float(data.get("format", {}).get("duration", 0) or 0)
    has_audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    return duration, has_audio


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write("\nffmpeg failed:\n  " + " ".join(cmd) + "\n")
        sys.stderr.write(result.stderr[-3000:] + "\n")
        sys.exit(1)


# ---------------------------------------------------------------- music / beats

def load_beats(cfg, base_dir):
    """Return (beat_times starting at 0, adjusted music_start) or (None, start)."""
    music_start = parse_time(cfg.get("music_start", 0))
    if not cfg.get("music") or not cfg.get("beat_sync", True):
        return None, music_start

    path = (base_dir / cfg["music"]).expanduser()
    if not path.exists():
        sys.exit(f"Music file not found: {path}")

    if cfg.get("bpm"):
        period = 60.0 / float(cfg["bpm"])
        print(f"  beat grid: {float(cfg['bpm']):.0f} bpm (from config)")
        return [i * period for i in range(4000)], music_start

    try:
        import librosa
        import numpy as np
    except ImportError:
        sys.exit("Beat sync needs librosa (pip install librosa), or set bpm: in the "
                 "config, or set beat_sync: false.")

    y, sr = librosa.load(str(path), sr=22050, mono=True, offset=music_start, duration=240)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    beats = [float(b) for b in beats]
    if len(beats) < 4:
        sys.exit("Couldn't find a steady beat in that track. Set bpm: in the config "
                 "or beat_sync: false.")

    # Start the song on its first detected beat so cut 1 lands on a beat.
    first = beats[0]
    beats = [b - first for b in beats]
    step = float(np.median(np.diff(beats)))
    while len(beats) < 4000:  # extend past the end of the song if needed
        beats.append(beats[-1] + step)
    print(f"  beat grid: ~{float(np.atleast_1d(tempo)[0]):.0f} bpm (detected)")
    return beats, music_start + first


# ---------------------------------------------------------------- folder sources

def capture_time(path):
    """When the clip was recorded, falling back to the file timestamp."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format_tags=creation_time",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=30).stdout.strip()
        if out:
            from datetime import datetime
            return datetime.fromisoformat(out.replace("Z", "+00:00")).timestamp()
    except Exception:
        pass
    return path.stat().st_mtime


def expand_folders(cfg, base_dir):
    """Turn any `folder:` source into one source per file inside it."""
    expanded, notes = [], []
    for src in cfg["sources"]:
        if "folder" not in src:
            expanded.append(src)
            continue

        folder = (base_dir / src["folder"]).expanduser()
        if not folder.is_dir():
            sys.exit(f"Folder not found: {folder}")
        files = [q for q in folder.iterdir()
                 if q.suffix.lower() in (VIDEO_EXTS | IMAGE_EXTS)
                 and not q.name.startswith(".")]
        if not files:
            sys.exit(f"No video or photo files in {folder}")

        order = src.get("sort", "time")
        if order == "time":
            files.sort(key=capture_time)
        elif order == "name":
            files.sort(key=lambda q: q.name.lower())
        elif order == "shuffle":
            import random
            random.shuffle(files)
        else:
            sys.exit(f"Unknown sort: {order} (use time, name, or shuffle)")

        auto = src.get("auto_start", "30%")
        min_start = parse_time(src.get("min_start", 2))
        floor = parse_time(src.get("skip_shorter_than", 3))
        inherit = {k: v for k, v in src.items()
                   if k not in ("folder", "sort", "limit", "auto_start", "min_start",
                                "skip_shorter_than", "file", "id", "start", "step", "times")}

        kept = 0
        for path in files:
            if src.get("limit") and kept >= int(src["limit"]):
                break
            entry = dict(inherit)
            entry["file"] = str(path)
            entry["id"] = path.stem[:16]

            if path.suffix.lower() in IMAGE_EXTS:
                entry.setdefault("in_round", "all")
                expanded.append(entry)
                kept += 1
                continue

            duration, _ = probe(path)
            if duration < floor:
                notes.append(f"skipped '{path.name}' ({duration:.1f}s)")
                continue
            if isinstance(auto, str) and auto.strip().endswith("%"):
                start = duration * float(auto.strip().rstrip("%")) / 100
            else:
                start = parse_time(auto)
            start = max(min(start, duration - 0.5), min(min_start, duration / 3))
            entry["times"] = [round(start, 2)]
            expanded.append(entry)
            kept += 1

        notes.append(f"{kept} clips from {folder.name}/ (sorted by {order})")

    cfg["sources"] = expanded
    return notes


# ---------------------------------------------------------------- planning

def rounds_for_image(src, total_rounds):
    """Which rounds an image appears in. Default: last round only."""
    spec = src.get("in_round", "last")
    out = set()
    for s in (spec if isinstance(spec, list) else [spec]):
        if s == "last":
            out.add(total_rounds)
        elif s == "first":
            out.add(1)
        elif s == "all":
            out.update(range(1, total_rounds + 1))
        else:
            out.add(int(s))
    return out


def transition_between(a, b, cfg, index):
    t = cfg.get("transitions", {}) or {}
    soft_every = int(t.get("soft_every", 0) or 0)
    if b["kind"] == "image":
        name = t.get("into_image", "dissolve")
    elif a["kind"] == "image":
        name = t.get("out_of_image", "dissolve")
    elif a["round"] != b["round"]:
        name = t.get("between_rounds", "dissolve")
    elif soft_every and (index + 1) % soft_every == 0:
        name = t.get("between_rounds", "dissolve")
    else:
        name = t.get("within_round", "cut")
    return TRANSITIONS.get(name, name)


def build_plan(cfg, base_dir, beats):
    fps = cfg["fps"]
    default_len = float(cfg.get("clip_length", 1.5))
    default_hold = float(cfg.get("image_hold", 2.5))
    beats_per_cut = int(cfg.get("beats_per_cut", 2))
    sources = cfg["sources"]

    total_rounds = cfg.get("rounds")
    if total_rounds is None:
        explicit = [len(s["times"]) for s in sources if "times" in s]
        total_rounds = max(explicit) if explicit else 3
    total_rounds = int(total_rounds)

    for src in sources:
        path = (base_dir / src["file"]).expanduser()
        if not path.exists():
            sys.exit(f"File not found: {path}")
        src["_path"] = path
        src["_is_image"] = path.suffix.lower() in IMAGE_EXTS
        if not src["_is_image"]:
            src["_duration"], src["_has_audio"] = probe(path)

    # 1. Which cuts exist, in order.
    plan, warnings = [], []
    for r in range(1, total_rounds + 1):
        for src in sources:
            label = src.get("id", src["_path"].stem)
            if src["_is_image"]:
                if r in rounds_for_image(src, total_rounds):
                    plan.append({"kind": "image", "path": src["_path"], "label": label,
                                 "round": r, "start": 0.0,
                                 "seconds": float(src.get("hold", default_hold)),
                                 "beats": int(src.get("hold_beats", beats_per_cut * 2))})
                continue
            if "times" in src:
                if r > len(src["times"]):
                    continue
                start = parse_time(src["times"][r - 1])
            else:
                start = parse_time(src.get("start", 0)) + (r - 1) * parse_time(src.get("step", 20))
            if start > src["_duration"] - 0.3:
                warnings.append(f"round {r}: '{label}' is only {fmt(src['_duration'])} "
                                f"long, skipped cut at {fmt(start)}")
                continue
            plan.append({"kind": "video", "path": src["_path"], "label": label,
                         "round": r, "start": start, "src_duration": src["_duration"],
                         "has_audio": src["_has_audio"],
                         "seconds": float(src.get("length", default_len)),
                         "beats": int(src.get("beats", beats_per_cut))})

    # 2. Where each cut lands on the timeline, snapped to whole frames
    #    (and to beats when beat sync is on) so nothing drifts.
    cut_points, cursor_beat, t = [0.0], 0, 0.0
    for seg in plan:
        if beats is not None:
            cursor_beat += seg["beats"]
            t = beats[cursor_beat]
        else:
            t += seg["seconds"]
        cut_points.append(t)
    frames = [round(c * fps) for c in cut_points]
    for i, seg in enumerate(plan):
        seg["length"] = (frames[i + 1] - frames[i]) / fps

    # 3. Transitions between neighbours. Soft ones overlap, so the outgoing
    #    cut renders a little extra tail.
    base_d = float((cfg.get("transitions") or {}).get("duration", 0.35))
    for i, seg in enumerate(plan):
        seg["t_after"], seg["d_after"] = None, 0.0
        if i + 1 < len(plan):
            name = transition_between(seg, plan[i + 1], cfg, i)
            if name != "cut":
                d = min(base_d, 0.45 * seg["length"], 0.45 * plan[i + 1]["length"])
                seg["t_after"], seg["d_after"] = name, round(d * fps) / fps
        seg["render_length"] = seg["length"] + seg["d_after"]

    # 4. If a cut would run off the end of its clip, slide it earlier
    #    instead of shortening it, so the timing stays on the beat.
    for i, seg in enumerate(plan):
        if seg["kind"] != "video":
            continue
        overflow = seg["start"] + seg["render_length"] - seg["src_duration"]
        if overflow > 0:
            new_start = max(0.0, seg["start"] - overflow - 0.05)
            warnings.append(f"round {seg['round']}: '{seg['label']}' cut moved "
                            f"{fmt(seg['start'])} -> {fmt(new_start)} to fit before the clip ends")
            seg["start"] = new_start

    return plan, warnings


# ---------------------------------------------------------------- rendering

def video_codec(cfg):
    """x264 by default; Apple hardware encoder when encoder: videotoolbox."""
    if cfg.get("encoder") == "videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-b:v", str(cfg.get("bitrate", "12M"))]
    return ["-c:v", "libx264", "-preset", cfg.get("preset", "veryfast"),
            "-crf", str(cfg.get("crf", 18))]


def fit_filter(cfg, src_label, out_label):
    w, h = cfg["width"], cfg["height"]
    fit = cfg.get("fit", "fill")
    if fit == "fill":
        return (f"[{src_label}]scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h}[{out_label}]")
    if fit == "blur":
        return (f"[{src_label}]split[fa][fb];"
                f"[fa]scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},boxblur=30:5[fbg];"
                f"[fb]scale={w}:{h}:force_original_aspect_ratio=decrease[ffg];"
                f"[fbg][ffg]overlay=(W-w)/2:(H-h)/2[{out_label}]")
    if fit == "pad":
        color = BRAND_BG.get(cfg.get("pad_color", "forest"), cfg.get("pad_color"))
        return (f"[{src_label}]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={color}[{out_label}]")
    sys.exit(f"Unknown fit mode: {fit} (use fill, blur, or pad)")


def render_segment(seg, idx, cfg, workdir, keep_audio):
    """Render one cut to a uniform intermediate (x264 + PCM in mkv)."""
    w, h, fps = cfg["width"], cfg["height"], cfg["fps"]
    length = seg["render_length"]
    n_frames = round(length * fps)
    out = workdir / f"seg_{idx:03d}.mkv"
    cmd = ["ffmpeg", "-y", "-v", "error"]

    if seg["kind"] == "image":
        cmd += ["-i", str(seg["path"])]
    else:
        cmd += ["-ss", f"{seg['start']:.3f}", "-i", str(seg["path"])]

    use_source_audio = keep_audio and seg["kind"] == "video" and seg["has_audio"]
    if not use_source_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    a_in = "0:a:0" if use_source_audio else "1:a"

    graph = fit_filter(cfg, "0:v", "fit") + ";"
    if seg["kind"] == "image" and cfg.get("photo_motion", "push") == "push":
        # Slow, gentle push-in. Upscale first so the zoom doesn't wobble.
        zoom = float(cfg.get("photo_zoom", 0.06))
        graph += (f"[fit]scale={w * 2}:{h * 2},"
                  f"zoompan=z='1+{zoom}*on/{n_frames}':"
                  f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                  f"d={n_frames}:s={w}x{h}:fps={fps},")
    elif seg["kind"] == "image":
        graph += f"[fit]loop=loop={n_frames}:size=1,fps={fps},"
    else:
        graph += f"[fit]fps={fps},"
    graph += f"setsar=1,format=yuv420p,trim=end_frame={n_frames},setpts=PTS-STARTPTS[v];"
    graph += (f"[{a_in}]aformat=sample_rates=48000:channel_layouts=stereo,apad,"
              f"atrim=0:{length:.4f},asetpts=PTS-STARTPTS,"
              f"afade=t=in:d={EDGE_FADE},"
              f"afade=t=out:st={max(length - EDGE_FADE, 0):.4f}:d={EDGE_FADE}[a]")

    cmd += ["-filter_complex", graph, "-map", "[v]", "-map", "[a]",
            *video_codec(cfg), "-r", str(fps),
            "-c:a", "pcm_s16le", str(out)]
    run(cmd)
    return out


def assemble(segs, plan, cfg, workdir):
    """Join all cuts, applying hard cuts or crossfades between them."""
    fps = cfg["fps"]
    out = workdir / "assembled.mkv"
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for p in segs:
        cmd += ["-i", str(p)]

    tb = f"settb=1/{fps * 1000}"
    graph = [f"[{i}:v]{tb},setpts=PTS-STARTPTS[v{i}in]" for i in range(len(segs))]
    vcur, acur = "[v0in]", "[0:a]"
    acc = plan[0]["render_length"]
    for k in range(1, len(segs)):
        prev = plan[k - 1]
        if prev["t_after"] is None:
            graph.append(f"{vcur}[v{k}in]concat=n=2:v=1:a=0,{tb}[vc{k}]")
            graph.append(f"{acur}[{k}:a]concat=n=2:v=0:a=1[ac{k}]")
            acc += plan[k]["render_length"]
        else:
            d = prev["d_after"]
            graph.append(f"{vcur}[v{k}in]xfade=transition={prev['t_after']}:"
                         f"duration={d:.4f}:offset={acc - d:.4f},{tb}[vc{k}]")
            graph.append(f"{acur}[{k}:a]acrossfade=d={d:.4f}:c1=tri:c2=tri[ac{k}]")
            acc += plan[k]["render_length"] - d
        vcur, acur = f"[vc{k}]", f"[ac{k}]"

    cmd += ["-filter_complex", ";".join(graph), "-map", vcur, "-map", acur,
            *video_codec(cfg), "-r", str(fps),
            "-c:a", "pcm_s16le", str(out)]
    run(cmd)
    return out


def finish(assembled, cfg, base_dir, music_start, total_len, keep_audio, output):
    music = cfg.get("music")
    common = ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
              "-movflags", "+faststart", "-t", f"{total_len:.3f}", str(output)]

    if not music:
        audio = ["-map", "0:a"] if keep_audio else ["-an"]
        run(["ffmpeg", "-y", "-v", "error", "-i", str(assembled),
             "-map", "0:v", *audio, *common])
        return

    music_path = (base_dir / music).expanduser()
    music_vol = float(cfg.get("music_volume", 1.0))
    fade = min(float(cfg.get("music_fade_out", 2.0)), total_len / 3)
    music_chain = (f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                   f"volume={music_vol},"
                   f"afade=t=out:st={max(total_len - fade, 0):.3f}:d={fade:.3f}")

    if keep_audio:  # glasses audio as a quiet ambient bed under the music
        bed = float(cfg.get("original_volume", 0.35))
        graph = (f"{music_chain}[m];[0:a]volume={bed}[o];"
                 f"[o][m]amix=inputs=2:duration=first:normalize=0,"
                 f"alimiter=limit=0.95[a]")
    else:
        graph = f"{music_chain}[a]"

    run(["ffmpeg", "-y", "-v", "error",
         "-i", str(assembled),
         "-ss", f"{music_start:.3f}", "-i", str(music_path),
         "-filter_complex", graph, "-map", "0:v", "-map", "[a]", *common])


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Interleaved steward montage builder")
    ap.add_argument("config", help="montage YAML file")
    ap.add_argument("--dry-run", action="store_true", help="print the cut list, don't render")
    args = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"{tool} not found. Install ffmpeg first (e.g. brew install ffmpeg).")

    config_path = Path(args.config).resolve()
    base_dir = config_path.parent
    cfg = yaml.safe_load(config_path.read_text())
    cfg.setdefault("width", 1080)
    cfg.setdefault("height", 1920)
    cfg.setdefault("fps", 30)

    print()
    for note in expand_folders(cfg, base_dir):
        print(f"  {note}")
    beats, music_start = load_beats(cfg, base_dir)
    plan, warnings = build_plan(cfg, base_dir, beats)
    if not plan:
        sys.exit("Nothing to cut. Check your start/step/times against clip lengths.")

    total = sum(s["length"] for s in plan)
    print(f"\n{len(plan)} cuts, {total:.1f}s total\n")
    t = 0.0
    for seg in plan:
        where = "hold" if seg["kind"] == "image" else f"from {fmt(seg['start'])}"
        print(f"  {fmt(t):>7}  r{seg['round']}  {seg['label']:<16} {where:<12} {seg['length']:.2f}s")
        if seg["t_after"]:
            friendly = {v: k for k, v in TRANSITIONS.items()}.get(seg["t_after"], seg["t_after"])
            print(f"  {'':>7}      ~ {friendly} {seg['d_after']:.2f}s")
        t += seg["length"]
    for w in warnings:
        print(f"  ! {w}")
    print()

    if args.dry_run:
        return

    keep_audio = bool(cfg.get("original_audio", True))
    output = (base_dir / cfg.get("output", "montage.mp4")).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        segs = []
        for i, seg in enumerate(plan):
            print(f"  cutting {i + 1}/{len(plan)}: {seg['label']}          ", end="\r")
            segs.append(render_segment(seg, i, cfg, workdir, keep_audio))
        print("  joining cuts...                         ", end="\r")
        assembled = assemble(segs, plan, cfg, workdir)
        print("  mixing sound...                         ", end="\r")
        finish(assembled, cfg, base_dir, music_start, total, keep_audio, output)

    print(f"Done: {output}                          \n")


if __name__ == "__main__":
    main()
