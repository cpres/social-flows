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
import array
import json
import math
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

# Glasses audio (the clips' own sound): `glasses_audio:` primary (the lane in
# the primary slot: top/left, or the one alone), A (lane A whenever it's on
# screen, never B) or off. Older configs say `original_audio: true/false`.
GLASSES_MODES = ("primary", "A", "off")
SWITCH_FADE = 0.04   # where a scene's sound comes from somewhere else: out 40ms, in 40ms
# The song ducks under loud glasses audio (`duck_music:`, on by default), as
# it does under the voice. The same numbers are in studio/web/src/audioMix.js.
DUCK_DB = 9.0          # how far the song drops
DUCK_ATTACK = 0.15     # seconds to drop
DUCK_RELEASE = 0.4     # seconds to come back
DUCK_THRESHOLD = -38.0  # dBFS of the kept glasses audio (over 0.2s) that counts as loud
DUCK_GAP = 0.5         # quieter gaps shorter than this stay ducked
DUCK_MIN = 0.15        # loud moments shorter than this don't duck


# ---------------------------------------------------------------- helpers

def glasses_mode(cfg):
    mode = cfg.get("glasses_audio")
    if mode in GLASSES_MODES:
        return mode
    return "primary" if cfg.get("original_audio") else "off"


def mix_level(cfg, layer):
    """A layer's fader (`mix:` {A, B, music, voice}, 0..1.5; 1 if unset)."""
    try:
        return min(max(float((cfg.get("mix") or {}).get(layer, 1)), 0.0), 1.5)
    except (TypeError, ValueError):
        return 1.0


def scene_sound(scene, lanes, mode):
    """Which lane's sound a scene keeps, or None for none."""
    if mode == "off":
        return None
    if mode == "A":
        return "A" if "A" in lanes else None
    primary = "A" if scene.get("layout") in ("soloA", "stack") else "B"
    return primary if primary in lanes else lanes[0]

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
        if src.get("gap"):   # a Stack reel's "top alone": no footage underneath
            continue
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
            if src.get("gap"):
                seconds = float(src.get("length", 2.0))
                if src.get("beats") is None and beats is not None:   # whole beats, nearest the seconds
                    steps = sorted(b - a for a, b in zip(beats, beats[1:]))
                    beat = steps[len(steps) // 2] if steps else 0.5
                    n = max(1, round(seconds / beat))
                else:
                    n = beat_count(src.get("beats"), 4)
                plan.append({"kind": "gap", "label": src.get("id", "top alone"), "round": r,
                             "start": 0.0, "pane": "gap", "transition": "cut", "scene": src.get("scene"),
                             "seconds": seconds, "beats": n})
                continue
            label = src.get("id", src["_path"].stem)
            pane = "solo" if src.get("pane") == "solo" else "split"
            scene = src.get("scene")
            if src["_is_image"]:
                if r in rounds_for_image(src, total_rounds):
                    plan.append({"kind": "image", "path": src["_path"], "label": label,
                                 "round": r, "start": 0.0, "focus": src.get("focus", (0.5, 0.5)),
                                 "transition": src.get("transition"),
                                 "lighten": float(src.get("lighten", 0) or 0),
                                 "zoom": float(src.get("zoom", 1) or 1),
                                 "fit": src.get("fit"), "pane": pane, "scene": scene,
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
                         "fit": src.get("fit"), "pane": pane, "scene": scene,
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
            if ("gap" in (seg["kind"], nxt["kind"]) or seg.get("pane") != nxt.get("pane")
                    or seg.get("scene") != nxt.get("scene")):
                pass   # the layout changes here: the scene's own transition is used
            elif style == "zoom":            # a hard cut; the next shot punches in
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


def fit_filter(cfg, src_label, out_label, focus=(0.5, 0.5), zoom=1.0, fit=None, pre=""):
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
        return (f"[{src_label}]{pre}scale={zw}:{zh}:force_original_aspect_ratio=increase,"
                f"{crop}[{out_label}]")
    if fit == "blur":
        return (f"[{src_label}]{pre}split[fa][fb];"
                f"[fa]scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"{crop},boxblur=30:5[fbg];"
                f"[fb]scale={w}:{h}:force_original_aspect_ratio=decrease[ffg];"
                f"[fbg][ffg]overlay=(W-w)/2:(H-h)/2[{out_label}]")
    if fit == "pad":
        color = BRAND_BG.get(cfg.get("pad_color", "forest"), cfg.get("pad_color"))
        return (f"[{src_label}]{pre}scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={color}[{out_label}]")
    sys.exit(f"Unknown fit mode: {fit} (use fill, blur, or pad)")


def gap_footage(plan, i):
    """What plays underneath during "top alone" (plan[i]): the part before it
    carries on, so it doesn't freeze while it slides away; at the very start,
    nothing (it's never seen). Silent either way."""
    seg = plan[i]
    prev = plan[i - 1] if i > 0 else None
    while prev is not None and prev["kind"] == "gap":
        prev = prev.get("_from")
    if prev is None:
        return {**seg, "kind": "blank"}
    out = {**prev, **{k: seg[k] for k in ("length", "render_length", "label", "round")},
           "has_audio": False, "punch_in": 0.0, "whip_in": 0.0, "whip_out": 0.0,
           "hold_extra": seg.get("hold_extra", 0.0), "_from": prev}
    if prev["kind"] == "video":
        out["start"] = prev["start"] + prev["length"]
    return out


def render_segment(seg, idx, cfg, workdir, keep_audio):
    """Render one cut to a uniform intermediate (x264 + PCM in mkv)."""
    w, h, fps = cfg["width"], cfg["height"], cfg["fps"]
    if seg["kind"] == "blank":
        out = workdir / (f"seg_{idx:03d}.mkv" if isinstance(idx, int) else f"seg_{idx}.mkv")
        length = seg["render_length"]
        run(["ffmpeg", "-nostdin", "-y", "-v", "error",
             "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={fps}",
             "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
             "-t", f"{length:.4f}", "-map", "0:v", "-map", "1:a", *video_codec(cfg),
             "-r", str(fps), "-c:a", "pcm_s16le", str(out)])
        return out
    length = seg["render_length"]
    n_frames = round(length * fps)
    out = workdir / (f"seg_{idx:03d}.mkv" if isinstance(idx, int) else f"seg_{idx}.mkv")
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
    # Lift shadows and midtones (gamma) rather than flat brightness, so shade
    # opens up without blowing out the sky; then the reel's look.
    pre = hdr_fix(seg["path"]) if seg["kind"] == "video" else ""
    post = grade(cfg, lift)
    if post:
        graph = fit_filter(cfg, "0:v", "fit0", *framing, pre=pre) + f";[fit0]{post.rstrip(',')}[fit];"
    else:
        graph = fit_filter(cfg, "0:v", "fit", *framing, pre=pre) + ";"
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


def assemble(segs, plan, cfg, workdir, name="assembled"):
    """Join all cuts, applying hard cuts or crossfades between them."""
    fps = cfg["fps"]
    out = workdir / f"{name}.mkv"
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


SLIDE = 0.5          # seconds the Stack's panes take to slide into a new layout
QUIET_KEEP = 3.0     # quiet cuts never leave a piece shorter than this
QUIET_GAP = 12.0     # ... and take out about this much at a time, at most
QUIET_LEVEL = 0.22   # "nothing much happening": movement below this share of the clip's busiest
QUIET_MIN = 1.5      # a lull has to last this long to be cut out


def load_top(cfg, base_dir):
    """A stack piece: `top:` is a clip shown in the top pane (the left one in
    a wide frame), `stack:` the split and the divider. The cuts play in the
    other pane, so this narrows cfg's height (or width) to it. Returns the
    top, or None.

    With stack fit on (the default) the top clip is made to end with the
    cuts: sped up or slowed down (fit_by: speed), or with its quiet stretches
    taken out (fit_by: quiet, from `top.activity`). With it off, the top
    clip plays at normal speed: a piece whose layout never changes is then
    as long as the top clip, and the cuts are cut short or hold their last
    frame.

    A cut can fill the frame on its own (pane: solo) and a `gap:` source is
    the top clip on its own; then the panes slide between the layouts, a
    pane on its own sits in the middle over a blurred copy of itself, and
    the top clip pauses while it's off screen."""
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
    axis = "x" if cfg["width"] > cfg["height"] else "y"   # side by side in a wide frame
    along = "width" if axis == "x" else "height"
    full = cfg[along]
    divider = min(max(int(st.get("divider", 4)) // 2 * 2, 0), 40)
    split = min(max(float(st.get("split", 0.5)), 0.1), 0.9)
    top_size = round((full - divider) * split / 2) * 2
    out = {"path": path, "start": start, "length": length, "axis": axis, "along": along,
           "size": top_size, "full": full, "under": full - divider - top_size,
           "width": top_size if axis == "x" else cfg["width"],
           "height": top_size if axis == "y" else cfg["height"],
           "focus": top.get("focus", (0.5, 0.5)), "zoom": float(top.get("zoom", 1) or 1),
           "lighten": float(top.get("lighten", 0) or 0),
           "divider": divider, "color": str(st.get("divider_color", "#f7f1e3")).replace("#", "0x"),
           "fit": bool(st.get("fit", True)),
           "fit_by": "quiet" if st.get("fit_by") == "quiet" else "speed",
           "speed": min(max(float(st.get("speed", 1) or 1), 0.25), 16.0),   # with fit off
           "activity": [(float(t), float(v)) for t, v in top.get("activity") or []]}
    cfg[along] = out["under"]
    return out


def layout_keys(plan, fps):
    """Where the Stack's layout is over time, as [(frame, x)]: x is -1 with
    the top clip alone, 0 split, 1 the cuts alone; between two keys it
    eases from one to the other. Each change starts at the cut and slides
    for SLIDE seconds (less if the next change comes sooner)."""
    state = {"gap": -1, "solo": 1}
    marks, f = [], 0
    for seg in plan:
        marks.append((f, state.get(seg.get("pane"), 0)))
        f += round(seg["length"] * fps)
    total = f
    changes = [marks[0]] + [(b, x) for (b, x), (_, prev) in zip(marks[1:], marks) if x != prev]
    keys = [changes[0]]
    for i, (b, x) in enumerate(changes[1:], 1):
        nxt = changes[i + 1][0] if i + 1 < len(changes) else total
        slide = max(1, min(round(SLIDE * fps), nxt - b))
        keys += [(b, keys[-1][1]), (b + slide, x)]
    return keys, total


def x_at(keys, frame):
    """The layout at a frame: as layout_expr, in Python."""
    import math
    x = keys[0][1]
    for (f0, x0), (f1, x1) in zip(keys, keys[1:]):
        if frame < f0:
            break
        if frame < f1 and f1 > f0:
            u = (frame - f0) / (f1 - f0)
            return x0 + (x1 - x0) * (0.5 - 0.5 * math.cos(math.pi * u))
        x = x1
    return x


def layout_expr(keys, fps):
    """x(t) for an ffmpeg expression: eased from key to key."""
    out = f"{keys[-1][1]}"
    for (f0, x0), (f1, x1) in reversed(list(zip(keys, keys[1:]))):
        t0, t1 = f0 / fps, f1 / fps
        if x0 == x1 or f1 <= f0:
            piece = f"{x0}"
        else:
            piece = f"({x0}+({x1 - x0})*(0.5-0.5*cos(PI*(t-{t0:.4f})/{t1 - t0:.4f})))"
        out = f"if(lt(t,{t1:.4f}),{piece},{out})"
    return out


def quiet_cut(points, start, length, need=None):
    """Pieces [(start, length)] of the stretch start..start+length with its
    quiet moments taken out. points are [(seconds, 0..1)] of how much
    happens (the studio's movement measure).

    With `need` (seconds), about length - need is taken out, a few seconds
    at a time from the quietest stretches, so the pieces add up to need.
    Without it, every lull (QUIET_LEVEL for QUIET_MIN seconds or more) is
    taken out. Pieces are never shorter than QUIET_KEEP; the first and last
    stay put. What can't be taken out is left in."""
    end = start + length
    step = 0.25
    n = int(length / step)
    if n < 4:
        return [(start, length)]
    pts = sorted(p for p in points if start - 2 <= p[0] <= end + 2)

    def level(t):   # straight lines between the measured points
        if not pts:
            return 1.0
        if t <= pts[0][0]:
            return pts[0][1]
        for (ta, va), (tb, vb) in zip(pts, pts[1:]):
            if t <= tb:
                return va + (vb - va) * (t - ta) / max(tb - ta, 1e-6)
        return pts[-1][1]

    raw = [level(start + (i + 0.5) * step) for i in range(n)]
    act = [sum(raw[max(0, i - 2):i + 3]) / len(raw[max(0, i - 2):i + 3]) for i in range(n)]
    keep_n = int(QUIET_KEEP / step)
    gaps = []   # [(first bin, bins)] taken out

    def free(a, k):   # a gap at bins a..a+k leaves every piece at least QUIET_KEEP
        if a < keep_n or a + k > n - keep_n:
            return False
        return all(a + k + keep_n <= g or g + gk + keep_n <= a for g, gk in gaps)

    lulls, i, min_k = [], 0, int(QUIET_MIN / step)
    while i < n:   # stretches where nothing much happens, a moment in from each end
        if act[i] < QUIET_LEVEL:
            j = i
            while j < n and act[j] < QUIET_LEVEL:
                j += 1
            if j - i - 2 >= min_k:
                lulls.append((sum(act[i:j]) / (j - i), i + 1, j - i - 2))
            i = j
        else:
            i += 1
    drop = int(round(max(length - need, 0) / step)) if need is not None else n
    for _, a, k in sorted(lulls):   # the quietest first
        if drop <= 0:
            break
        if k > drop:                # only part of it is needed: from its middle
            a, k = a + (k - drop) // 2, drop
        while k >= 2 and not free(a, k):   # too near an end or another cut
            a, k = a + 1, k - 2
        if k >= 2:
            gaps.append((a, k))
            drop -= k
    if need is not None:            # still too long: the quietest of what's left
        k = min(drop, int(QUIET_GAP / step))
        while drop > 0 and k >= 2:
            k = min(k, drop)
            options = [(sum(act[a:a + k]) / k, a) for a in range(n - k + 1) if free(a, k)]
            if not options:   # no room for one this long: try shorter ones
                k //= 2
                continue
            gaps.append((min(options)[1], k))
            drop -= k
    pieces, at = [], 0
    for a, k in sorted(gaps):
        pieces.append((round(start + at * step, 3), round((a - at) * step, 3)))
        at = a + k
    pieces.append((round(start + at * step, 3), round(end - (start + at * step), 3)))
    return [p for p in pieces if p[1] > 0.05]


def top_plan(top, keys, total, fps):
    """How the top clip fills the time it's on screen: the frames it shows
    (on the piece's clock), the pieces of the clip it plays and how fast."""
    visible = [x_at(keys, f) < 0.999 for f in range(total)]
    shown = sum(visible) / fps
    pieces, rate = [(top["start"], top["length"])], top["speed"]
    if top["fit"] and shown > 0:
        if top["fit_by"] == "quiet":
            pieces = quiet_cut(top["activity"], top["start"], top["length"], shown)
            rate = max(1.0, sum(l for _, l in pieces) / shown)   # what couldn't be cut, sped up
        else:
            rate = top["length"] / shown
    return visible, pieces, rate


def top_length(top, under, keys=None):
    """How long the piece runs: the cuts' length when the top is fitted to
    them or the layout changes, else the top clip's own length."""
    moving = keys is not None and len(keys) > 1
    return under if top["fit"] or moving or top["fit_by"] == "quiet" else round(top["length"] / top["speed"] * 1000) / 1000


# A reel's look, laid on every clip as it's cut (not on the cards or captions,
# so the brand's colours stay exact). vivid: more colour, a touch more contrast
# and depth in the shadows; rich: more of both.
LOOKS = {
    "vivid": "eq=contrast=1.08:saturation=1.28:brightness=-0.012:gamma=0.97",
    "rich": "eq=contrast=1.15:saturation=1.45:brightness=-0.02:gamma=0.94",
}


def grade(cfg, lift=0.0):
    """A clip's lighten (its own) and the reel's look, as filters to chain."""
    look = LOOKS.get((cfg or {}).get("look") or "")
    return lighten_eq(lift) + (f"{look}," if look else "")


# HDR video (iPhones record HLG by default) turned into ordinary video without
# tone mapping comes out grey and washed out. Such clips are tone mapped first.
_HDR = {}
_ZSCALE = None


def hdr_fix(path):
    """Filters that tone map an HDR clip to ordinary (BT.709) video, or ''."""
    global _ZSCALE
    path = str(path)
    if path not in _HDR:
        try:
            out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                  "stream=color_transfer,color_primaries", "-of", "csv=p=0", path],
                                 capture_output=True, text=True, timeout=30).stdout
        except Exception:
            out = ""
        _HDR[path] = any(t in out for t in ("arib-std-b67", "smpte2084"))
    if not _HDR[path]:
        return ""
    if _ZSCALE is None:
        filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
        _ZSCALE = " zscale " in filters and " tonemap " in filters
    if not _ZSCALE:
        return ""
    return ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
            "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,")


def lighten_eq(lift):
    lift = min(max(lift, 0.0), 1.0)
    return f"eq=gamma={1 + LIGHTEN_GAMMA * lift:.3f}:saturation={1 + 0.08 * lift:.3f}," if lift else ""


def compose_top(top, assembled, cfg, under, workdir, plan=None):
    """The top clip over the divider over the cuts (left of them, in a wide
    frame). With a layout that changes (see load_top), compose_layout."""
    fps = cfg["fps"]
    keys, frames_total = layout_keys(plan, fps) if plan else ([(0, 0)], round(under * fps))
    if len(keys) > 1 or top["fit_by"] == "quiet":
        return compose_layout(top, assembled, cfg, keys, frames_total, workdir)
    total = top_length(top, under)
    along = top["along"]
    pane = cfg[along]
    out = workdir / "stacked.mkv"
    cfg[along] = top["size"]
    graph = fit_filter(cfg, "0:v", "tfit", top["focus"], top["zoom"], "fill", pre=hdr_fix(top["path"])) + ";"
    cfg[along] = pane
    speed = total / top["length"] if top["fit"] else 1 / top["speed"]
    frames = round(total * fps)
    graph += (f"[tfit]setpts=(PTS-STARTPTS)*{speed:.6f},fps={fps},{grade(cfg, top['lighten'])}setsar=1,"
              f"format=yuv420p,trim=end_frame={frames},setpts=PTS-STARTPTS[top];")
    # Cuts shorter than the top clip hold their last frame (and go quiet).
    hold = max(total - under, 0)
    pad = f",tpad=stop_mode=clone:stop_duration={hold:.3f}" if hold > 0.001 else ""
    graph += (f"[1:v]setpts=N/({fps}*TB),setsar=1,format=yuv420p{pad},trim=end_frame={frames},setpts=PTS-STARTPTS[bot];"
              f"[1:a]apad,atrim=0:{total:.4f},asetpts=PTS-STARTPTS[a];")
    stack = "hstack" if top["axis"] == "x" else "vstack"
    if top["divider"]:
        size = f"{top['divider']}x{cfg['height']}" if top["axis"] == "x" else f"{cfg['width']}x{top['divider']}"
        graph += (f"color=c={top['color']}:s={size}:r={fps},format=yuv420p,"
                  f"trim=end_frame={frames}[div];[top][div][bot]{stack}=inputs=3[v]")
    else:
        graph += f"[top][bot]{stack}=inputs=2[v]"
    run(["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-ss", f"{top['start']:.3f}", "-t", f"{top['length']:.3f}", "-i", str(top["path"]),
         "-i", str(assembled), "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
         *video_codec(cfg), "-r", str(fps), "-c:a", "pcm_s16le", str(out)])
    cfg[along] = top["full"]
    return out


def compose_layout(top, assembled, cfg, keys, total, workdir):
    """A Stack whose layout changes: the top clip, the divider and the cuts
    each move to where the layout has them at every frame, over a blurred
    copy of whichever pane is on its own. total is in frames."""
    fps, along = cfg["fps"], top["along"]
    cfg[along] = top["full"]
    W, H = cfg["width"], cfg["height"]
    visible, pieces, rate = top_plan(top, keys, total, fps)
    shown = sum(visible)

    # 1. The top clip as it plays while on screen: its pieces, one after
    #    another, framed to its pane (and held on its last frame if short).
    seq = workdir / "top_seq.mkv"
    tcfg = {**cfg, "width": top["width"], "height": top["height"]}
    cmd, graph = ["ffmpeg", "-nostdin", "-y", "-v", "error"], []
    for i, (s, l) in enumerate(pieces):
        cmd += ["-ss", f"{s:.3f}", "-t", f"{l:.3f}", "-i", str(top["path"])]
        graph.append(fit_filter(tcfg, f"{i}:v", f"f{i}", top["focus"], top["zoom"], "fill", pre=hdr_fix(top["path"]))
                     + f";[f{i}]setpts=(PTS-STARTPTS)/{rate:.6f},fps={fps},setsar=1,format=yuv420p[p{i}]")
    graph.append("".join(f"[p{i}]" for i in range(len(pieces)))
                 + f"concat=n={len(pieces)}:v=1:a=0,{grade(cfg, top['lighten'])}"
                 + f"tpad=stop_mode=clone:stop_duration={total / fps + 1:.3f},"
                 + f"trim=end_frame={max(shown, 1)},setpts=PTS-STARTPTS[v]")
    run(cmd + ["-filter_complex", ";".join(graph), "-map", "[v]", *video_codec(cfg), "-r", str(fps), str(seq)])

    # 2. ... on the piece's clock: playing while on screen, paused while not.
    runs, f = [], 0
    while f < total:
        g = f
        while g < total and visible[g] == visible[f]:
            g += 1
        runs.append((visible[f], g - f))
        f = g
    shows = [n for on, n in runs if on] or [1]
    graph = [f"[0:v]setpts=N/({fps}*TB),split={len(shows)}" + "".join(f"[s{i}]" for i in range(len(shows)))]
    at, chunks, k = 0, [], -1
    for j, (on, n) in enumerate(runs):
        if on:
            k += 1
            pre = (f"tpad=start_mode=clone:start_duration={runs[0][1] / fps:.4f},"
                   if k == 0 and j == 1 else "")
            post = (f",tpad=stop_mode=clone:stop_duration={runs[j + 1][1] / fps:.4f}"
                    if j + 1 < len(runs) else "")
            graph.append(f"[s{k}]trim=start_frame={at}:end_frame={at + n},setpts=PTS-STARTPTS,"
                         f"{pre}setpts=PTS-STARTPTS{post}[c{k}]")
            chunks.append(f"[c{k}]")
            at += n
    if not chunks:   # never on screen
        graph.append(f"[s0]trim=end_frame=1,tpad=stop_mode=clone:stop_duration={total / fps:.4f}[c0]")
        chunks = ["[c0]"]
    graph.append("".join(chunks) + f"concat=n={len(chunks)}:v=1:a=0,trim=end_frame={total},"
                 "setpts=PTS-STARTPTS,split[A][Ab]")

    # 3. Where everything sits. x: -1 top alone, 0 split, 1 cuts alone.
    X = f"({layout_expr(keys, fps)})"
    L, a, b, d = top["full"], top["size"], top["under"], top["divider"]
    pos_a = f"if(lt({X},0),{(L - a) / 2}*(-{X}),-{a + d}*{X})"
    pos_b = f"if(lt({X},0),{L - b}+{d + b}*(-{X}),{a + d}+{(L - b) / 2 - (a + d)}*{X})"
    pos_d = f"if(lt({X},0),{L - b - d}+{d + b}*(-{X}),{a}-{a + d}*{X})"
    seconds = total / fps

    def at_xy(pos):
        return f"x='{pos}':y=0" if top["axis"] == "x" else f"x=0:y='{pos}'"

    blur = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"boxblur=30:5,eq=brightness=-0.06")
    graph += [f"[1:v]setpts=N/({fps}*TB),setsar=1,format=yuv420p,tpad=stop_mode=clone:stop_duration={seconds:.4f},"
              f"trim=end_frame={total},setpts=PTS-STARTPTS,split[B][Bb]",
              f"[Ab]{blur}[bgA]", f"[Bb]{blur}[bgB]",
              f"color=c=black:s={W}x{H}:r={fps}:d={seconds:.4f},format=yuv420p[base]",
              f"[base][bgA]overlay=enable='lt({X},-0.001)'[l1]",
              f"[l1][bgB]overlay=enable='gt({X},0.001)'[l2]",
              f"[l2][A]overlay={at_xy(pos_a)}[l3]",
              f"[l3][B]overlay={at_xy(pos_b)}[l4]"]
    last = "[l4]"
    if d:
        size = f"{d}x{H}" if top["axis"] == "x" else f"{W}x{d}"
        graph += [f"color=c={top['color']}:s={size}:r={fps}:d={seconds:.4f},format=yuv420p[div]",
                  f"[l4][div]overlay={at_xy(pos_d)}[l5]"]
        last = "[l5]"
    graph += [f"{last}format=yuv420p,trim=end_frame={total}[v]",
              f"[1:a]apad,atrim=0:{seconds:.4f},asetpts=PTS-STARTPTS[a]"]
    out = workdir / "stacked.mkv"
    run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(seq), "-i", str(assembled),
         "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]",
         *video_codec(cfg), "-r", str(fps), "-c:a", "pcm_s16le", str(out)])
    return out


# ---------------------------------------------------------------- scenes

# A reel in scenes: two lanes of footage (A, a long clip or a few; B, the
# cuts) and a list of scenes saying what's on screen, one after another:
#   soloA   A fills the frame (B waits)
#   stack   A in the primary slot (top, or left in a wide frame), B in the other
#   soloB   B fills the frame (A waits)
#   swap    B in the primary slot, A in the other
# Each source carries the scene it plays in (`scene:`); a soloA scene is a
# `gap:` source. A scene with A on screen plays a stretch of an A clip:
#   a: {item, file, start, end (the part of the clip it can use), in, out
#       (null: carry on from the scene before / share what's left),
#       timing: fit | quiet | hold, speed, focus, zoom, lighten, activity}
# split is the primary slot's share, or "square" (the other slot square);
# into is how the scene comes in: cut | slide | push | dissolve; fill is how
# a lane on its own fills the frame (fill | blur).

SCENE_IN = 0.8       # seconds a scene's transition in takes
HANDOFF_MOVE = 1.0   # hand off: the solo frame moving into A's slot as B comes in
HANDOFF_FADE = 0.6   # ... and, its overlap over, dissolving into A


def handoff(scenes, k, secs):
    """Seconds scene k is handed off from the Solo B scene before it: that
    scene's last frame moves into A's slot while B comes in, stays there for
    this long, then dissolves into A (which starts then). 0: no hand off."""
    sc = scenes[k]
    if (k == 0 or sc.get("into") != "handoff" or scenes[k - 1].get("layout") != "soloB"
            or sc.get("layout") not in ("stack", "swap")):
        return 0.0
    if sc.get("relay"):
        return 0.0   # a relay carries the shot on instead of handing off to A
    return max(0.0, min(float(sc.get("handoff", 3) or 0), secs[k] - 0.5))


def moves_in(scenes, k):
    """Scene k comes in with a move rather than over a still frame: hand off
    (after Solo B, the shot moves into A's slot as B comes in) or take over
    (into Solo B after a split, B grows to the full frame as A slides out)."""
    if k == 0:
        return None
    sc, prev = scenes[k], scenes[k - 1]
    if sc.get("into") == "handoff" and prev.get("layout") == "soloB" and sc.get("layout") in ("stack", "swap"):
        return "handoff"
    if sc.get("into") == "takeover" and sc.get("layout") == "soloB" and prev.get("layout") in ("stack", "swap"):
        return "takeover"
    return None


LAYOUTS = ("soloA", "stack", "soloB", "swap")


def scene_slots(scene, w, h, divider):
    """Where each lane sits: {lane: (width, height, x, y)}, and the divider's
    rect (or None)."""
    layout = scene.get("layout", "stack")
    if layout == "soloA":
        return {"A": (w, h, 0, 0)}, None
    if layout == "soloB":
        return {"B": (w, h, 0, 0)}, None
    axis = "x" if w > h else "y"
    full, cross = (w, h) if axis == "x" else (h, w)
    d = min(max(int(divider) // 2 * 2, 0), 40)
    split = scene.get("split", 0.5)
    if split == "square" and full - d - cross >= full * 0.25:
        second = cross
        first = full - d - second
    else:
        split = 0.5 if split == "square" else min(max(float(split), 0.2), 0.8)
        first = round((full - d) * split / 2) * 2
        second = full - d - first
    lanes = ("A", "B") if layout == "stack" else ("B", "A")
    if axis == "y":
        slots = {lanes[0]: (w, first, 0, 0), lanes[1]: (w, second, 0, first + d)}
        div = (w, d, 0, first) if d else None
    else:
        slots = {lanes[0]: (first, h, 0, 0), lanes[1]: (second, h, first + d, 0)}
        div = (d, h, first, 0) if d else None
    return slots, div


def a_timing(scene):
    """How A plays in a scene: real (1x, the default), quiet (1x, skipping
    lulls), hold (the speed you picked), or fit (sped up or slowed down to
    fit its range: only when asked for). Solo A plays at its own speed."""
    t = (scene.get("a") or {}).get("timing") or "real"
    if scene.get("layout") == "soloA":
        return "hold"
    return {"range": "real"}.get(t, t) if t in ("real", "range", "quiet", "hold", "fit") else "real"


def quiet_fill(points, ain, end, seconds):
    """`seconds` of the clip from ain at real speed, skipping its lulls:
    pieces [(start, length)]. Shorter than asked when the clip runs out."""
    pieces = quiet_cut(points, ain, end - ain) if end - ain > seconds else [(ain, end - ain)]
    out, got = [], 0.0
    for s, l in pieces:
        take = min(l, seconds - got)
        if take <= 0.04:
            break
        out.append((round(s, 3), round(take, 3)))
        got += take
    return out or [(ain, min(seconds, max(end - ain, 0.2)))]


def resolve_a(scenes, secs):
    """Each scene's stretch of its A clip: (in, out) in the clip. A scene
    that doesn't say where A starts carries on where the last scene on that
    clip stopped. At real speed (and skipping lulls) a scene takes as much
    of the clip as it lasts, up to the clip's end (`duration`); at its own
    speed, that times the speed. Only `fit` scenes squeeze A's range into
    the scene, sharing what's left of the range by their lengths. As
    scenes.js resolveA."""
    out = [None] * len(scenes)
    cursor = {}
    shows = [i for i, sc in enumerate(scenes) if sc.get("layout") != "soloB" and sc.get("a") and not sc.get("relay")]
    for n, i in enumerate(shows):
        a = scenes[i]["a"]
        timing = a_timing(scenes[i])
        item, start = a.get("item"), float(a["start"])
        end = float(a["end"]) if timing == "fit" else float(a.get("duration") or a["end"])
        speed = float(a.get("speed") or 1)
        ain = a.get("in")
        ain = min(max(float(ain) if ain is not None else cursor.get(item, start), start), end - 0.2)
        if timing == "quiet":
            pieces = quiet_fill([(float(t), float(v)) for t, v in a.get("activity") or []], ain, end, secs[i])
            aout = pieces[-1][0] + pieces[-1][1]
        elif timing != "fit":
            aout = min(end, ain + secs[i] * (speed if timing == "hold" else 1.0))
        elif a.get("out") is not None:
            aout = min(max(float(a["out"]), ain + 0.2), end)
        else:
            stop, need, share = end, 0.0, secs[i]
            for j in shows[n + 1:]:
                b = scenes[j]["a"]
                if b.get("item") != item:
                    continue
                if b.get("in") is not None:
                    stop = min(stop, float(b["in"]))
                    break
                if a_timing(scenes[j]) == "fit":
                    if b.get("out") is not None:
                        stop = min(stop, float(b["out"]))   # (it starts where we stop)
                        break
                    share += secs[j]
                else:
                    need += secs[j] * (float(b.get("speed") or 1) if a_timing(scenes[j]) == "hold" else 1.0)
            room = max(stop - ain - need, 0.2)
            aout = min(end, ain + room * secs[i] / max(share, 1e-6))
        cursor[item] = aout
        out[i] = (round(ain, 3), round(max(aout, ain + 0.2), 3))
    return out


def scene_a_plan(a, ain, aout, seconds, scene=None):
    """The pieces of the A clip a scene plays, and how fast. Only `fit` and
    a picked speed change it; it holds its last frame if it runs out."""
    timing = a_timing(scene or {"a": a, "layout": "soloA" if a.get("_solo") else "stack"})
    length = aout - ain
    if timing == "hold":
        return [(ain, length)], float(a.get("speed") or 1)
    if timing == "quiet":
        end = float(a.get("duration") or a["end"])
        return quiet_fill([(float(t), float(v)) for t, v in a.get("activity") or []], ain, end, seconds), 1.0
    if timing == "fit":
        return [(ain, length)], length / seconds
    return [(ain, length)], 1.0


def render_scene_a(a, path, pieces, rate, size, frames, cfg, keep_audio, workdir, k):
    """A's stretch for scene k, framed to its slot and timed to the scene
    (held on its last frame if it runs out), with its sound when asked for
    and it plays at normal speed."""
    fps = cfg["fps"]
    w, h = size
    out = workdir / f"scene{k:02d}_a.mkv"
    tcfg = {**cfg, "width": w, "height": h}
    _, has_audio = probe(path)
    sound = keep_audio and has_audio and abs(rate - 1) < 0.01
    cmd, graph = ["ffmpeg", "-nostdin", "-y", "-v", "error"], []
    for i, (s, l) in enumerate(pieces):
        cmd += ["-ss", f"{s:.3f}", "-t", f"{l:.3f}", "-i", str(path)]
        graph.append(fit_filter(tcfg, f"{i}:v", f"f{i}", a.get("focus", (0.5, 0.5)), a.get("zoom", 1), a.get("fit"), pre=hdr_fix(path))
                     + f";[f{i}]setpts=(PTS-STARTPTS)/{rate:.6f},fps={fps},setsar=1,format=yuv420p[p{i}]")
        if sound:
            graph.append(f"[{i}:a:0]aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[q{i}]")
    n = len(pieces)
    joined = "".join(f"[p{i}]" + (f"[q{i}]" if sound else "") for i in range(n))
    graph.append(f"{joined}concat=n={n}:v=1:a={1 if sound else 0}[vc]" + ("[ac]" if sound else ""))
    graph.append(f"[vc]{grade(cfg, a.get('lighten', 0))}tpad=stop_mode=clone:stop_duration={frames / fps + 1:.3f},"
                 f"trim=end_frame={frames},setpts=PTS-STARTPTS[v]")
    if not sound:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        graph.append(f"[{n}:a]atrim=0:{frames / fps:.4f}[a]")
    else:
        graph.append(f"[ac]apad,atrim=0:{frames / fps:.4f},asetpts=PTS-STARTPTS[a]")
    run(cmd + ["-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]",
               *video_codec(cfg), "-r", str(fps), "-c:a", "pcm_s16le", str(out)])
    return out


def compose_scene(scene, slots, div, files, frames, tail, cfg, workdir, k):
    """One scene's frame: each lane in its slot (and the divider), held on
    its last frame for `tail` more frames so the next scene can come in over
    it. The sound is the primary lane's (A in soloA and stack, B otherwise),
    lane A's in `glasses_audio: A`, or none."""
    fps, w, h = cfg["fps"], cfg["width"], cfg["height"]
    color = str((cfg.get("stack") or {}).get("divider_color", "#f7f1e3")).replace("#", "0x")
    lanes = [lane for lane in ("A", "B") if lane in slots]
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error"]
    graph = [f"color=c=black:s={w}x{h}:r={fps},format=yuv420p,trim=end_frame={frames + tail}[base]"]
    cur = "[base]"
    for i, lane in enumerate(lanes):
        file, crop = files[lane] if isinstance(files[lane], tuple) else (files[lane], None)
        cmd += ["-i", str(file)]
        sw, sh, x, y = slots[lane]
        fit = f"crop={sw}:{sh}:{crop[0]}:{crop[1]}" if crop else f"scale={sw}:{sh}"
        # Frame times from the file are whole milliseconds, which overlay reads as
        # landing a hair after the frame's 1/fps step: renumber them exactly, or
        # every third frame repeats the one before.
        graph.append(f"[{i}:v]setpts=N/({fps}*TB),{fit},setsar=1,format=yuv420p,"
                     f"tpad=stop_mode=clone:stop_duration={(frames + tail) / fps + 1:.3f},"
                     f"trim=end_frame={frames + tail},setpts=PTS-STARTPTS[l{i}]")
        graph.append(f"{cur}[l{i}]overlay=x={x}:y={y}:eof_action=repeat[c{i}]")
        cur = f"[c{i}]"
    if div:
        dw, dh, x, y = div
        graph.append(f"color=c={color}:s={dw}x{dh}:r={fps},format=yuv420p,trim=end_frame={frames + tail}[div]")
        graph.append(f"{cur}[div]overlay=x={x}:y={y}[cd]")
        cur = "[cd]"
    sound = scene_sound(scene, lanes, glasses_mode(cfg))
    graph.append(f"{cur}format=yuv420p,trim=end_frame={frames + tail},setpts=PTS-STARTPTS[v]")
    if sound:
        level = mix_level(cfg, sound)   # that lane's fader
        graph.append(f"[{lanes.index(sound)}:a]volume={level:.3f},apad,atrim=0:{frames / fps:.4f},asetpts=PTS-STARTPTS[a]")
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        graph.append(f"[{len(lanes)}:a]atrim=0:{frames / fps:.4f},asetpts=PTS-STARTPTS[a]")
    out = workdir / f"scene{k:02d}.mkv"
    run(cmd + ["-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]",
               *video_codec(cfg), "-r", str(fps), "-c:a", "pcm_s16le", str(out)])
    return out


def join_scenes(files, scenes, frames, tails, cfg, workdir, slots=None, hand_f=None, switches=None, morphs=None):
    """The scenes one after another. A scene comes in over the last frame of
    the one before: cut, slide (it slides in from the bottom, or the right
    in a wide frame), push (it pushes the last one out) or dissolve."""
    fps, w, h = cfg["fps"], cfg["width"], cfg["height"]
    axis = "x" if w > h else "y"
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error"]
    for f in files:
        cmd += ["-i", str(f)]
    n = len(files)
    morph_in = {}
    for k, f in (morphs or {}).items():
        if f:
            morph_in[k] = len(files) + len(morph_in)
            cmd += ["-i", str(f)]
    graph, pieces, labels = [], [], {}
    for k in range(n):   # each scene is used for its body, its head and the tail the next comes in over
        uses = ["body"] + (["head"] if k > 0 and tails[k - 1] else []) + (["tail"] if k + 1 < n and tails[k] else [])
        labels[k] = {u: f"[s{k}{u}]" for u in uses}
        exact = f"[{k}:v]setpts=N/({fps}*TB),"   # exact frame times (see compose_scene)
        graph.append(f"{exact}split={len(uses)}" + "".join(labels[k].values()) if len(uses) > 1
                     else f"{exact}null{labels[k]['body']}")
    for k in range(n):
        head = tails[k - 1] if k > 0 else 0
        if head:
            d = head / fps
            graph.append(f"{labels[k - 1]['tail']}trim=start_frame={frames[k - 1]}:end_frame={frames[k - 1] + head},"
                         f"setpts=PTS-STARTPTS[pt{k}]")
            graph.append(f"{labels[k]['head']}trim=end_frame={head},setpts=PTS-STARTPTS[nh{k}]")
            ease = f"(0.5-0.5*cos(PI*t/{d:.4f}))"
            into = scenes[k].get("into", "cut")
            if k in morph_in:   # A moving between full frame and its slot, drawn frame by frame
                into = "morph"
                graph.append(f"[pt{k}]nullsink;[nh{k}]nullsink")
                graph.append(f"[{morph_in[k]}:v]setsar=1,format=yuv420p,trim=end_frame={head},setpts=PTS-STARTPTS[tr{k}]")
            if into in ("handoff", "takeover") and moves_in(scenes, k) != into:
                into = "slide"
            if into == "morph":
                pass
            elif into == "takeover":
                # B grows from its slot to the full frame (the next scene is its
                # shot alone, full frame) while A and the divider slide out.
                aw, ah, ax, ay = slots[k - 1]["A"]
                bw, bh, bx, by = slots[k - 1]["B"]
                ox, oy = band_offset(slots[k - 1]["B"], w, h, scenes[k - 1].get("band_b"))
                if axis == "x":
                    a0, a1 = min(ax, bx + bw), max(ax + aw, bx)      # A and the divider beside it
                    block = (a1 - a0, h, a0, 0)
                    away = -block[0] - a0 if a0 == 0 else w - a0
                    new_move = f"x='({bx - ox})*(1-{ease})':y=0"
                    old_move = f"x='{a0}+({away})*{ease}':y=0"
                else:
                    a0, a1 = min(ay, by + bh), max(ay + ah, by)
                    block = (w, a1 - a0, 0, a0)
                    away = -block[1] - a0 if a0 == 0 else h - a0
                    new_move = f"x=0:y='({by - oy})*(1-{ease})'"
                    old_move = f"x=0:y='{a0}+({away})*{ease}'"
                graph.append(f"color=c=black:s={w}x{h}:r={fps},format=yuv420p,trim=end_frame={head}[cv{k}]")
                graph.append(f"[cv{k}][nh{k}]overlay={new_move}[pm{k}]")
                graph.append(f"[pt{k}]crop={block[0]}:{block[1]}:{block[2]}:{block[3]}[ab{k}]")
                graph.append(f"[pm{k}][ab{k}]overlay={old_move}[tr{k}]")
            elif into == "handoff":
                # The solo frame moves so its band (the bottom, unless framed) lands on A's slot,
                # while B (and the divider) come in from their side.
                aw, ah, ax, ay = slots[k]["A"]
                ox, oy = band_offset(slots[k]["A"], w, h, scenes[k].get("band_a"))
                bw, bh, bx, by = slots[k]["B"]
                if axis == "x":
                    bx0, bx1 = min(bx, ax + aw), max(bx + bw, ax)   # B and the divider beside it
                    block = (bx1 - bx0, h, bx0, 0)
                    start = w if bx0 > 0 else -block[0]
                    old_move = f"x='{ax - ox}*{ease}':y=0"
                    new_move = f"x='{start}+({bx0}-({start}))*{ease}':y=0"
                else:
                    by0, by1 = min(by, ay + ah), max(by + bh, ay)
                    block = (w, by1 - by0, 0, by0)
                    start = h if by0 > 0 else -block[1]
                    old_move = f"x=0:y='{ay - oy}*{ease}'"
                    new_move = f"x=0:y='{start}+({by0}-({start}))*{ease}'"
                graph.append(f"color=c=black:s={w}x{h}:r={fps},format=yuv420p,trim=end_frame={head}[cv{k}]")
                graph.append(f"[cv{k}][pt{k}]overlay={old_move}[pm{k}]")
                graph.append(f"[nh{k}]crop={block[0]}:{block[1]}:{block[2]}:{block[3]}[nb{k}]")
                graph.append(f"[pm{k}][nb{k}]overlay={new_move}[tr{k}]")
            elif into == "dissolve":
                graph.append(f"[pt{k}][nh{k}]xfade=transition=fade:duration={d:.4f}:offset=0[tr{k}]")
            elif into == "push":
                move = (f"x='-{w}*{ease}':y=0", f"x='{w}*(1-{ease})':y=0") if axis == "x" else \
                       (f"x=0:y='-{h}*{ease}'", f"x=0:y='{h}*(1-{ease})'")
                graph.append(f"color=c=black:s={w}x{h}:r={fps},format=yuv420p,trim=end_frame={head}[cv{k}]")
                graph.append(f"[cv{k}][pt{k}]overlay={move[0]}[pp{k}]")
                graph.append(f"[pp{k}][nh{k}]overlay={move[1]}[tr{k}]")
            else:   # slide
                move = f"x='{w}*(1-{ease})':y=0" if axis == "x" else f"x=0:y='{h}*(1-{ease})'"
                graph.append(f"[pt{k}][nh{k}]overlay={move}[tr{k}]")
            pieces.append(f"[tr{k}]")
        graph.append(f"{labels[k]['body']}trim=start_frame={head}:end_frame={frames[k]},setpts=PTS-STARTPTS[b{k}]")
        pieces.append(f"[b{k}]")
    graph.append("".join(pieces) + f"concat=n={len(pieces)}:v=1:a=0,format=yuv420p[v]")
    # The sound, scene after scene: where it switches source, the one going
    # fades over its last SWITCH_FADE and the one coming over its first.
    switches = switches or [False] * n
    for k in range(n):
        fades = []
        if switches[k]:
            fades.append(f"afade=t=in:d={SWITCH_FADE}:curve=qsin")
        if k + 1 < n and switches[k + 1]:
            fades.append(f"afade=t=out:st={max(frames[k] / fps - SWITCH_FADE, 0):.4f}:d={SWITCH_FADE}:curve=qsin")
        graph.append(f"[{k}:a]{','.join(fades) or 'anull'}[sa{k}]")
    graph.append("".join(f"[sa{k}]" for k in range(n)) + f"concat=n={n}:v=0:a=1[a]")
    out = workdir / "scenes.mkv"
    run(cmd + ["-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]",
               *video_codec(cfg), "-r", str(fps), "-c:a", "pcm_s16le", str(out)])
    return out


def scene_frames(plan, n_scenes, fps):
    """Each scene's length in frames, from the plan's cuts."""
    frames = [0] * n_scenes
    for seg in plan:
        frames[seg.get("scene") or 0] += round(seg["length"] * fps)
    return frames


def scene_report(cfg, plan, base_dir):
    """What each scene shows, for the dry run; and the resolved A stretches."""
    scenes, fps = cfg["scenes"], cfg["fps"]
    frames = scene_frames(plan, len(scenes), fps)
    secs = [f / fps for f in frames]
    hands = [handoff(scenes, k, secs) for k in range(len(scenes))]
    a_secs = [secs[k] - hands[k] for k in range(len(scenes))]
    ranges = resolve_a(scenes, a_secs)
    names = {"soloA": "Solo A", "stack": "A over B", "soloB": "Solo B", "swap": "B over A"}
    if cfg["width"] > cfg["height"]:
        names.update(stack="A | B", swap="B | A")
    lines, t = [], 0.0
    for k, sc in enumerate(scenes):
        line = f"  {fmt(t):>7}  scene {k + 1}  {names.get(sc.get('layout'), sc.get('layout')):<9} {secs[k]:.2f}s"
        if sc.get("relay") and sc.get("carry") and moves_in(scenes, k) == "handoff":
            line += f"  (relay: {Path(sc['carry']['file']).name} carries on in A's slot)"
        elif moves_in(scenes, k) == "takeover":
            line += "  (take over: B grows to the full frame)"
        elif hands[k]:
            line += f"  (hand off: the last frame in A's slot {hands[k]:.1f}s)"
        elif k and sc.get("into", "cut") != "cut":
            line += f"  (in: {sc['into']})"
        if ranges[k]:
            a = sc["a"]
            pieces, rate = scene_a_plan(a, *ranges[k], max(a_secs[k], 0.04), sc)
            line += f"  · A {Path(a['file']).name} {fmt(ranges[k][0])} -> {fmt(ranges[k][1])} at {rate:.2f}x"
            if len(pieces) > 1:
                line += f", {len(pieces)} pieces"
            short = a_secs[k] - sum(l for _, l in pieces) / rate
            if short > 0.05:
                line += f", runs out: holds its last frame {short:.1f}s"
            if rate > 4.001:
                line += "  ! over 4x"
        lines.append(line)
        t += secs[k]
    return lines, ranges, frames, hands


def render_scenes(plan, segs_of, cfg, base_dir, keep_audio, workdir):
    """Every scene rendered and joined: returns the picture and sound for
    the whole piece. segs_of(k, w, h, fill) renders scene k's cuts at that
    size and returns the assembled file (None when B isn't on screen)."""
    scenes, fps = cfg["scenes"], cfg["fps"]
    w, h = cfg["width"], cfg["height"]
    divider = int((cfg.get("stack") or {}).get("divider", 4))
    _, ranges, frames, hands = scene_report(cfg, plan, base_dir)
    hand_f = [round(x * fps) for x in hands]
    tails = [min(round((HANDOFF_MOVE if moves_in(scenes, k + 1) else SCENE_IN) * fps), frames[k], frames[k + 1])
             if k + 1 < len(scenes) and scenes[k + 1].get("into", "cut") != "cut" else 0 for k in range(len(scenes))]
    files, all_slots, sources = [], [], []
    a_play = {}   # scene -> (path, a, first source second, rate): for A moving between scenes
    mode = glasses_mode(cfg)
    for k, sc in enumerate(scenes):
        print(f"  scene {k + 1}/{len(scenes)}...                     ", end="\r")
        slots, div = scene_slots(sc, w, h, divider)
        solo_fill = sc.get("fill") or ("blur" if w > h else "fill")
        lane_files = {}
        relay = bool(sc.get("relay") and sc.get("carry") and moves_in(scenes, k) == "handoff")
        if relay:
            print(f"  scene {k + 1}/{len(scenes)}: relay, {Path(sc['carry']['file']).name} carrying on...", end="\r")
            # A relay: the shot before carries on in A's slot and B plays in its own,
            # each as a band of its full frame (the bottom, unless framed), so they
            # move in and out seamlessly.
            lane_files["B"] = (segs_of(k, w, h, solo_fill, tails[k]), band_offset(slots["B"], w, h, sc.get("band_b")))
            lane_files["A"] = (render_carry(sc["carry"], frames[k] + tails[k], cfg, base_dir, keep_audio, workdir, k, solo_fill),
                               band_offset(slots["A"], w, h, sc.get("band_a")))
        elif "B" in slots:
            bw, bh = slots["B"][:2]
            lane_files["B"] = segs_of(k, bw, bh, solo_fill if sc.get("layout") == "soloB" else None, tails[k])
        if "A" in slots and not relay:
            a = {**sc["a"]}
            if sc.get("layout") == "soloA":
                a["_solo"] = True
                a.setdefault("fit", solo_fill)
            ain, aout = ranges[k]
            a_frames = frames[k] - hand_f[k]
            print(f"  scene {k + 1}/{len(scenes)}: lane A, {Path(a['file']).name} {fmt(ain)} -> {fmt(aout)}...", end="\r")
            pieces, rate = scene_a_plan(a, ain, aout, max(a_frames / fps, 0.04), sc)
            path = (base_dir / a["file"]).expanduser()
            # A carries on past the scene too, while the next comes in.
            more = pieces[:-1] + [(pieces[-1][0], pieces[-1][1] + tails[k] / fps * rate)]
            lane_files["A"] = render_scene_a(a, path, more, rate, slots["A"][:2], a_frames + tails[k], cfg,
                                             keep_audio, workdir, k)
            a_play[k] = (path, a, pieces[0][0], rate, solo_fill if sc.get("layout") == "soloA" else "fill")
            if hand_f[k]:
                lane_files["A"] = hand_off_a(files[k - 1], slots["A"], lane_files["A"], hand_f[k], frames[k] + tails[k],
                                             cfg, workdir, k, sc.get("band_a"))
        all_slots.append(slots)
        print(f"  scene {k + 1}/{len(scenes)}: putting the lanes in their slots...", end="\r")
        files.append(compose_scene(sc, slots, div, lane_files, frames[k], tails[k], cfg, workdir, k))
        # Where its sound comes from: lane A's clip from where to where (and how fast), or the B parts.
        lane = scene_sound(sc, [x for x in ("A", "B") if x in slots], mode)
        if lane == "A" and relay:
            sources.append(("carry",))   # the Solo B shot before, carrying on in A's slot
        elif lane == "A":
            sources.append(("A", sc["a"]["file"], ranges[k][0], ranges[k][1], round(rate, 3), hand_f[k]))
        else:
            sources.append((lane,))
    if len(files) == 1:
        return files[0]
    # A short switch where the sound comes from somewhere else; none where
    # the same A clip carries straight on at real speed, or a relay carries
    # on the shot the Solo B before it was playing.
    def carries_on(k):
        now, before = sources[k], sources[k - 1]
        if now[0] == "carry":
            return before[0] == "B"
        return (now[0] == "A" and before[0] == "A" and now[1] == before[1] and not now[5]
                and abs(now[2] - before[3]) < 0.05)
    switches = [k > 0 and not carries_on(k) for k in range(len(files))]
    # Into and out of Solo A with a slide, A doesn't leave: it shrinks from the
    # full frame into its slot (or grows back), playing on, as B comes or goes.
    morphs = {}
    for k in range(1, len(files)):
        if (tails[k - 1] and scenes[k].get("into") == "slide" and k in a_play and k - 1 in a_play
                and "soloA" in (scenes[k - 1].get("layout"), scenes[k].get("layout"))
                and scenes[k - 1].get("layout") != scenes[k].get("layout")
                and a_play[k][0] == a_play[k - 1][0] and not hand_f[k]):
            print(f"  moving A into scene {k + 1}...            ", end="\r")
            morphs[k] = morph_a(k, files, all_slots, a_play, frames, tails[k - 1], cfg, workdir)
    print(f"  joining {len(files)} scenes and their transitions...          ", end="\r")
    return join_scenes(files, scenes, frames, tails, cfg, workdir, all_slots, hand_f, switches, morphs)


def cover_window(sw, sh, tw, th, focus=(0.5, 0.5), zoom=1.0):
    """The part of a sw x sh picture that fills a tw x th box (as fit_filter's
    fill): (x, y, width, height) in the picture."""
    fx, fy = (min(max(float(v), 0.0), 1.0) for v in focus)
    sc = max(tw / sw, th / sh) * min(max(float(zoom or 1), 1.0), 3.0)
    ww, wh = tw / sc, th / sc
    return ((sw - ww) * fx, (sh - wh) * fy, ww, wh)


def morph_a(k, files, slots, a_play, frames, n, cfg, workdir):
    """The frames of A moving between the full frame (Solo A) and its slot
    (scene k or k-1 split), drawn one by one so it keeps playing and its
    picture eases from one framing to the other: Solo A -> split, A shrinks
    into its slot while B comes in from its side; split -> Solo A, A grows
    while B goes out. Returns the clip of n frames that opens scene k."""
    from PIL import Image, ImageFilter
    import math
    fps, w, h = cfg["fps"], cfg["width"], cfg["height"]
    shrink = "B" not in slots[k - 1]          # Solo A before: A shrinks
    path, a, t0, rate, _ = a_play[k]
    tmp = workdir / f"morph{k:02d}"
    tmp.mkdir(exist_ok=True)
    # A as it plays through the move (the scene coming in sets where it is).
    run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-ss", f"{t0:.3f}", "-i", str(path),
         "-vf", f"{hdr_fix(path)}setpts=(PTS-STARTPTS)/{rate:.6f},fps={fps},{grade(cfg, a.get('lighten', 0))}null",
         "-frames:v", str(n), str(tmp / "a%03d.png")])
    # B's frames: the scene coming in (B arriving) or the last frame of the one going.
    if shrink:
        run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(files[k]), "-frames:v", str(n), str(tmp / "s%03d.png")])
        split_slots, solo = slots[k], a_play[k - 1]
    else:
        run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(files[k - 1]),
             "-vf", f"select='gte(n,{frames[k - 1]})'", "-vsync", "0", "-frames:v", str(n), str(tmp / "s%03d.png")])
        split_slots, solo = slots[k - 1], a_play[k]
    split_a = (a_play[k] if shrink else a_play[k - 1])[1]
    aw, ah, ax, ay = split_slots["A"]
    bw, bh, bx, by = split_slots["B"]
    axis = "x" if w > h else "y"
    if axis == "y":
        b0, b1 = min(by, ay + ah), max(by + bh, ay)
        block = (0, b0, w, b1)
        off = (0, h - b0) if b0 > 0 else (0, -b1)          # where B goes to be out of frame
    else:
        b0, b1 = min(bx, ax + aw), max(bx + bw, ax)
        block = (b0, 0, b1, h)
        off = (w - b0, 0) if b0 > 0 else (-b1, 0)
    frames_a = sorted(tmp.glob("a*.png"))
    if not frames_a:
        return None
    sw, sh = Image.open(frames_a[0]).size
    # The two framings of A: full (fill, or the whole picture over a blur) and its slot.
    full_fit = solo[4]
    if full_fit == "blur":
        sc_ = min(w / sw, h / sh)
        full_dest = ((w - sw * sc_) / 2, (h - sh * sc_) / 2, sw * sc_, sh * sc_)
        full_win = (0, 0, sw, sh)
    else:
        full_dest = (0, 0, w, h)
        full_win = cover_window(sw, sh, w, h, solo[1].get("focus", (0.5, 0.5)), solo[1].get("zoom", 1))
    slot_dest = (ax, ay, aw, ah)
    slot_win = cover_window(sw, sh, aw, ah, split_a.get("focus", (0.5, 0.5)), split_a.get("zoom", 1))
    lerp = lambda p, q, e: tuple(x + (y - x) * e for x, y in zip(p, q))   # noqa: E731
    for i in range(n):
        u = (i + 1) / n
        e = 0.5 - 0.5 * math.cos(math.pi * u)
        to_slot = e if shrink else 1 - e          # 0: A full, 1: A in its slot
        canvas = Image.new("RGB", (w, h), (0, 0, 0))
        img = Image.open(frames_a[min(i, len(frames_a) - 1)]).convert("RGB")
        if full_fit == "blur" and to_slot < 1:    # A alone's blurred backdrop stays behind it as it moves
            canvas = img.resize((w, h), Image.BILINEAR).filter(ImageFilter.GaussianBlur(30))
        dx, dy, dw, dh = lerp(full_dest, slot_dest, to_slot)
        wx, wy, ww, wh = lerp(full_win, slot_win, to_slot)
        piece = img.crop((round(wx), round(wy), round(wx + ww), round(wy + wh))).resize(
            (max(1, round(dw)), max(1, round(dh))), Image.BILINEAR)
        canvas.paste(piece, (round(dx), round(dy)))
        # B (and the divider) come in from their side, or go out.
        shots = sorted(tmp.glob("s*.png"))   # the B side, playing on
        src = Image.open(shots[min(i, len(shots) - 1)]).convert("RGB")
        part = src.crop(block)
        away = 1 - e if shrink else e
        canvas.paste(part, (round(block[0] + off[0] * away), round(block[1] + off[1] * away)))
        canvas.save(tmp / f"m{i + 1:03d}.png")
    out = workdir / f"morph{k:02d}.mkv"
    run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-framerate", str(fps), "-i", str(tmp / "m%03d.png"),
         "-frames:v", str(n), *video_codec(cfg), "-r", str(fps), str(out)])
    return out


def render_carry(carry, frames, cfg, base_dir, keep_audio, workdir, k, fill):
    """A relay's A lane: the shot from the scene before carrying on (a video
    from where its part ended, a photo held), full frame."""
    fps, w, h = cfg["fps"], cfg["width"], cfg["height"]
    path = (base_dir / carry["file"]).expanduser()
    out = workdir / f"scene{k:02d}_carry.mkv"
    image = carry.get("kind") == "photo" or path.suffix.lower() in IMAGE_EXTS
    cmd = ["ffmpeg", "-nostdin", "-y", "-v", "error"]
    cmd += ["-loop", "1", "-framerate", str(fps), "-i", str(path)] if image else \
           ["-ss", f"{float(carry.get('start', 0)):.3f}", "-i", str(path)]
    sound = keep_audio and not image and probe(path)[1]
    fcfg = {**cfg, "width": w, "height": h}
    graph = [fit_filter(fcfg, "0:v", "f", carry.get("focus", (0.5, 0.5)), carry.get("zoom", 1), carry.get("fit") or fill,
                        pre="" if image else hdr_fix(path))
             + f";[f]fps={fps},{grade(cfg, carry.get('lighten', 0))}setsar=1,format=yuv420p,"
             f"tpad=stop_mode=clone:stop_duration={frames / fps + 1:.3f},trim=end_frame={frames},setpts=PTS-STARTPTS[v]"]
    if sound:
        graph.append(f"[0:a:0]aformat=sample_rates=48000:channel_layouts=stereo,apad,atrim=0:{frames / fps:.4f},asetpts=PTS-STARTPTS[a]")
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        graph.append(f"[1:a]atrim=0:{frames / fps:.4f}[a]")
    run(cmd + ["-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]",
               *video_codec(cfg), "-r", str(fps), "-c:a", "pcm_s16le", str(out)])
    return out


BAND_DEFAULT = (0.5, 1.0)   # a full-frame shot moving into a half slot shows its bottom (hands are low in glasses footage)


def band_offset(slot, w, h, focus=None):
    """Which band of a full frame a slot shows when a full-frame shot moves
    into it (or grows out of it): a band of the slot's size, placed by focus
    (x, y: 0 = left/top, 1 = right/bottom; the bottom by default)."""
    sw, sh = slot[:2]
    fx, fy = (min(max(float(v), 0.0), 1.0) for v in (focus or BAND_DEFAULT))
    return (round((w - sw) * fx) // 2 * 2, 0) if w > h else (0, round((h - sh) * fy) // 2 * 2)


def hand_off_a(prev_file, slot, a_file, hold, frames, cfg, workdir, k, band=None):
    """Lane A for a scene handed off from a Solo B scene: the middle band of
    that scene's last frame fills A's slot for `hold` frames, then dissolves
    into A (whose sound starts with it)."""
    fps, w, h = cfg["fps"], cfg["width"], cfg["height"]
    sw, sh = slot[:2]
    ox, oy = band_offset(slot, w, h, band)
    last = workdir / f"scene{k:02d}_from.png"
    run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-sseof", "-0.2", "-i", str(prev_file),
         "-update", "1", "-vf", f"crop={sw}:{sh}:{ox}:{oy}", str(last)])
    fade = min(round(HANDOFF_FADE * fps), frames - hold)
    out = workdir / f"scene{k:02d}_a_handoff.mkv"
    graph = (f"[0:v]fps={fps},setsar=1,format=yuv420p,trim=end_frame={hold + fade},setpts=PTS-STARTPTS,settb=1/{fps}[h];"
             f"[1:v]fps={fps},setsar=1,format=yuv420p,setpts=PTS-STARTPTS,settb=1/{fps}[a];")
    graph += (f"[h][a]xfade=transition=fade:duration={fade / fps:.4f}:offset={hold / fps:.4f},"
              f"trim=end_frame={frames}[v];" if fade > 0 else f"[h][a]concat=n=2:v=1:a=0,trim=end_frame={frames}[v];")
    ms = round(hold / fps * 1000)
    graph += f"[1:a]adelay={ms}|{ms},apad,atrim=0:{frames / fps:.4f},asetpts=PTS-STARTPTS[aa]"
    run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-loop", "1", "-framerate", str(fps),
         "-t", f"{(hold + fade) / fps + 0.1:.3f}", "-i", str(last), "-i", str(a_file),
         "-filter_complex", graph, "-map", "[v]", "-map", "[aa]",
         *video_codec(cfg), "-r", str(fps), "-c:a", "pcm_s16le", str(out)])
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
        fader = [] if cfg.get("scenes") else ["-af", f"volume={mix_level(cfg, 'B'):.3f}"]   # scenes: done per lane
        audio = ["-map", "0:a", *fader] if keep_audio else ["-an"]
        run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(assembled),
             "-map", "0:v", *audio, *common])
        return

    inputs = ["-i", str(assembled)]
    graph, mix = [], []
    # The assembled audio sets the length; silent unless the clips' sound is kept.
    bed = (float(cfg.get("original_volume", 0.35)) if music else 1.0) if keep_audio else 0.0
    if not cfg.get("scenes"):
        bed *= mix_level(cfg, "B")   # without scenes, all the clips' sound is the cut list's (with scenes, per lane)
    graph.append(f"[0:a]volume={bed}[o]")
    mix.append("[o]")
    if music:
        inputs += ["-ss", f"{music_start:.3f}", "-i", str(music_path(cfg, base_dir))]
        fade = min(float(cfg.get("music_fade_out", 2.0)), total_len / 3)
        duck = bool(cfg.get("duck_music", True))
        if voice:
            base = song_level(voice) if duck else f"{voice['between']:.3f}"
        else:
            base = f"{float(cfg.get('music_volume', 1.0)):.3f}"
        runs = loud_runs(assembled, bed) if duck and bed > 0 else []
        if runs:
            print(f"  ducking the song under the glasses audio in {len(runs)} place{'s' if len(runs) != 1 else ''}"
                  "                ")
            base = f"({base})*({duck_level(runs)})"
        level = f"volume='({base})*{mix_level(cfg, 'music'):.3f}':eval=frame"
        graph.append(f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,{level},"
                     f"afade=t=out:st={max(total_len - fade, 0):.3f}:d={fade:.3f}[m]")
        mix.append("[m]")
    if voice:
        n0 = inputs.count("-i")
        parts = []
        for i, p in enumerate(voice["pieces"]):
            inputs += ["-ss", f"{p['start']:.3f}", "-t", f"{p['length']:.3f}", "-i", str(p["path"])]
            clean = "highpass=f=80,afftdn=nf=-25," if voice["clean"] else ""
            delay = round(p["at"] * 1000)
            chain = (f"[{n0 + i}:a:0]aformat=channel_layouts=mono,{clean}"
                     f"loudnorm=I=-16:TP=-1.5:LRA=11,"
                     f"aformat=sample_rates=48000:channel_layouts=stereo,"
                     f"afade=t=in:d={VOICE_EDGE},"
                     f"afade=t=out:st={max(p['length'] - VOICE_EDGE * 2, 0):.3f}:d={VOICE_EDGE * 2},"
                     f"volume={voice['volume'] * mix_level(cfg, 'voice'):.3f}")
            if not p["fx"]:
                graph.append(f"{chain},adelay=delays={delay}:all=1[v{i}]")
                parts.append(f"[v{i}]")
                continue
            # Phrases with an effect: the plain voice steps aside for them,
            # and each plays through its effect at the same moment.
            graph.append(f"{chain},asplit={len(p['fx']) + 1}[d{i}]" + "".join(f"[f{i}_{k}]" for k in range(len(p["fx"]))))
            gate = "*".join(f"(1-clip((t-{f['start'] - p['start']:.3f})/{FX_EDGE},0,1)"
                            f"*clip(({f['end'] - p['start']:.3f}-t)/{FX_EDGE},0,1))" for f in p["fx"])
            graph.append(f"[d{i}]volume='{gate}':eval=frame,adelay=delays={delay}:all=1[v{i}]")
            parts.append(f"[v{i}]")
            for k, f in enumerate(p["fx"]):
                r0, length = f["start"] - p["start"], f["end"] - f["start"]
                key = f"x{i}_{k}"
                graph.append(f"[f{i}_{k}]atrim=start={r0:.3f}:end={r0 + length:.3f},asetpts=PTS-STARTPTS,"
                             f"afade=t=in:d={FX_EDGE},afade=t=out:st={max(length - FX_EDGE, 0):.3f}:d={FX_EDGE},"
                             f"apad=pad_dur={f['tail']:.2f}[{key}in]")
                graph += fx_graph(f, f"{key}in", f"{key}fx", key)
                graph.append(f"[{key}fx]atrim=0:{length + f['tail']:.3f},"
                             f"adelay=delays={round((p['at'] + r0) * 1000)}:all=1[{key}]")
                parts.append(f"[{key}]")
        if len(parts) > 1:
            graph.append("".join(parts) + f"amix=inputs={len(parts)}:normalize=0:duration=longest[voice]")
        else:
            graph.append(f"{parts[0]}anull[voice]")
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
        piece = {"path": path, "start": start, "length": end - start, "at": parse_time(p.get("at", 0)), "fx": []}
        for f in sorted(p.get("fx") or [], key=lambda f: parse_time(f["start"])):
            if f.get("effect") not in VOICE_FX:
                continue
            fs, fe = max(parse_time(f["start"]), start), min(parse_time(f["end"]), end)
            if piece["fx"] and fs < piece["fx"][-1]["end"]:
                fs = piece["fx"][-1]["end"]    # never two effects on the same words
            if fe - fs < 0.1:
                continue
            amount = min(max(float(f.get("amount", 1) or 1), 0.3), 2.0)
            piece["fx"].append({"effect": f["effect"], "amount": amount, "start": fs, "end": fe,
                                "tail": fx_tail(f["effect"], amount)})
        pieces.append(piece)
    if not pieces:
        return None
    # The voice ends when its last piece does, or a little later if an echo
    # or hall is still ringing.
    end = max(max([p["at"] + p["length"]] + [p["at"] + f["end"] - p["start"] + f["tail"] for f in p["fx"]])
              for p in pieces)
    return {"pieces": pieces, "end": end,
            "fit": bool(v.get("fit", True)), "clean": bool(v.get("clean", True)),
            "volume": float(v.get("volume", 1.0)),
            "under": float(v.get("song_under", 0.15)), "between": float(v.get("song_between", 0.3))}


# Effects on a phrase of the voice, to lift it out: the words from `start` to
# `end` (in the take) are played through the effect in place of the plain
# voice; an echo or hall rings on after them. `amount` is 0.6 light, 1
# medium, 1.4 strong. Footage Studio's Play reel does a rough version of each
# (voicePlayer.js).
VOICE_FX = ("echo", "hall", "waver", "pulse", "doubled")
ECHO_GAP = 0.32      # seconds between the repeats
FX_EDGE = 0.025      # crossfade between the plain voice and the effect


def fx_tail(effect, amount):
    """How long an effect rings on after its words."""
    return {"echo": 3 * ECHO_GAP + 0.6, "hall": 1.6 + amount}.get(effect, 0.15)


def fx_graph(f, src, out, key):
    """Filter chains that run [src] (the phrase, padded with silence for the
    tail) through the effect into [out]."""
    a = f["amount"]
    if f["effect"] == "echo":    # the phrase repeats three times, fading
        gaps = "|".join(str(round(ECHO_GAP * 1000 * n)) for n in (1, 2, 3))
        decays = "|".join(f"{min(0.95, d * a):.2f}" for d in (0.5, 0.3, 0.18))
        return [f"[{src}]aecho=0.9:0.9:{gaps}:{decays}[{out}]"]
    if f["effect"] == "hall":    # a big space: convolved with a decaying burst of noise
        length = f["tail"]
        return [f"anoisesrc=d={length:.2f}:c=pink:r=48000:a=0.5:seed=7,"
                f"aformat=sample_rates=48000:channel_layouts=stereo,"
                f"afade=t=out:st=0:d={length:.2f}:curve=exp[{key}ir]",
                f"[{src}]asplit[{key}d][{key}w]",
                f"[{key}w]volume=0.06[{key}wv]",
                f"[{key}wv][{key}ir]afir=gtype=none[{key}r]",
                f"[{key}d][{key}r]amix=inputs=2:normalize=0:weights=1 {0.45 * a:.2f}[{out}]"]
    if f["effect"] == "waver":   # the pitch wavers
        # ffmpeg's vibrato puts out a burst of garbage in its first samples
        # (after loudnorm), so it gets a moment of silence first, cut off after.
        return [f"[{src}]adelay=delays=50:all=1,vibrato=f=5:d={min(1.0, 0.1 + 0.25 * a):.2f},"
                f"atrim=start=0.05,asetpts=PTS-STARTPTS[{out}]"]
    if f["effect"] == "pulse":   # the loudness throbs
        return [f"[{src}]tremolo=f=6:d={min(0.95, 0.35 + 0.3 * a):.2f},volume=1.2[{out}]"]
    # doubled: a second and third voice just behind, drifting (chorus)
    decays = "|".join(f"{min(0.9, d * a):.2f}" for d in (0.5, 0.45, 0.4))
    return [f"[{src}]chorus=0.7:0.9:40|60|80:{decays}:0.3|0.4|0.3:1.5|2|1.2,volume=0.75[{out}]"]


def loud_runs(path, gain):
    """Where the kept glasses audio (at `gain`) is loud enough to duck the
    song under: [(start, end)]. Its level every 40ms, averaged over 0.2s,
    above DUCK_THRESHOLD; quieter gaps under DUCK_GAP joined, and moments
    under DUCK_MIN dropped. audioMix.js finds the same from the envelopes."""
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-vn",
                          "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True).stdout
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) // 2 * 2])
    step = 320   # 40ms at 8kHz
    powers = [sum(x * x for x in samples[i:i + step]) / (max(len(samples[i:i + step]), 1) * 32768.0 ** 2) * gain * gain
              for i in range(0, len(samples), step)]
    return runs_from_powers(powers, 0.04)


def runs_from_powers(powers, step):
    on = []
    for i in range(len(powers)):
        near = powers[max(0, i - 2):i + 3]
        p = sum(near) / len(near)
        on.append(p > 0 and 10 * math.log10(p) > DUCK_THRESHOLD)
    runs = []
    for i, x in enumerate(on):
        if not x:
            continue
        t = i * step
        if runs and t - runs[-1][1] < DUCK_GAP:
            runs[-1][1] = t + step
        else:
            runs.append([t, t + step])
    return [(round(a, 3), round(b, 3)) for a, b in runs if b - a >= DUCK_MIN]


def duck_level(runs):
    """1, dropping DUCK_DB over DUCK_ATTACK into each loud run and coming
    back over DUCK_RELEASE after it: an ffmpeg expression."""
    depth = 1 - 10 ** (-DUCK_DB / 20)
    env = "+".join(f"clip((t-{a:.3f})/{DUCK_ATTACK},0,1)*clip(({b + DUCK_RELEASE:.3f}-t)/{DUCK_RELEASE},0,1)"
                   for a, b in runs)   # a sum, not nested max(): flat however many runs
    return f"1-{depth:.4f}*min(1,{env})"


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


def latest_cards(config_path, cfg, cards, times, plan, total, base_dir):
    """Re-read the title and end card from the config file, which may have
    changed since the render started. How long the end card holds can't
    change now (it set the reel's length); its words and logos can."""
    try:
        fresh = yaml.safe_load(Path(config_path).read_text()) or {}
        now_cfg = {k: v for k, v in cfg.items() if k not in ("title", "end_card")}
        for key in ("title", "end_card"):
            if fresh.get(key):
                now_cfg[key] = fresh[key]
        new = load_cards(now_cfg, base_dir)
    except (OSError, ValueError, yaml.YAMLError, SystemExit):
        return cards, times
    spec = lambda cs: [(c["kind"], c["spec"]) for c in cs]   # noqa: E731
    if spec(new) != spec(cards):
        print("  using the title and end card as they are now (changed during the render)")
    return new, card_times(new, plan, total)


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
    k = min(w / 1080, h / 1350)   # a square or 4:5 frame gets a smaller card, so it fits
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
    # The words sit in a centred column no wider than the frame is tall, so a
    # wide (16:9) frame gets captions sized as on a square one.
    cw = min(w, h)
    ox = (w - cw) / 2
    size = CAPTION_SIZE[style] * scale * float(cap.get("size", 1) or 1) * cw / 100
    font = load_caption_font(caption_font_path(name, base_dir), max(8, round(size)), weight)
    side, pad_x, pad_y = (v * cw / 100 for v in CAPTION_BOX[bg])
    lay = {"w": w, "h": h, "cw": cw, "style": style, "bg": bg, "font": font, "size": size,
           "lead": size * CAPTION_LEADING, "x0": ox + side, "x1": ox + cw - side, "pad_x": pad_x, "pad_y": pad_y,
           "ink": PAPER_INK if bg == "paper" else CARD_INK, "title": "", "base_dir": base_dir,
           "fps": cfg["fps"]}
    lay["text_x"] = ox + side + pad_x
    lay["text_w"] = cw - 2 * (side + pad_x)
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
    k = lay["cw"] / 1080
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
    k = lay["cw"] / 1080
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


# When an effect hits, its words show it too: copies of them under the line,
# offset, blurred or moving in time with the sound (all in % of the width).
#   echo     three ghosts stepping down and away, one per repeat
#   hall     a warm glow that swells and lingers while the room rings
#   waver    a trembling copy
#   pulse    a glow that throbs
#   doubled  two copies drifting either side
# Each is like a CSS text-shadow; the preview (captions.js emphasis) draws
# the same ones that way.
FX_GLOW = (0xf6, 0xdf, 0xa8)


def emphasis_specs(f):
    """The copies an effect puts under its words: [{t0, t1, fi, fo, dx, dy,
    blur, glow, alpha, xmove, ymove, pulse}]. Moves are ffmpeg expressions in
    t, in units of CQW (1% of the width). Same numbers as captions.js."""
    a, fs, fe = f["amount"], f["start"], f["end"]
    base = {"dx": 0.0, "dy": 0.0, "blur": 0.0, "glow": False}
    if f["effect"] == "echo":
        return [{**base, "t0": fs + k * ECHO_GAP, "t1": fe + k * ECHO_GAP, "fi": 0.06, "fo": 0.35,
                 "dx": 0.5 * k, "dy": 0.9 * k, "blur": 0.2 * k, "alpha": min(0.9, dec * a * 1.6)}
                for k, dec in ((1, 0.5), (2, 0.3), (3, 0.18))]
    if f["effect"] == "hall":
        tail = fx_tail("hall", a)
        span = {"t0": fs, "t1": fe + 0.8 * tail, "fi": 0.25, "fo": 0.6 * tail}
        return [{**base, **span, "blur": 3.0, "glow": True, "alpha": min(1.0, 0.7 + 0.2 * a)},
                {**base, **span, "blur": 1.0, "glow": True, "alpha": min(1.0, 0.5 + 0.2 * a)}]
    if f["effect"] == "waver":
        amp = 0.45 + 0.25 * a
        return [{**base, "t0": fs, "t1": fe, "fi": 0.1, "fo": 0.1, "blur": 0.2, "alpha": 0.7,
                 "xmove": f"{amp / 2:.3f}*CQW*cos(2*PI*5*(t-{fs:.3f}))",
                 "ymove": f"{amp:.3f}*CQW*sin(2*PI*5*(t-{fs:.3f}))"}]
    if f["effect"] == "pulse":
        span = {"t0": fs, "t1": fe, "fi": 0.1, "fo": 0.1, "glow": True, "pulse": (6, fs)}
        return [{**base, **span, "blur": 2.0, "alpha": 1.0}, {**base, **span, "blur": 0.6, "alpha": min(1.0, 0.5 + 0.3 * a)}]
    width = 1.0 + 0.4 * a   # doubled
    return [{**base, "t0": fs, "t1": fe, "fi": 0.15, "fo": 0.15, "blur": 0.15, "alpha": 0.5,
             "xmove": f"{sign}*{width:.3f}*CQW*(0.45+0.3*sin(2*PI*0.9*(t-{fs:.3f})+{phase}))"}
            for sign, phase in ((1, 0), (-1, 3.1416))]


def phrase_image(lay, rows, words, e, out):
    """Just the words from index words[0] to words[1] of a wrapped line, where
    they sit in it, in the ink (or a warm glow), blurred as asked. Returns
    (path, margin)."""
    from PIL import Image, ImageDraw, ImageFilter
    k = lay["cw"] / 1080
    m = round(80 * k)
    lead, font = lay["lead"], lay["font"]
    ascent, descent = font.getmetrics()
    color = (PAPER_INK if lay["bg"] == "paper" else FX_GLOW) if e["glow"] else lay["ink"]
    im = Image.new("RGBA", (round(lay["text_w"]) + 2 * m, round(lead * len(rows)) + 2 * m), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    n = 0
    for r, row in enumerate(rows):
        ws = row.split()
        x0 = m + (0 if lay["style"] == "page" else (lay["text_w"] - d.textlength(row, font=font)) / 2)
        y = m + r * lead + (lead - ascent - descent) / 2
        for i, word in enumerate(ws):
            if words[0] <= n <= words[1]:
                before = " ".join(ws[:i]) + (" " if i else "")
                d.text((x0 + d.textlength(before, font=font), y), word, font=font, fill=(*color, 255))
            n += 1
    mask = im.getchannel("A")
    if e["blur"]:   # a CSS shadow's blur radius is two standard deviations; blur only
        # the coverage, so the glow keeps its colour instead of fading to black
        mask = mask.filter(ImageFilter.GaussianBlur(e["blur"] * lay["cw"] / 100 / 2))
    im = Image.new("RGBA", im.size, (*color, 0))
    im.putalpha(mask.point(lambda v: v * e["alpha"]))
    im.save(out)
    return out, m


def caption_layers(lines, cap, cfg, base_dir, workdir, total):
    """Everything to lay over the picture for the captions, in order:
    {kind: png | color | blur, t0, t1, fi, fo, x, y, ...}."""
    lay = caption_layout(cap, cfg, base_dir)
    w, k = lay["cw"], lay["cw"] / 1080   # sizes go by the column's width
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
            layers.append({"kind": "color", "color": "0x2d3e26@0.48", "x": 0, "y": 0, "size": (lay["w"], lay["h"]), **span})
        elif lay["bg"] == "band":
            layers.append({"kind": "color", "color": "0x2d3e26@0.64", "x": 0, "y": top, "size": (lay["w"], bh), **span})
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
        for l, (y, rows), segs in zip(g["lines"], geo["lines"], caption_segments(g, lay["style"])):
            for f in l.get("fx") or []:   # the words an effect lifts out, under the line itself
                for e in emphasis_specs(f):
                    t0, t1 = max(e["t0"], g["a"]), min(e["t1"], g["b"], total)
                    if t1 - t0 < 0.08:
                        continue
                    n += 1
                    png, m = phrase_image(lay, rows, f["words"], e, workdir / f"cap-fx-{n:03d}.png")
                    layer = {"kind": "png", "path": png, "x": round(lay["text_x"] + e["dx"] * w / 100) - m,
                             "y": round(y + e["dy"] * w / 100) - m, "t0": t0, "t1": t1,
                             "fi": min(e["fi"], (t1 - t0) / 2), "fo": min(e["fo"], (t1 - t0) / 2),
                             "xmove": e.get("xmove", "").replace("CQW", f"{w / 100:.3f}"),
                             "ymove": e.get("ymove", "").replace("CQW", f"{w / 100:.3f}"), "pulse": e.get("pulse")}
                    if drift:
                        layer["drift"] = (2.2 * w / 100, 1.2 * w / 100, g["a"], g["b"], g["fi"], g["fo"])
                    layers.append(layer)
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
            throb = ""
            if l.get("pulse"):   # the glow's strength rises and falls
                hz, t0 = l["pulse"]
                throb = (f",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)'"
                         f":a='alpha(X,Y)*(0.6+0.4*sin(2*PI*{hz}*(T-{t0:.3f})))'")
            graph.append(f"[{idx}:v]format=rgba,{fades}{throb}[L{i}]")
        x, y = str(l["x"]), str(l["y"])
        if l.get("drift"):
            up, away, a, b, fi, fo = l["drift"]
            y += (f"+{up:.1f}*max(0,1-(t-{a:.3f})/{max(fi, 0.01):.3f})"
                  f"-{away:.1f}*max(0,1-({b:.3f}-t)/{max(fo, 0.01):.3f})")
        if l.get("xmove"):
            x += f"+{l['xmove']}"
        if l.get("ymove"):
            y += f"+{l['ymove']}"
        graph.append(f"{cur}[L{i}]overlay=x='{x}':y='{y}':eof_action=pass[c{i}]")
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
              "text": str(l.get("text", "")), "stanza": bool(l.get("stanza")),
              "fx": [{"effect": f["effect"], "amount": float(f.get("amount", 1) or 1),
                      "start": parse_time(f["start"]), "end": parse_time(f["end"]),
                      "words": [int(i) for i in f.get("words") or [0, 999]]}
                     for f in l.get("fx") or [] if f.get("effect") in VOICE_FX]}
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
    top = None if cfg.get("scenes") else load_top(cfg, base_dir)
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
        where = {"image": "hold", "gap": ""}.get(seg["kind"], f"from {fmt(seg['start'])}")
        if seg.get("pane") == "solo":
            where += " (alone)"
        layout = ""
        if seg.get("fit"):
            layout = f"  [{seg['fit']}]"
        print(f"  {fmt(t):>7}  r{seg['round']}  {seg['label']:<16} {where:<12} {seg['length']:.2f}s{layout}")
        if seg["t_after"]:
            print(f"  {'':>7}      ~ {seg['label_after']} {seg['d_after']:.2f}s")
        elif seg["label_after"]:
            print(f"  {'':>7}      ~ {seg['label_after']}")
        t += seg["length"]
    keys = layout_keys(plan, cfg["fps"])[0] if top else None
    if cfg.get("scenes"):
        print(f"\n  {len(cfg['scenes'])} scene{'s' if len(cfg['scenes']) != 1 else ''}:")
        for line in scene_report(cfg, plan, base_dir)[0]:
            print(line)
    if top:
        line = (f"\n  top: {top['path'].name} {fmt(top['start'])} -> "
                f"{fmt(top['start'] + top['length'])} · Top {fmt(top['length'])} · Underneath {fmt(total)}")
        if len(keys) > 1 or top["fit_by"] == "quiet":
            frames = round(total * cfg["fps"])
            visible, pieces, rate = top_plan(top, keys, frames, cfg["fps"])
            shown = sum(visible) / cfg["fps"]
            line += f" · on screen {fmt(shown)}"
            if len(pieces) > 1:
                line += f" · {len(pieces)} pieces, {fmt(top['length'] - sum(l for _, l in pieces))} quiet taken out"
            if abs(rate - 1) > 0.005:
                line += f" · at {rate:.2f}x"
            print(line)
            if len(pieces) > 1:
                print("        " + "  ".join(f"{fmt(s)}+{l:.1f}s" for s, l in pieces))
            names = {-1: "top alone", 0: "split", 1: f"{'right' if top['axis'] == 'x' else 'underneath'} alone"}
            moves = [keys[0]] + [(f, x) for (f, _), (_, x) in zip(keys[1::2], keys[2::2])]
            print("  layout: " + " · ".join(f"{fmt(f / cfg['fps'])} {names[x]}" for f, x in moves))
        else:
            run_len = top["length"] / top["speed"]
            if top["fit"]:
                line += f" · timelapse at {top['length'] / total:.2f}x"
            else:
                if abs(top["speed"] - 1) > 0.005:
                    line += f" · at {top['speed']:.2f}x, {fmt(run_len)}"
                if total > run_len:
                    line += f" · underneath cut at {fmt(run_len)}"
                elif total < run_len:
                    line += f" · last part holds {run_len - total:.1f}s"
            print(line)
    length = top_length(top, total, keys) if top else total
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
            for f in p["fx"]:
                print(f"  {fmt(p['at'] + f['start'] - p['start']):>7}    ~ {f['effect']} on {f['end'] - f['start']:.1f}s")
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

    mode = glasses_mode(cfg)
    # Lane A only exists in scenes: without them, "A only" keeps nothing.
    keep_audio = mode == "primary" or (mode == "A" and bool(cfg.get("scenes")))
    output = (base_dir / cfg.get("output", "montage.mp4")).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        if cfg.get("scenes"):
            def segs_of(k, w, h, fill, tail=0):
                """Scene k's cuts at w x h; the last carries on `tail` frames
                past the scene, so it keeps playing while the next comes in."""
                idx = [i for i, seg in enumerate(plan) if (seg.get("scene") or 0) == k and seg["kind"] != "gap"]
                if not idx:
                    return None
                kcfg = {**cfg, "width": w, "height": h, **({"fit": fill} if fill else {})}
                segs = [plan[i] for i in idx]
                if tail:
                    segs[-1] = {**segs[-1], "render_length": segs[-1]["render_length"] + tail / cfg["fps"]}
                files = []
                for i, seg in zip(idx, segs):
                    print(f"  cutting {i + 1}/{len(plan)}: {plan[i]['label']}          ", end="\r")
                    files.append(render_segment(seg, f"{i:03d}_{k}_{w}", kcfg, workdir, keep_audio))
                return assemble(files, segs, kcfg, workdir, f"scene{k:02d}_b{w}")
            assembled = render_scenes(plan, segs_of, cfg, base_dir, keep_audio, workdir)
            plan_done = True
        else:
            plan_done = False
        segs = []
        for i, seg in enumerate(plan if not plan_done else []):
            print(f"  cutting {i + 1}/{len(plan)}: {seg['label']}          ", end="\r")
            if seg["kind"] == "gap":
                seg = gap_footage(plan, i)
                plan[i]["_from"] = seg.get("_from")
            segs.append(render_segment(seg, i, cfg, workdir, keep_audio))
        if not plan_done:
            print("  joining cuts...                         ", end="\r")
            assembled = assemble(segs, plan, cfg, workdir)
        if top:
            print("  stacking under the top clip...          ", end="\r")
            assembled = compose_top(top, assembled, cfg, total, workdir, plan)
            total = top_length(top, total, keys)
        if cap_lines:
            print("  laying the captions over...             ", end="\r")
            assembled = add_captions(assembled, cap_lines, cap, cfg, base_dir, total, workdir)
        # The title and end card as they are now: the studio keeps this file up
        # to date while a render runs, so their words and logos can still change.
        cards, times = latest_cards(config_path, cfg, cards, times, plan, total, base_dir)
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
