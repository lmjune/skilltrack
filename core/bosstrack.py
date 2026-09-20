"""
보스 디버프 추적기. 매 프레임 BarRead 를 받아 '빠진 디버프' 목록과 이벤트를 낸다.

- 띠가 있는 보스(BarRead.has_strip)일 때만 동작. 바가 없거나 띠가 없으면 idle (목록 비움, 알림 없음)
- 감시 디버프(watch): 아이콘 id → 이름, 재표시 임계값 [60, 40, 20] (초)
    * 띠에 없음        → 빠짐(missing) 표시
    * 남은 시간 ≤ 임계 → 다시 표시 (임계 통과할 때 이벤트 1회씩)
    * 라벨이 'M'(분)이면 초 단위는 모른다 → n분 = 정확히 모름. 60초 임계는 '분 라벨이 사라지고 초 라벨이 보이는 순간'에 잡힌다
    * 라벨이 없는 아이콘(시간 없음)은 있음/없음만 본다
- 버스트(burst): 아이콘이 나타나는 순간 이벤트 ("붕괴의 파동 적용!"). 사라지면 burst_off
- 디바운싱: 걸림은 2프레임, 빠짐은 4프레임 연속일 때. 남은 시간이 30초 넘게 있던 디버프는 15프레임(3초) — 이펙트가 띠를 덮은 경우.
- 띠 패널은 있는데 아이콘이 0개인 상태(아무것도 안 걸림)도 활성 → 감시 항목 전부 '빠짐'으로 표시. 바가 잠깐 안 보이면(메뉴 등) 상태는 유지하고 시간은 벽시계로 추정
- 모르는 아이콘(icon_id None)은 unknown 에 모아 UI 에서 이름 붙이게 한다
"""
from dataclasses import dataclass, field
import time

from core.bossbar import BarRead

DEBOUNCE_ON = 2        # 걸림: 2프레임 연속 보이면
DEBOUNCE_OFF = 4       # 빠짐: 4프레임 연속 안 보이면 (깜빡임·이펙트로 한두 프레임 놓쳐도 유지)
DEBOUNCE_OFF_LONG = 15 # 남은 시간이 SUSPECT_SECS 넘게 있던 디버프가 안 보이면 이펙트가 덮은 것일 가능성이 커서 3초 요구
SUSPECT_SECS = 30
LOST_RESET = 30.0      # 바가 이만큼 안 보이면 전투 끝으로 보고 초기화


@dataclass
class DebuffWatch:
    icon_id: str                       # 대표 아이콘 id
    label: str
    icon_ids: list[str] = field(default_factory=list)   # 같은 디버프의 다른 아이콘 (스택 수 표시 등). 비우면 icon_id 만
    thresholds: list[int] = field(default_factory=lambda: [60, 40, 20])
    burst: bool = False
    burst_text: str = ""       # 비우면 "{label} 적용!"
    show_missing: bool = True  # False 면 목록에 안 띄움 (버스트 알림만)


@dataclass
class DebuffEvent:
    kind: str                  # "missing" | "found" | "under" | "burst" | "burst_off" | "start" | "end"
    label: str
    value: int | None = None
    at: float = 0.0


@dataclass
class DebuffState:
    watch: DebuffWatch
    present: bool | None = None       # None = 아직 모름
    seconds: int | None = None        # 마지막으로 읽은 초 (분 라벨이면 n*60, 정확치 않음)
    exact: bool = False               # 초 단위로 읽었는가
    read_at: float = 0.0
    pending: bool | None = None
    pending_n: int = 0
    fired: set = field(default_factory=set)
    suspect: bool = False             # 이번 프레임에 '남은 시간 충분한데 안 보임' 이 시작됨 (진단 저장용)

    def remaining(self, now) -> int | None:
        if not self.present or self.seconds is None:
            return None
        return max(0, int(self.seconds - (now - self.read_at)))

    @property
    def shown(self) -> bool:
        """오버레이에 '빠짐/곧 끝남' 으로 보여줄지."""
        if self.present is None or not self.watch.show_missing:
            return False
        if not self.present:
            return True
        if not self.exact or self.seconds is None:
            return False
        return any(self.seconds <= t for t in self.watch.thresholds)


class BossTracker:
    def __init__(self, watches: list[DebuffWatch]):
        self.states = {w.icon_id: DebuffState(w) for w in watches}
        self.active = False
        self.last_seen = 0.0
        self.unknown: dict[str, object] = {}     # key → 12×12 icon (라벨링 대기)

    def reset(self):
        for s in self.states.values():
            s.present = s.pending = None; s.pending_n = 0; s.seconds = None; s.exact = False; s.fired.clear()
        self.active = False

    def update(self, r: BarRead, now=None) -> list[DebuffEvent]:
        now = time.time() if now is None else now
        ev = []
        for st in self.states.values():
            st.suspect = False                # 지난 프레임 표시가 남지 않게 (바가 안 보이는 프레임 포함)
        if not r.present or not r.has_strip:
            if self.active and now - self.last_seen > LOST_RESET:
                self.reset(); ev.append(DebuffEvent("end", "", at=now))
            return ev
        self.last_seen = now
        if not self.active:
            self.active = True; ev.append(DebuffEvent("start", "", at=now))

        seen = {}
        for s in r.slots:
            if s.icon_id is None:
                from core.bossbar import IconLib
                if not IconLib.is_dim(s.icon):    # 어둡게 깜빡이는 프레임은 학습용으로 부적합
                    self.unknown.setdefault(IconLib.key_of(s.icon), s.icon)
            elif s.icon_id not in seen or (s.seconds is not None and (seen[s.icon_id].seconds or 0) < s.seconds):
                seen[s.icon_id] = s               # 같은 아이콘 여러 개면 가장 긴 것

        for k, st in self.states.items():
            slot = None
            for kk in [k] + [i for i in st.watch.icon_ids if i != k]:
                c = seen.get(kk)
                if c is not None and (slot is None or (c.seconds or 0) > (slot.seconds or 0)):
                    slot = c
            on = slot is not None
            # 디바운스
            st.suspect = False
            if on != st.pending:
                st.pending, st.pending_n = on, 1
                if not on and st.present and (st.remaining(now) or 0) > SUSPECT_SECS:
                    st.suspect = True
            else:
                st.pending_n += 1
            need = DEBOUNCE_ON if on else (DEBOUNCE_OFF_LONG if (st.remaining(now) or 0) > SUSPECT_SECS else DEBOUNCE_OFF)
            if st.pending_n >= need and on != st.present:
                st.present = on
                st.fired.clear()
                w = st.watch
                if on:
                    ev.append(DebuffEvent("found", w.label, at=now))
                    if w.burst:
                        ev.append(DebuffEvent("burst", w.burst_text or f"{w.label} 적용!", at=now))
                else:
                    st.seconds, st.exact = None, False
                    ev.append(DebuffEvent("missing", w.label, at=now))
                    if w.burst:
                        ev.append(DebuffEvent("burst_off", w.label, at=now))
            # 시간
            if on and slot.seconds is not None:
                st.seconds, st.read_at = slot.seconds, now
                st.exact = not slot.label.endswith("M")
                if st.present and st.exact:
                    for t in st.watch.thresholds:
                        if slot.seconds <= t and t not in st.fired:
                            st.fired.add(t)
                            ev.append(DebuffEvent("under", st.watch.label, t, at=now))
        return ev

    def shown(self, now=None) -> list[DebuffState]:
        """오버레이 표시 목록 (빠진 것 + 임계 이하)."""
        if not self.active:
            return []
        return [s for s in self.states.values() if s.shown]