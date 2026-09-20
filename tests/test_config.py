import tempfile
from pathlib import Path

from core.config import Config, MirrorRow


def test_profiles_roundtrip():
    c = Config()
    a = c.add_profile("본캐"); b = c.add_profile("부캐")
    c.profiles[a].regions.status = [2880, 1230, 300, 550]
    c.profiles[a].watches[5] = c.profiles[a].watches.get(5) or __import__("core.config", fromlist=["WatchCfg"]).WatchCfg(label="마나실드", keep=True)
    c.profiles[a].mirror_rows = [MirrorRow(row=5, time=False)]
    c.current = b
    p = Path(tempfile.mktemp(suffix=".json")); c.save(p)
    d = Config.load(p)
    assert set(d.profiles) == {a, b} and d.current == b
    assert d.profiles[a].regions.status == [2880, 1230, 300, 550]
    assert d.profiles[a].watches[5].label == "마나실드" and d.profiles[a].mirror_rows[0].row == 5
    assert d.profiles[a].watch_opts()[5]["keep"] is True
    d.remove_profile(b); assert d.current == a


def test_legacy_migration():
    p = Path(tempfile.mktemp(suffix=".json"))
    p.write_text('{"regions": {"status": [1,2,3,4]}, "watches": {"3": {"label": "x"}}, "overlays": {"mirror_rows": [{"row": 3}]}}', encoding="utf-8")
    c = Config.load(p)
    pr = c.profile()
    assert pr and pr.regions.status == [1, 2, 3, 4] and pr.watches[3].label == "x" and pr.mirror_rows[0].row == 3


def test_missing_file():
    c = Config.load(Path(tempfile.mktemp()))
    assert c.profiles == {} and c.profile() is None