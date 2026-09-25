"""
설정 모델 + JSON 저장/불러오기. profiles/config.json 하나에 전부.

  general    fps, 소리, 단축키 …  (공통)
  overlays   알림/미러 위치·배율   (공통)
  profiles   {id: Profile}         캐릭터별: 이름, 영역(상태창·스킬창·보스), 감시 설정, 미러 행
  current    현재 선택된 프로필 id

레이아웃(행 좌표·획 자리)은 profiles/layouts/<id>.json 에 프로필 id 로 저장된다.
"""
from dataclasses import dataclass, field, asdict
import json
import uuid
from pathlib import Path

from core.paths import PROFILES

CONFIG_FILE = PROFILES / "config.json"


@dataclass
class General:
    window_title: str = "마비노기"
    fps: int = 5
    sound: bool = False                    # 알림 소리. 기본 무음
    sound_file: str = ""
    diag_save: bool = False
    active: bool = False                   # 마스터 스위치. 켜면 감시·알림·오버레이 전부 동작, 끄면 트레이만 (던전 들어갈 때 켜고 나와서 끔)
    hotkeys_enabled: bool = False          # 단축키 사용 (키 상태 폴링. 게임에도 키가 들어가니 안 쓰는 키로)
    hotkey_toggle: str = "F9"              # 마스터 스위치
    hotkey_settings: str = "F10"           # 홈 화면
    hotkey_edit: str = "Ctrl+F10"          # 배치 편집
    hide_when_inactive: bool = True        # 켜져 있어도 게임 창이 뒤로 가면 오버레이 숨김
    capturable: bool = False               # 오버레이를 스크린샷에 포함 (가이드 작성용). 평소엔 꺼둘 것
    boss_learn_icons: bool = False         # 보스 디버프: 모르는 아이콘을 assets/boss_icons 에 자동 등록 (디버그용. 배경 탓에 변형된 그림이 쌓이므로 평소엔 끔)


@dataclass
class WatchCfg:
    label: str = ""
    enabled: bool = True
    alert_off: bool = True
    alert_on: bool = False
    alert_under: list = field(default_factory=lambda: [60, 30])
    alert_under_extended: list = field(default_factory=lambda: [120, 60])
    keep: bool = False
    keep_delay: float = 10.0
    keep_interval: float = 30.0


@dataclass
class BossWatchCfg:
    """보스 디버프 감시 항목. 키 = 아이콘 이름(icons.json 의 name). 같은 이름의 아이콘(스택 변형 등)은 한 항목.
    enabled(감시) = 빠지면 목록에 표시. burst 만 켜면 목록엔 안 뜨고 걸리는 순간 알림만."""
    enabled: bool = True
    thresholds: list = field(default_factory=lambda: [60, 40, 20])   # 남은 초가 이 이하로 내려갈 때 다시 표시 (초 단위 라벨일 때만)
    burst: bool = False                                              # 걸리는 순간 알림 (버스트 스킬)
    burst_text: str = ""                                             # 비우면 "{이름} 적용!"


@dataclass
class MirrorRow:
    row: int
    icon: bool = True
    name: bool = True
    time: bool = True
    only_active: bool = False
    dim_inactive: bool = True
    pos: list | None = None          # [x, y] 화면 절대. None 이면 앞 항목 아래 자동
    scale: float | None = None       # None 이면 overlays.mirror_scale


@dataclass
class Overlays:
    alert_pos: list = field(default_factory=lambda: [1500, 1500])
    alert_width: int = 520
    alert_font_pt: int = 18
    mirror_pos: list = field(default_factory=lambda: [1500, 1300])     # 버프 표시 기본 시작 위치
    mirror_scale: float = 2.0
    mirror_opacity: float = 0.95
    skill_pos: list = field(default_factory=lambda: [1500, 1600])      # 스킬 표시 기본 시작 위치
    skill_scale: float = 2.0
    skill_opacity: float = 0.95
    skill_smooth: bool = True                                          # 스킬 아이콘 확대 시 부드럽게 (끄면 픽셀 그대로)
    boss_pos: list = field(default_factory=lambda: [1500, 1150])       # 보스 디버프 목록 위치
    boss_scale: float = 3.0                                            # 아이콘 12px × 배율
    boss_opacity: float = 0.95


@dataclass
class SkillItem:
    region: str                      # regions.skill 의 id
    slot: int
    mode: str = "always"             # always | cooling | dimmed
    pos: list | None = None
    scale: float | None = None


@dataclass
class Regions:
    status: list | None = None            # [x, y, w, h] 클라이언트 기준
    skill: list = field(default_factory=list)   # [{"id", "rect", "grid"}]
    boss: list | None = None              # None 이면 win.boss_session.BOSS_RECT (바가 화면 고정이라 보통 필요 없음)


@dataclass
class Profile:
    name: str = "캐릭터"
    regions: Regions = field(default_factory=Regions)
    watches: dict = field(default_factory=dict)          # {row: WatchCfg}
    mirror_rows: list = field(default_factory=list)      # [MirrorRow]
    skill_items: list = field(default_factory=list)      # [SkillItem]
    boss_enabled: bool = True                            # 보스 디버프 감시 (띠가 있는 보스에서만 동작)
    boss_watches: dict = field(default_factory=dict)     # {아이콘 이름: BossWatchCfg}

    def boss_watch_list(self, icon_meta: dict) -> list:
        """icons.json 의 meta({id: {name, tags}}) 로 DebuffWatch 목록 생성. 같은 이름의 아이콘은 icon_ids 로 묶는다."""
        from core.bosstrack import DebuffWatch
        by_name = {}
        for k, m in icon_meta.items():
            if m.get("name"):
                by_name.setdefault(m["name"], []).append(k)
        out = []
        for name, w in self.boss_watches.items():
            ids = by_name.get(name)
            if not ids or not (w.enabled or w.burst):
                continue
            out.append(DebuffWatch(ids[0], name, icon_ids=list(ids), thresholds=list(w.thresholds),
                                   burst=w.burst, burst_text=w.burst_text, show_missing=w.enabled))
        return out

    def watch_opts(self) -> dict:
        out = {}
        for row, w in self.watches.items():
            if not w.enabled:
                continue
            out[row] = dict(label=w.label or f"행{row}", alert_off=w.alert_off, alert_on=w.alert_on,
                            alert_under=list(w.alert_under), alert_under_extended=list(w.alert_under_extended),
                            keep=w.keep, keep_delay=w.keep_delay, keep_interval=w.keep_interval)
        return out


@dataclass
class Config:
    general: General = field(default_factory=General)
    overlays: Overlays = field(default_factory=Overlays)
    profiles: dict = field(default_factory=dict)          # {id: Profile}
    current: str = ""

    # ------------------------------------------------------------ 프로필
    def profile(self, pid=None) -> Profile | None:
        return self.profiles.get(pid or self.current)

    def add_profile(self, name) -> str:
        pid = uuid.uuid4().hex[:8]
        self.profiles[pid] = Profile(name=name or "캐릭터")
        if not self.current:
            self.current = pid
        return pid

    def remove_profile(self, pid):
        self.profiles.pop(pid, None)
        if self.current == pid:
            self.current = next(iter(self.profiles), "")

    # ------------------------------------------------------------ 저장/로드
    def save(self, path=CONFIG_FILE):
        d = asdict(self)
        for p in d["profiles"].values():
            p["watches"] = {str(k): v for k, v in p["watches"].items()}
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path=CONFIG_FILE):
        p = Path(path)
        if not p.exists():
            return cls()
        d = json.loads(p.read_text(encoding="utf-8"))
        c = cls()
        c.general = General(**_pick(d.get("general", {}), General))
        c.overlays = Overlays(**_pick(d.get("overlays", {}), Overlays))
        for pid, pd in d.get("profiles", {}).items():
            c.profiles[pid] = _profile_from(pd)
        c.current = d.get("current", "")
        # 구버전 (regions/watches 가 최상위) → 프로필 하나로 옮김
        if not c.profiles and (d.get("regions", {}).get("status") or d.get("watches")):
            pid = c.add_profile("캐릭터")
            c.profiles[pid] = _profile_from({"name": "캐릭터", "regions": d.get("regions", {}), "watches": d.get("watches", {}),
                                             "mirror_rows": d.get("overlays", {}).get("mirror_rows", [])})
        if c.current not in c.profiles:
            c.current = next(iter(c.profiles), "")
        return c


def _pick(d, cls):
    return {k: v for k, v in d.items() if k in cls.__dataclass_fields__}


def _profile_from(pd):
    rg = pd.get("regions", {})
    ws = {int(k): WatchCfg(**_pick(v, WatchCfg)) for k, v in pd.get("watches", {}).items()}
    ms = [MirrorRow(**_pick(r, MirrorRow)) for r in pd.get("mirror_rows", [])]
    sk = [SkillItem(**_pick(r, SkillItem)) for r in pd.get("skill_items", [])]
    bw = {k: BossWatchCfg(**_pick(v, BossWatchCfg)) for k, v in pd.get("boss_watches", {}).items()}
    return Profile(name=pd.get("name", "캐릭터"), regions=Regions(status=rg.get("status"), skill=rg.get("skill", []), boss=rg.get("boss")),
                   watches=ws, mirror_rows=ms, skill_items=sk, boss_enabled=pd.get("boss_enabled", True), boss_watches=bw)