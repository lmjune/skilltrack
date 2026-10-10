"""
윈도우 HDR 켜짐 감지 (게임 창이 있는 모니터).

HDR 이 켜지면 캡처 화면이 밝아져 부드러운 글꼴(UI 150%·UI 배율 조정 100%)의 글자가 255 로 꽉 차고,
꺼지면 200~250 으로 남는다. 둘은 글자 판정 기준이 달라 앱이 시작할 때 이걸로 고른다 (core/screen.set_hdr).

QueryDisplayConfig → 활성 경로마다 DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO (advancedColorEnabled).
경로의 원본 이름(\\\\.\\DISPLAY1)을 게임 창 모니터 이름과 맞춘다. 실패하면 None (호출 쪽이 기본값).
"""
import ctypes
from ctypes import wintypes

QDC_ONLY_ACTIVE_PATHS = 0x2
GET_SOURCE_NAME = 1
GET_ADVANCED_COLOR_INFO = 9
MONITOR_DEFAULTTONEAREST = 2


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", ctypes.c_uint32), ("HighPart", ctypes.c_int32)]


class PATH_SOURCE(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32),
                ("statusFlags", ctypes.c_uint32)]


class RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", ctypes.c_uint32), ("Denominator", ctypes.c_uint32)]


class PATH_TARGET(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32),
                ("outputTechnology", ctypes.c_uint32), ("rotation", ctypes.c_uint32), ("scaling", ctypes.c_uint32),
                ("refreshRate", RATIONAL), ("scanLineOrdering", ctypes.c_uint32), ("targetAvailable", ctypes.c_int32),
                ("statusFlags", ctypes.c_uint32)]


class PATH_INFO(ctypes.Structure):
    _fields_ = [("sourceInfo", PATH_SOURCE), ("targetInfo", PATH_TARGET), ("flags", ctypes.c_uint32)]


class MODE_INFO(ctypes.Structure):
    _fields_ = [("infoType", ctypes.c_uint32), ("id", ctypes.c_uint32), ("adapterId", LUID),
                ("data", ctypes.c_byte * 48)]


class HEADER(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("size", ctypes.c_uint32), ("adapterId", LUID), ("id", ctypes.c_uint32)]


class SOURCE_NAME(ctypes.Structure):
    _fields_ = [("header", HEADER), ("viewGdiDeviceName", ctypes.c_wchar * 32)]


class ADVANCED_COLOR_INFO(ctypes.Structure):
    _fields_ = [("header", HEADER), ("value", ctypes.c_uint32), ("colorEncoding", ctypes.c_uint32),
                ("bitsPerColorChannel", ctypes.c_uint32)]


class MONITORINFOEX(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", ctypes.c_wchar * 32)]


def _monitor_name(hwnd) -> str | None:
    try:
        u = ctypes.windll.user32
        u.MonitorFromWindow.restype = wintypes.HANDLE
        mon = u.MonitorFromWindow(wintypes.HWND(hwnd), MONITOR_DEFAULTTONEAREST)
        mi = MONITORINFOEX(); mi.cbSize = ctypes.sizeof(MONITORINFOEX)
        if u.GetMonitorInfoW(mon, ctypes.byref(mi)):
            return mi.szDevice
    except Exception:
        pass
    return None


def displays() -> list[tuple[str, bool]]:
    """[(원본 이름 '\\\\.\\DISPLAY1', HDR 켜짐)] 활성 모니터 전부."""
    u = ctypes.windll.user32
    n_path, n_mode = ctypes.c_uint32(), ctypes.c_uint32()
    if u.GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(n_path), ctypes.byref(n_mode)) != 0:
        return []
    paths = (PATH_INFO * n_path.value)(); modes = (MODE_INFO * n_mode.value)()
    if u.QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(n_path), paths, ctypes.byref(n_mode), modes, None) != 0:
        return []
    out = []
    for p in paths[:n_path.value]:
        sn = SOURCE_NAME()
        sn.header.type, sn.header.size = GET_SOURCE_NAME, ctypes.sizeof(SOURCE_NAME)
        sn.header.adapterId, sn.header.id = p.sourceInfo.adapterId, p.sourceInfo.id
        name = sn.viewGdiDeviceName if u.DisplayConfigGetDeviceInfo(ctypes.byref(sn)) == 0 else ""
        ci = ADVANCED_COLOR_INFO()
        ci.header.type, ci.header.size = GET_ADVANCED_COLOR_INFO, ctypes.sizeof(ADVANCED_COLOR_INFO)
        ci.header.adapterId, ci.header.id = p.targetInfo.adapterId, p.targetInfo.id
        if u.DisplayConfigGetDeviceInfo(ctypes.byref(ci)) != 0:
            continue
        out.append((name, bool(ci.value & 0x2)))          # 비트 1 = advancedColorEnabled
    return out


def hdr_enabled(hwnd=None) -> bool | None:
    """게임 창 모니터의 HDR 켜짐. 창을 모르면 모니터 중 하나라도 켜져 있으면 True. 알 수 없으면 None."""
    try:
        ds = displays()
    except Exception:
        return None
    if not ds:
        return None
    name = _monitor_name(hwnd) if hwnd else None
    if name:
        for n, on in ds:
            if n == name:
                return on
    return any(on for _, on in ds)
