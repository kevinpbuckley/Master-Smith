"""OpenRouter image generation (POST /api/v1/images): a picture from a prompt, or from a prompt plus reference
pictures (the edit case). Every successful call is appended to `calls` with OpenRouter's reported usage.cost so
the pipeline can settle the bill; the price table only reserves."""
import base64
import io
import json
import os
import time

import requests
from PIL import Image

from . import config
from .pricing import image_price

URL = "https://openrouter.ai/api/v1/images"
REFUSAL_WORDS = ("safety", "moderat", "policy", "block", "refus", "prohibited", "violat", "not allowed", "flagged", "could not generate")


class ImageError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class ImageRefused(ImageError):
    """The provider's content checker declined the prompt or the reference picture."""


def data_url(path):
    low = str(path).lower()
    mime = "image/png" if low.endswith(".png") else "image/webp" if low.endswith(".webp") else "image/jpeg"
    with open(path, "rb") as f:
        return "data:%s;base64,%s" % (mime, base64.b64encode(f.read()).decode())


def reference_url(ref):
    """A local path becomes a data URL; an http(s) URL is passed through."""
    if isinstance(ref, str) and ref.startswith(("http://", "https://", "data:")):
        return ref
    return data_url(ref)


def refused(status, text):
    return status in (400, 403, 422) and any(w in (text or "").lower() for w in REFUSAL_WORDS)


class Images:
    def __init__(self, key=None, log=print):
        self.key = key or os.environ.get("OPENROUTER_API_KEY", "")
        if not self.key:
            raise ImageError("OPENROUTER_API_KEY is not set (put it in .env)")
        self.log = log
        self.http = requests.Session()
        self.calls = []
        self.stage = ""                  # the pipeline names the stage; every call carries it for the cost breakdown

    def _headers(self):
        return {"Authorization": "Bearer " + self.key, "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/kevinpbuckley/Master-Smith", "X-Title": "Master Smith"}

    def generate(self, prompt, path, model=None, references=(), aspect_ratio="4:3", resolution=None, timeout=300):
        """One PNG at `path`. `references`: local paths or URLs the picture must follow (an edit)."""
        model = model or config.CONCEPT_MODEL
        reserve = image_price(model)                  # refuses unpriced models before any money moves
        body = {"model": model, "prompt": prompt, "n": 1, "aspect_ratio": aspect_ratio,
                "resolution": resolution or config.IMAGE_RESOLUTION, "output_format": "png"}
        refs = [r for r in (references or []) if r]
        if refs:
            body["input_references"] = [{"type": "image_url", "image_url": {"url": reference_url(r)}} for r in refs[:4]]
        t0 = time.time()
        r = None
        for attempt in range(3):
            try:
                r = self.http.post(URL, headers=self._headers(), data=json.dumps(body), timeout=timeout)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt == 2:
                    raise ImageError("openrouter images unreachable: %s" % str(exc)[:200])
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            break
        if r.status_code != 200:
            text = r.text[:400]
            if refused(r.status_code, text):
                raise ImageRefused("%s refused the request: %s" % (model, text), r.status_code)
            raise ImageError("openrouter images %s: HTTP %d %s" % (model, r.status_code, text), r.status_code)
        data = r.json()
        if data.get("error"):
            text = str(data["error"])[:400]
            if any(w in text.lower() for w in REFUSAL_WORDS):
                raise ImageRefused("%s refused the request: %s" % (model, text), 422)
            raise ImageError("openrouter images %s: %s" % (model, text))
        items = data.get("data") or []
        b64 = items[0].get("b64_json") if items and isinstance(items[0], dict) else None
        if not b64:
            # an empty answer with no error is how some providers report a content refusal
            raise ImageRefused("%s returned no picture (content checker?)" % model, 422)
        raw = base64.b64decode(b64)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        im = Image.open(io.BytesIO(raw))
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        im.save(path)
        usage = data.get("usage") or {}
        usd = float(usage.get("cost") or 0.0) or reserve
        secs = round(time.time() - t0, 1)
        if usd > 4 * reserve:
            # one tile of four cost $0.67 against a $0.08 reserve (2026-09-18): the provider route matters; say so
            self.log("  WARNING: %s charged $%.3f for one picture (reserve $%.2f); check the provider routing" % (model, usd, reserve))
        self.calls.append({"model": model, "seconds": secs, "usd": usd, "references": len(refs), "stage": self.stage})
        self.log("  image %s: %.0fs, $%.3f%s" % (
            model, secs, usd, (" (%d reference%s)" % (len(refs), "" if len(refs) == 1 else "s")) if refs else ""))
        return path

    def spent(self):
        return round(sum(c["usd"] for c in self.calls), 6)
