"""투아림 샘플 수집: 숫자가 바뀔 때만, 안정된 프레임만, 같은 모양은 한 번만 저장."""
import cv2
import numpy as np

from core.tuarim_collect import SampleCollector, env_key


def frame(dorca, pct, bg=40):
    f = np.full((60, 90, 3), bg, np.uint8)
    cv2.circle(f, (22, 28), 18, (120, 20, 110), -1)                  # 보라 원 (글자 아님)
    cv2.rectangle(f, (50, 18), (80, 28), (200, 120, 220), -1)         # 분홍 칸 (글자 아님)
    cv2.putText(f, str(dorca), (10, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(f, f"{pct}%", (48, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
    return f


def run(col, frames, t0=0.0):
    saved = []
    for i, f in enumerate(frames):
        if col.feed(f, now=t0 + i * 0.2):
            saved.append(i)
    return saved


def test_saves_once_per_value(tmp_path):
    c = SampleCollector(tmp_path / "s")
    seq = [frame(15, 70)] * 5 + [frame(14, 70)] * 5 + [frame(14, 71)] * 5
    assert len(run(c, seq)) == 3                                     # 15/70, 14/70, 14/71
    assert len(list((tmp_path / "s").glob("*.png"))) == 3


def test_skips_unstable_frames(tmp_path):
    c = SampleCollector(tmp_path / "s")
    # 값이 프레임마다 바뀜 (중간 프레임만 있음) → 안정된 두 프레임이 없으니 저장 안 함
    seq = [frame(d, 70) for d in range(15, 5, -1)]
    assert run(c, seq) == []


def test_same_value_again_not_saved(tmp_path):
    c = SampleCollector(tmp_path / "s")
    seq = [frame(15, 70)] * 3 + [frame(13, 70)] * 3 + [frame(15, 70)] * 3   # 15 로 돌아옴
    assert len(run(c, seq)) == 2


def test_max_files(tmp_path):
    c = SampleCollector(tmp_path / "s", max_files=2)
    seq = sum(([frame(15, p)] * 3 for p in range(70, 76)), [])
    assert len(run(c, seq)) == 2 and c.full


def test_env_key():
    assert env_key("150_mabi", (3840, 2160)) == "150_mabi_3840x2160"
