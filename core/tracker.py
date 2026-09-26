"""
상태 추적기. 매 프레임 RowState 목록을 받아 이전 상태와 비교해 이벤트를 낸다.

- 감시 대상은 이름 지문으로 찾는다 (행 순서가 바뀌어도 따라감)
- active=None 은 '모름' → 그 프레임은 판단에 쓰지 않는다
- 디바운싱: 같은 판정이 N프레임 연속일 때만 상태 전환
- 알림 스팸 방지: 같은 종류 이벤트는 cooldown 초 안에 반복 안 함
"""
from dataclasses import dataclass, field
import time

from core import screen
from core.status import RowState, fp_same


@dataclass
class Watch:
    name_fp: bytes
    label: str
    alert_off: bool = True
    alert_on: bool = False
    alert_under: list[int] = field(default_factory=lambda: [60, 30])
    cooldown: float = 10.0
    # 연장 변형: 이름 뒤에 글자가 붙어 폭이 base_width 보다 EXT_MARGIN 이상 길어지면 '연장' 상태.
    # (예: '전장의 서곡' → '전장의 서곡(투안의 노래)') 연장 중엔 alert_under_extended 를 쓴다.
    base_width: int | None = None
    alert_under_extended: list[int] | None = None
    row_index: int | None = None      # 지정하면 지문 대신 행 번호로 찾음 (레이아웃 고정일 때)
    # 유지 필수: 꺼진 상태가 keep_delay 초 이상 이어지면 keep_interval 초마다 반복 알림
    # (마나실드·반신화: 꺼지면 위험 / 엘레멘탈 부여: 부활 후 꺼진 채로 남음)
    keep: bool = False
    keep_delay: float = 10.0
    keep_interval: float = 30.0


EXT_MARGIN = 10
EXPIRE_GRACE = 5    # 추정이 0 아래로 이만큼 내려가면 만료로 봄
RESYNC_TOL = 5      # 읽은 값이 추정과 이만큼 이상 다르면 재동기화 (버프 갱신/연장)
REFRESH_GAP = 10.0  # 이 안에 꺼졌다 켜지면 '갱신'으로 본다 (정화의 물결처럼 다시 쓰면 잠깐 꺼졌다 켜지는 버프)


@dataclass
class Event:
    kind: str            # "off" | "on" | "under" | "lost" | "found" | "extended" | "unextended" | "resync" | "keep"
    label: str
    value: int | None = None
    at: float = 0.0


@dataclass
class _Track:
    watch: Watch
    active: bool | None = None
    seconds: int | None = None
    pending: bool | None = None
    pending_n: int = 0
    fired_under: set = field(default_factory=set)
    last_fired: dict = field(default_factory=dict)
    missing_n: int = 0
    extended: bool | None = None
    ext_pending: bool | None = None
    ext_n: int = 0
    # 남은 시간 추정 (인식이 끊겨도 시간은 흐른다): 마지막으로 읽은 초와 그 시각
    last_sec: int | None = None
    last_at: float = 0.0
    off_since: float | None = None     # 확정 '꺼짐' 시작 시각 (유지 필수용)
    last_keep: float = -1e9
    jump_cand: int | None = None       # 값이 갑자기 늘어난 후보 (재동기화 전 2프레임 확인)
    off_est: int | None = None         # 꺼지기 직전 남은 시간 추정 (잠깐 꺼졌다 켜진 '갱신' 감지용)
    off_at: float | None = None
    relit_at: float | None = None      # 꺼진 지 REFRESH_GAP 안에 다시 켜진 시각
    jump_n: int = 0

    def estimate(self, now):
        if self.last_sec is None:
            return None
        est = self.last_sec - (now - self.last_at)
        if est < -EXPIRE_GRACE:              # 0을 지나 한참 = 만료. 더 이상 추정하지 않음
            self.last_sec = None
            return None
        return max(0, int(round(est)))


class Tracker:
    def __init__(self, watches: list[Watch], debounce: int = 3, missing_limit: int = 15, keep_enabled: bool = True,
                 ext_off_debounce: int | None = None):
        self.tracks = [_Track(w) for w in watches]
        self.debounce = debounce
        # 연장 끝은 더 오래 확인 (밝은 바닥·이펙트에서 접미어가 몇 프레임 안 잡히는 일이 흔하다). None = debounce 와 같음
        self.ext_off_debounce = ext_off_debounce or debounce
        self.missing_limit = missing_limit
        self.keep_enabled = keep_enabled      # 반복 알림 마스터 토글. 유저가 전투 들어갈 때 켜고 나올 때 끈다

    def update(self, rows: list[RowState], seconds_of: dict, now=None) -> list[Event]:
        now = now if now is not None else time.time()
        events = []
        for t in self.tracks:
            if t.watch.row_index is not None:
                row = next((r for r in rows if r.index == t.watch.row_index), None)
            else:
                row = next((r for r in rows if fp_same(r.name_fp, t.watch.name_fp)), None)
            if row is None:
                t.missing_n += 1
                if t.missing_n == self.missing_limit:
                    events.append(Event("lost", t.watch.label, at=now))
                continue
            if t.missing_n >= self.missing_limit:
                events.append(Event("found", t.watch.label, at=now))
            t.missing_n = 0

            # 모름(None) 프레임은 켜짐/꺼짐 판정만 보류. 시간·연장 처리는 아래에서 계속한다
            # (밝은 배경에서 오래 모름이어도 시간 추정과 임계값 알림이 멈추면 안 됨)
            if row.active is not None:
                if row.active == t.pending:
                    t.pending_n += 1
                else:
                    t.pending, t.pending_n = row.active, 1
            if row.active is not None and t.pending_n >= self.debounce and t.pending != t.active:
                prev, t.active = t.active, t.pending
                if prev is not None:
                    kind = "on" if t.active else "off"
                    if (t.active and t.watch.alert_on) or (not t.active and t.watch.alert_off):
                        events += self._fire(t, Event(kind, t.watch.label, at=now), now)
                if t.active:
                    t.fired_under.clear()
                    t.off_since = None
                    if prev is False and t.off_at is not None and now - t.off_at <= REFRESH_GAP:
                        t.relit_at = now
                else:
                    t.off_since = now
                    t.last_keep = -1e9
                    t.off_est, t.off_at = t.estimate(now), now

            # --- 유지 필수: 꺼진 채로 유예 시간이 지나면 주기적으로 ---
            if self.keep_enabled and t.watch.keep and t.active is False and t.off_since is not None:
                if now - t.off_since >= t.watch.keep_delay and now - t.last_keep >= t.watch.keep_interval:
                    t.last_keep = now
                    events.append(Event("keep", t.watch.label, at=now))

            # --- 연장 변형 감지 (이름 폭). 활성 행에서만 (비활성은 연장될 수 없고, 밝은 배경에선 이름 폭이 불안정) ---
            if t.watch.base_width and row.name_width and t.active and not getattr(row, "ext_unknown", False):
                if row.name_width < t.watch.base_width - 4:
                    t.watch.base_width = row.name_width      # 연장된 채로 캘리브레이션했던 경우: 짧은 쪽이 기준
                ext = row.extended if row.extended is not None else (row.name_width >= t.watch.base_width + screen.px(EXT_MARGIN))
                if ext == t.ext_pending:
                    t.ext_n += 1
                else:
                    t.ext_pending, t.ext_n = ext, 1
                need = self.debounce if t.ext_pending else self.ext_off_debounce
                if t.ext_n >= need and t.ext_pending != t.extended:
                    prev, t.extended = t.extended, t.ext_pending
                    if prev is not None:
                        events += self._fire(t, Event("extended" if t.extended else "unextended", t.watch.label, at=now), now)
                        t.fired_under.clear()
                        t.last_sec = None; t.jump_cand = None    # 연장 전후 시간이 크게 달라짐 → 다음 값을 첫 관측으로

            thresholds = t.watch.alert_under
            if t.extended and t.watch.alert_under_extended is not None:
                thresholds = t.watch.alert_under_extended

            raw = seconds_of.get(row.index)
            if t.active is False:                          # 확정 꺼짐일 때만 타이머 삭제 (모름(None)은 유지)
                t.last_sec = None; t.jump_cand = None
            elif raw is not None:
                est = t.estimate(now)
                if est is None and t.relit_at is not None:
                    # 잠깐 꺼졌다 다시 켜진 뒤 첫 값: 꺼지기 전보다 늘었으면 '갱신' (꺼짐→켜짐을 거쳐 재동기화 경로를 못 탐)
                    if now - t.relit_at <= 5 and (t.off_est is None or raw > t.off_est + RESYNC_TOL):
                        events.append(Event("resync", t.watch.label, raw, at=now))
                    t.relit_at = None
                if est is None or raw <= est + RESYNC_TOL:
                    t.last_sec, t.last_at = raw, now    # 첫 관측이거나 정상(줄었음/오차 이내) → 조용히 갱신
                    t.jump_cand = None
                elif t.jump_cand is not None and abs(raw - t.jump_cand) <= max(2, RESYNC_TOL):
                    # 늘어난 값이 2프레임 연속 = 진짜 연장/갱신. (한 프레임만 튄 건 이동·화면전환 오독 → 무시)
                    events.append(Event("resync", t.watch.label, raw, at=now))
                    t.fired_under.clear()
                    t.last_sec, t.last_at = raw, now; t.jump_cand = None
                else:
                    t.jump_cand = raw                   # 후보만 기록, 이번 프레임은 추정 유지
            sec = t.estimate(now) if t.active is not False else None
            if sec is not None:
                t.seconds = sec
                for thr in sorted(thresholds, reverse=True):
                    if sec < thr and thr not in t.fired_under:
                        t.fired_under.add(thr)
                        events += self._fire(t, Event("under", t.watch.label, thr, at=now), now)
        return events

    def _fire(self, t: _Track, ev: Event, now: float) -> list[Event]:
        key = (ev.kind, ev.value)
        if now - t.last_fired.get(key, -1e9) < t.watch.cooldown:
            return []
        t.last_fired[key] = now
        return [ev]


    def estimates(self, now=None) -> dict:
        """{row_index 또는 label: 추정 남은 초}. 표시용."""
        now = now if now is not None else time.time()
        out = {}
        for t in self.tracks:
            key = t.watch.row_index if t.watch.row_index is not None else t.watch.label
            out[key] = t.estimate(now)
        return out