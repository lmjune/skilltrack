import tempfile
from pathlib import Path

from core.config import Config, WatchCfg, MirrorRow


def test_roundtrip():
    c = Config()
    c.regions.status = [2880, 1230, 300, 550]
    c.watch(5).label = "마나실드"; c.watch(5).keep = True; c.watch(5).keep_delay = 5
    c.watch(2).alert_under = [30]; c.watch(2).alert_under_extended = [120, 60]
    c.overlays.mirror_rows = [MirrorRow(row=2), MirrorRow(row=5, time=False, only_active=True)]
    p = Path(tempfile.mktemp(suffix=".json"))
    c.save(p)
    d = Config.load(p)
    assert d.regions.status == [2880, 1230, 300, 550]
    assert d.watches[5].label == "마나실드" and d.watches[5].keep and d.watches[5].keep_delay == 5
    assert d.watches[2].alert_under == [30]
    assert [m.row for m in d.overlays.mirror_rows] == [2, 5] and d.overlays.mirror_rows[1].only_active
    assert d.watch_opts()[5]["label"] == "마나실드"
    assert d.watch_opts()[2]["label"] == "행2"


def test_missing_file_gives_defaults():
    c = Config.load(Path(tempfile.mktemp()))
    assert c.general.fps == 5 and c.regions.status is None and c.watches == {}


def test_disabled_watch_excluded():
    c = Config(); c.watch(3).enabled = False; c.watch(4)
    assert set(c.watch_opts()) == {4}