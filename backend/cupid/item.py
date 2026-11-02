from dataclasses import dataclass, field

import numpy as np

from .tagging import features


@dataclass
class Item:
    id: str
    title: str
    price: float | None
    tags: dict[str, str]
    emb: np.ndarray  # unit-length fingerprint from the vision model
    store: str = ""
    link: str = ""
    image: str = ""
    n_stores: int = 1          # listings merged into this one (same product, other sellers)
    brand: str = ""
    old_price: float | None = None
    rating: float | None = None
    reviews: int | None = None
    bought: str | None = None  # e.g. "5K+ bought last month"
    features: list[str] = field(init=False)

    def __post_init__(self):
        self.features = features(self.tags)
