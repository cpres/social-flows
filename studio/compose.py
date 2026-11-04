"""
Make a background track for a reel with AI music (Google's Lyria 3, through
OpenRouter), built up and broken down to the reel's exact length.

The music models take text (and images), not audio, so "like these songs" is
done here: the reference songs on the shelf are measured (tempo, key, how
bright, how beat-driven, how the energy moves) and their categories read,
and that becomes the style part of the prompt. The arc (intro, build, drop,
breakdown, outro) is laid out on whole bars at the target tempo and written
into the prompt with timestamps, so the build-ups land where the reel is.

    OPENROUTER_API_KEY=sk-or-...  (in the shell that runs ./studio/run.sh)

Also runs on its own, to try prompts without the studio:

    python3 studio/compose.py --seconds 32 --ref ~/Music/Reels/some-song.mp3
    python3 studio/compose.py --seconds 32 --bpm 96 --style "lo-fi hip hop" --dry-run
"""

import base64
import json
import math
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ENDPOINT = os.environ.get("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")
MODELS = {
    "pro": "google/lyria-3-pro-preview",    # full songs, length set in the prompt (~$0.08 a song)
    "clip": "google/lyria-3-clip-preview",  # always 30 seconds (~$0.04): cheap prompt tests
}
CLIP_SECONDS = 30.0


# ---------------------------------------------------------------- the reference songs

KEYS = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
# Krumhansl–Kessler key profiles.
MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def measure(path, beats=None):
    """What a song sounds like, in numbers and words: {bpm, key, bright,
    drive, dynamics, words}. `beats` is the shelf's cached analysis if there
    is one (saves finding the tempo again). Needs librosa (./studio/run.sh --beat)."""
    import librosa
    import numpy as np

    # The middle 60 seconds says enough, and keeps this quick.
    dur = librosa.get_duration(path=str(path))
    offset = max(0.0, dur / 2 - 30)
    y, sr = librosa.load(str(path), sr=22050, mono=True, offset=offset, duration=60)
    if beats and beats.get("bpm"):
        bpm = float(beats["bpm"])
    else:
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = float(np.atleast_1d(tempo)[0])

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)
    best = (-2.0, "C major")
    for i in range(12):
        for profile, mode in ((MAJOR, "major"), (MINOR, "minor")):
            r = float(np.corrcoef(chroma, np.roll(profile, i))[0, 1])
            if r > best[0]:
                best = (r, f"{KEYS[i]} {mode}")
    key = best[1]

    centroid = float(librosa.feature.spectral_centroid(y=y, sr=sr).mean())
    harmonic, percussive = librosa.effects.hpss(y)
    drive = float((percussive ** 2).sum() / max((y ** 2).sum(), 1e-9))   # share of energy in the hits
    rms = librosa.feature.rms(y=y)[0]
    loud = rms[rms > rms.max() * 0.05]
    dynamics = float(np.percentile(loud, 90) / max(np.percentile(loud, 10), 1e-6)) if len(loud) else 1.0

    words = []
    words.append("bright, airy top end" if centroid > 3000 else
                 "warm, rounded tone" if centroid > 1800 else "dark, bass-heavy, mellow tone")
    words.append("punchy, beat-forward drums" if drive > 0.35 else
                 "steady groove under melodic layers" if drive > 0.18 else
                 "soft, mostly melodic with light percussion")
    words.append("big contrast between quiet and loud parts" if dynamics > 4 else
                 "even, consistent energy")
    return {"bpm": round(bpm, 1), "key": key, "bright": round(centroid), "drive": round(drive, 2),
            "dynamics": round(dynamics, 1), "words": words}


def blend(refs):
    """Several measured songs -> one style: the tempo they share (median,
    folded so 70 and 140 count as the same), the first song's key, and the
    words they have in common (or the first song's)."""
    if not refs:
        return {}
    bpms = sorted(r["bpm"] for r in refs)
    mid = bpms[len(bpms) // 2]
    folded = sorted(b * 2 if b < mid * 0.7 else b / 2 if b > mid * 1.4 else b for b in bpms)
    bpm = folded[len(folded) // 2]
    common = [w for w in refs[0]["words"] if all(w in r["words"] for r in refs)]
    return {"bpm": round(bpm), "key": refs[0]["key"], "words": common or refs[0]["words"]}


# ---------------------------------------------------------------- the arc

# Each section: (name, share of the reel, what happens), by how many bars
# of 4 beats the reel has (8 bars is about 19s at 100 bpm). Shares are scaled
# to whole bars; short reels get fewer sections.
ARCS = [
    (8, [("Intro", 0.3, "sparse: a simple motif and a light pulse, room to grow"),
          ("Build", 0.3, "layers stack up, rising filter and a short drum fill into the drop"),
          ("Drop", 0.4, "full beat and bass, the main hook, confident and bright")]),
    (16, [("Intro", 0.15, "sparse: the main motif alone with a soft pulse"),
          ("Build", 0.2, "drums come in, layers stack, energy rising, riser into the drop"),
          ("Drop", 0.35, "full groove and bass, the hook at full energy"),
          ("Breakdown", 0.15, "drums pull back to the motif and pads, a breath"),
          ("Final drop", 0.15, "everything back in, biggest moment, ends on a clean final hit")]),
    (32, [("Intro", 0.1, "sparse: the main motif alone with a soft pulse"),
          ("Build", 0.15, "drums come in, layers stack, energy rising, riser into the drop"),
          ("Drop", 0.22, "full groove and bass, the hook at full energy"),
          ("Breakdown", 0.15, "drums drop out, pads and the motif, half-time feel"),
          ("Build", 0.1, "snare roll and rising filter, tension building back up"),
          ("Final drop", 0.2, "everything back in, biggest moment of the track"),
          ("Outro", 0.08, "layers fall away, ends on a clean final hit")]),
    (math.inf, [("Intro", 0.08, "sparse: the main motif alone with a soft pulse"),
                ("Build", 0.1, "drums come in, layers stack, energy rising"),
                ("Drop", 0.18, "full groove and bass, the hook at full energy"),
                ("Breakdown", 0.12, "drums drop out, pads and the motif, half-time feel"),
                ("Build", 0.08, "snare roll and rising filter, tension building back up"),
                ("Drop", 0.16, "full groove again with a new counter-melody"),
                ("Breakdown", 0.08, "a short pull-back, just bass and keys"),
                ("Final drop", 0.14, "everything in, biggest moment of the track"),
                ("Outro", 0.06, "layers fall away, ends on a clean final hit")]),
]


def arc(seconds, bpm):
    """The sections, on whole bars of 4 beats: [{name, start, end, bars, what}]."""
    bar = 240.0 / bpm
    bars = max(2, round(seconds / bar))
    plan = next(p for limit, p in ARCS if bars <= limit)
    # Whole bars for each, at least one, adding up to the total.
    want = [share * bars for _, share, _ in plan]
    counts = [max(1, math.floor(w)) for w in want]
    while sum(counts) < bars:
        i = max(range(len(want)), key=lambda k: want[k] - counts[k])
        counts[i] += 1
    while sum(counts) > bars:
        i = max((k for k in range(len(counts)) if counts[k] > 1), key=lambda k: counts[k] - want[k])
        counts[i] -= 1
    out, at = [], 0
    for (name, _, what), n in zip(plan, counts):
        out.append({"name": name, "start": round(at * bar, 2), "end": round((at + n) * bar, 2),
                    "bars": n, "what": what})
        at += n
    # The last section ends with the reel, not on the bar after.
    out[-1]["end"] = round(seconds, 2)
    return out


def clock(t):
    t = max(0, round(t))
    return f"{t // 60}:{t % 60:02d}"


def prompt(seconds, bpm, key=None, style="", words=(), notes="", sections=None):
    """The prompt for Lyria: instrumental, tempo and key, the style, and the
    arc with timestamps."""
    sections = sections or arc(seconds, bpm)
    lines = [f"An instrumental background track for a short social video, exactly {clock(seconds)} long "
             f"({seconds:.0f} seconds).",
             "Instrumental only: no vocals, no singing, no spoken words.",
             f"Tempo {bpm:.0f} BPM in 4/4" + (f", in {key}." if key else ".") +
             " Keep a steady, clearly audible beat the whole way through, so video cuts can land on it."]
    feel = ", ".join([s for s in [style.strip()] if s] + list(words))
    if feel:
        lines.append(f"Style: {feel}.")
    lines.append("Structure:")
    for s in sections:
        lines.append(f"[{clock(s['start'])} - {clock(s['end'])}] {s['name']}: {s['what']}.")
    if notes.strip():
        lines.append(notes.strip())
    return "\n".join(lines)


# ---------------------------------------------------------------- OpenRouter

class ComposeError(Exception):
    pass


def api_key():
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        f = Path("~/.config/openrouter/key").expanduser()
        key = f.read_text().strip() if f.exists() else ""
    if not key:
        raise ComposeError("No OpenRouter key: set OPENROUTER_API_KEY (or put the key in "
                           "~/.config/openrouter/key) and restart the studio.")
    return key


def request(text, model, stream=False):
    body = {"model": model, "messages": [{"role": "user", "content": text}],
            "modalities": ["audio", "text"]}
    if stream:
        body["stream"] = True
    # Room to try other shapes of request without changing code, e.g.
    # OPENROUTER_EXTRA='{"audio": {"format": "wav"}}'
    body.update(json.loads(os.environ.get("OPENROUTER_EXTRA", "{}") or "{}"))
    return urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {api_key()}", "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:3009", "X-Title": "Footage Studio"})


def call(text, model, log_dir=None):
    """Ask for the track; returns (audio bytes, the response with audio left out).
    Tries a plain request, then a streamed one if the model only streams."""
    for stream in (False, True):
        try:
            with urllib.request.urlopen(request(text, model, stream), timeout=600) as res:
                raw = res.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            if not stream and "stream" in detail.lower():
                continue
            raise ComposeError(f"OpenRouter said {e.code}: {short_error(detail)}")
        except urllib.error.URLError as e:
            raise ComposeError(f"Couldn't reach OpenRouter: {e.reason}")
        responses = sse(raw) if stream or raw.lstrip().startswith("data:") else [json.loads(raw)]
        if log_dir:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            (Path(log_dir) / f"response-{datetime.now():%Y%m%d-%H%M%S}.json").write_text(
                json.dumps(redacted(responses), indent=1)[:200_000])
        for r in responses:
            if r.get("error"):
                raise ComposeError(f"OpenRouter: {short_error(json.dumps(r['error']))}")
        audio = find_audio(responses)
        if audio:
            return audio, redacted(responses)
        said = " ".join(text_of(responses)).strip()
        raise ComposeError("No audio came back" + (f"; the model said: {said[:300]}" if said else
                                                   " (the response is saved next to the music cache)"))
    raise ComposeError("OpenRouter wanted a streamed request, and that didn't work either.")


def short_error(detail):
    try:
        d = json.loads(detail)
        e = d.get("error", d)
        msg = e.get("message") if isinstance(e, dict) else str(e)
        meta = e.get("metadata", {}) if isinstance(e, dict) else {}
        raw = meta.get("raw") if isinstance(meta, dict) else None
        return f"{msg}" + (f" ({str(raw)[:300]})" if raw else "")
    except Exception:
        return detail[:400]


def sse(raw):
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]"):
            try:
                out.append(json.loads(line[5:].strip()))
            except json.JSONDecodeError:
                pass
    return out


B64 = re.compile(r"^[A-Za-z0-9+/=\r\n]+$")


def find_audio(responses):
    """The audio in the response, wherever the model put it: a data: URL, a
    base64 `data` under an audio field (joined across streamed chunks), or a
    link to fetch."""
    pieces, urls = [], []

    def walk(v, under_audio=False, key=""):
        if isinstance(v, dict):
            typed = "audio" in str(v.get("type", "")).lower()
            for k, x in v.items():
                walk(x, under_audio or typed or "audio" in str(k).lower(), str(k))
        elif isinstance(v, list):
            for x in v:
                walk(x, under_audio, key)
        elif isinstance(v, str):
            if v.startswith("data:audio/") and "," in v:
                pieces.append(v.split(",", 1)[1])
            elif under_audio and v.startswith("http"):
                urls.append(v)
            # (a streamed piece can be short; anything else this long and base64 is audio)
            elif under_audio and (key == "data" or len(v) > 200) and v.strip() and B64.match(v[:2000]):
                pieces.append(v)

    walk(responses)
    if pieces:
        # Streamed pieces are either one base64 string cut up, or each encoded on its own.
        if any("=" in x.strip() for x in pieces[:-1]):
            return b"".join(base64.b64decode(x) for x in pieces)
        return base64.b64decode("".join(pieces))
    for u in urls:
        with urllib.request.urlopen(u, timeout=300) as res:
            return res.read()
    return None


def text_of(responses):
    out = []
    for r in responses:
        for c in r.get("choices", []):
            m = c.get("message") or c.get("delta") or {}
            if isinstance(m.get("content"), str):
                out.append(m["content"])
    return out


def redacted(v):
    """The response with long base64 strings shortened, for the log."""
    if isinstance(v, dict):
        return {k: redacted(x) for k, x in v.items()}
    if isinstance(v, list):
        return [redacted(x) for x in v]
    if isinstance(v, str) and len(v) > 300:
        return v[:80] + f"... ({len(v)} chars)"
    return v


def extension(data):
    if data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return ".mp3"
    if data[:4] == b"RIFF":
        return ".wav"
    if data[:4] == b"fLaC":
        return ".flac"
    if data[:4] == b"OggS":
        return ".ogg"
    if data[4:8] == b"ftyp":
        return ".m4a"
    return ".mp3"


# ---------------------------------------------------------------- the file

def duration_of(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(path)], capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def save(audio, out_path, seconds, bpm, tags):
    """Write the track as an MP3 with its tags. A track that runs well past
    the reel is cut a bar after it, fading over that bar."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"raw{extension(audio)}"
        src.write_bytes(audio)
        got = duration_of(src)
        bar = 240.0 / bpm
        cut = []
        if seconds and got > seconds + 2 * bar:
            end = seconds + bar
            cut = ["-t", f"{end:.3f}", "-af", f"afade=t=out:st={seconds:.3f}:d={bar:.3f}"]
        meta = [x for k, v in tags.items() if v for x in ("-metadata", f"{k}={v}")]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), *cut, *meta,
                            "-id3v2_version", "3", "-c:a", "libmp3lame", "-b:a", "320k", str(out_path)],
                           capture_output=True, text=True)
        if r.returncode:
            raise ComposeError(f"Couldn't save the track: {r.stderr.strip()[-300:]}")
        return got


def compose(seconds, bpm, out_dir, name, key=None, style="", words=(), notes="", model="pro",
            text=None, log_dir=None):
    """Make the track and put it in out_dir. Returns {file, path, prompt, generated, ...}."""
    if model == "clip":
        seconds = min(seconds, CLIP_SECONDS)
    sections = arc(seconds, bpm)
    text = text or prompt(seconds, bpm, key, style, words, notes, sections)
    audio, _ = call(text, MODELS.get(model, model), log_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    safe = re.sub(r"[^\w\- ]+", "", name).strip()[:40] or "reel"
    out = Path(out_dir).expanduser() / f"AI {safe} {round(seconds)}s {round(bpm)}bpm {stamp}.mp3"
    got = save(audio, out, seconds, bpm, {
        "title": f"AI · {name} · {clock(seconds)}",
        "artist": "Lyria (OpenRouter)",
        "genre": "; ".join(["AI"] + [g.strip() for g in re.split(r"[;,]", style) if g.strip()]),
        "comment": text.replace("\n", " ")[:900]})
    return {"file": out.name, "path": str(out), "prompt": text, "sections": sections, "seconds": seconds,
            "bpm": bpm, "key": key, "generated": round(got, 2), "model": MODELS.get(model, model)}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Make an AI background track of a given length.")
    ap.add_argument("--seconds", type=float, required=True, help="how long the reel is")
    ap.add_argument("--ref", action="append", default=[], help="a song to take the style from (repeatable)")
    ap.add_argument("--bpm", type=float, help="tempo (default: the reference songs', else 100)")
    ap.add_argument("--key", help='e.g. "A minor" (default: the first reference song\'s)')
    ap.add_argument("--style", default="", help='genre words, e.g. "lo-fi hip hop, warm keys"')
    ap.add_argument("--notes", default="", help="anything else to ask for")
    ap.add_argument("--model", default="pro", choices=["pro", "clip"])
    ap.add_argument("--out", default=os.environ.get("MUSIC_DIR", "~/Music/Reels"))
    ap.add_argument("--name", default="test")
    ap.add_argument("--dry-run", action="store_true", help="print the prompt, don't call the API")
    a = ap.parse_args()

    measured = []
    for r in a.ref:
        m = measure(Path(r).expanduser())
        print(f"  {Path(r).name}: {m['bpm']} bpm, {m['key']}, {', '.join(m['words'])}")
        measured.append(m)
    style = blend(measured)
    bpm = a.bpm or style.get("bpm") or 100
    key = a.key or style.get("key")
    words = style.get("words", [])
    seconds = min(a.seconds, CLIP_SECONDS) if a.model == "clip" else a.seconds
    text = prompt(seconds, bpm, key, a.style, words, a.notes)
    print("\n" + text + "\n")
    if a.dry_run:
        return
    print(f"Asking {MODELS[a.model]} ...")
    done = compose(seconds, bpm, a.out, a.name, key, a.style, words, a.notes, a.model, text=text,
                   log_dir=Path(tempfile.gettempdir()) / "footage-studio-compose")
    print(f"Saved {done['path']} (came back {done['generated']:.1f}s long; asked for {seconds:.1f}s)")


if __name__ == "__main__":
    main()
