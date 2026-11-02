"""YouCam API (Perfect Corp): Skin Tone Analysis and Clothes Virtual Try-On.

Every task is: upload images through the File API → start a task → poll it. Try-on
results are cached per (photo, garment), so the same super like never costs twice.
"""

import time
from pathlib import Path

import httpx

from .config import DATA_DIR, YOUCAM_API_KEY

BASE = "https://yce-api-01.makeupar.com"
POLL_EVERY = 1.5     # seconds
TIMEOUT = 120        # seconds a task may take before we give up
TRYON_DIR = DATA_DIR / "tryon"
TRYON_TASK = "cloth-v4"
SKIN_TONE_TASK = "skin-tone-analysis"


class YouCamError(RuntimeError):
    pass


def _client() -> httpx.Client:
    if not YOUCAM_API_KEY:
        raise YouCamError("YOUCAM_API_KEY is not set. Add it to backend/.env.")
    return httpx.Client(base_url=BASE, timeout=60, headers={"Authorization": f"Bearer {YOUCAM_API_KEY}"})


def _find(obj, key):
    """First value for `key` anywhere in a JSON response (the docs show slightly different nestings)."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        obj = list(obj.values())
    if isinstance(obj, list):
        for v in obj:
            found = _find(v, key)
            if found is not None:
                return found
    return None


def _check(resp: httpx.Response) -> dict:
    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code != 200 or data.get("error"):
        raise YouCamError(f"YouCam {resp.request.url.path}: HTTP {resp.status_code} {data.get('error_code') or data.get('error') or ''}")
    return data


def upload(path: Path) -> str:
    """Upload an image through the File API. Returns its file_id."""
    content = path.read_bytes()
    ctype = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    with _client() as c:
        data = _check(c.post("/s2s/v2.0/file", json={
            "files": [{"content_type": ctype, "file_name": path.name, "file_size": len(content)}]}))
    file_id, request = _find(data, "file_id"), (_find(data, "requests") or [{}])
    request = request[0] if isinstance(request, list) else request
    url = request.get("url")
    if not file_id or not url:
        raise YouCamError("File API response had no file_id or upload URL")
    headers = {**(request.get("headers") or {}), "Content-Type": ctype, "Content-Length": str(len(content))}
    put = httpx.put(url, content=content, headers=headers, timeout=60)
    if put.status_code not in (200, 201, 204):
        raise YouCamError(f"Image upload failed: HTTP {put.status_code}")
    return file_id


def run(task: str, payload: dict) -> dict:
    """Start a task and poll it until it finishes. Returns the task's data."""
    with _client() as c:
        task_id = _find(_check(c.post(f"/s2s/v2.0/task/{task}", json=payload)), "task_id")
        if not task_id:
            raise YouCamError(f"{task}: no task_id in response")
        deadline = time.time() + TIMEOUT
        while time.time() < deadline:
            data = _check(c.get(f"/s2s/v2.0/task/{task}/{task_id}"))
            status = _find(data, "task_status")
            if status == "success":
                return data
            if status in ("error", "failed"):
                raise YouCamError(f"{task}: {_find(data, 'error') or 'failed'}")
            time.sleep(POLL_EVERY)
    raise YouCamError(f"{task}: timed out after {TIMEOUT}s")


def skin_tone(photo_file_id: str) -> dict[str, str]:
    """Colours of the shopper's skin, eyes, lips, hair and eyebrows (hex), from one photo."""
    # Phone photos are rarely dead straight; the default ("high") rejects a slightly turned head.
    data = run(SKIN_TONE_TASK, {"src_file_id": photo_file_id, "face_angle_strictness_level": "low"})
    keys = ("skin_color", "eye_color", "lip_color", "hair_color", "eyebrow_color", "eye_color_name", "hair_color_name")
    return {k: v for k in keys if (v := _find(data, k))}


def try_on(photo_file_id: str, garment: Path, out: Path) -> Path:
    """Render the shopper wearing the garment. Cached on disk per (photo, garment)."""
    if out.exists():
        return out
    garment_id = upload(garment)
    data = run(TRYON_TASK, {"src_file_id": photo_file_id, "ref_file_id": garment_id, "garment_category": "full_body"})
    url = _find(data, "url")
    if not url:
        raise YouCamError("Try-on finished but returned no image")
    image = httpx.get(url, timeout=60)
    image.raise_for_status()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(image.content)
    return out
