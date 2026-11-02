import pytest

from cupid import catalogue, db
from cupid.amazon import AmazonSearch


@pytest.fixture
def conn(tmp_path, monkeypatch):
    def no_real_calls(search):
        raise AssertionError("tests must never call SerpAPI")
    monkeypatch.setattr(catalogue.amazon, "run", no_real_calls)
    monkeypatch.setattr(catalogue, "SERPAPI_DAILY_LIMIT", 2)
    return db.connect(tmp_path / "test.db")


def test_cached_searches_are_free_even_over_budget(conn):
    s = AmazonSearch(k="women kurta")
    db.save_search(conn, s.key(), {"organic_results": []}, 0)
    db.record_call(conn, "a")
    db.record_call(conn, "b")
    offers, _, cached = catalogue.search(conn, s)
    assert cached and offers == []
    assert db.calls_last_24h(conn) == 2


def test_new_searches_stop_at_the_daily_cap(conn):
    db.record_call(conn, "a")
    db.record_call(conn, "b")
    with pytest.raises(catalogue.BudgetError):
        catalogue.search(conn, AmazonSearch(k="women saree"))
    assert db.calls_last_24h(conn) == 2


def test_ingest_stops_instead_of_retrying_every_search(conn):
    db.record_call(conn, "a")
    db.record_call(conn, "b")
    logs = []
    searches = [AmazonSearch(k=k) for k in ("women dress", "women top", "women shirt")]
    report = catalogue.ingest(conn, searches, encoder=None, log=logs.append)
    assert report.searches_run == 0
    assert sum("budget" in line for line in logs) == 1
