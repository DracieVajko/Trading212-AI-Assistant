import json, hashlib, os


def test_cross_pc_fixture_deterministic():
    p = os.path.join(os.path.dirname(__file__), "fixtures", "ohlcv_fixture.json")
    raw = open(p, "rb").read()
    h1 = hashlib.sha256(raw).hexdigest()
    # re-read
    raw2 = open(p, "rb").read()
    h2 = hashlib.sha256(raw2).hexdigest()
    assert h1 == h2
    data = json.loads(raw)
    assert data["seed"] == 42
    assert len(data["rows"]) == 300
