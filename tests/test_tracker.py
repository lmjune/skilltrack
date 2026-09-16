"""추적기 시나리오 테스트. 화면 없이 RowState를 가짜로 만들어 돌린다."""
import numpy as np

from core.status import RowState
from core.tracker import Tracker, Watch

FP_A = bytes([0xAA] * 64)
FP_B = bytes([0x55] * 64)


def row(fp, active=True, index=0, width=40):
    return RowState(index=index, name_fp=fp, icon_fp=b"", active=active, has_time=False, red=False,
                    name_img=np.zeros((1, 1, 3), np.uint8), time_img=None, name_range=(0, width - 1))


def run(tracker, frames, secs=None):
    out = []
    for i, rows in enumerate(frames):
        s = secs[i] if secs else {}
        out += [(e.kind, e.value) for e in tracker.update(rows, s, now=i * 0.1)]
    return out


def test_off_requires_debounce():
    t = Tracker([Watch(FP_A, "A")], debounce=3)
    frames = [[row(FP_A, True)]] * 3 + [[row(FP_A, False)]] * 2 + [[row(FP_A, True)]] * 3
    assert run(t, frames) == []
    assert run(t, [[row(FP_A, False)]] * 3) == [("off", None)]


def test_first_state_is_not_an_event():
    t = Tracker([Watch(FP_A, "A")], debounce=3)
    assert run(t, [[row(FP_A, False)]] * 5) == []


def test_unknown_frames_are_ignored():
    t = Tracker([Watch(FP_A, "A")], debounce=3)
    frames = [[row(FP_A, True)]] * 3 + [[row(FP_A, None)]] * 10 + [[row(FP_A, True)]]
    assert run(t, frames) == []


def test_under_thresholds_fire_once_each():
    t = Tracker([Watch(FP_A, "A", alert_under=[60, 30])], debounce=1)
    secs = [{0: s} for s in (120, 90, 59, 58, 40, 29, 28, 5)]
    assert run(t, [[row(FP_A, True)]] * len(secs), secs) == [("under", 60), ("under", 30)]


def test_under_resets_when_reactivated():
    t = Tracker([Watch(FP_A, "A", alert_under=[60], alert_off=False, cooldown=0)], debounce=1)
    frames = [[row(FP_A, True)], [row(FP_A, False)], [row(FP_A, True)]]
    assert run(t, frames, [{0: 50}, {}, {0: 50}]) == [("under", 60), ("under", 60)]


def test_follows_row_by_fingerprint_not_index():
    t = Tracker([Watch(FP_A, "A")], debounce=1)
    frames = [[row(FP_B, True, 0), row(FP_A, True, 1)], [row(FP_A, False, 0), row(FP_B, True, 1)]]
    assert run(t, frames) == [("off", None)]


def test_lost_and_found():
    t = Tracker([Watch(FP_A, "A")], debounce=1, missing_limit=3)
    assert run(t, [[row(FP_A)]] + [[]] * 3 + [[row(FP_A)]]) == [("lost", None), ("found", None)]


def test_extension_switches_thresholds():
    """전장의 서곡: 기본 30초 미만 알림. 연장(이름이 길어짐)되면 120/60초 미만 알림."""
    w = Watch(FP_A, "서곡", alert_under=[30], base_width=40, alert_under_extended=[120, 60], cooldown=0)
    t = Tracker([w], debounce=1)
    frames = [[row(FP_A, width=40)]] * 3 + [[row(FP_A, width=90)]] * 5
    secs = [{0: 40}, {0: 25}, {0: 20},            # 기본: 30 미만 1회
            {0: 500}, {0: 119}, {0: 100}, {0: 59}, {0: 10}]   # 연장 후: 120, 60
    assert run(t, frames, secs) == [("under", 30), ("extended", None), ("resync", 500), ("under", 120), ("under", 60)]


def test_extension_end_returns_to_base():
    w = Watch(FP_A, "서곡", alert_under=[30], base_width=40, alert_under_extended=[120], cooldown=0)
    t = Tracker([w], debounce=1)
    frames = [[row(FP_A, width=40)], [row(FP_A, width=90)], [row(FP_A, width=90)], [row(FP_A, width=40)], [row(FP_A, width=40)]]
    secs = [{0: 100}, {0: 300}, {0: 100}, {0: 100}, {0: 20}]
    assert run(t, frames, secs) == [("extended", None), ("resync", 300), ("under", 120), ("unextended", None), ("under", 30)]


def test_timer_keeps_running_when_unreadable():
    """읽힌 뒤 인식이 끊겨도 추정값으로 임계값 알림이 나간다."""
    t = Tracker([Watch(FP_A, "A", alert_under=[30], cooldown=0)], debounce=1)
    out = []
    out += t.update([row(FP_A, True)], {0: 40}, now=0.0)       # 40초 읽음
    for k in range(1, 30):
        out += t.update([row(FP_A, True)], {}, now=float(k))   # 못 읽음, 시간은 흐름
    assert [(e.kind, e.value) for e in out] == [("under", 30)]
    assert t.tracks[0].estimate(now=29.0) == 11


def test_resync_when_buff_refreshed():
    t = Tracker([Watch(FP_A, "A", alert_under=[30], cooldown=0)], debounce=1)
    out = []
    out += t.update([row(FP_A, True)], {0: 20}, now=0.0)       # 20초 → 30 미만 알림
    out += t.update([row(FP_A, True)], {0: 300}, now=1.0)      # 갱신됨 → 재동기화, 임계값 초기화
    for k in range(2, 290):
        out += t.update([row(FP_A, True)], {}, now=float(k))   # 인식 없이 흐름
    kinds = [(e.kind, e.value) for e in out]
    assert kinds == [("under", 30), ("resync", 300), ("under", 30)]


def test_timer_cleared_when_inactive():
    t = Tracker([Watch(FP_A, "A", alert_under=[30], cooldown=0)], debounce=1)
    t.update([row(FP_A, True)], {0: 100}, now=0.0)
    t.update([row(FP_A, False)], {}, now=1.0)
    assert t.tracks[0].estimate(now=2.0) is None


def test_extension_ignored_when_inactive():
    w = Watch(FP_A, "A", base_width=40, alert_under_extended=[120], cooldown=0)
    t = Tracker([w], debounce=1)
    frames = [[row(FP_A, True, width=40)]] + [[row(FP_A, False, width=160)]] * 5
    assert [k for k, _ in run(t, frames)] == ["off"]


def test_base_width_lowers_if_calibrated_while_extended():
    w = Watch(FP_A, "A", base_width=90, alert_under_extended=[120], cooldown=0)
    t = Tracker([w], debounce=1)
    run(t, [[row(FP_A, True, width=40)]] * 3)
    assert w.base_width == 40
    assert [k for k, _ in run(t, [[row(FP_A, True, width=90)]] * 2)] == ["extended"]


def test_keep_nags_while_off_after_delay():
    """유지 필수: 꺼진 지 10초 지나면 30초마다. 다시 켜지면 멈춤."""
    w = Watch(FP_A, "A", alert_off=False, keep=True, keep_delay=10, keep_interval=30)
    t = Tracker([w], debounce=1)
    out = []
    out += t.update([row(FP_A, True)], {}, now=0.0)
    for k in range(1, 100):                       # 99초 동안 꺼짐
        out += t.update([row(FP_A, False)], {}, now=float(k))
    assert [e.at for e in out if e.kind == "keep"] == [11.0, 41.0, 71.0]   # 꺼짐 확정이 t=1
    out2 = t.update([row(FP_A, True)], {}, now=100.0)
    for k in range(101, 200):
        out2 += t.update([row(FP_A, True)], {}, now=float(k))
    assert not any(e.kind == "keep" for e in out2)


def test_keep_ignores_brief_off():
    w = Watch(FP_A, "A", alert_off=False, keep=True, keep_delay=10)
    t = Tracker([w], debounce=1)
    out = t.update([row(FP_A, True)], {}, now=0.0)
    for k in range(1, 8):
        out += t.update([row(FP_A, False)], {}, now=float(k))   # 7초만 꺼짐
    out += t.update([row(FP_A, True)], {}, now=8.0)
    assert not any(e.kind == "keep" for e in out)


def test_keep_starts_from_initial_off():
    """프로그램 켰을 때 이미 꺼져 있어도 (첫 확정) 유지 필수는 잔소리한다."""
    w = Watch(FP_A, "A", keep=True, keep_delay=5, keep_interval=100)
    t = Tracker([w], debounce=1)
    out = []
    for k in range(0, 10):
        out += t.update([row(FP_A, False)], {}, now=float(k))
    assert [e.kind for e in out] == ["keep"]