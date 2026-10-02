"""
소리 알림 규칙 (순수 로직, Qt·Windows 없음 → 테스트 가능).

이벤트 → 말할 문구(또는 효과음) → 대기열. 재생은 win/voice.py.

원칙 (실사용 기준):
  - 줄 세우지 않는다: 새 소리가 오면 재생 중인 것을 끊고 바로 새것을 (밀려서 늦게 나오면 상황과 안 맞음).
  - 우선순위: 1 보스 버스트 > 2 상태창 > 3 보스 디버프. 낮은 것이 재생 중이면 높은 것이 끊고,
    높은 것이 재생 중이면 낮은 것은 잠깐(STALE) 기다렸다가, 그 사이 안 끝나면 버린다.
  - 한 틱에 나온 상태창 알림은 한 문장으로 합친다 ("마나실드 꺼짐, 햄버프 30초") → 서로 끊지 않게.
  - 같은 순간 여러 개 꺼지면 (죽음·맵 이동) 하나씩 말하지 않고 "버프 N개 꺼짐" 한 마디.
  - "켜질 때까지 반복"은 화면 알림과 같은 순간에 말한다 (간격은 사용자가 정한 반복 간격 그대로).
    같은 틱에 나온 것끼리 한 문장 ("서곡, 상지 꺼져 있음"). 버프끼리 박자는 추적기가 맞춘다 (tracker.KEEP_ALIGN).
  - 시작할 때 이미 꺼져 있던 것은 말하지 않는다 (추적기가 첫 판정은 이벤트로 안 낸다).
  - 보스 디버프: 음성/효과음으로 정한 항목만, 목록에 뜨는 순간 같이. "모모 빠짐", "모모 20초".
    전투 시작 때 처음부터 없는 것도 말한다 (목록에 바로 뜨므로). 한꺼번에 GROUP_MIN 개 이상이면 "보스 디버프 N개 빠짐".
    계속 빠져 있으면 BOSS_REPEAT(20초)마다 다시 "모모 빠짐".
"""
from dataclasses import dataclass

# 우선순위 (작을수록 먼저). 같거나 높은 우선순위가 오면 재생 중인 것을 끊는다
P_BURST, P_STATUS, P_BOSS = 0, 1, 2
P_OFF = P_INFO = P_STATUS          # 예전 이름 (상태창)
STALE = {P_BURST: 2.0, P_STATUS: 1.5, P_BOSS: 6.0}   # 높은 것이 재생 중일 때 이만큼까지만 기다린다
# (보스 디버프는 천천히 바뀌므로 몇 초 늦어도 의미가 있다 → 상태창 알림이 끝날 때까지 넉넉히 기다림)
BOSS_REPEAT = 20.0     # 보스 디버프가 계속 빠져 있으면 이 간격으로 다시 알림
GROUP_MIN = 3          # 한 틱(또는 GROUP_WINDOW 안)에 이만큼 이상 꺼지면 묶어서 한 마디
GROUP_WINDOW = 1.5     # 묶음 알림 직후 이 안에 더 꺼지는 것은 조용히 (같은 사건)
KEEP_MAX_NAMES = 3     # 이보다 많으면 "버프 N개 꺼져 있음"

MODES = ("voice", "effect", "none")


@dataclass
class SoundCfg:
    """감시 항목 하나의 소리 설정."""
    mode: str = "none"             # voice | effect | none
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
    """이벤트 묶음(한 틱) → Utterance 목록. 여러 개 꺼짐 묶기 상태를 가진다."""
    group_until: float = -1e9

    def plan(self, events, cfg_of, now) -> list[Utterance]:
        """events: [(kind, label, value)]. cfg_of(label) → SoundCfg | None (None = 감시 항목 아님 → 효과음)."""
        out: list[Utterance] = []
        offs, keeps = [], []
        keep_effect = False
        for kind, label, value in events:
            cfg = cfg_of(label)
            mode = cfg.mode if cfg else "effect"
            if mode == "none":
                continue
            name = spoken_name(label, cfg)
            if kind == "keep":
                if mode == "voice":
                    keeps.append(name)
                else:
                    keep_effect = True
                continue
            if kind == "off":
                offs.append((name, mode))
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

        # 반복: 화면 알림과 같은 순간에, 같은 틱 것은 한 문장
        if keeps:
            out.append(Utterance("voice", keep_phrase(sorted(set(keeps))), "danger", P_INFO, now, key="keep"))   # 정렬: 미리 합성한 문구와 같게
        elif keep_effect:
            out.append(Utterance("effect", level="danger", prio=P_INFO, at=now, key="keep"))
        return out


def boss_utterance(events, mode_of, now) -> Utterance | None:
    """보스 디버프 이벤트 한 틱 → 소리 하나 (우선순위 3).
    events: [(kind, label, value, initial)]. mode_of(label) → "voice" | "effect" | "none" (None = 감시 아님 → 조용히)."""
    missing, under, modes = [], [], []
    for kind, label, value, initial in events:
        mode = mode_of(label)
        if mode not in ("voice", "effect"):
            continue
        if kind == "missing":
            modes.append(mode)
            if mode == "voice":
                missing.append(label)
        elif kind == "under" and value is not None:
            modes.append(mode)
            if mode == "voice":
                under.append(f"{label} {int(value)}초")
    if not modes:
        return None
    if "voice" not in modes:
        return Utterance("effect", level="warn", prio=P_BOSS, at=now, key="boss")
    if len(missing) >= GROUP_MIN:
        parts = [f"보스 디버프 {len(missing)}개 빠짐"]
    else:
        parts = [f"{n} 빠짐" for n in dict.fromkeys(missing)]
    text = ", ".join(parts + list(dict.fromkeys(under)))
    return Utterance("voice", text, "warn", P_BOSS, now, key=text)


class BossSpeaker:
    """보스 디버프 소리: 이벤트(빠짐·재표시) + 계속 빠져 있는 것 다시 알림.
    다시 알림은 하나의 시계로: 마지막 보스 '빠짐' 알림 후 BOSS_REPEAT 가 지나면 지금 빠져 있는 것 전부를 한 문장으로."""

    def __init__(self, repeat=BOSS_REPEAT):
        self.repeat = repeat
        self.last = None                         # 마지막 '빠짐' 알림 시각 (None = 빠진 것 없음)

    def plan(self, events, missing_now, mode_of, now) -> Utterance | None:
        """events: [(kind, label, value, initial)], missing_now: 지금 빠져 있는 감시 항목 이름들."""
        missing_now = sorted({m for m in missing_now if mode_of(m) in ("voice", "effect")})
        events = list(events)
        if not missing_now:
            self.last = None                     # 전부 걸림 → 다음에 빠지면 처음부터
        elif any(k == "missing" and mode_of(l) in ("voice", "effect") for k, l, _, _ in events):
            self.last = now                      # 방금 말함 → 시계 다시
        elif self.last is None:
            self.last = now                      # 이벤트 없이 빠져 있던 것 (설정을 막 바꿨을 때 등): 여기서부터 셈
        elif now - self.last >= self.repeat:
            self.last = now
            events += [("missing", m, None, False) for m in missing_now]
        return boss_utterance(events, mode_of, now)

    def reset(self):
        self.last = None


def boss_phrases(name: str, thresholds) -> list[str]:
    """미리 합성할 보스 디버프 문구."""
    return [f"{name} 빠짐"] + [f"{name} {int(t)}초" for t in thresholds]


def merge(us: list[Utterance], now: float) -> Utterance | None:
    """한 틱의 상태창 알림 → 하나. 음성이 있으면 문장을 이어 붙이고, 효과음뿐이면 가장 심각한 것 하나."""
    if not us:
        return None
    voice = [u.text for u in us if u.kind == "voice" and u.text]
    if voice:
        text = ", ".join(dict.fromkeys(voice))
        return Utterance("voice", text, "danger", P_STATUS, now, key=text)
    order = {"danger": 0, "warn": 1, "info": 2, "ok": 3}
    best = min(us, key=lambda u: order.get(u.level, 9))
    return Utterance("effect", level=best.level, prio=P_STATUS, at=now, key=f"effect:{best.level}")


class SoundQueue:
    """대기 칸: 우선순위마다 가장 최근 것 하나만 (밀려서 쌓이지 않게). 오래 기다린 것은 버림."""

    def __init__(self):
        self.slots: dict[int, Utterance] = {}

    def push(self, u: Utterance) -> bool:
        self.slots[u.prio] = u                     # 같은 우선순위는 최신이 이전 것을 대신
        return True

    def best_prio(self, now) -> int | None:
        self._drop_stale(now)
        return min(self.slots) if self.slots else None

    def has_urgent(self) -> bool:
        return P_BURST in self.slots

    def pop(self, now) -> Utterance | None:
        p = self.best_prio(now)
        return self.slots.pop(p) if p is not None else None

    def _drop_stale(self, now):
        for p in [p for p, u in self.slots.items() if u.stale(now)]:
            u = self.slots.pop(p)
            print(f"[소리] 늦어서 건너뜀: {u.text or u.level}")

    def __len__(self):
        return len(self.slots)
