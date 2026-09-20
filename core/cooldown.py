"""
스킬 슬롯 쿨타임 판정 (표시용. 알림 아님).

기준 이미지 없이 동작한다: 각 슬롯에서 관측된 프레임 중 가장 밝은 것을 '준비 상태'로 삼고
(쿨 중엔 항상 어두우니 최대 밝기 = 준비), 지금 프레임이 그보다 충분히 어두우면 쿨 중.
히스테리시스(켤 때/끌 때 임계 다름) + 디바운스(N프레임 연속)로 깜빡임을 막는다.
"""
import numpy as np

ON_DIFF, OFF_DIFF = 28.0, 18.0     # 평균 밝기 차이: 이 이상이면 쿨 시작, 이 이하로 내려오면 쿨 끝
DEBOUNCE = 2


class SlotCooldown:
    def __init__(self):
        self.baseline = None         # 준비 상태 평균 밝기
        self.cooling = False
        self._pend, self._n = None, 0

    def update(self, slot_bgr) -> bool:
        lum = float(slot_bgr.mean())
        if self.baseline is None or lum > self.baseline:
            self.baseline = lum      # 더 밝은 프레임 = 준비 상태 갱신
        diff = self.baseline - lum
        want = diff > ON_DIFF if not self.cooling else diff > OFF_DIFF
        if want == self._pend:
            self._n += 1
        else:
            self._pend, self._n = want, 1
        if self._n >= DEBOUNCE:
            self.cooling = want
        return self.cooling