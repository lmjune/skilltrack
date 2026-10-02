"""
소리 알림 규칙 (순수 로직, Qt·Windows 없음 → 테스트 가능).

이벤트 → 말할 문구(또는 효과음) → 대기열. 재생은 win/voice.py.

원칙 (실사용 로그 기준):
  - 한 번에 하나만. 겹치지 않게 줄을 세운다.
  - 오래 기다린 말은 버린다 (STALE 초 지난 "30초 미만"은 의미 없음).
  - 보스 버스트는 새치기: 재생 중인 것을 끊고 바로.
  - 같은 순간 여러 개 꺼지면 (죽음·맵 이동) 하나씩 말하지 않고 "버프 N개 꺼짐" 한 마디.
  - "켜질 때까지 반복"은 버프마다 따로 말하지 않고 꺼져 있는 것들을 한 문장으로, KEEP_GAP 에 한 번.
  - 시작할 때 이미 꺼져 있던 것은 말하지 않는다 (추적기가 첫 판정은 이벤트로 안 낸다).
"""
from dataclasses import dataclass, field

# 우선순위 (작을수록 먼저)
P_BURST, P_OFF, P_INFO = 0, 1, 2
STALE = {P_BURST: 2.0, P_OFF: 4.0, P_INFO: 3.0}   # 이만큼 기다렸으면 버린다
GROUP_MIN = 3          # 한 틱(또는 GROUP_WINDOW 안)에 이만큼 이상 꺼지면 묶어서 한 마디
GROUP_WINDOW = 1.5     # 묶음 알림 직후 이 안에 더 꺼지는 것은 조용히 (같은 사건)
KEEP_GAP = 20.0        # 반복 알림 문장 사이 최소 간격
KEEP_MAX_NAMES = 3     # 이보다 많으면 "버프 N개 꺼져 있음"

MODES = ("voice", "effect", "none")


@dataclass
class SoundCfg:
    """감시 항목 하나의 소리 설정."""
    mode: str = "voice"            # voice | effect | none
    text: str = ""                 # 부를 이름. 비우면 표시 이름


@dataclass
class Utterance:
    kind: str                      # "voice" | "effect"
    text: str = ""                 # voice: 말할 문구
    level: str = "info"            # effect: 심각도 (기본 효과음 선택)
    prio: int = P_INFO
    at: float = 0.0
    key: str = ""                  # 중복 제거용

    def stale(self, now) -> bool:
        return now - self.at > STALE.get(self.prio, 3.0)


def spoken_name(label: str, cfg: SoundCfg | None) -> str:
    """부를 이름. 사용자가 정한 문구 > 표시 이름. '행3' 같은 기본 이름은 '4번 버프'로 (TTS 가 '행삼'으로 읽음)."""
    if cfg and cfg.text.strip():
        return cfg.text.strip()
    s = (label or "").strip()
    if s.startswith("행") and s[1:].isdigit():
        return f"{int(s[1:]) + 1}번 버프"
    return s or "버프"


def phrase(kind: str, name: str, value=None) -> str | None:
    """상태창 이벤트 → 문구. None = 말하지 않음."""
    if kind == "off":
        return f"{name} 꺼짐"
    if kind == "on":
        return f"{name} 켜짐"
    if kind == "under" and value is not None:
        return f"{name} {int(value)}초"
    if kind == "extended":
        return f"{name} 연장"
    return None                    # resync(갱신: 내가 한 일), lost/found, unextended 는 말하지 않음


LEVEL_OF = {"off": "danger", "keep": "danger", "under": "warn", "on": "ok", "extended": "info"}


def keep_phrase(names: list[str]) -> str:
    if len(names) > KEEP_MAX_NAMES:
        return f"버프 {len(names)}개 꺼져 있음"
    return f"{', '.join(names)} 꺼져 있음"


@dataclass
class Planner:
    """이벤트 묶음(한 틱) → Utterance 목록. 묶기·반복 합치기 상태를 가진다."""
    group_until: float = -1e9
    keep_pending: dict = field(default_factory=dict)    # name → 처음 요청 시각
    keep_last: float = -1e9

    def plan(self, events, cfg_of, now) -> list[Utterance]:
        """events: [(kind, label, value)]. cfg_of(label) → SoundCfg | None (None = 감시 항목 아님 → 효과음)."""
        out: list[Utterance] = []
        offs = []
        for kind, label, value in events:
            cfg = cfg_of(label)
            mode = cfg.mode if cfg else "effect"
            if mode == "none":
                continue
            name = spoken_name(label, cfg)
            if kind == "on":
                self.keep_pending.pop(name, None)           # 켜졌으면 반복 대기에서 뺀다
            if kind == "keep":
                if mode == "voice":
                    self.keep_pending.setdefault(name, now)
                else:
                    out.append(Utterance("effect", level="danger", prio=P_INFO, at=now, key=f"keep:{name}"))
                continue
            if kind == "off":
                offs.append((name, mode))
                self.keep_pending.pop(name, None)           # 방금 꺼짐을 말하니 반복은 다음 차례부터
                continue
            text = phrase(kind, name, value)
            if text is None:
                continue
            level = LEVEL_OF.get(kind, "info")
            if mode == "voice":
                out.append(Utterance("voice", text, level, P_INFO, now, key=text))
            else:
                out.append(Utterance("effect", level=level, prio=P_INFO, at=now, key=f"{kind}:{name}"))

        # 꺼짐: 여럿이 한꺼번에면 한 마디, 직후 추가분은 조용히
        if offs:
            if now <= self.group_until:
                self.group_until = now + GROUP_WINDOW
            elif len(offs) >= GROUP_MIN:
                self.group_until = now + GROUP_WINDOW
                if any(m == "voice" for _, m in offs):
                    t = f"버프 {len(offs)}개 꺼짐"
                    out.insert(0, Utterance("voice", t, "danger", P_OFF, now, key="group"))
                else:
                    out.insert(0, Utterance("effect", level="danger", prio=P_OFF, at=now, key="group"))
            else:
                for name, m in reversed(offs):           # insert(0) 이라 거꾸로 → 원래 순서
                    if m == "voice":
                        t = f"{name} 꺼짐"
                        out.insert(0, Utterance("voice", t, "danger", P_OFF, now, key=t))
                    else:
                        out.insert(0, Utterance("effect", level="danger", prio=P_OFF, at=now, key=f"off:{name}"))

        # 반복: 꺼져 있는 것들을 한 문장으로, KEEP_GAP 에 한 번
        for n, t0 in list(self.keep_pending.items()):
            if now - t0 > 60:
                del self.keep_pending[n]                    # 오래된 요청 (그사이 상황이 바뀌었을 것)
        if self.keep_pending and now - self.keep_last >= KEEP_GAP and now > self.group_until:
            names = sorted(self.keep_pending, key=self.keep_pending.get)
            out.append(Utterance("voice", keep_phrase(names), "danger", P_INFO, now, key="keep"))
            self.keep_pending.clear()
            self.keep_last = now
        return out


class SoundQueue:
    """재생 대기열. 우선순위 → 먼저 온 순. 같은 key 는 하나만. 오래된 건 버림."""

    def __init__(self):
        self.items: list[Utterance] = []

    def push(self, u: Utterance) -> bool:
        """넣었으면 True. 같은 key 가 이미 기다리면 무시."""
        if u.key and any(x.key == u.key for x in self.items):
            return False
        self.items.append(u)
        return True

    def has_urgent(self) -> bool:
        return any(x.prio == P_BURST for x in self.items)

    def pop(self, now) -> Utterance | None:
        self.items = [x for x in self.items if not x.stale(now)]
        if not self.items:
            return None
        best = min(range(len(self.items)), key=lambda i: (self.items[i].prio, self.items[i].at, i))
        return self.items.pop(best)

    def __len__(self):
        return len(self.items)
