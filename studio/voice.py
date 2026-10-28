"""
Voice takes: recordings of a reading (audio files, or the sound of videos) in
the shoot folders, and what's said in them.

A take's sound is pulled out once into ~/.cache/footage-studio/voice/, for the
browser to play and for transcribing. Transcripts come from faster-whisper
(installed with ./studio/run.sh --voice): it runs once per take in the
background, and every word with its start and end is cached as JSON under
~/Footage/.studio/voice/. Lines for the captions are made from those words.
"""

import difflib
import hashlib
import json
import os
import re
import subprocess
import threading
from array import array
from pathlib import Path

MODEL = os.environ.get("VOICE_MODEL", "large-v3-turbo")
PEAK_RATE = 50          # waveform points per second
LINE_CHARS = 42         # a caption line longer than this breaks at the next word
LINE_PAUSE = 0.35       # a pause this long ends a line
STANZA_PAUSE = 1.2      # ... and this long (or a sentence end and 0.7s) starts a stanza


def transcription_available():
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


class Voice:
    def __init__(self, cache_dir, transcript_dir):
        self.cache_dir = Path(cache_dir)
        self.transcript_dir = Path(transcript_dir)
        self._guard = threading.Lock()
        self._locks = {}
        self._jobs = {}      # key -> {status, progress, error}
        self._model = None
        self._model_lock = threading.Lock()
        self._durations = {}

    # ------------------------------------------------------------ files

    @staticmethod
    def key(path):
        st = path.stat()
        return hashlib.sha1(f"{path.resolve()}|{st.st_size}|{st.st_mtime}".encode()).hexdigest()[:16]

    def _lock(self, key):
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def audio(self, path):
        """The take's sound as a small mono M4A (made once)."""
        key = self.key(path)
        out = self.cache_dir / f"{path.stem[:40]}-{key}.m4a"
        with self._lock(f"audio-{key}"):
            if not out.exists():
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                tmp = out.with_suffix(".part.m4a")
                result = subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(path), "-vn",
                                         "-map", "0:a:0", "-ac", "1", "-ar", "48000", "-c:a", "aac", "-b:a", "96k",
                                         str(tmp)], capture_output=True, text=True)
                if result.returncode != 0:
                    tmp.unlink(missing_ok=True)
                    raise ValueError(f"No sound in {path.name}")
                tmp.rename(out)
        return out

    def duration(self, path):
        st = path.stat()
        key = (str(path), st.st_size, st.st_mtime)
        if key not in self._durations:
            out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                  "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout
            try:
                self._durations[key] = round(float(out.strip()), 3)
            except ValueError:
                self._durations[key] = 0.0
        return self._durations[key]

    def peaks(self, path):
        """How loud the take is along its length: {rate, peaks: [0..1]}."""
        key = self.key(path)
        out = self.cache_dir / f"{path.stem[:40]}-{key}.peaks.json"
        if out.exists():
            return json.loads(out.read_text())
        raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(self.audio(path)),
                              "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True).stdout
        samples = array("h")
        samples.frombytes(raw[: len(raw) // 2 * 2])
        step = 8000 // PEAK_RATE
        peaks = [round(max(map(abs, samples[i:i + step]), default=0) / 32768, 3)
                 for i in range(0, len(samples), step)]
        data = {"rate": PEAK_RATE, "peaks": peaks}
        out.write_text(json.dumps(data))
        return data

    # ------------------------------------------------------------ transcripts

    def transcript_file(self, path):
        return self.transcript_dir / f"{path.stem[:40]}-{self.key(path)}.json"

    def transcript(self, path):
        f = self.transcript_file(path)
        return json.loads(f.read_text()) if f.exists() else None

    def status(self, path):
        """{status: done | running | failed | none, progress 0..1, error}"""
        if self.transcript_file(path).exists():
            return {"status": "done", "progress": 1.0}
        job = self._jobs.get(self.key(path))
        return dict(job) if job else {"status": "none", "progress": 0.0}

    def start(self, path):
        """Transcribe the take in the background (once)."""
        key = self.key(path)
        with self._guard:
            job = self._jobs.get(key)
            if self.transcript_file(path).exists() or (job and job["status"] == "running"):
                return self.status(path)
            self._jobs[key] = {"status": "running", "progress": 0.0, "stage": "starting"}
        threading.Thread(target=self._run, args=(path, key), daemon=True).start()
        return self.status(path)

    def _load_model(self, job):
        with self._model_lock:
            if self._model is None:
                job["stage"] = "loading"   # the first time, this downloads the model (~1.6 GB)
                from faster_whisper import WhisperModel
                self._model = WhisperModel(MODEL, device="cpu", compute_type="int8",
                                           cpu_threads=os.cpu_count() or 4)
            return self._model

    def _run(self, path, key):
        job = self._jobs[key]
        try:
            audio = self.audio(path)
            model = self._load_model(job)
            job["stage"] = "listening"
            segments, info = model.transcribe(str(audio), word_timestamps=True, vad_filter=True,
                                              beam_size=5)
            words = []
            for seg in segments:
                for w in seg.words or []:
                    text = w.word.strip()
                    if text:
                        words.append({"w": text, "s": round(w.start, 3), "e": round(w.end, 3)})
                job["progress"] = min(0.99, seg.end / (info.duration or 1))
            data = {"words": words, "language": info.language, "duration": round(info.duration, 3),
                    "model": MODEL}
            self.transcript_dir.mkdir(parents=True, exist_ok=True)
            self.transcript_file(path).write_text(json.dumps(data))
            job.update(status="done", progress=1.0)
        except Exception as e:  # shown in the studio; the take can be tried again
            job.update(status="failed", error=f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------- lines

def line_of(words, stanza):
    return {"s": words[0]["s"], "e": words[-1]["e"], "text": " ".join(w["w"] for w in words),
            "br": stanza, "words": [[w["w"], w["s"], w["e"]] for w in words]}


def lines_from_words(words):
    """Caption lines from a transcript's words: a new line at a pause, after
    a full stop, after a comma (once a line has a few words), or when it gets long;
    a new stanza at a longer pause or a sentence end and a breath."""
    lines, cur, stanza, prev = [], [], True, None
    for w in words:
        if cur:
            gap = w["s"] - prev["e"]
            end = prev["w"][-1:]
            long = len(" ".join(x["w"] for x in cur)) + 1 + len(w["w"]) > LINE_CHARS
            if gap >= LINE_PAUSE or end in ".?!" or (end in ",;:—–" and len(cur) >= 3) or long:
                lines.append(line_of(cur, stanza))
                stanza = gap >= STANZA_PAUSE or (end in ".?!" and gap >= 0.7)
                cur = []
        cur.append(w)
        prev = w
    if cur:
        lines.append(line_of(cur, stanza))
    return lines


def norm(word):
    return re.sub(r"[^\w']", "", word.lower())


def align(words, text, start, end):
    """Time a written text (pasted, a line per caption line, a blank line
    between stanzas) to what was said: each of its words is matched to the
    transcript's, so the lines keep their exact wording and breaks. Lines with
    no match share the time between their neighbours."""
    rows, stanza = [], True
    for raw in text.splitlines():
        if not raw.strip():
            stanza = True
            continue
        rows.append({"text": " ".join(raw.split()), "br": stanza})
        stanza = False
    if not rows:
        return []
    tokens = [(i, t) for i, r in enumerate(rows) for t in r["text"].split()]
    sm = difflib.SequenceMatcher(a=[norm(w["w"]) for w in words], b=[norm(t) for _, t in tokens],
                                 autojunk=False)
    match = {}
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            match[blk.b + k] = blk.a + k
    for i, r in enumerate(rows):
        hits = [match[j] for j, (li, _) in enumerate(tokens) if li == i and j in match]
        r["s"], r["e"] = (words[min(hits)]["s"], words[max(hits)]["e"]) if hits else (None, None)
        r["words"] = [[words[k]["w"], words[k]["s"], words[k]["e"]] for k in range(min(hits), max(hits) + 1)] if hits else []
    # Unmatched lines: spread over the gap between the matched ones, by length.
    i = 0
    while i < len(rows):
        if rows[i]["s"] is not None:
            i += 1
            continue
        j = i
        while j < len(rows) and rows[j]["s"] is None:
            j += 1
        lo = rows[i - 1]["e"] if i > 0 else start
        hi = rows[j]["s"] if j < len(rows) else end
        chars = [len(r["text"]) + 4 for r in rows[i:j]]
        t, per = lo, max(hi - lo, 0.1 * (j - i)) / sum(chars)
        for r, c in zip(rows[i:j], chars):
            r["s"], r["e"] = round(t, 3), round(t + c * per * 0.9, 3)
            t += c * per
        i = j
    # Keep them in order and from overlapping.
    for a, b in zip(rows, rows[1:]):
        if b["s"] < a["e"]:
            b["s"] = a["e"]
            b["e"] = max(b["e"], b["s"] + 0.2)
    return rows
