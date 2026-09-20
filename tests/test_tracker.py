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
    frames = [[row(FP_A, width=40)]] * 3 + [[row(FP_A, width=90)]] * 6
    secs = [{0: 40}, {0: 25}, {0: 20},            # 기본: 30 미만 1회
            {0: 500}, {0: 500}, {0: 119}, {0: 100}, {0: 59}, {0: 10}]   # 연장(500 2프레임) 후: 120, 60
    assert run(t, frames, secs) == [("under", 30), ("extended", None), ("under", 120), ("under", 60)]



def test_extension_end_returns_to_base():
    w = Watch(FP_A, "서곡", alert_under=[30], base_width=40, alert_under_extended=[120], cooldown=0)
    t = Tracker([w], debounce=1)
    frames = [[row(FP_A, width=40)], [row(FP_A, width=90)], [row(FP_A, width=90)], [row(FP_A, width=100)], [row(FP_A, width=40)], [row(FP_A, width=40)]]
    secs = [{0: 100}, {0: 300}, {0: 300}, {0: 100}, {0: 100}, {0: 20}]
    assert run(t, frames, secs) == [("extended", None), ("under", 120), ("unextended", None), ("under", 30)]


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
    out += t.update([row(FP_A, True)], {0: 300}, now=1.0)      # 후보
    out += t.update([row(FP_A, True)], {0: 300}, now=1.5)      # 확인 → 재동기화, 임계값 초기화
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


def test_keep_master_toggle():
    """Tracker.keep_enabled 가 꺼져 있으면 잔소리 없음 (앱은 마스터 스위치로 tick 자체를 멈추지만, 추적기 단독으로도 제어 가능)."""
    a = Watch(FP_A, "A", keep=True, keep_delay=5, keep_interval=100, alert_off=False)
    t = Tracker([a], debounce=1, keep_enabled=False)
    out = []
    for k in range(0, 20):
        out += t.update([row(FP_A, False)], {}, now=float(k))
    assert not out
    t.keep_enabled = True
    for k in range(20, 40):
        out += t.update([row(FP_A, False)], {}, now=float(k))
    assert [e.kind for e in out] == ["keep"]


def test_time_keeps_counting_while_state_unknown():
    """밝은 배경 등으로 활성 판정이 '모름'이어도 시간 추정과 임계값 알림은 계속된다."""
    t = Tracker([Watch(FP_A, "A", alert_under=[30], cooldown=0)], debounce=1)
    out = t.update([row(FP_A, True)], {0: 40}, now=0.0)
    for k in range(1, 25):
        out += t.update([row(FP_A, None)], {}, now=float(k))          # 모름 + 못 읽음
    assert [(e.kind, e.value) for e in out] == [("under", 30)]
    assert 10 <= t.tracks[0].estimate(now=24.0) <= 17


def test_time_read_while_state_unknown():
    """모름 상태에서도 시간이 읽히면 그 값을 쓴다."""
    t = Tracker([Watch(FP_A, "A", alert_under=[30], cooldown=0)], debounce=1)
    out = t.update([row(FP_A, True)], {0: 100}, now=0.0)
    out += t.update([row(FP_A, None)], {0: 20}, now=1.0)
    assert [(e.kind, e.value) for e in out] == [("under", 30)]


def test_time_spike_is_ignored():
    """이동·화면전환으로 한 프레임 값이 튀어도(늘어나도) 재동기화·임계값에 영향 없다."""
    t = Tracker([Watch(FP_A, "A", alert_under=[30], cooldown=0)], debounce=1)
    out = t.update([row(FP_A, True)], {0: 40}, now=0.0)
    out += t.update([row(FP_A, True)], {0: 300}, now=0.2)
    out += t.update([row(FP_A, True)], {0: 39}, now=0.4)
    for k in range(2, 15):
        out += t.update([row(FP_A, True)], {0: 40 - k}, now=float(k) * 0.2 + 0.4)
    kinds = [(e.kind, e.value) for e in out]
    assert ("resync", 300) not in kinds
    assert ("under", 30) in kinds


def test_real_refresh_needs_two_frames():
    """진짜 연장(리필)은 늘어난 값이 2프레임 연속이면 재동기화."""
    t = Tracker([Watch(FP_A, "A", alert_under=[30], cooldown=0)], debounce=1)
    out = t.update([row(FP_A, True)], {0: 20}, now=0.0)
    out += t.update([row(FP_A, True)], {0: 300}, now=0.2)
    out += t.update([row(FP_A, True)], {0: 300}, now=0.4)
    assert ("resync", 300) in [(e.kind, e.value) for e in out]