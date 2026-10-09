"""
투아림 샘플 수집 (인식 만들기 전 단계).

투아림 영역(도르카 숫자 0~15 + 부스트 0~100%)을 실제 화면 그대로 저장한다. 숫자가 바뀔 때만 저장해서
부스트 한 바퀴(전투 600초)면 0~9 글자와 도르카 0~15 가 다 모인다. 게임 스크린샷 기능은 글꼴이 달라서 못 쓴다.

판단: 영역 안의 '흰 글자 픽셀'(무채색, 밝기 ≥ TEXT_MIN) 모양이
  - 마지막으로 저장한 것과 DIFF_MIN 픽셀 넘게 다르고
  - 직전 프레임과는 거의 같을 때 (바뀌는 중간 프레임·이펙트 한 장 거르기)
저장. 똑같은 모양은 다시 저장하지 않는다 (같은 숫자로 돌아온 경우).
"""
import hashlib
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

TEXT_MIN = 200       # 글자 픽셀 밝기 하한 (안티앨리어싱 가장자리 일부 포함)
NEUTRAL = 24         # 무채색 판정 (채널 최대-최소). 분홍 칸·보라 원은 빠진다
DIFF_MIN = 6         # 저장한 것과 이만큼 넘게 다르면 '바뀜'
STABLE_MAX = 2       # 직전 프레임과 이 이하로 다르면 '안정'
MIN_GAP = 0.3        # 저장 사이 최소 간격 (초)
MAX_FILES = 600      # 한 폴더 최대 (넘으면 그만 저장)


def text_mask(crop) -> np.ndarray:
    px = crop.astype(np.int16)
    mn, mx = px.min(axis=2), px.max(axis=2)
    return (mn >= TEXT_MIN) & ((mx - mn) <= NEUTRAL)


def env_key(ui_variant: str, client_wh) -> str:
    """저장 폴더 이름: UI 크기 변형 + 게임 창 크기 (4K/QHD·글꼴별로 글자 모양이 달라서 나눠 모은다)."""
    w, h = client_wh
    return f"{ui_variant}_{w}x{h}"


class SampleCollector:
    def __init__(self, folder: Path, max_files=MAX_FILES):
        self.folder = Path(folder)
        self.max_files = max_files
        self.prev = None             # 직전 프레임 글자 모양
        self.last_saved = None       # 마지막으로 저장한 글자 모양
        self.seen = set()            # 저장한 모양 해시 (같은 숫자로 돌아오면 다시 저장 안 함)
        self.last_time = -1e9
        self.count = len(list(self.folder.glob("*.png"))) if self.folder.exists() else 0

    @property
    def full(self) -> bool:
        return self.count >= self.max_files

    def feed(self, crop, now=None) -> str | None:
        """프레임 하나. 저장했으면 파일 이름, 아니면 None."""
        now = time.time() if now is None else now
        m = text_mask(crop)
        prev, self.prev = self.prev, m
        if self.full or prev is None or prev.shape != m.shape:
            return None
        if int((m ^ prev).sum()) > STABLE_MAX:
            return None                               # 바뀌는 중
        if self.last_saved is not None and self.last_saved.shape == m.shape and int((m ^ self.last_saved).sum()) <= DIFF_MIN:
            return None                               # 마지막 저장과 같음
        if not m.any() or now - self.last_time < MIN_GAP:
            return None
        h = hashlib.md5(np.packbits(m).tobytes()).hexdigest()
        if h in self.seen:
            self.last_saved = m
            return None
        self.seen.add(h); self.last_saved = m; self.last_time = now
        self.folder.mkdir(parents=True, exist_ok=True)
        name = datetime.fromtimestamp(now).strftime("%Y%m%d_%H%M%S_%f")[:-3] + ".png"
        cv2.imwrite(str(self.folder / name), crop)     # png = 무손실 (실제 화면 픽셀 그대로)
        self.count += 1
        return name
