"""How loud a file is along its length, for the audio rows under a reel's
timeline: the mix strip (what will actually be heard) and a row per source
(A glasses, B glasses, music, voice).

Each file is measured once (ffmpeg decodes it to mono PCM, then the RMS of
every STEP-second window) and cached. Levels are dBFS (full scale = 0,
floored at FLOOR), not scaled per file, so a quiet glasses mic and a loud
song stay comparable: the browser maps each part's in/out and speed onto
these and sums the sources with the render's own gains (audioMix.js), without
running ffmpeg again.
"""
import hashlib
import json
import math
import subprocess
import uuid
from array import array

RATE = 8000          # samples a second to measure at: loudness, not fidelity
STEP = 0.04          # seconds per window (spec: 20-50ms)
FLOOR = -70          # dBFS: quieter than this is silence
VERSION = 1          # bump to re-measure everything


def has_audio(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                          "stream=index", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, timeout=60).stdout
    return bool(out.strip())


def measure(path):
    """{step, db: [dBFS per window], duration, hasAudio} for one file."""
    if not has_audio(path):
        return {"step": STEP, "db": [], "duration": 0.0, "hasAudio": False}
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-vn",
                          "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"],
                         capture_output=True, timeout=600).stdout
    samples = array("h")
    samples.frombytes(raw[: len(raw) // 2 * 2])
    n = round(RATE * STEP)
    db = []
    for i in range(0, len(samples), n):
        win = samples[i:i + n]
        if len(win) < n // 4 and db:
            break   # a sliver at the very end: not worth a window of its own
        power = sum(s * s for s in win) / (len(win) * 32768.0 * 32768.0)
        db.append(max(FLOOR, round(10 * math.log10(power), 1)) if power > 0 else FLOOR)
    return {"step": STEP, "db": db, "duration": round(len(samples) / RATE, 3), "hasAudio": True}


def envelope(path, cache_dir):
    """measure(path), once per version of the file."""
    st = path.stat()
    key = hashlib.sha1(f"envelope|{VERSION}|{path}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()
    out = cache_dir / f"{key}.json"
    if out.exists():
        try:
            return json.loads(out.read_text())
        except ValueError:
            pass   # a damaged cache file: measure again
    data = measure(path)
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f"{key}.{uuid.uuid4().hex}.tmp")   # never read half-written
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    tmp.replace(out)
    return data
