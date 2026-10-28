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
can sit quietly underneath as an ambient bed. A voice track (a reading, laid
over the footage from one or more takes) plays on top, with the song kept low
under it, and its words can be shown as captions.

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

# Short, punchy transitions for build reels. Each part can pick the one that
# leads out of it with `transition:` (cut | flash | whip | zoom | dissolve | dip).
FLASH_D = 0.16    # fade through white
WHIP_D = 0.22     # fast slide with horizontal motion blur either side of the join
PUNCH_D = 0.30    # incoming shot starts zoomed in and snaps back
PUNCH_ZOOM = 0.18

LIGHTEN_GAMMA = 0.6   # per-source `lighten:` 0..1; 1 = gamma 1.6

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

def music_path(cfg, base_dir):
    """The music file: absolute, ~/..., or relative to the config file."""
    path = Path(cfg["music"]).expanduser()
    return path if path.is_absolute() else base_dir / path


def beat_grid(beats, music_start):
    """Beats (song time) -> times from the first beat at/after music_start."""
    beats = [b - music_start for b in beats if b >= music_start - 0.02]
    if len(beats) < 4:
        sys.exit("Couldn't find a steady beat after music_start. Set bpm: in the "
                 "config or beat_sync: false.")
    first = beats[0]
    beats = [b - first for b in beats]
    steps = sorted(b - a for a, b in zip(beats, beats[1:]))
    step = steps[len(steps) // 2]
    while len(beats) < 4000:  # extend past the end of the song if needed
        beats.append(beats[-1] + step)
    return beats, music_start + first, 60.0 / step


def load_beats(cfg, base_dir):
    """Return (beat_times starting at 0, adjusted music_start) or (None, start)."""
    music_start = parse_time(cfg.get("music_start", 0))
    if not cfg.get("music") or not cfg.get("beat_sync", True):
        return None, music_start

    path = music_path(cfg, base_dir)
    if not path.exists():
        sys.exit(f"Music file not found: {path}")

    # Beats already detected for the whole song (Footage Studio caches them),
    # so the preview and the render cut on exactly the same beats.
    if cfg.get("beat_file"):
        data = json.loads(Path(cfg["beat_file"]).expanduser().read_text())
        beats, start, bpm = beat_grid(data["beats"], music_start)
        print(f"  beat grid: ~{bpm:.0f} bpm (from {Path(cfg['beat_file']).name})")
        return beats, start

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


def beat_time(beats, at):
    """Where beat number `at` falls; a fraction (0.5, 0.25) is that share of
    the way to the next beat, so quick photos can cut on half and quarter beats."""
    i = int(at)
    if at == i:
        return beats[i]
    return beats[i] + (at - i) * (beats[i + 1] - beats[i])


def beat_count(value, default):
    """A cut's length in beats: whole beats, or ½ and ¼ for quick ones."""
    n = round(float(value if value is not None else default) * 4) / 4
    return max(n, 0.25)


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


def build_plan(cfg, base_dir, beats, voice=None):
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
                                 "round": r, "start": 0.0, "focus": src.get("focus", (0.5, 0.5)),
                                 "transition": src.get("transition"),
                                 "lighten": float(src.get("lighten", 0) or 0),
                                 "zoom": float(src.get("zoom", 1) or 1),
                                 "fit": src.get("fit"),
                                 "seconds": float(src.get("hold", default_hold)),
                                 "beats": beat_count(src.get("hold_beats"), beats_per_cut * 2)})
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
                         "focus": src.get("focus", (0.5, 0.5)),
                         "transition": src.get("transition"),
                         "lighten": float(src.get("lighten", 0) or 0),
                         "zoom": float(src.get("zoom", 1) or 1),
                         "fit": src.get("fit"),
                         "has_audio": src["_has_audio"],
                         "seconds": float(src.get("length", default_len)),
                         "beats": beat_count(src.get("beats"), beats_per_cut)})

    # The end card plays over the last part, which holds that much longer.
    end = cfg.get("end_card")
    if end and plan:
        end = end if isinstance(end, dict) else {}
        plan[-1]["card_beats"] = beat_count(end.get("beats"), 4)
        plan[-1]["card_seconds"] = float(end.get("hold", 2.0))
        plan[-1]["beats"] += plan[-1]["card_beats"]
        plan[-1]["seconds"] += plan[-1]["card_seconds"]
        plan[-1]["end_card"] = True

    # 2. Where each cut lands on the timeline, snapped to whole frames
    #    (and to beats when beat sync is on) so nothing drifts.
    cut_points, cursor_beat, t = [0.0], 0, 0.0
    card_at = None   # where the end card's extra hold starts
    for seg in plan:
        if beats is not None:
            if seg.get("end_card"):
                card_at = beat_time(beats, cursor_beat + seg["beats"] - seg["card_beats"])
            cursor_beat += seg["beats"]
            t = beat_time(beats, cursor_beat)
        else:
            if seg.get("end_card"):
                card_at = t + seg["seconds"] - seg["card_seconds"]
            t += seg["seconds"]
        cut_points.append(t)
    frames = [round(c * fps) for c in cut_points]
    for i, seg in enumerate(plan):
        seg["length"] = (frames[i + 1] - frames[i]) / fps
        seg["hold_extra"] = 0.0

    # A reading that runs past the parts: the last part holds until the voice
    # has finished (and a moment after), then the end card plays.
    if voice and voice["fit"] and plan:
        body_end = card_at if card_at is not None else frames[-1] / fps
        need = voice["end"] + VOICE_TAIL - body_end
        if need > 0:
            extra = -(-round(need * fps * 1000) // 1000) / fps   # whole frames, rounded up
            plan[-1]["length"] += extra
            plan[-1]["hold_extra"] = extra
            card_at = card_at + extra if card_at is not None else None
    if card_at is not None:
        # The card comes in with the last part, or once the voice is done.
        last_start = frames[-2] / fps
        plan[-1]["card_from"] = max(last_start, min(voice["end"] + VOICE_TAIL, card_at)) if voice else last_start

    # 3. Transitions between neighbours. Soft ones overlap, so the outgoing
    #    cut renders a little extra tail.
    base_d = float((cfg.get("transitions") or {}).get("duration", 0.35))
    for seg in plan:
        seg["t_after"], seg["d_after"], seg["label_after"] = None, 0.0, None
        seg.setdefault("whip_in", 0.0)
        seg.setdefault("whip_out", 0.0)
        seg.setdefault("punch_in", 0.0)
    for i, seg in enumerate(plan):
        if i + 1 < len(plan):
            nxt = plan[i + 1]
            style = seg.get("transition")
            if style == "zoom":            # a hard cut; the next shot punches in
                nxt["punch_in"] = min(PUNCH_D, nxt["length"])
                seg["label_after"] = "zoom punch-in"
            else:
                if style in ("flash", "whip"):
                    name, want = ("fadewhite", FLASH_D) if style == "flash" else ("slideleft", WHIP_D)
                else:
                    name = TRANSITIONS.get(style, style) if style else transition_between(seg, nxt, cfg, i)
                    want = base_d
                if name != "cut":
                    d = min(want, 0.45 * seg["length"], 0.45 * nxt["length"])
                    seg["t_after"], seg["d_after"] = name, round(d * fps) / fps
                    seg["label_after"] = style or {v: k for k, v in TRANSITIONS.items()}.get(name, name)
                    if style == "whip":
                        seg["whip_out"] = nxt["whip_in"] = seg["d_after"]
        seg["render_length"] = seg["length"] + seg["d_after"]

    # 4. If a cut would run off the end of its clip, slide it earlier
    #    instead of shortening it, so the timing stays on the beat.
    for i, seg in enumerate(plan):
        if seg["kind"] != "video":
            continue
        # (a hold for the voice plays on past the clip's end on its last frame; it doesn't move the cut)
        overflow = seg["start"] + seg["render_length"] - seg["hold_extra"] - seg["src_duration"]
        if overflow > 0:
            new_start = max(0.0, seg["start"] - overflow - 0.05)
            warnings.append(f"round {seg['round']}: '{seg['label']}' cut moved "
                            f"{fmt(seg['start'])} -> {fmt(new_start)} to fit before the clip ends")
            seg["start"] = new_start

    return plan, warnings


# ---------------------------------------------------------------- rendering

def video_codec(cfg):
    """x264 by default; Apple hardware encoder when encoder: videotoolbox.

    Always 8-bit 4:2:0 — filters like xfade can negotiate yuv444p, which
    QuickTime/iOS can't decode (audio plays, video is black).
    """
    pix = ["-pix_fmt", "yuv420p"]
    if cfg.get("encoder") == "videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-b:v", str(cfg.get("bitrate", "12M")), *pix]
    return ["-c:v", "libx264", "-preset", cfg.get("preset", "veryfast"),
            "-crf", str(cfg.get("crf", 18)), "-profile:v", "high", *pix]


def fit_filter(cfg, src_label, out_label, focus=(0.5, 0.5), zoom=1.0, fit=None):
    """Frame a source to the output size. `focus` picks which part of a
    too-wide or too-tall source the crop keeps: 0 = left/top, 1 = right/bottom.
    `zoom` > 1 (fill only) crops tighter: the source is scaled up first.
    `fit` overrides the config's for one cut."""
    w, h = cfg["width"], cfg["height"]
    fx, fy = (min(max(float(v), 0.0), 1.0) for v in focus)
    crop = f"crop={w}:{h}:(iw-{w})*{fx:.4f}:(ih-{h})*{fy:.4f}"
    fit = fit or cfg.get("fit", "fill")
    if fit == "fill":
        z = min(max(float(zoom or 1), 1.0), 3.0)
        zw, zh = round(w * z / 2) * 2, round(h * z / 2) * 2
        return (f"[{src_label}]scale={zw}:{zh}:force_original_aspect_ratio=increase,"
                f"{crop}[{out_label}]")
    if fit == "blur":
        return (f"[{src_label}]split[fa][fb];"
                f"[fa]scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"{crop},boxblur=30:5[fbg];"
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
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error"]

    if seg["kind"] == "image":
        cmd += ["-i", str(seg["path"])]
    else:
        cmd += ["-ss", f"{seg['start']:.3f}", "-i", str(seg["path"])]

    use_source_audio = keep_audio and seg["kind"] == "video" and seg["has_audio"]
    if not use_source_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    a_in = "0:a:0" if use_source_audio else "1:a"

    framing = (seg.get("focus", (0.5, 0.5)), seg.get("zoom", 1), seg.get("fit"))
    lift = min(max(seg.get("lighten", 0), 0.0), 1.0)
    if lift:
        # Lift shadows and midtones (gamma) rather than flat brightness, so
        # shade opens up without blowing out the sky.
        graph = (fit_filter(cfg, "0:v", "fit0", *framing) +
                 f";[fit0]eq=gamma={1 + LIGHTEN_GAMMA * lift:.3f}:saturation={1 + 0.08 * lift:.3f}[fit];")
    else:
        graph = fit_filter(cfg, "0:v", "fit", *framing) + ";"
    # Zoom punch-in: start PUNCH_ZOOM larger and ease back to normal.
    punch_frames = round(seg.get("punch_in", 0) * fps)
    punch = (f"+{PUNCH_ZOOM}*pow(max(0,1-on/{punch_frames}),2)" if punch_frames else "")
    if seg["kind"] == "image" and cfg.get("photo_motion", "push") == "push":
        # Slow, gentle push-in. Upscale first so the zoom doesn't wobble.
        zoom = float(cfg.get("photo_zoom", 0.06))
        graph += (f"[fit]scale={w * 2}:{h * 2},"
                  f"zoompan=z='1+{zoom}*on/{n_frames}{punch}':"
                  f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                  f"d={n_frames}:s={w}x{h}:fps={fps},")
    elif seg["kind"] == "image":
        if punch:
            graph += (f"[fit]scale={w * 2}:{h * 2},zoompan=z='1{punch}':"
                      f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                      f"d={n_frames}:s={w}x{h}:fps={fps},")
        else:
            graph += f"[fit]loop=loop={n_frames}:size=1,fps={fps},"
    elif punch:
        graph += (f"[fit]fps={fps},scale={w * 2}:{h * 2},zoompan=z='1{punch}':d=1:"
                  f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps},")
    else:
        graph += f"[fit]fps={fps},"
    if seg["kind"] == "video":   # a clip that ends early holds its last frame
        graph += f"tpad=stop_mode=clone:stop_duration={length:.3f},"
    graph += f"setsar=1,format=yuv420p,trim=end_frame={n_frames},setpts=PTS-STARTPTS"
    # Whip: horizontal motion blur on both sides of the slide.
    if seg.get("whip_out"):
        graph += f",avgblur=sizeX=48:sizeY=1:enable='gte(t,{length - seg['whip_out']:.3f})'"
    if seg.get("whip_in"):
        graph += f",avgblur=sizeX=48:sizeY=1:enable='lte(t,{seg['whip_in']:.3f})'"
    graph += "[v];"
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
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error"]
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

    # A one-cut reel never enters the loop: its audio is the input stream itself.
    if acur == "[0:a]":
        acur = "0:a"
    cmd += ["-filter_complex", ";".join(graph), "-map", vcur, "-map", acur,
            *video_codec(cfg), "-r", str(fps),
            "-c:a", "pcm_s16le", str(out)]
    run(cmd)
    return out


def load_top(cfg, base_dir):
    """A stack piece: `top:` is a clip shown in the top pane for the whole
    piece, `stack:` the split and the divider. The cuts play underneath, so
    this narrows cfg's height to the bottom pane. Returns the top, or None.

    With stack fit on (the default) the top clip is sped up or slowed down to
    end with the cuts; with it off, the piece is as long as the top clip at
    normal speed and the cuts are cut short, or hold their last frame."""
    top = cfg.get("top")
    if not top:
        return None
    path = (base_dir / top["file"]).expanduser()
    if not path.exists():
        sys.exit(f"File not found: {path}")
    duration, _ = probe(path)
    start = parse_time(top.get("start", 0))
    length = parse_time(top.get("length")) or duration - start
    length = max(0.2, min(length, duration - start))
    st = cfg.get("stack") or {}
    h = cfg["height"]
    divider = min(max(int(st.get("divider", 4)) // 2 * 2, 0), 40)
    split = min(max(float(st.get("split", 0.5)), 0.1), 0.9)
    top_h = round((h - divider) * split / 2) * 2
    out = {"path": path, "start": start, "length": length, "height": top_h,
           "focus": top.get("focus", (0.5, 0.5)), "zoom": float(top.get("zoom", 1) or 1),
           "lighten": float(top.get("lighten", 0) or 0), "full_height": h,
           "divider": divider, "color": str(st.get("divider_color", "#f7f1e3")).replace("#", "0x"),
           "fit": bool(st.get("fit", True))}
    cfg["height"] = h - divider - top_h
    return out


def top_length(top, under):
    """How long the piece runs: the cuts' length when the top is fitted to
    them, else the top clip's own length."""
    return under if top["fit"] else round(top["length"] * 1000) / 1000


def compose_top(top, assembled, cfg, under, workdir):
    """The top clip (sped to fit, or not) over the divider over the cuts."""
    w, fps = cfg["width"], cfg["fps"]
    total = top_length(top, under)
    bottom_h = cfg["height"]
    out = workdir / "stacked.mkv"
    cfg["height"] = top["height"]
    graph = fit_filter(cfg, "0:v", "tfit", top["focus"], top["zoom"], "fill") + ";"
    cfg["height"] = bottom_h
    lift = min(max(top["lighten"], 0.0), 1.0)
    eq = (f"eq=gamma={1 + LIGHTEN_GAMMA * lift:.3f}:saturation={1 + 0.08 * lift:.3f}," if lift else "")
    speed = total / top["length"] if top["fit"] else 1.0
    frames = round(total * fps)
    graph += (f"[tfit]setpts=(PTS-STARTPTS)*{speed:.6f},fps={fps},{eq}setsar=1,format=yuv420p,"
              f"trim=end_frame={frames},setpts=PTS-STARTPTS[top];")
    # Cuts shorter than the top clip hold their last frame (and go quiet).
    hold = max(total - under, 0)
    pad = f",tpad=stop_mode=clone:stop_duration={hold:.3f}" if hold > 0.001 else ""
    graph += (f"[1:v]setsar=1,format=yuv420p{pad},trim=end_frame={frames},setpts=PTS-STARTPTS[bot];"
              f"[1:a]apad,atrim=0:{total:.4f},asetpts=PTS-STARTPTS[a];")
    if top["divider"]:
        graph += (f"color=c={top['color']}:s={w}x{top['divider']}:r={fps},format=yuv420p,"
                  f"trim=end_frame={frames}[div];[top][div][bot]vstack=inputs=3[v]")
    else:
        graph += "[top][bot]vstack=inputs=2[v]"
    run(["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-ss", f"{top['start']:.3f}", "-t", f"{top['length']:.3f}", "-i", str(top["path"]),
         "-i", str(assembled), "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
         *video_codec(cfg), "-r", str(fps), "-c:a", "pcm_s16le", str(out)])
    cfg["height"] = top["full_height"]
    return out


def finish(assembled, cfg, base_dir, music_start, total_len, keep_audio, output, voice=None):
    """Mix the sound under the finished picture: the clips' own audio (as a
    bed), the song, and the voice track, with the song kept low under it."""
    # music_in_video: false times the cuts to the song but leaves it out of the
    # file, for adding the same song in Instagram (which licenses it).
    music = cfg.get("music") if cfg.get("music_in_video", True) else None
    common = ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
              "-movflags", "+faststart", "-t", f"{total_len:.3f}", str(output)]

    if not music and not voice:
        audio = ["-map", "0:a"] if keep_audio else ["-an"]
        run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(assembled),
             "-map", "0:v", *audio, *common])
        return

    inputs = ["-i", str(assembled)]
    graph, mix = [], []
    # The assembled audio sets the length; silent unless the clips' sound is kept.
    bed = (float(cfg.get("original_volume", 0.35)) if music else 1.0) if keep_audio else 0.0
    graph.append(f"[0:a]volume={bed}[o]")
    mix.append("[o]")
    if music:
        inputs += ["-ss", f"{music_start:.3f}", "-i", str(music_path(cfg, base_dir))]
        fade = min(float(cfg.get("music_fade_out", 2.0)), total_len / 3)
        level = (f"volume='{song_level(voice)}':eval=frame" if voice
                 else f"volume={float(cfg.get('music_volume', 1.0))}")
        graph.append(f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,{level},"
                     f"afade=t=out:st={max(total_len - fade, 0):.3f}:d={fade:.3f}[m]")
        mix.append("[m]")
    if voice:
        n0 = inputs.count("-i")
        for i, p in enumerate(voice["pieces"]):
            inputs += ["-ss", f"{p['start']:.3f}", "-t", f"{p['length']:.3f}", "-i", str(p["path"])]
            clean = "highpass=f=80,afftdn=nf=-25," if voice["clean"] else ""
            delay = round(p["at"] * 1000)
            graph.append(f"[{n0 + i}:a:0]aformat=channel_layouts=mono,{clean}"
                         f"loudnorm=I=-16:TP=-1.5:LRA=11,"
                         f"aformat=sample_rates=48000:channel_layouts=stereo,"
                         f"afade=t=in:d={VOICE_EDGE},"
                         f"afade=t=out:st={max(p['length'] - VOICE_EDGE * 2, 0):.3f}:d={VOICE_EDGE * 2},"
                         f"volume={voice['volume']},adelay=delays={delay}:all=1[v{i}]")
        k = len(voice["pieces"])
        if k > 1:
            graph.append("".join(f"[v{i}]" for i in range(k))
                         + f"amix=inputs={k}:normalize=0:duration=longest[voice]")
        else:
            graph.append("[v0]anull[voice]")
        mix.append("[voice]")
    graph.append("".join(mix) + f"amix=inputs={len(mix)}:duration=first:normalize=0,"
                 "alimiter=limit=0.95[a]")
    run(["ffmpeg", "-nostdin", "-y", "-v", "error", *inputs,
         "-filter_complex", ";".join(graph), "-map", "0:v", "-map", "[a]", *common])


# ---------------------------------------------------------------- voice

# A reading laid over the footage: pieces of one or more takes (audio files,
# or the sound of videos), each placed at a time on the reel. The song dips
# to `song_under` while the voice speaks and sits at `song_between` around it.
VOICE_TAIL = 0.8     # the last part holds this long after the voice ends
VOICE_EDGE = 0.04    # fade at each end of a piece, so cuts in a take never click
DUCK_RAMP = 0.4      # how long the song takes to dip under the voice, and come back


def load_voice(cfg, base_dir):
    """`voice:` from the config, checked: {pieces, end, ...}, or None."""
    v = cfg.get("voice")
    if not v or not v.get("pieces"):
        return None
    pieces = []
    for p in v["pieces"]:
        path = (base_dir / p["file"]).expanduser()
        if not path.exists():
            sys.exit(f"Voice file not found: {path}")
        start, end = parse_time(p.get("start", 0)), parse_time(p["end"])
        if end - start < 0.1:
            continue
        pieces.append({"path": path, "start": start, "length": end - start,
                       "at": parse_time(p.get("at", 0))})
    if not pieces:
        return None
    return {"pieces": pieces, "end": max(p["at"] + p["length"] for p in pieces),
            "fit": bool(v.get("fit", True)), "clean": bool(v.get("clean", True)),
            "volume": float(v.get("volume", 1.0)),
            "under": float(v.get("song_under", 0.15)), "between": float(v.get("song_between", 0.3))}


def song_level(voice):
    """The song's volume over time as an ffmpeg expression: `between`, dipping
    to `under` while each piece of the voice plays."""
    r = DUCK_RAMP
    envs = [f"clip((t-{p['at'] - r:.3f})/{r},0,1)*clip(({p['at'] + p['length'] + r:.3f}-t)/{r},0,1)"
            for p in voice["pieces"]]
    duck = envs[0]
    for e in envs[1:]:
        duck = f"max({duck},{e})"
    return f"{voice['between']:.3f}+({voice['under'] - voice['between']:.3f})*{duck}"


# ---------------------------------------------------------------- title and end card

# Both are overlays on the footage that's already there: a translucent forest
# scrim with cream text (and logos), fading in and out. Never a black card.
CARD_SCRIM = (0x2d, 0x3e, 0x26)   # forest-panel
CARD_INK = (0xf7, 0xf1, 0xe3)     # cream
CARD_FADE = 0.6
# Keep text out of what Reels/TikTok cover at 1080x1920: top bar, caption, buttons.
SAFE_TOP, SAFE_BOTTOM, SAFE_SIDE = 250, 420, 120

FONT_DIRS = ["~/Library/Fonts", "/Library/Fonts", "/System/Library/Fonts",
             "/System/Library/Fonts/Supplemental", "/usr/share/fonts", "/usr/local/share/fonts"]
DISPLAY_FONTS = ["PlayfairDisplay-ExtraBold.*", "PlayfairDisplay-Bold.*", "PlayfairDisplay[[]wght[]].ttf",
                 "PlayfairDisplay*.ttf",
                 "Georgia Bold.ttf", "DejaVuSerif-Bold.ttf"]
BODY_FONTS = ["Roboto-Regular.*", "Roboto*.ttf", "Avenir Next.ttc", "Helvetica.ttc", "DejaVuSans.ttf"]


def find_font(override, patterns, base_dir):
    """A font file: the config's, else the brand fonts (in brand/ or installed),
    else a system serif/sans. None = Pillow's built-in font."""
    if override:
        path = (base_dir / override).expanduser()
        if not path.exists():
            sys.exit(f"Font not found: {path}")
        return path
    dirs = [base_dir / "brand", Path(__file__).resolve().parent.parent / "brand", *FONT_DIRS]
    for pattern in patterns:
        for d in dirs:
            d = Path(d).expanduser()
            if d.is_dir():
                hit = next(iter(sorted(d.rglob(pattern))), None)
                if hit:
                    return hit
    return None


def load_font(path, size, bold):
    from PIL import ImageFont
    if path is None:
        return ImageFont.load_default(size)
    font = ImageFont.truetype(str(path), size)
    try:   # a variable font (PlayfairDisplay[wght].ttf): pick its heaviest named weight
        names = [n.decode() if isinstance(n, bytes) else n for n in font.get_variation_names()]
        want = [n for n in ("ExtraBold", "Bold") if n in names] if bold else ["Regular"]
        if want:
            font.set_variation_by_name(want[0])
    except (OSError, AttributeError):
        pass
    return font


def wrap(draw, text, font, width):
    """Break text into lines no wider than width."""
    lines = []
    for para in str(text).split("\n"):
        words, line = para.split(), ""
        for word in words:
            trial = f"{line} {word}".strip()
            if line and draw.textlength(trial, font=font) > width:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
    return lines


def load_cards(cfg, base_dir):
    """`title:` and `end_card:` from the config, checked. Returns a list of
    {kind, spec, logos} (empty when there are none)."""
    cards = []
    for kind in ("title", "end_card"):
        spec = cfg.get(kind)
        if not spec:
            continue
        if isinstance(spec, str):
            spec = {"text": spec} if kind == "title" else {"lines": [spec]}
        logos = spec.get("logos") or ([spec["logo"]] if spec.get("logo") else [])
        paths = []
        for logo in logos:
            path = (base_dir / logo).expanduser()
            if not path.exists():
                sys.exit(f"Logo not found: {path}")
            paths.append(path)
        by = spec.get("presented_by")
        if by:
            by = {"logo": by} if isinstance(by, str) else dict(by)
            by.setdefault("text", "presented by")
            if by.get("logo"):
                by["logo"] = (base_dir / by["logo"]).expanduser()
                if not by["logo"].exists():
                    sys.exit(f"Logo not found: {by['logo']}")
            spec = {**spec, "presented_by": by}
        cards.append({"kind": kind, "spec": spec, "logos": paths})
    if cards:
        try:
            import PIL  # noqa: F401
        except ImportError:
            sys.exit("The title and end card need Pillow: pip install pillow")
    return cards


def card_times(cards, plan, total):
    """When each card is on screen: (start, end) in output seconds. The end card
    comes in with the last part (which build_plan held longer for it) and stays
    to the end."""
    times = {}
    if any(card["kind"] == "end_card" for card in cards):
        start = plan[-1].get("card_from", sum(seg["length"] for seg in plan[:-1]))
        times["end_card"] = (min(start, total), total)
    for card in cards:
        spec = card["spec"]
        if card["kind"] == "title":
            start = float(spec.get("at", 0.2))
            end = start + CARD_FADE + float(spec.get("hold", 2.5)) + CARD_FADE
            limit = times.get("end_card", (total, total))[0] - 0.2
            times["title"] = (start, max(min(end, limit), start + 2 * CARD_FADE))
    return times


def logo_size(im, side):
    """Width and height giving the logo the area of a side x side square."""
    aspect = im.width / im.height
    return side * aspect ** 0.5, side / aspect ** 0.5


def render_card(card, cfg, base_dir, out):
    """Draw one card as a full-frame transparent PNG: the scrim, the logos and
    the text, centred in the safe area."""
    from PIL import Image, ImageDraw, ImageFilter
    w, h = cfg["width"], cfg["height"]
    k = w / 1080
    spec, kind = card["spec"], card["kind"]
    fonts = cfg.get("fonts") or {}
    display = find_font(fonts.get("display"), DISPLAY_FONTS, base_dir)
    body = find_font(fonts.get("body"), BODY_FONTS, base_dir)
    dim = min(max(float(spec.get("dim", 0.45 if kind == "title" else 0.62)), 0.0), 0.95)

    # What to stack, top to bottom: ("logos", height) or (text, font, color, gap above).
    if kind == "title":
        rows = [(spec.get("text", ""), load_font(display, round(124 * k), True), 255)]
        if spec.get("sub"):
            rows.append((spec["sub"], load_font(body, round(54 * k), False), 225))
        logo_side = 280 * k
    else:
        lines = spec.get("lines") or []
        rows = [(line, load_font(display if i == 0 else body, round((82 if i == 0 else 50) * k), i == 0),
                 255 if i == 0 else 225) for i, line in enumerate(lines)]
        logo_side = 340 * k
    by = spec.get("presented_by") if kind == "end_card" else None

    scratch = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    max_w = w - 2 * round(SAFE_SIDE * k)
    blocks = []   # (image, gap above)
    logos = [Image.open(p).convert("RGBA") for p in card["logos"]]
    if logos:
        gap = round(70 * k)
        # Each the same area as a logo_side square, so a wide wordmark and a
        # round mark look alike in weight; smaller together if too wide.
        sizes = [logo_size(im, logo_side) for im in logos]
        fit = min(1.0, (max_w - gap * (len(logos) - 1)) / sum(w_ for w_, _ in sizes))
        sized = [im.resize((max(1, round(w_ * fit)), max(1, round(h_ * fit))), Image.LANCZOS)
                 for im, (w_, h_) in zip(logos, sizes)]
        row = Image.new("RGBA", (sum(im.width for im in sized) + gap * (len(sized) - 1),
                                 max(im.height for im in sized)), (0, 0, 0, 0))
        x = 0
        for im in sized:
            row.alpha_composite(im, (x, (row.height - im.height) // 2))
            x += im.width + gap
        blocks.append((row, 0))
    for i, (text, font, alpha) in enumerate(rows):
        lines = [l for l in wrap(scratch, text, font, max_w) if l] or [""]
        ascent, descent = font.getmetrics()
        lead = round((ascent + descent) * 1.12)
        widths = [scratch.textlength(l, font=font) for l in lines]
        im = Image.new("RGBA", (max_w, lead * len(lines)), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for n, (line, lw) in enumerate(zip(lines, widths)):
            d.text(((max_w - lw) / 2, n * lead), line, font=font, fill=(*CARD_INK, alpha))
        gap = round((44 if blocks and i == 0 else 18) * k)
        blocks.append((im, gap if blocks else 0))

    if by:   # "presented by" and a smaller logo, under the rest
        if by.get("text"):
            font = load_font(body, round(36 * k), False)
            ascent, descent = font.getmetrics()
            im = Image.new("RGBA", (max_w, ascent + descent), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            d.text(((max_w - scratch.textlength(by["text"], font=font)) / 2, 0), by["text"],
                   font=font, fill=(*CARD_INK, 200))
            blocks.append((im, round(80 * k) if blocks else 0))
        if by.get("logo"):
            logo = Image.open(by["logo"]).convert("RGBA")
            w_, h_ = logo_size(logo, 260 * k)
            logo = logo.resize((min(round(w_), max_w), round(h_ * min(1.0, max_w / w_))), Image.LANCZOS)
            blocks.append((logo, round(16 * k) if by.get("text") else round(70 * k)))

    frame = Image.new("RGBA", (w, h), (*CARD_SCRIM, round(dim * 255)))
    content = sum(im.height + gap for im, gap in blocks)
    top_px, bottom_px = round(SAFE_TOP * h / 1920), round(SAFE_BOTTOM * h / 1920)
    y = top_px + max((h - top_px - bottom_px - content) // 2, 0)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for im, gap in blocks:
        y += gap
        layer.alpha_composite(im, ((w - im.width) // 2, y))
        y += im.height
    # A soft shadow under everything keeps the text clear over bright footage.
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shadow.putalpha(layer.getchannel("A").point(lambda a: a * 0.55))
    shadow = shadow.filter(ImageFilter.GaussianBlur(round(10 * k)))
    frame.alpha_composite(shadow, (0, round(3 * k)))
    frame.alpha_composite(layer)
    frame.save(out)
    return out


def add_cards(assembled, cards, times, cfg, base_dir, total, workdir):
    """Lay the cards over the finished picture, fading in and out."""
    fps = cfg["fps"]
    out = workdir / "carded.mkv"
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(assembled)]
    graph, cur = [], "[0:v]"
    for i, card in enumerate(cards, start=1):
        png = render_card(card, cfg, base_dir, workdir / f"{card['kind']}.png")
        start, end = times[card["kind"]]
        cmd += ["-loop", "1", "-framerate", str(fps), "-t", f"{total:.3f}", "-i", str(png)]
        fades = f"fade=t=in:st={start:.3f}:d={CARD_FADE}:alpha=1"
        if end < total - 0.01:
            fades += f",fade=t=out:st={end - CARD_FADE:.3f}:d={CARD_FADE}:alpha=1"
        graph.append(f"[{i}:v]format=rgba,{fades}[c{i}]")
        graph.append(f"{cur}[c{i}]overlay=0:0:eof_action=pass:"
                     f"enable='between(t,{start:.3f},{end:.3f})'[o{i}]")
        cur = f"[o{i}]"
    graph.append(f"{cur}format=yuv420p[v]")
    run(cmd + ["-filter_complex", ";".join(graph), "-map", "[v]", "-map", "0:a",
               *video_codec(cfg), "-r", str(fps), "-c:a", "copy", str(out)])
    return out


# ---------------------------------------------------------------- captions

# The words of the voice track, on screen as they're said. Four styles:
#   stanza  the whole stanza shows; the line being said is bright, the rest dim
#   unfold  lines fade in as they're said and stay until the stanza ends
#   breath  one line at a time, centred, drifting up as it comes in
#   page    set left on the panel under a small title, lines appearing as said
# over one of five backgrounds: scrim (the whole frame dimmed), band, paper (a
# cream panel, forest ink), blur (the footage blurred behind the words) or
# shadow (just a soft shadow). Sizes are in % of the frame's width, like CSS
# cqw; Footage Studio's preview (web/src/captions.js) follows the same rules.
CAPTION_SIZE = {"stanza": 4.3, "unfold": 4.3, "breath": 6.2, "page": 4.3}
CAPTION_BGS = ("scrim", "band", "paper", "blur", "shadow")
CAPTION_FONTS = {   # file in brand/fonts, weight, size next to the others
    "playfair": ("PlayfairDisplay[wght].ttf", 600, 1.0),
    "playfair-italic": ("PlayfairDisplay-Italic[wght].ttf", 500, 1.0),
    "garamond-italic": ("EBGaramond-Italic[wght].ttf", 400, 1.12),
    "cormorant-italic": ("CormorantGaramond-Italic[wght].ttf", 500, 1.18),
    "courier": ("CourierPrime-Regular.ttf", 400, 0.9),
    "roboto": ("Roboto[wdth,wght].ttf", 400, 0.96),
    "caveat": ("Caveat[wght].ttf", 500, 1.32),
}
# Where the words sit: the panel's sides and the padding inside it (% of width).
CAPTION_BOX = {"band": (0, 11, 3.4), "paper": (9, 5.4, 4.4), "blur": (7, 4, 3.6),
               "scrim": (11, 0, 0), "shadow": (11, 0, 0)}
CAPTION_LEADING = 1.32
CAPTION_BOTTOM = 0.75   # the block's bottom edge, as a share of the height (breath: centred)
CAPTION_DIM = 0.38      # stanza: the lines not being said
CAPTION_PAST = 0.82     # unfold: lines already said
CAPTION_X = 0.3         # crossfade as a line brightens or dims
CAPTION_APPEAR = 0.5    # unfold and page: a new line fading in
PAPER_INK = (0x2d, 0x3e, 0x26)


def caption_groups(lines, style):
    """What's on screen together: a stanza (lines up to a stanza break), or for
    breath a single line. Each {a, b, fi, fo, lines}: on screen from a to b,
    fading in over fi and out over fo, never overlapping the next."""
    lines = sorted((l for l in lines if str(l.get("text", "")).strip()), key=lambda l: l["start"])
    if style == "breath":
        sets = [[l] for l in lines]
        lead, tail, fi, fo = 0.35, 0.6, 0.7, 0.6
    else:
        sets = []
        for l in lines:
            if not sets or l.get("stanza"):
                sets.append([])
            sets[-1].append(l)
        lead, tail, fi, fo = 0.45, 0.8, 0.5, 0.5
    groups = [{"a": max(0.0, ls[0]["start"] - lead), "b": ls[-1]["end"] + tail, "lines": ls} for ls in sets]
    for prev, g in zip(groups, groups[1:]):
        if prev["b"] > g["a"] - 0.05:
            prev["b"] = max(prev["lines"][-1]["end"] + 0.05, g["a"] - 0.05)
            g["a"] = max(g["a"], prev["b"])
    for g in groups:
        span = g["b"] - g["a"]
        g["fi"], g["fo"] = min(fi, span / 2), min(fo, span / 2)
    return groups


def caption_segments(group, style):
    """For each line of a group, the stretches it's on screen at one opacity:
    [(alpha, t0, t1, fade_in, fade_out)]. Changes of opacity crossfade."""
    ls, a, b = group["lines"], group["a"], group["b"]
    last = len(ls) - 1
    out = []
    for k, l in enumerate(ls):
        if style == "stanza":   # bright from just before it's said until the next line
            on = a if k == 0 else l["start"] - 0.15
            points = [(a, CAPTION_DIM), (on, 1.0)] if k else [(a, 1.0)]
            if k < last:
                points.append((ls[k + 1]["start"] - 0.15, CAPTION_DIM))
        elif style in ("unfold", "page"):
            at = a if k == 0 else max(a, l["start"] - 0.2)
            points = [(at, 1.0)]
            if style == "unfold" and k < last:
                points.append((max(at, ls[k + 1]["start"] - 0.2), CAPTION_PAST))
        else:
            points = [(a, 1.0)]
        first_fade = group["fi"] if points[0][0] <= a + 1e-6 else CAPTION_APPEAR
        segs = []
        for i, (t, alpha) in enumerate(points):
            t0 = t if i == 0 else t - CAPTION_X / 2
            t1 = points[i + 1][0] + CAPTION_X / 2 if i + 1 < len(points) else b
            t0, t1 = max(t0, a), min(t1, b)
            if t1 - t0 < 0.04:
                continue
            fin = first_fade if i == 0 else CAPTION_X
            fout = CAPTION_X if i + 1 < len(points) else group["fo"]
            segs.append((alpha, t0, t1, min(fin, (t1 - t0) / 2), min(fout, (t1 - t0) / 2)))
        out.append(segs)
    return out


def caption_font_path(name, base_dir):
    """A caption font's file: brand/fonts (next to the config or in the repo),
    else installed; else the card's display font."""
    file = CAPTION_FONTS.get(name, CAPTION_FONTS["playfair"])[0]
    repo = Path(__file__).resolve().parent.parent / "brand"
    for d in [base_dir / "brand" / "fonts", repo / "fonts", base_dir / "brand", repo, *FONT_DIRS]:
        p = Path(d).expanduser() / file
        if p.exists():
            return p
    return find_font(None, DISPLAY_FONTS, base_dir)


def load_caption_font(path, size, weight):
    from PIL import ImageFont
    if path is None:
        return ImageFont.load_default(size)
    font = ImageFont.truetype(str(path), size)
    try:   # a variable font: set its weight axis
        axes = font.get_variation_axes()
        font.set_variation_by_axes([weight if str(ax.get("name", b"")).find("Weight") >= 0
                                    else ax["default"] for ax in axes])
    except (OSError, AttributeError):
        pass
    return font


def caption_layout(cap, cfg, base_dir):
    """The font and where the block of words sits, in pixels."""
    w, h = cfg["width"], cfg["height"]
    style = cap.get("style") if cap.get("style") in CAPTION_SIZE else "breath"
    bg = cap.get("background") if cap.get("background") in CAPTION_BGS else "shadow"
    name = cap.get("font") if cap.get("font") in CAPTION_FONTS else "playfair"
    _, weight, scale = CAPTION_FONTS[name]
    size = CAPTION_SIZE[style] * scale * float(cap.get("size", 1) or 1) * w / 100
    font = load_caption_font(caption_font_path(name, base_dir), max(8, round(size)), weight)
    side, pad_x, pad_y = (v * w / 100 for v in CAPTION_BOX[bg])
    lay = {"w": w, "h": h, "style": style, "bg": bg, "font": font, "size": size,
           "lead": size * CAPTION_LEADING, "x0": side, "x1": w - side, "pad_x": pad_x, "pad_y": pad_y,
           "ink": PAPER_INK if bg == "paper" else CARD_INK, "title": "", "base_dir": base_dir,
           "fps": cfg["fps"]}
    lay["text_x"] = side + pad_x
    lay["text_w"] = w - 2 * (side + pad_x)
    if style == "page" and str(cap.get("title") or "").strip():
        lay["title"] = str(cap["title"]).strip().upper()
        lay["title_font"] = load_caption_font(caption_font_path(name, base_dir),
                                              max(8, round(size * 0.62)), weight)
    return lay


def caption_block(lay, group):
    """Where a group's block and each of its lines sit: {y0, y1, lines: [(y, rows)],
    title_y}. The rows are each line wrapped to the block's width."""
    from PIL import Image, ImageDraw
    scratch = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lead = lay["lead"]
    fold = wrap if lay["style"] == "page" else balanced   # a page wraps like print
    rows = [[r for r in fold(scratch, l["text"].strip(), lay["font"], lay["text_w"]) if r] or [""]
            for l in group["lines"]]
    title_h = lay["size"] * 0.62 * (CAPTION_LEADING + 0.9) if lay["title"] else 0
    content = title_h + lead * sum(len(r) for r in rows)
    block = content + 2 * lay["pad_y"]
    y0 = lay["h"] / 2 - block / 2 if lay["style"] == "breath" else lay["h"] * CAPTION_BOTTOM - block
    y = y0 + lay["pad_y"] + title_h
    placed = []
    for r in rows:
        placed.append((y, r))
        y += lead * len(r)
    return {"y0": y0, "y1": y0 + block, "lines": placed, "title_y": y0 + lay["pad_y"]}


def balanced(draw, text, font, width):
    """Wrap text into as few rows as fit, with the rows as even as they can be
    (like CSS text-wrap: balance), so no word is left on its own."""
    rows = [r for r in wrap(draw, text, font, width) if r] or [""]
    if len(rows) < 2:
        return rows
    lo, hi = width / len(rows), width
    while hi - lo > 2:
        mid = (lo + hi) / 2
        if len([r for r in wrap(draw, text, font, mid) if r]) <= len(rows):
            hi = mid
        else:
            lo = mid
    return [r for r in wrap(draw, text, font, hi) if r]


def caption_line_image(lay, rows, alpha, out):
    """One line (wrapped to one or more rows) as a transparent PNG, with room
    around it for its shadow. Returns (path, margin)."""
    from PIL import Image, ImageDraw, ImageFilter
    k = lay["w"] / 1080
    m = round(40 * k)
    lead, font = lay["lead"], lay["font"]
    ascent, descent = font.getmetrics()
    im = Image.new("RGBA", (round(lay["text_w"]) + 2 * m, round(lead * len(rows)) + 2 * m), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, row in enumerate(rows):
        rw = d.textlength(row, font=font)
        x = m + (0 if lay["style"] == "page" else (lay["text_w"] - rw) / 2)
        d.text((x, m + i * lead + (lead - ascent - descent) / 2), row, font=font, fill=(*lay["ink"], 255))
    if lay["bg"] in ("shadow", "scrim"):   # a soft shadow keeps the words clear on bright footage
        shadow = Image.new("RGBA", im.size, (0, 0, 0, 0))
        shadow.putalpha(im.getchannel("A").point(lambda v: v * 0.55))
        shadow = shadow.filter(ImageFilter.GaussianBlur(13 * k))
        base = Image.new("RGBA", im.size, (0, 0, 0, 0))
        base.alpha_composite(shadow, (0, round(3 * k)))
        base.alpha_composite(im)
        im = base
    if alpha < 1:
        im.putalpha(im.getchannel("A").point(lambda v: v * alpha))
    im.save(out)
    return out, m


def caption_title_image(lay, out):
    from PIL import Image, ImageDraw
    font = lay["title_font"]
    ascent, descent = font.getmetrics()
    lead = lay["size"] * 0.62 * CAPTION_LEADING
    im = Image.new("RGBA", (round(lay["text_w"]), round(lead)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x, spacing = 0.0, lay["size"] * 0.62 * 0.14
    for ch in lay["title"]:   # letter-spaced, like the preview
        d.text((x, (lead - ascent - descent) / 2), ch, font=font, fill=(*lay["ink"], round(255 * 0.75)))
        x += d.textlength(ch, font=font) + spacing
    im.save(out)
    return out


def caption_panel_image(lay, width, height, out):
    """The paper background: a cream panel with soft corners and a shadow."""
    from PIL import Image, ImageDraw, ImageFilter
    k = lay["w"] / 1080
    sigma = 21.6 * k
    m = round(3 * sigma)
    im = Image.new("RGBA", (round(width) + 2 * m, round(height) + 2 * m + round(11 * k)), (0, 0, 0, 0))
    shadow = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle([m, m + round(11 * k), m + width, m + height + round(11 * k)],
                                     fill=(0, 0, 0, round(255 * 0.3)))
    im.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(sigma)))
    ImageDraw.Draw(im).rounded_rectangle([m, m, m + width, m + height], radius=round(8.6 * k),
                                         fill=(*CARD_INK, round(255 * 0.95)))
    im.save(out)
    return out, m


def caption_layers(lines, cap, cfg, base_dir, workdir, total):
    """Everything to lay over the picture for the captions, in order:
    {kind: png | color | blur, t0, t1, fi, fo, x, y, ...}."""
    lay = caption_layout(cap, cfg, base_dir)
    w, k = lay["w"], lay["w"] / 1080
    layers, n = [], 0
    for gi, g in enumerate(caption_groups(lines, lay["style"])):
        if g["a"] >= total:
            break
        g["b"] = min(g["b"], total)
        geo = caption_block(lay, g)
        span = {"t0": g["a"], "t1": g["b"], "fi": g["fi"], "fo": g["fo"]}
        top, bh = round(geo["y0"]), round(geo["y1"] - geo["y0"])
        x0, x1 = round(lay["x0"]), round(lay["x1"])
        if lay["bg"] == "scrim":
            layers.append({"kind": "color", "color": "0x2d3e26@0.48", "x": 0, "y": 0, "size": (w, lay["h"]), **span})
        elif lay["bg"] == "band":
            layers.append({"kind": "color", "color": "0x2d3e26@0.64", "x": 0, "y": top, "size": (w, bh), **span})
        elif lay["bg"] == "blur":
            layers.append({"kind": "blur", "x": x0, "y": top, "size": (x1 - x0, bh), "sigma": 26 * k, **span})
            layers.append({"kind": "color", "color": "0x121812@0.26", "x": x0, "y": top, "size": (x1 - x0, bh), **span})
        elif lay["bg"] == "paper":
            png, m = caption_panel_image(lay, x1 - x0, bh, workdir / f"cap-panel-{gi}.png")
            layers.append({"kind": "png", "path": png, "x": x0 - m, "y": top - m, **span})
        if lay["title"]:
            png = caption_title_image(lay, workdir / "cap-title.png")
            layers.append({"kind": "png", "path": png, "x": round(lay["text_x"]), "y": round(geo["title_y"]), **span})
        drift = lay["style"] == "breath"
        for (y, rows), segs in zip(geo["lines"], caption_segments(g, lay["style"])):
            for alpha, t0, t1, fi, fo in segs:
                if t0 >= total:
                    continue
                n += 1
                png, m = caption_line_image(lay, rows, alpha, workdir / f"cap-{n:03d}.png")
                layer = {"kind": "png", "path": png, "x": round(lay["text_x"]) - m, "y": round(y) - m,
                         "t0": t0, "t1": min(t1, total), "fi": fi, "fo": fo}
                if drift:   # rises 2.2% of the width as it comes in, 1.2% as it goes
                    layer["drift"] = (2.2 * w / 100, 1.2 * w / 100, g["a"], g["b"], g["fi"], g["fo"])
                layers.append(layer)
    return layers


def add_captions(assembled, lines, cap, cfg, base_dir, total, workdir):
    """Lay the captions over the picture: each line and background only for
    the time it's on screen, fading in and out."""
    fps, w, h = cfg["fps"], cfg["width"], cfg["height"]
    layers = caption_layers(lines, cap, cfg, base_dir, workdir, total)
    if not layers:
        return assembled
    out = workdir / "captioned.mkv"
    inputs, graph = ["-i", str(assembled)], []
    blurs = [l for l in layers if l["kind"] == "blur"]
    cur = "[0:v]"
    if blurs:
        graph.append(f"[0:v]split={len(blurs) + 1}[base]" + "".join(f"[bl{i}]" for i in range(len(blurs))))
        cur = "[base]"
    nb = 0
    for i, l in enumerate(layers):
        dur = l["t1"] - l["t0"]
        if dur < 0.04:
            continue
        fades = (f"fade=t=in:st=0:d={l['fi']:.3f}:alpha=1,"
                 f"fade=t=out:st={max(dur - l['fo'], 0):.3f}:d={l['fo']:.3f}:alpha=1,"
                 f"setpts=PTS-STARTPTS+{l['t0']:.3f}/TB")
        if l["kind"] == "blur":
            cw, ch = l["size"]
            graph.append(f"[bl{nb}]trim=start={l['t0']:.3f}:end={l['t1']:.3f},setpts=PTS-STARTPTS,"
                         f"crop={cw}:{ch}:{l['x']}:{l['y']},gblur=sigma={l['sigma']:.1f},format=rgba,{fades}[L{i}]")
            nb += 1
        else:
            idx = inputs.count("-i")
            if l["kind"] == "color":
                cw, ch = l["size"]
                inputs += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i",
                           f"color=c={l['color']}:s={cw}x{ch}:r={fps},format=rgba"]
            else:
                inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", str(l["path"])]
            graph.append(f"[{idx}:v]format=rgba,{fades}[L{i}]")
        y = str(l["y"])
        if l.get("drift"):
            up, away, a, b, fi, fo = l["drift"]
            y = (f"'{l['y']}+{up:.1f}*max(0,1-(t-{a:.3f})/{max(fi, 0.01):.3f})"
                 f"-{away:.1f}*max(0,1-({b:.3f}-t)/{max(fo, 0.01):.3f})'")
        graph.append(f"{cur}[L{i}]overlay=x={l['x']}:y={y}:eof_action=pass[c{i}]")
        cur = f"[c{i}]"
    graph.append(f"{cur}format=yuv420p[v]")
    run(["ffmpeg", "-nostdin", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(graph),
         "-map", "[v]", "-map", "0:a", *video_codec(cfg), "-r", str(fps), "-c:a", "copy", str(out)])
    return out


def load_captions(cfg):
    """`captions:` from the config: (lines, style settings), or (None, None)."""
    cap = cfg.get("captions")
    if not cap or not cap.get("lines"):
        return None, None
    lines = [{"start": parse_time(l["start"]), "end": parse_time(l["end"]),
              "text": str(l.get("text", "")), "stanza": bool(l.get("stanza"))}
             for l in cap["lines"] if str(l.get("text", "")).strip()]
    if lines:
        try:
            import PIL  # noqa: F401
        except ImportError:
            sys.exit("Captions need Pillow: pip install pillow")
    return (lines or None), cap


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
    top = load_top(cfg, base_dir)
    cards = load_cards(cfg, base_dir)
    voice = load_voice(cfg, base_dir)
    cap_lines, cap = load_captions(cfg)
    plan, warnings = build_plan(cfg, base_dir, beats, voice)
    if not plan:
        sys.exit("Nothing to cut. Check your start/step/times against clip lengths.")

    total = sum(s["length"] for s in plan)
    print(f"\n{len(plan)} cuts, {total:.1f}s total\n")
    t = 0.0
    for seg in plan:
        where = "hold" if seg["kind"] == "image" else f"from {fmt(seg['start'])}"
        layout = ""
        if seg.get("fit"):
            layout = f"  [{seg['fit']}]"
        print(f"  {fmt(t):>7}  r{seg['round']}  {seg['label']:<16} {where:<12} {seg['length']:.2f}s{layout}")
        if seg["t_after"]:
            print(f"  {'':>7}      ~ {seg['label_after']} {seg['d_after']:.2f}s")
        elif seg["label_after"]:
            print(f"  {'':>7}      ~ {seg['label_after']}")
        t += seg["length"]
    if top:
        line = (f"\n  top: {top['path'].name} {fmt(top['start'])} -> "
                f"{fmt(top['start'] + top['length'])} · Top {fmt(top['length'])} · Underneath {fmt(total)}")
        if top["fit"]:
            line += f" · timelapse at {top['length'] / total:.2f}x"
        elif total > top["length"]:
            line += f" · underneath cut at {fmt(top['length'])}"
        elif total < top["length"]:
            line += f" · last part holds {top['length'] - total:.1f}s"
        print(line)
    length = top_length(top, total) if top else total
    times = card_times(cards, plan, length)
    for card in cards:
        start, end = times[card["kind"]]
        what = card["spec"].get("text") if card["kind"] == "title" else " · ".join(card["spec"].get("lines") or [])
        name = "title" if card["kind"] == "title" else "end card"
        print(f"\n  {name}: {fmt(start)} -> {fmt(end)}  {what or ''}".rstrip()
              + (f"  [{', '.join(p.name for p in card['logos'])}]" if card["logos"] else ""))
    if voice:
        print(f"\n  voice: {len(voice['pieces'])} piece{'s' if len(voice['pieces']) != 1 else ''}, "
              f"{fmt(voice['pieces'][0]['at'])} -> {fmt(voice['end'])}"
              + (f" · song at {round(voice['under'] * 100)}% under it" if cfg.get("music") else ""))
        for p in voice["pieces"]:
            print(f"  {fmt(p['at']):>7}  {p['path'].name:<24} {fmt(p['start'])} -> {fmt(p['start'] + p['length'])}")
        if plan[-1]["hold_extra"]:
            print(f"  {'':>7}  last part holds {plan[-1]['hold_extra']:.1f}s longer for the voice")
        if voice["end"] > length + 0.05:
            warnings.append(f"the voice runs {voice['end'] - length:.1f}s past the end and is cut there")
    if cap_lines:
        print(f"\n  captions: {len(cap_lines)} lines · {cap.get('style', 'breath')}, "
              f"{cap.get('font', 'playfair')}, {cap.get('background', 'shadow')}")
    for w in warnings:
        print(f"  ! {w}")
    print()

    if args.dry_run:
        return

    keep_audio = bool(cfg.get("original_audio", False))
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
        if top:
            print("  stacking under the top clip...          ", end="\r")
            assembled = compose_top(top, assembled, cfg, total, workdir)
            total = top_length(top, total)
        if cap_lines:
            print("  laying the captions over...             ", end="\r")
            assembled = add_captions(assembled, cap_lines, cap, cfg, base_dir, total, workdir)
        if cards:
            print("  laying the title and end card over...    ", end="\r")
            assembled = add_cards(assembled, cards, times, cfg, base_dir, total, workdir)
        print("  mixing sound...                         ", end="\r")
        finish(assembled, cfg, base_dir, music_start, total, keep_audio, output, voice)

    print(f"Done: {output}                          ")
    if cfg.get("music") and not cfg.get("music_in_video", True):
        print(f"Song left out; add it in Instagram starting at {fmt(music_start)}")
    print()


if __name__ == "__main__":
    main()
