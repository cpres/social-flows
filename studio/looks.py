"""
What's in a photo, for Smart hold (Weave and the reel page).

    people, animals  whether there are any in it, from macOS's own Vision
                     framework (through PyObjC, which run.sh installs on a
                     Mac). None when it can't tell: not a Mac, or PyObjC
                     isn't installed.
    look             a tiny version of the photo (8×8 grey, then 4×4 colour,
                     as base64) that the page compares to find look-alikes:
                     several shots of the same thing, taken together.
"""

import base64
import subprocess
import threading

try:
    import objc
    import Vision
    from Foundation import NSURL
except ImportError:   # not a Mac, or PyObjC isn't installed
    Vision = None

# Labels from Vision's scene classifier that mean someone or something alive
# is in the picture, not just a garden.
PEOPLE = {"people", "adult", "child", "baby", "teen", "crowd", "portrait", "selfie"}
ANIMALS = {"animal", "mammal", "bird", "insect", "reptile", "amphibian", "fish", "arachnid",
           "dog", "cat", "canine", "feline", "pet", "livestock", "poultry", "chicken", "duck",
           "goose", "bee", "butterfly", "caterpillar", "ladybug", "spider", "snail", "worm",
           "horse", "cattle", "sheep", "goat", "pig", "rabbit", "squirrel", "lizard", "frog"}
SURE = 0.5      # a face, person or pet the detectors found
LIKELY = 0.35   # a scene label

_one_at_a_time = threading.Lock()


def can_detect():
    return Vision is not None


def subjects(path):
    """{'people': bool, 'animals': bool}, or None if Vision can't say."""
    if Vision is None:
        return None
    with _one_at_a_time, objc.autorelease_pool():
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(
            NSURL.fileURLWithPath_(str(path)), {})
        requests = {name: getattr(Vision, kind).alloc().init()
                    for name, kind in (("faces", "VNDetectFaceRectanglesRequest"),
                                       ("bodies", "VNDetectHumanRectanglesRequest"),
                                       ("pets", "VNRecognizeAnimalsRequest"),
                                       ("scene", "VNClassifyImageRequest"))
                    if hasattr(Vision, kind)}   # an older macOS may lack one
        if hasattr(requests.get("bodies"), "setUpperBodyOnly_"):
            requests["bodies"].setUpperBodyOnly_(False)   # whole people, not just head and shoulders
        # One at a time, so one that fails can't sink the rest.
        found = {}
        for name, request in requests.items():
            ok, _ = handler.performRequests_error_([request], None)
            if ok:
                found[name] = list(request.results() or [])
        if not found:
            return None
        labels = {str(o.identifier()): o.confidence() for o in found.get("scene", [])}

        def sure(*names):
            return any(o.confidence() >= SURE for n in names for o in found.get(n, []))

        def likely(names):
            return any(labels.get(n, 0) >= LIKELY for n in names)

        return {"people": sure("faces", "bodies") or likely(PEOPLE),
                "animals": sure("pets") or likely(ANIMALS)}


def look(thumb):
    """The photo at 8×8 in grey and 4×4 in colour (176 bytes, base64), made
    from its thumbnail. None if ffmpeg can't read it."""
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(thumb),
                          "-vf", "scale=16:16:flags=area", "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, timeout=30).stdout
    if len(raw) != 16 * 16 * 3:
        return None
    px = [raw[i:i + 3] for i in range(0, len(raw), 3)]

    def block(x, y, size):   # mean colour of a size×size block of the 16×16
        cells = [px[(y * size + j) * 16 + x * size + i] for j in range(size) for i in range(size)]
        return [sum(c[k] for c in cells) / len(cells) for k in range(3)]

    grey = [round(0.299 * r + 0.587 * g + 0.114 * b)
            for r, g, b in (block(x, y, 2) for y in range(8) for x in range(8))]
    colour = [round(v) for y in range(4) for x in range(4) for v in block(x, y, 4)]
    return base64.b64encode(bytes(grey + colour)).decode()
