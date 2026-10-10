"""
화면 변형 (게임 안 UI 크기 옵션 × 글꼴). 일반 설정의 "UI 크기 변경"으로 사용자가 고른다.

- "100"       UI 크기 변경 없음 (기본). 게임이 자체 비트맵 글꼴로 그림 → 글자 픽셀 완전 일치
- "150_mabi"  4K, UI 150%, 마비옛체     → 치수 1.5배, 안티앨리어싱 글꼴 (같은 글자도 위치에 따라 모양이 조금씩 다름)
- "150_nanum" 4K, UI 150%, 나눔고딕
- "100_mabi"  UI 배율 조정 켬 + 100% + 마비옛체 → 크기는 기본과 같지만 글자가 작은 부드러운 글꼴.
              시간 글자는 행 위치(세로 반 픽셀)마다 가장자리가 달라 흑백 모양 대신 밝기로 비교 (gray)

치수는 전부 100% 기준 상수 × scale 로 쓴다 (px/area). scale=1.0 이면 기존 값과 정확히 같다.
현재 변형은 프로세스 전역 하나 (앱이 설정을 읽을 때 set_screen). core 테스트 기본값은 "100".
"""
from dataclasses import dataclass
from pathlib import Path

from core.paths import ASSETS, PROFILES


@dataclass(frozen=True)
class Screen:
    key: str
    label: str
    scale: float
    glyphs: Path          # 상태창 시간 글자
    fuzzy: bool           # True = ±1px 어긋남·여러 모양 허용 비교 (안티앨리어싱 글꼴)
    gray: bool = False    # True = 시간 글자를 밝기 템플릿으로 비교 (glyphs = 밝기 글자 파일)


SCREENS = {
    "100": Screen("100", "UI 크기 변경 없음", 1.0, ASSETS / "glyphs.json", False),
    "150_mabi": Screen("150_mabi", "4K · UI 150% · 마비옛체", 1.5, ASSETS / "screens" / "150_mabi" / "glyphs.json", True),
    "150_nanum": Screen("150_nanum", "4K · UI 150% · 나눔고딕", 1.5, ASSETS / "screens" / "150_nanum" / "glyphs.json", True),
    "100_mabi": Screen("100_mabi", "UI 배율 조정 켬 · 100% · 마비옛체", 1.0, ASSETS / "screens" / "100_mabi" / "time_gray.json",
                       False, gray=True),
}
DEFAULT = "100"
BASE_PITCH = 24           # 100% 상태창 행 간격

_cur = SCREENS[DEFAULT]
_hdr = True               # 윈도우 HDR 켜짐. 부드러운 글꼴 변형은 HDR 이 꺼지면 글자 밝기가 달라 기준을 바꾼다 (soft_sdr)


def set_screen(key: str) -> Screen:
    global _cur
    _cur = SCREENS.get(key, SCREENS[DEFAULT])
    return _cur


def set_hdr(on: bool) -> None:
    """윈도우 HDR 상태 (앱이 시작할 때·설정 바꿀 때). HDR 이 켜지면 캡처가 밝아져 글자가 255 로 꽉 찬다."""
    global _hdr
    _hdr = bool(on)


def hdr() -> bool:
    return _hdr


def soft_sdr() -> bool:
    """부드러운 글꼴(UI 150%·UI 배율 조정 100%) + HDR 꺼짐.
    HDR 이 꺼지면 켜진 글자가 255 가 아니라 200~250 (가장자리 섞임), 꺼진 글자는 209 가 아니라 127.
    기본 UI(비트맵 글꼴)는 HDR 과 무관하게 255 / 127·209 라 해당 없음."""
    return not _hdr and (_cur.fuzzy or _cur.gray)


class as_hdr:
    """with screen.as_hdr(): HDR 기준으로 잠깐 판정 (밝기를 키운 HDR 꺼짐 이미지를 기존 HDR 글자 세트로 읽을 때)."""
    def __enter__(self):
        global _hdr
        self._old, _hdr = _hdr, True

    def __exit__(self, *a):
        global _hdr
        _hdr = self._old


def sdr_glyphs() -> Path | None:
    """HDR 꺼짐용 시간 글자 (밝기 템플릿, 열 끊김으로 나눔). 없으면 None."""
    if not (_cur.fuzzy or _cur.gray):
        return None
    p = _cur.glyphs.parent / "time_sdr.json"
    return p if p.exists() else None


def current() -> Screen:
    return _cur


def scale() -> float:
    return _cur.scale


def px(v: float) -> int:
    """길이 상수 (px) × 배율."""
    return int(round(v * _cur.scale))


def area(v: float) -> int:
    """넓이 상수 (픽셀 수) × 배율²."""
    return int(round(v * _cur.scale * _cur.scale))


def boss_glyphs() -> Path:
    """보스 띠 라벨 글자. 100% 는 상태창과 같은 5×7 글자, 150% 는 변형 폴더의 boss_glyphs.json (부드러운 글꼴)."""
    if _cur.gray:
        return _cur.glyphs.parent / "boss_gray.json"       # 밝기 템플릿 (UI 배율 조정 100%)
    p = _cur.glyphs.parent / "boss_glyphs.json"
    return p if _cur.fuzzy else ASSETS / "glyphs.json"


def user_glyphs() -> Path | None:
    """사용 중 배운 시간 글자 (안티앨리어싱 변형만). 업데이트해도 남도록 profiles 에."""
    return PROFILES / "glyphs" / f"{_cur.key}.json" if _cur.fuzzy else None


def time_text(sec: int) -> str:
    """게임이 그리는 시간 글자열 (공백 제외): 146 → '2분26초', 40 → '40초'."""
    m, s = divmod(int(sec), 60)
    return f"{m}분{s}초" if m else f"{s}초"


def pitch_matches(pitch: int) -> bool:
    """검출한 행 간격이 고른 UI 크기와 맞는가 (24 ↔ 100%, 36 ↔ 150%)."""
    return abs(pitch - BASE_PITCH * _cur.scale) <= 2


def guess_from_pitch(pitch: int) -> str | None:
    """행 간격으로 본 UI 크기 설명 (안내 문구용)."""
    for s in (1.0, 1.5):
        if abs(pitch - BASE_PITCH * s) <= 2:
            return f"{int(s * 100)}%"
    return None
