import random

import numpy as np
import pytest

from cupid.engine import Cupid, Pool, Stated
from cupid.item import Item
from cupid.simulate import PERSONAS, run_session, synthetic_pool
from cupid.tagging import derive_tags, tags_from_title


@pytest.fixture(scope="module")
def pool():
    return synthetic_pool(n=800, seed=1)


def make_item(item_id, tags, price=1200, emb=None):
    emb = emb if emb is not None else np.random.default_rng(hash(item_id) % 2**32).normal(size=16)
    return Item(id=item_id, title=f"test {item_id}", price=price, tags=derive_tags(tags, price),
                emb=(emb / np.linalg.norm(emb)).astype(np.float32))


def test_learning_beats_its_starting_point_and_a_random_feed(pool):
    persona = PERSONAS["two tastes"]   # no stated preferences, so it starts from zero
    gains, deck_vs_random = [], []
    # Six shoppers, not three: the engine's set ordering follows Python's per-run hash seed,
    # so a single run's margin wobbles; the average over six holds whatever the seed.
    for seed in range(6):
        cupid, result = run_session(persona, pool, swipes=100, seed=seed)
        gains.append(result["curve"][-1]["pick_right"] - result["curve"][0]["pick_right"])
        rand, _ = run_session(persona, pool, swipes=100, seed=seed, feed="random")
        deck_vs_random.append(np.mean([s.liked for s in cupid.log]) - np.mean([s.liked for s in rand.log]))
    assert np.mean(gains) > 0.08
    assert np.mean(deck_vs_random) > 0.1


def test_surprise_drives_learning():
    item = make_item("a", {"colour": "olive", "fit": "relaxed"})
    confident = Cupid(stated=Stated(likes=["colour:olive"]))
    unsure = Cupid()
    confident.swipe(item, "like")
    unsure.swipe(item, "like")
    assert unsure.w["fit:relaxed"] > confident.w["fit:relaxed"] > 0


def test_crush_counts_more_than_like():
    item = make_item("a", {"colour": "olive"})
    like, crush = Cupid(), Cupid()
    like.swipe(item, "like")
    crush.swipe(item, "crush")
    assert crush.w["colour:olive"] > like.w["colour:olive"]


def test_too_pricey_lifts_style_and_lowers_price():
    item = make_item("a", {"colour": "olive", "fabric": "linen"}, price=120)
    cupid = Cupid()
    cupid.swipe(item, "pricey")
    assert cupid.w["colour:olive"] > 0 and cupid.w["fabric:linen"] > 0
    assert cupid.w["price:90-150"] < 0


def test_long_look_nope_counts_less():
    item = make_item("a", {"colour": "red"})
    quick, tempted = Cupid(), Cupid()
    quick.swipe(item, "nope", dwell_ms=1500)
    tempted.swipe(item, "nope", dwell_ms=5000)
    assert quick.w["colour:red"] < tempted.w["colour:red"] < 0


def test_rewind_undoes_the_last_swipe():
    a, b = make_item("a", {"colour": "olive"}), make_item("b", {"colour": "red"})
    cupid = Cupid()
    cupid.swipe(a, "like")
    before = (dict(cupid.w), cupid.bias, cupid.n, len(cupid.mem_ids))
    cupid.swipe(b, "nope")
    assert cupid.rewind() == "b"
    assert (dict(cupid.w), cupid.bias, cupid.n, len(cupid.mem_ids)) == before
    assert cupid.rewind() is None   # only one step back


def test_hard_limits_are_never_dealt(pool):
    cupid = Cupid(stated=Stated(budget=1500, dealbreakers=["category:crop top"]), seed=0)
    seen = set()
    for _ in range(60):
        item, slot, pred = cupid.next_card(pool, seen)
        assert item.price <= 1500 and item.tags["category"] != "crop top"
        cupid.swipe(item, random.choice(["like", "nope"]), slot=slot, pred=pred)
        seen.add(item.id)


def test_warmup_covers_different_style_families(pool):
    from cupid.engine import WARMUP
    cupid, seen, vibes = Cupid(seed=0), set(), []
    for _ in range(WARMUP):
        item, slot, pred = cupid.next_card(pool, seen)
        assert slot == "warmup"
        vibes.append(item.tags["vibe"])
        cupid.swipe(item, "nope", slot=slot, pred=pred)
        seen.add(item.id)
    assert len(set(vibes)) == WARMUP


def test_flags_go_from_hunch_to_confident_and_always_include_a_real_con():
    liked = make_item("liked", {"colour": "olive", "fit": "relaxed", "pattern": "solid"})
    disliked = make_item("disliked", {"colour": "red", "fit": "fitted", "pattern": "floral"})
    candidate = make_item("new", {"colour": "olive", "fit": "relaxed", "pattern": "floral"})
    cupid = Cupid()

    for _ in range(6):
        cupid.swipe(liked, "like")
        cupid.swipe(disliked, "nope")
    green, red = cupid.flags(candidate, cupid.predict(candidate))
    assert any("Early sign" in g and "olive" in g for g in green)
    assert red, "a real con exists (floral), so a red flag must show"

    for _ in range(14):
        cupid.swipe(liked, "like")
        cupid.swipe(disliked, "nope")
    green, red = cupid.flags(candidate, cupid.predict(candidate))
    assert "You keep liking olive" in green
    assert any("floral prints" in r and "Early sign" not in r for r in red)


def test_similar_items_already_liked_is_a_red_flag():
    base = np.random.default_rng(0).normal(size=16)
    cupid = Cupid()
    for i in range(3):
        cupid.swipe(make_item(f"l{i}", {"colour": "olive"}, emb=base + 0.01 * i), "like")
    twin = make_item("twin", {"colour": "olive"}, emb=base + 0.005)
    _, red = cupid.flags(twin, cupid.predict(twin))
    assert any("already liked 3" in r for r in red)


def test_title_tagging():
    tags = derive_tags(tags_from_title("Women Olive Linen Straight Kurta Set with Palazzo"), 45)
    assert tags == {"colour": "olive", "tone": "earthy", "category": "kurta set", "group": "ethnic",
                    "fabric": "linen", "fit": "straight", "price": "40-60"}
    assert tags_from_title("Women's Button Down Shirt Dress")["category"] == "dress"
    assert tags_from_title("Oversized Graphic T-Shirt")["category"] == "t-shirt"
    # Real titles from the first catalogue run
    assert tags_from_title("Inoya Shirt Kurta with Handkerchief Hem")["category"] == "kurta"
    assert tags_from_title("Women's Indigo & Rust Floral Block Print Kurta")["colour"] == "navy"


def test_pool_runs_out_cleanly():
    items = [make_item(str(i), {"colour": "olive"}) for i in range(3)]
    pool, cupid, seen = Pool(items), Cupid(), set()
    for _ in range(3):
        item, _, _ = cupid.next_card(pool, seen)
        seen.add(item.id)
    assert cupid.next_card(pool, seen) is None


def test_a_deck_only_holds_what_was_asked_for():
    from cupid.api import Pick
    from cupid.amazon import LOOKING_FOR, answer_search, visible_colours
    dresses = Pick("dresses", "Dresses", answer_search("dresses", "everyday"), allows=LOOKING_FOR["dresses"]["allows"],
                   colours=visible_colours(["Black"]))
    assert dresses.fits(make_item("d", {"category": "maxi dress", "colour": "black"}))
    assert not dresses.fits(make_item("k", {"category": "kurta set", "colour": "black"})), \
        '"women dress" on amazon.in returns kurta sets'
    assert not dresses.fits(make_item("p", {"category": "dress", "colour": "pink"})), \
        "Amazon's colour filter matches any variant; the photo must show the colour asked for"
