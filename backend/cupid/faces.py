"""Find the face in a full-length photo, for Skin Tone Analysis.

Try-on needs the whole body; Skin Tone Analysis needs the face to fill most of the
frame (over 60% of its width, at least 320 px). So from one photo we crop a face
close-up for the colour reading and keep the full photo for try-ons.
"""

from pathlib import Path

import cv2

FACE_SHARE = 0.72   # the face's share of the crop's width (YouCam asks for over 60%)
MIN_SIDE = 512      # px; upscale small crops past YouCam's 320 px minimum

_detector = None


def _faces():
    global _detector
    if _detector is None:
        _detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    return _detector


def face_crop(photo: Path, out: Path) -> Path | None:
    """Save a face close-up from the photo. Returns its path, or None if no face is visible."""
    img = cv2.imread(str(photo))
    if img is None:
        return None
    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    found = _faces().detectMultiScale(grey, scaleFactor=1.1, minNeighbors=6, minSize=(40, 40))
    if len(found) == 0:
        return None
    x, y, w, h = max(found, key=lambda f: f[2] * f[3])   # the biggest face is the shopper
    side = int(w / FACE_SHARE)
    cx, cy = x + w // 2, y + h // 2
    left, top = max(0, cx - side // 2), max(0, cy - side // 2)
    crop = img[top:min(img.shape[0], top + side), left:min(img.shape[1], left + side)]
    short = min(crop.shape[:2])
    if short < MIN_SIDE:
        scale = MIN_SIDE / short
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    cv2.imwrite(str(out), crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return out
