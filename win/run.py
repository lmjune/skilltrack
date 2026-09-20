"""
실행 진입점. 트레이 아이콘이 생기고 거기서 모든 설정을 연다. 자세한 건 win/app.py.

  python win/run.py            소스 실행: 로그는 콘솔
  mabiaura.exe                 exe(콘솔 없음): 로그는 exe 옆 mabiaura.log (실행할 때마다 새로, 이전 것은 skilltrack.log.1)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _setup_logging():
    """콘솔이 없을 때(exe) stdout/stderr 를 파일로. print 로 찍던 로그와 예외 traceback 이 모두 여기 남는다."""
    from core.paths import DATA, FROZEN, EXE_NAME
    if not FROZEN and sys.stdout is not None:
        return
    log = DATA / f"{EXE_NAME}.log"
    try:
        if log.exists():
            log.replace(DATA / f"{EXE_NAME}.log.1")
        f = open(log, "w", encoding="utf-8", buffering=1)     # 줄 단위 flush (죽어도 남게)
        sys.stdout = sys.stderr = f
    except OSError:
        pass


if __name__ == "__main__":
    _setup_logging()
    from win.app import App
    try:
        sys.exit(App(sys.argv).exec())
    except Exception:
        import traceback
        traceback.print_exc()
        raise