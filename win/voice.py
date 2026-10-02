"""
소리 재생: 윈도우 내장 음성(SAPI, 예: Microsoft Heami)으로 문구를 wav 로 만들어 두고 재생 + 기본 효과음.

- 문구 wav 는 profiles/voice/ 에 캐시 (목소리·빠르기·문구별). 처음 한 번만 합성, 이후 즉시 재생.
- 볼륨은 재생용 사본에 곱해서 굽는다 (winsound 는 볼륨 조절이 없음). 음성/효과음 볼륨 따로.
- 재생은 별도 스레드 하나: 대기열(core/speech.SoundQueue)에서 꺼내 하나씩, 끝날 때까지 기다림.
  버스트(P_BURST)가 들어오면 기다리던 걸 끊고 바로 재생 (winsound 비동기 재생은 새 재생이 이전 것을 멈춘다).
- 음성을 못 쓰면 (SAPI 없음·한국어 목소리 없음) 효과음으로 대신.
"""
import hashlib
import threading
import time
import wave
from pathlib import Path

import numpy as np

from core.paths import ASSETS, PROFILES
from core.speech import P_BURST, SoundQueue, Utterance

VOICE_DIR = PROFILES / "voice"
SOUND_DIR = ASSETS / "sounds"
LEVEL_FILE = {"danger": "danger.wav", "warn": "warn.wav", "info": "info.wav", "ok": "info.wav"}
GAP = 0.15                      # 소리 사이 쉼


# ---------------------------------------------------------------- wav 다루기 (OS 무관)
def wav_duration(path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate() or 1)


def scaled_copy(src, volume: int, out_dir: Path) -> Path:
    """16비트 PCM wav 를 volume(0~100)% 로 줄인 사본. 이미 있으면 그대로."""
    src = Path(src)
    volume = max(0, min(100, int(volume)))
    if volume >= 100:
        return src
    key = hashlib.md5(f"{src.resolve()}|{src.stat().st_mtime_ns}|{volume}".encode()).hexdigest()[:12]
    dst = out_dir / f"v{volume}_{key}.wav"
    if dst.exists():
        return dst
    with wave.open(str(src), "rb") as r:
        params = r.getparams()
        data = r.readframes(r.getnframes())
    if params.sampwidth != 2:
        return src                                  # 16비트가 아니면 원본 (기본 효과음·SAPI 출력은 16비트)
    a = np.frombuffer(data, np.int16).astype(np.float32) * (volume / 100.0)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setparams(params)
        w.writeframes(np.clip(a, -32768, 32767).astype(np.int16).tobytes())
    tmp.replace(dst)
    return dst


# ---------------------------------------------------------------- 음성 합성 (Windows SAPI)
class Tts:
    """SAPI 로 문구 → wav. 스레드 하나에서만 쓴다 (COM)."""

    def __init__(self, voice_name="", rate=1):
        self.voice_name, self.rate = voice_name, int(rate)
        self.sp = None
        self.ok = None              # None = 아직 안 해 봄

    @staticmethod
    def list_voices() -> list[tuple[str, bool]]:
        """[(이름, 한국어인가)]. 실패하면 []."""
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            v = win32com.client.Dispatch("SAPI.SpVoice")
            out = []
            for i in range(v.GetVoices().Count):
                t = v.GetVoices().Item(i)
                lang = (t.GetAttribute("Language") or "").lower()
                out.append((t.GetDescription(), "412" in lang.split(";")))
            return out
        except Exception:
            return []

    def _init(self):
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            sp = win32com.client.Dispatch("SAPI.SpVoice")
            voices = [sp.GetVoices().Item(i) for i in range(sp.GetVoices().Count)]
            pick = None
            if self.voice_name:
                pick = next((t for t in voices if t.GetDescription() == self.voice_name), None)
            if pick is None:        # 기본: 한국어 목소리 (Language 412)
                pick = next((t for t in voices if "412" in (t.GetAttribute("Language") or "").lower().split(";")), None)
            if pick is None:
                print("음성: 한국어 목소리가 없습니다 → 효과음으로 대신")
                self.ok = False
                return
            sp.Voice = pick
            sp.Rate = max(-10, min(10, self.rate))
            self.sp, self.ok = sp, True
            print(f"음성: {pick.GetDescription()} (빠르기 {self.rate})")
        except Exception as e:
            print(f"음성 사용 불가 ({e}) → 효과음으로 대신")
            self.ok = False

    def path_for(self, text: str) -> Path:
        key = hashlib.md5(f"{self.voice_name}|{self.rate}|{text}".encode("utf-8")).hexdigest()[:16]
        return VOICE_DIR / f"{key}.wav"

    def synth(self, text: str) -> Path | None:
        """문구 wav 경로 (없으면 만듦). 실패하면 None."""
        p = self.path_for(text)
        if p.exists():
            return p
        if self.ok is None:
            self._init()
        if not self.ok:
            return None
        try:
            import win32com.client
            VOICE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp.wav")
            fmt = win32com.client.Dispatch("SAPI.SpAudioFormat")
            fmt.Type = 22                           # SAFT22kHz16BitMono
            st = win32com.client.Dispatch("SAPI.SpFileStream")
            st.Format = fmt
            st.Open(str(tmp), 3)                    # SSFMCreateForWrite
            self.sp.AudioOutputStream = st
            self.sp.Speak(text, 0)                  # 동기
            st.Close()
            self.sp.AudioOutputStream = None
            tmp.replace(p)
            return p
        except Exception as e:
            print(f"음성 합성 실패 '{text}': {e}")
            return None


# ---------------------------------------------------------------- 재생기
class Player:
    """대기열 하나 + 재생 스레드 하나. app 은 say()/prewarm()/set_options() 만 부른다."""

    def __init__(self, voice=True, voice_volume=90, effect_volume=70, rate=1, voice_name="", effect_file=""):
        self.q = SoundQueue()
        self.lock = threading.Condition()
        self.voice, self.voice_volume, self.effect_volume = voice, voice_volume, effect_volume
        self.effect_file = effect_file
        self.tts = Tts(voice_name, rate)
        self.prewarm_list: list[str] = []
        self.busy_until = 0.0
        self.running = True
        self.th = threading.Thread(target=self._loop, name="sound", daemon=True)
        self.th.start()

    # ---- app 쪽
    def set_options(self, voice, voice_volume, effect_volume, rate, voice_name, effect_file):
        with self.lock:
            self.voice, self.voice_volume, self.effect_volume = voice, voice_volume, effect_volume
            self.effect_file = effect_file
            if (rate, voice_name) != (self.tts.rate, self.tts.voice_name):
                self.tts = Tts(voice_name, rate)
            self.lock.notify_all()

    def say(self, u: Utterance):
        with self.lock:
            if self.q.push(u):
                self.lock.notify_all()

    def prewarm(self, texts):
        """자주 쓸 문구를 미리 합성 (버스트가 첫 재생에서 늦지 않게). 백그라운드."""
        with self.lock:
            self.prewarm_list = list(dict.fromkeys(t for t in texts if t))
            self.lock.notify_all()

    def stop(self):
        with self.lock:
            self.running = False
            self.lock.notify_all()

    # ---- 스레드
    def _effect_path(self, level) -> Path | None:
        p = Path(self.effect_file) if self.effect_file else SOUND_DIR / LEVEL_FILE.get(level, "info.wav")
        return p if p.exists() else None

    def _resolve(self, u: Utterance) -> Path | None:
        if u.kind == "voice" and self.voice:
            p = self.tts.synth(u.text)
            if p is not None:
                return scaled_copy(p, self.voice_volume, VOICE_DIR / "play")
        p = self._effect_path(u.level)                                     # 효과음 (또는 음성 실패 시 대신)
        return scaled_copy(p, self.effect_volume, VOICE_DIR / "play") if p else None

    def _play(self, path: Path):
        try:
            import winsound
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except Exception:
            pass

    def _loop(self):
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass
        while True:
            with self.lock:
                while self.running:
                    now = time.time()
                    urgent = self.q.has_urgent()
                    if (now >= self.busy_until or urgent) and len(self.q):
                        break
                    if self.prewarm_list and now >= self.busy_until:
                        break
                    wait = max(0.02, self.busy_until - now) if self.busy_until > now else 0.5
                    self.lock.wait(timeout=min(wait, 0.5))
                if not self.running:
                    return
                u = self.q.pop(time.time()) if len(self.q) else None
                warm = self.prewarm_list.pop(0) if (u is None and self.prewarm_list) else None
            if warm is not None:
                if self.voice:
                    self.tts.synth(warm)
                continue
            if u is None:
                continue
            try:
                path = self._resolve(u)
                if path is None:
                    continue
                self._play(path)
                self.busy_until = time.time() + wav_duration(path) + GAP
            except Exception as e:
                print(f"소리 재생 실패: {e}")
