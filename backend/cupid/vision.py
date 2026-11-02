"""Fingerprints and zero-shot tags from Marqo-FashionSigLIP."""

import os

import numpy as np

from .config import MODEL_NAME
from .tagging import ZERO_SHOT_PROMPTS, ZERO_SHOT_VALUES


class FashionEncoder:
    def __init__(self, model_name: str = MODEL_NAME):
        import open_clip
        import torch

        self.torch = torch
        self.device = os.getenv("CUPID_DEVICE") or ("mps" if torch.backends.mps.is_available() else "cpu")
        model, _, preprocess = open_clip.create_model_and_transforms(model_name)
        self.model = model.to(self.device).eval()
        self.preprocess = preprocess
        self.tokenizer = open_clip.get_tokenizer(model_name)
        self._labels: dict[str, np.ndarray] = {}

    def encode_images(self, images) -> np.ndarray:
        batch = self.torch.stack([self.preprocess(img.convert("RGB")) for img in images]).to(self.device)
        with self.torch.no_grad():
            feats = self.model.encode_image(batch, normalize=True)
        return feats.float().cpu().numpy()

    def encode_texts(self, texts: list[str]) -> np.ndarray:
        tokens = self.tokenizer(texts).to(self.device)
        with self.torch.no_grad():
            feats = self.model.encode_text(tokens, normalize=True)
        return feats.float().cpu().numpy()

    def zero_shot(self, embs: np.ndarray) -> list[dict[str, tuple[str, float]]]:
        """For each image, the closest label per attribute and its confidence."""
        out = [{} for _ in range(len(embs))]
        for key, values in ZERO_SHOT_VALUES.items():
            if key not in self._labels:
                self._labels[key] = self.encode_texts([ZERO_SHOT_PROMPTS[key](v) for v in values])
            logits = 100.0 * embs @ self._labels[key].T
            probs = np.exp(logits - logits.max(axis=1, keepdims=True))
            probs /= probs.sum(axis=1, keepdims=True)
            for i, row in enumerate(probs):
                j = int(row.argmax())
                out[i][key] = (values[j], float(row[j]))
        return out
