"""The beat builder: AI music made to a reel's exact length, building up and
cooling down with an energy curve over the reel (see web/src/beat.js for the
levers, presets and the prompt).

A reel's `beat` setting holds what it was asked for:

    {from: {kind: song|scratch, name?, category?},
     curve: [[t 0..1, energy 0..1], ...], preset: follow|arc|slow|peaks|steady|custom,
     hits: bool (a fill, riser or drop on each scene change),
     end: bool (resolve on the last frame, else fade out),
     levers: {funky..earthy: 0..5}, vibe: the preset the levers came from,
     tempo: bpm or null (derived from the levers), key: "F major" or null (derived),
     prompt: the edited prompt, or null (built from the above)}
"""

import json
import math
import os
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

LEVERS = ("funky", "happy", "chill", "upbeat", "grungy", "futuristic", "ecstatic", "drummy", "bass", "earthy")
PRESETS = ("follow", "arc", "slow", "peaks", "steady", "custom")
TEMPO_RANGE = (60, 180)
ENGINES = ("elevenlabs", "lyria")


def _num(v, lo, hi, default):
    try:
        return min(max(float(v), lo), hi)
    except (TypeError, ValueError):
        return default


def clean(beat):
    """A reel's `beat` setting, kept in range (None if it isn't one)."""
    if not isinstance(beat, dict):
        return None
    src = beat.get("from") if isinstance(beat.get("from"), dict) else {}
    kind = "song" if src.get("kind") == "song" and src.get("name") else "scratch"
    out = {"from": {"kind": kind, **({"name": str(src["name"])[:300],
                                      "category": str(src.get("category") or "")[:60]} if kind == "song" else {})}}
    points = []
    for p in beat.get("curve") or []:
        if isinstance(p, (list, tuple)) and len(p) == 2:
            points.append([round(_num(p[0], 0, 1, 0), 4), round(_num(p[1], 0, 1, 0.5), 3)])
    points.sort(key=lambda p: p[0])
    if len(points) < 2:
        points = [[0, 0.5], [1, 0.5]]
    points[0][0], points[-1][0] = 0, 1
    out["curve"] = points[:40]
    out["preset"] = beat.get("preset") if beat.get("preset") in PRESETS else "custom"
    out["hits"] = bool(beat.get("hits", True))
    out["end"] = bool(beat.get("end", True))
    levers = beat.get("levers") if isinstance(beat.get("levers"), dict) else {}
    out["levers"] = {k: int(_num(levers.get(k), 0, 5, 0)) for k in LEVERS}
    out["vibe"] = str(beat.get("vibe") or "")[:40]
    tempo = beat.get("tempo")
    out["tempo"] = None if tempo in (None, "") else round(_num(tempo, *TEMPO_RANGE, 100))
    key = " ".join(str(beat.get("key") or "").split())[:20]
    out["key"] = key or None
    prompt = beat.get("prompt")
    out["prompt"] = str(prompt)[:4000] if isinstance(prompt, str) and prompt.strip() else None
    ceil = beat.get("ceiling")
    out["ceiling"] = None if ceil in (None, "") or _num(ceil, 0.1, 1, 1) >= 0.995 else round(_num(ceil, 0.1, 1, 1), 2)
    out["engine"] = beat.get("engine") if beat.get("engine") in ENGINES else "elevenlabs"
    use = beat.get("inUse")
    out["inUse"] = ({"take": str(use["take"])[:40], "length": round(_num(use.get("length"), 0, 3600, 0), 2),
                     "tempo": round(_num(use.get("tempo"), *TEMPO_RANGE, 100))}
                    if isinstance(use, dict) and use.get("take") else None)
    return out


# ---------------------------------------------------------------- what the levers point to
# The same as web/src/beat.js, so the server asks for what the page shows.

WORDS = {"funky": ("funky", "very funky"), "happy": ("happy", "joyful"), "chill": ("chill", "very laid-back"),
         "upbeat": ("upbeat", "driving"), "grungy": ("grungy", "dirty, distorted"),
         "futuristic": ("futuristic", "glitchy, synth-heavy"),
         "ecstatic": ("ecstatic", "euphoric, with chants and swells"), "drummy": ("drummy", "percussion-heavy"),
         "bass": ("bass", "heavy bass"), "earthy": ("earthy", "earthy, hand drums and kalimba")}


def tempo_of(beat):
    if beat.get("tempo"):
        return int(beat["tempo"])
    l = beat["levers"]
    t = 88 + 7 * l["upbeat"] - 5 * l["chill"] + 3 * l["ecstatic"] + l["funky"]
    return int(round(min(max(t, TEMPO_RANGE[0]), TEMPO_RANGE[1])))


def key_of(beat, ref_key=""):
    if beat.get("key"):
        return beat["key"]
    tonic = (ref_key or "").split(" ")[0] or "C"
    h = beat["levers"]["happy"]
    return f"{tonic} {'major' if h >= 3 else 'dorian' if h >= 1 else 'minor'}"


def lever_words(beat):
    return [WORDS[k][1] if v >= 4 else WORDS[k][0] for k, v in beat["levers"].items() if v >= 2]


def curve_at(points, x):
    """The energy curve at x (0..1), straight between points (the page draws
    it smooth; for a section's average that's the same)."""
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * ((x - x0) / max(x1 - x0, 1e-6))
    return points[-1][1]


# ---------------------------------------------------------------- sections

MIN_SECTION = 3.0     # the API's shortest section
MAX_SECTION = 20.0    # longer stretches are split, so the energy can move within them
MAX_SECTIONS = 30


def energy_words(e):
    return ("very sparse, soft, minimal percussion, lots of space" if e < 0.25 else
            "light groove, gentle percussion, warm" if e < 0.45 else
            "steady groove, fuller arrangement" if e < 0.65 else
            "driving, full drums and bass, energetic" if e < 0.85 else
            "peak energy, everything in, big and euphoric")


def sections(beat, length, edges):
    """The reel cut into sections for the music: at each scene change (so a
    hit can land on it), and long stretches split. Each: {start, end, name,
    energy, trend, edge_in, edge_out} in seconds; they add up to `length`."""
    if length < MIN_SECTION:
        raise BeatError(f"The reel is {length:.1f}s; a beat needs at least {MIN_SECTION:.0f}s.")
    if length > 600:
        raise BeatError("A beat can be at most 10 minutes long.")
    cuts, last = [0.0], 0.0
    for e in sorted(edges):
        if e - last >= MIN_SECTION and length - e >= MIN_SECTION:
            cuts.append(e)
            last = e
    scene_edges = set(cuts[1:])
    bounds = []
    for a, b in zip(cuts, cuts[1:] + [length]):
        n = max(1, math.ceil((b - a) / MAX_SECTION))
        bounds += [a + (b - a) * i / n for i in range(n)]
    bounds.append(length)
    while len(bounds) - 1 > MAX_SECTIONS:   # very long reels: merge the shortest neighbours
        i = min(range(1, len(bounds) - 1), key=lambda j: bounds[j + 1] - bounds[j - 1])
        bounds.pop(i)
    out = []
    pts = beat["curve"]
    for i, (a, b) in enumerate(zip(bounds, bounds[1:])):
        xs = [(a + (b - a) * j / 8) / length for j in range(9)]
        es = [curve_at(pts, x) for x in xs]
        e0, e1, em = es[0], es[-1], sum(es) / len(es)
        trend = "up" if e1 - e0 > 0.07 else "down" if e0 - e1 > 0.07 else "flat"
        last_one = i == len(bounds) - 2
        name = ("Intro" if i == 0 and em < 0.45 else
                "Outro" if last_one and trend == "down" else
                "Peak" if em >= 0.8 else
                "Build" if trend == "up" else
                "Breakdown" if trend == "down" else
                "Finale" if last_one else "Groove")
        out.append({"start": round(a, 3), "end": round(b, 3), "name": name, "energy": round(em, 2),
                    "trend": trend, "edge_in": a in scene_edges, "edge_out": b in scene_edges})
    return out


# The three takes of a run: the same plan, each leaning a different way.
VARIATIONS = [("tighter drums", ["tight, punchy drums", "crisp hi-hats"]),
              ("more bass, warmer", ["warm, round bass up front", "warmer tone"]),
              ("sparser, more space", ["sparse arrangement", "more space and air"])]
# Adapting a take: ways to change it, each a label, words for the music,
# lever nudges, and how the energy curve moves. The take keeps its seed and
# tempo (so it stays close, and still fits the cut).
ADAPTS = {
    "drums+": ("more drums", ["bigger, busier drums", "more percussion and fills"], {"drummy": 2}, 0),
    "drums-": ("fewer drums", ["lighter, sparser drums", "less percussion"], {"drummy": -2}, 0),
    "bass+": ("more bass", ["heavier bass", "more low end"], {"bass": 2}, 0),
    "calmer": ("calmer", ["calmer and softer", "more space"], {"chill": 1, "upbeat": -1}, -0.15),
    "energy+": ("more energy", ["more energy and drive", "bigger build-ups"], {"upbeat": 1}, 0.15),
    "brighter": ("brighter", ["brighter, happier tone", "sparkling top end"], {"happy": 1}, 0),
    "grittier": ("grittier", ["grittier, more texture", "a little tape dirt"], {"grungy": 2}, 0),
    "simpler": ("simpler", ["simpler arrangement", "fewer layers"], {}, 0),
}


def adapted(beat, tweaks, note):
    """A take's beat, changed by the tweaks (ADAPTS keys) and a note in your
    own words: (beat, extra words for the music, label)."""
    b = json.loads(json.dumps(beat))
    words, labels = [], []
    for k in tweaks:
        if k not in ADAPTS:
            continue
        label, extra, nudges, lift = ADAPTS[k]
        labels.append(label)
        words += extra
        for lever, d in nudges.items():
            b["levers"][lever] = int(min(max(b["levers"][lever] + d, 0), 5))
        if lift:
            b["curve"] = [[x, round(min(max(y + lift, 0.0), 1.0), 3)] for x, y in b["curve"]]
    note = " ".join(str(note or "").split())[:200]
    if note:
        words.append(note)
        labels.append(f"“{note}”")
    return b, words, (", ".join(labels) or "another like it")


NO_VOCALS = ["vocals", "singing", "lyrics", "spoken word", "rap"]


def composition_plan(beat, secs, style, variation):
    """An ElevenLabs music_v2_5 composition plan: a chunk per section, its
    duration exact (v2 models always keep them), the sound set by the first
    chunk's styles and the energy by each chunk's."""
    length = secs[-1]["end"]
    ms = [round(s["end"] * 1000) - round(s["start"] * 1000) for s in secs]
    ms[-1] = round(length * 1000) - sum(ms[:-1])
    negative = ["lead vocals", "lyrics", "spoken word", "rap"] if beat["levers"]["ecstatic"] >= 4 else list(NO_VOCALS)
    calm = (beat.get("ceiling") or 1) <= 0.65   # kept low: relaxed and steady the whole way
    if calm:
        negative += ["big drop", "aggressive"]
    chunks = []
    for i, (s, d) in enumerate(zip(secs, ms)):
        directions = []
        if s["edge_in"] and beat["hits"]:
            directions.append("big hit on the first beat")
        directions.append({"up": "building up, layers stacking, rising energy",
                           "down": "winding down, layers falling away"}.get(s["trend"], energy_words(s["energy"])))
        if s["edge_out"] and beat["hits"]:
            directions.append("drum fill into the next section")
        if i == len(secs) - 1:
            directions.append("resolves and ends on a final hit on the last beat" if beat["end"] else "fades out")
        styles = [energy_words(s["energy"])]
        if i == 0:
            styles = (["instrumental"] + style["genres"] + style["words"] + style["levers"]
                      + [f"{style['tempo']} BPM", style["key"]] + styles + variation
                      + (["relaxed, steady vibe throughout", "gentle lift, never peaks"] if calm else [])
                      + ["great production quality"])
        chunks.append({"text": f"[{s['name']}]\n" + "\n".join(f"{{{d_}}}" for d_ in directions),
                       "duration_ms": d, "positive_styles": [x[:200] for x in styles][:50],
                       "negative_styles": negative, "context_adherence": "high"})
    return {"chunks": chunks}


def timestamped(prompt, secs):
    """The prompt with its sections as [m:ss - m:ss] lines (Lyria reads timestamps)."""
    clock = lambda t: f"{int(t // 60)}:{int(t % 60):02d}"
    return prompt + "\n" + "\n".join(
        f"[{clock(s['start'])} - {clock(s['end'])}] {s['name']}: {energy_words(s['energy'])}"
        + (", building up" if s["trend"] == "up" else ", winding down" if s["trend"] == "down" else "")
        for s in secs) + "\nInstrumental, no vocals."


# ---------------------------------------------------------------- ElevenLabs

ELEVEN_URL = os.environ.get("ELEVENLABS_URL", "https://api.elevenlabs.io").rstrip("/")
ELEVEN_MODEL = "music_v2_5"
ELEVEN_FORMAT = "mp3_48000_192"
ELEVEN_BITRATE = 192_000   # bits a second of what comes back, to tell how much has arrived


class BeatError(Exception):
    pass


def eleven_key():
    for k in ("ELEVENLABS_API_KEY", "ELEVEN_LABS_API_KEY", "XI_API_KEY"):
        if os.environ.get(k, "").strip():
            return os.environ[k].strip()
    raise BeatError("No ElevenLabs key: put ELEVENLABS_API_KEY=... in the .env next to studio/, "
                    "then restart the studio.")


def eleven_error(code, body):
    try:
        d = json.loads(body).get("detail")
    except ValueError:
        d = None
    msg = (d.get("message") if isinstance(d, dict) else d if isinstance(d, str) else "") or body[:300]
    if code == 402:
        return BeatError(f"ElevenLabs: {msg} (Music needs a paid ElevenLabs plan; or switch the engine to Lyria.)")
    if code == 401:
        return BeatError(f"ElevenLabs didn't accept the key: {msg}")
    if isinstance(d, dict) and d.get("composition_plan_suggestion"):
        return BeatError(f"ElevenLabs turned the plan down: {msg}")
    return BeatError(f"ElevenLabs said {code}: {msg}")


def eleven_stream(body, on_bytes, timeout=600):
    """POST the request to /v1/music/stream; reads the MP3 as it comes,
    calling on_bytes(total) as it grows. Returns (audio bytes, song id)."""
    req = urllib.request.Request(f"{ELEVEN_URL}/v1/music/stream?output_format={ELEVEN_FORMAT}",
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"xi-api-key": eleven_key(), "Content-Type": "application/json",
                                          "Accept": "audio/mpeg"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            song = res.headers.get("song-id") or ""
            got = bytearray()
            while True:
                chunk = res.read(16384)
                if not chunk:
                    break
                got += chunk
                on_bytes(len(got))
    except urllib.error.HTTPError as e:
        raise eleven_error(e.code, e.read().decode("utf-8", "replace"))
    except urllib.error.URLError as e:
        raise BeatError(f"Couldn't reach ElevenLabs: {e.reason}")
    if len(got) < 1000:
        raise BeatError("ElevenLabs sent back no audio.")
    return bytes(got), song


# ---------------------------------------------------------------- landing it on the reel

def duration_of(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def land(audio, out_path, length, end, tags):
    """The take at exactly `length`: cut there (a 10ms fade so it doesn't
    click) or padded with silence if it came back short; faded over the last
    2s unless it's to end on the last frame. Returns how long it came back."""
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw.mp3"
        raw.write_bytes(audio)
        got = duration_of(raw)
        fade = min(2.0, length / 4) if not end else 0.01
        af = f"apad=whole_dur={length:.3f},atrim=0:{length:.3f},afade=t=out:st={max(length - fade, 0):.3f}:d={fade:.3f}"
        meta = [x for k, v in tags.items() if v for x in ("-metadata", f"{k}={v}")]
        r = subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(raw), "-af", af, *meta,
                            "-id3v2_version", "3", "-c:a", "libmp3lame", "-b:a", "320k", str(out_path)],
                           capture_output=True, text=True)
        if r.returncode:
            raise BeatError(f"Couldn't save the take: {r.stderr.strip()[-300:]}")
    return got


# ---------------------------------------------------------------- takes

def takes_dir(home, reel_id):
    return Path(home) / "beats" / str(int(reel_id))


def list_takes(home, reel_id):
    d = takes_dir(home, reel_id)
    out = []
    for meta in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            t = json.loads(meta.read_text())
        except ValueError:
            continue
        if (d / f"{t['id']}.mp3").exists():
            out.append(t)
    for t in out:   # names from before Adapt: "more like …" / "rebuilt to …"
        old = t.get("label", "")
        if old.startswith("more like ") or old.startswith("rebuilt to "):
            t["label"] = "another like it" if old.startswith("more like ") else "rebuilt for the new cut"
            (d / f"{t['id']}.json").write_text(json.dumps(t, indent=1))
    out.sort(key=lambda t: (t.get("created", ""), t.get("n", 0)))
    if len({t.get("n") for t in out}) < len(out):
        # Takes from before they were numbered on across runs (several "Take 1"s):
        # renumber them once, in the order they were made, and their "from Take n" with them.
        new = {t["id"]: i + 1 for i, t in enumerate(out)}
        for t in out:
            t["n"] = new[t["id"]]
            if t.get("from") in new:
                t["fromN"] = new[t["from"]]
            (d / f"{t['id']}.json").write_text(json.dumps(t, indent=1))
    return out[::-1]


def new_id():
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]


class Job:
    """One run of takes, with what's happening as it happens: a log of lines
    for people, and each take's state and how much of it has arrived."""

    def __init__(self, reel_id, engine, n):
        self.id = uuid.uuid4().hex[:12]
        self.reel_id = reel_id
        self.engine = engine
        self.status = "running"
        self.started = time.time()
        self.finished = None
        self.error = None
        self.log = []
        self.takes = [{"n": i + 1, "label": "", "state": "waiting", "received": 0.0, "expected": 0.0,
                       "first": None, "error": None, "take": None} for i in range(n)]
        self.plan = None
        self.source = None   # the take being adapted or rebuilt, if any
        self.lock = threading.Lock()

    def say(self, text, kind="info"):
        with self.lock:
            self.log.append({"t": round(time.time() - self.started, 1), "text": text, "kind": kind})

    def view(self):
        with self.lock:
            return {"id": self.id, "reelId": self.reel_id, "engine": self.engine, "status": self.status, "source": self.source,
                    "elapsed": round((self.finished or time.time()) - self.started, 1), "error": self.error,
                    "log": list(self.log), "takes": [dict(t) for t in self.takes], "plan": self.plan}


def clock(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def run_job(job, ctx, home, lyria=None):
    """Make the takes: ctx = {beat, length, edges, style, seeds, labels,
    variations, prompt, reel_name}. lyria(text) -> audio bytes (OpenRouter)."""
    beat, length = ctx["beat"], ctx["length"]
    style = ctx["style"]
    try:
        secs = sections(beat, length, ctx["edges"])
        job.plan = {"sections": secs, "length": length, "tempo": style["tempo"], "key": style["key"]}
        job.say(f"Laid out {len(secs)} section{'s' if len(secs) != 1 else ''} on your energy curve: "
                + ", ".join(f"{s['name']} {clock(s['start'])}" for s in secs))
        if ctx.get("ref_line"):
            job.say(ctx["ref_line"])
        edited = bool(beat.get("prompt"))
        n = len(job.takes)
        who = "ElevenLabs (music_v2_5)" if job.engine == "elevenlabs" else "Lyria 3 Pro (OpenRouter)"
        job.say(f"Asking {who} for {n} take{'s' if n != 1 else ''}, {clock(length)} each, "
                f"at {style['tempo']} BPM in {style['key']}"
                + (". Your edited prompt goes as written, so the sections are a guide, not exact." if edited and job.engine == "elevenlabs" else "."))
        d = takes_dir(home, job.reel_id)
        d.mkdir(parents=True, exist_ok=True)

        def one(i):
            t = job.takes[i]
            label, variation, seed = ctx["labels"][i], ctx["variations"][i], ctx["seeds"][i]
            with job.lock:
                t.update(label=label, state="asking", expected=length)
            asked = time.time()
            job.say(f"Take {t['n']} · {label}: composing…")
            if job.engine == "elevenlabs":
                if edited:
                    body = {"model_id": ELEVEN_MODEL, "prompt": beat["prompt"], "music_length_ms": round(length * 1000),
                            "force_instrumental": True}
                else:
                    body = {"model_id": ELEVEN_MODEL, "seed": seed,
                            "composition_plan": composition_plan(beat, secs, style, variation)}

                def arrived(nbytes):
                    secs_in = nbytes * 8 / ELEVEN_BITRATE
                    with job.lock:
                        if t["first"] is None:
                            t["first"] = round(time.time() - asked, 1)
                            t["state"] = "receiving"
                            first = True
                        else:
                            first = False
                        t["received"] = round(min(secs_in, length), 2)
                    if first:
                        job.say(f"Take {t['n']}: the first notes are in after {t['first']:.0f}s")
                audio, song = eleven_stream(body, arrived)
            else:
                text = timestamped(beat.get("prompt") or ctx["prompt"], secs) + f"\nLean: {', '.join(variation)}."
                audio = lyria(text)
                song = ""
                body = {"prompt": text}
            with job.lock:
                t["state"] = "finishing"
                t["received"] = length
            tid = new_id()
            got = land(audio, d / f"{tid}.mp3", length, beat["end"], {
                "title": f"Beat · {ctx['reel_name']} · take {t['n']}", "artist": who,
                "genre": "AI", "comment": (beat.get("prompt") or ctx["prompt"])[:900]})
            diff = got - length
            job.say(f"Take {t['n']}: came back {clock(got)} long"
                    + (" — exactly the reel" if abs(diff) < 0.05 else
                       f", trimmed to land on the last frame at {clock(length)}" if diff > 0 else
                       f", {-diff:.1f}s short, so it's padded with silence to {clock(length)}"))
            meta = {"id": tid, "run": job.id, "n": t["n"], "label": label, "engine": job.engine,
                    "from": ctx.get("from"), "fromN": ctx.get("fromN"), "starred": False,
                    "model": ELEVEN_MODEL if job.engine == "elevenlabs" else "google/lyria-3-pro-preview",
                    "seed": seed if job.engine == "elevenlabs" and not edited else None, "variation": variation,
                    "length": length, "generated": round(got, 2), "tempo": style["tempo"], "key": style["key"],
                    "prompt": beat.get("prompt") or ctx["prompt"], "request": body, "sections": secs,
                    "beat": beat, "songId": song, "created": datetime.now().isoformat(timespec="seconds"),
                    "took": round(time.time() - asked, 1)}
            (d / f"{tid}.json").write_text(json.dumps(meta, indent=1))
            with job.lock:
                t.update(state="done", take=tid)
            return meta

        with ThreadPoolExecutor(max_workers=n) as pool:
            futures = [pool.submit(one, i) for i in range(n)]
            for i, f in enumerate(futures):
                try:
                    f.result()
                except Exception as e:   # one take failing doesn't sink the others
                    msg = str(e) if isinstance(e, BeatError) else f"{type(e).__name__}: {e}"
                    with job.lock:
                        job.takes[i].update(state="failed", error=msg)
                    job.say(f"Take {job.takes[i]['n']} didn't come: {msg}", "error")
        ok = sum(t["state"] == "done" for t in job.takes)
        if ok:
            job.say(f"Done in {time.time() - job.started:.0f}s: {ok} take{'s' if ok != 1 else ''} ready. "
                    "Play them below; Use in reel puts one on the reel.", "done")
            job.status = "done"
        else:
            job.status = "failed"
            job.error = job.takes[0]["error"] if job.takes else "Nothing came back."
    except Exception as e:
        job.status = "failed"
        job.error = str(e) if isinstance(e, BeatError) else f"{type(e).__name__}: {e}"
        job.say(job.error, "error")
    finally:
        job.finished = time.time()
