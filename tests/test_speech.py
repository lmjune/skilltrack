"""소리 알림 규칙 (core/speech.py)."""
from core.speech import (P_BURST, P_OFF, Planner, SoundCfg, SoundQueue, Utterance, keep_phrase, phrase,
                         spoken_name)

VOICE = SoundCfg("voice")


def cfg_all(mode="voice"):
    return lambda label: SoundCfg(mode)


def texts(us):
    return [u.text for u in us if u.kind == "voice"]


def test_phrases():
    assert phrase("off", "마나실드") == "마나실드 꺼짐"
    assert phrase("under", "햄버프", 30) == "햄버프 30초"
    assert phrase("resync", "햄버프", 179) is None          # 갱신은 내가 한 일 → 말 안 함
    assert spoken_name("행3", None) == "4번 버프"            # TTS 가 '행삼'으로 읽지 않게
    assert spoken_name("마나실드", SoundCfg("voice", "실드")) == "실드"


def test_single_off_spoken():
    p = Planner()
    assert texts(p.plan([("off", "마나실드", None)], cfg_all(), 0)) == ["마나실드 꺼짐"]


def test_many_offs_grouped_then_silent():
    p = Planner()
    ev = [("off", n, None) for n in ("서곡", "햄버프", "물공포", "마나실드", "상지", "행진곡")]
    assert texts(p.plan(ev, cfg_all(), 100.0)) == ["버프 6개 꺼짐"]
    # 같은 사건으로 1초 뒤 더 꺼진 것은 조용히
    assert texts(p.plan([("off", "반신화", None)], cfg_all(), 101.0)) == []
    # 한참 뒤 하나 꺼지면 다시 말함
    assert texts(p.plan([("off", "마나실드", None)], cfg_all(), 110.0)) == ["마나실드 꺼짐"]


def test_keep_combined_and_rate_limited():
    p = Planner()
    ev = [("keep", n, None) for n in ("서곡", "햄버프", "상지")]
    assert texts(p.plan(ev, cfg_all(), 100.0)) == ["서곡, 햄버프, 상지 꺼져 있음"]
    # 10초 뒤 또 요청이 와도 KEEP_GAP(20초) 안이면 조용히, 그 뒤 한 번에
    assert texts(p.plan([("keep", "서곡", None)], cfg_all(), 110.0)) == []
    assert texts(p.plan([("keep", "햄버프", None)], cfg_all(), 121.0)) == ["서곡, 햄버프 꺼져 있음"]


def test_keep_drops_buff_turned_on():
    p = Planner()
    p.plan([("keep", "서곡", None), ("keep", "상지", None)], cfg_all(), 100.0)
    p.plan([("keep", "서곡", None), ("keep", "상지", None)], cfg_all(), 110.0)
    p.plan([("on", "서곡", None)], cfg_all(), 115.0)
    assert texts(p.plan([], cfg_all(), 121.0)) == ["상지 꺼져 있음"]


def test_keep_many_names_shortened():
    assert keep_phrase(["a", "b", "c", "d"]) == "버프 4개 꺼져 있음"


def test_modes_effect_and_none():
    p = Planner()
    us = p.plan([("off", "a", None), ("under", "b", 30)], lambda l: SoundCfg("effect" if l == "a" else "none"), 0)
    assert [(u.kind, u.level) for u in us] == [("effect", "danger")]


def test_queue_priority_stale_dedupe():
    q = SoundQueue()
    q.push(Utterance("voice", "햄버프 30초", prio=2, at=0, key="햄버프 30초"))
    assert not q.push(Utterance("voice", "햄버프 30초", prio=2, at=0.1, key="햄버프 30초"))   # 중복
    q.push(Utterance("voice", "마나실드 꺼짐", prio=P_OFF, at=0.2, key="m"))
    q.push(Utterance("voice", "붕파!", prio=P_BURST, at=0.3, key="b"))
    assert q.has_urgent()
    assert [q.pop(0.5).text for _ in range(3)] == ["붕파!", "마나실드 꺼짐", "햄버프 30초"]
    q.push(Utterance("voice", "오래됨", prio=2, at=0, key="x"))
    assert q.pop(10.0) is None                                                               # 3초 넘게 기다림 → 버림


def test_scaled_copy_volume(tmp_path):
    import wave
    import numpy as np
    from win.voice import scaled_copy, wav_duration
    src = tmp_path / "a.wav"
    with wave.open(str(src), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
        w.writeframes((np.ones(22050, np.int16) * 10000).tobytes())
    assert abs(wav_duration(src) - 1.0) < 1e-6
    assert scaled_copy(src, 100, tmp_path / "play") == src
    dst = scaled_copy(src, 50, tmp_path / "play")
    with wave.open(str(dst), "rb") as r:
        a = np.frombuffer(r.readframes(r.getnframes()), np.int16)
    assert int(a[0]) == 5000
    assert scaled_copy(src, 50, tmp_path / "play") == dst          # 캐시


def test_player_order_and_burst_preempts(monkeypatch, tmp_path):
    """재생 스레드: 하나씩 순서대로, 버스트는 기다리지 않고 바로."""
    import time
    import wave
    import numpy as np
    import win.voice as V

    def mk(name, secs):
        p = tmp_path / f"{name}.wav"
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
            w.writeframes(np.zeros(int(8000 * secs), np.int16).tobytes())
        return p
    files = {"긴 말": mk("long", 1.0), "짧은 말": mk("short", 0.1), "붕파!": mk("burst", 0.1)}
    played = []
    monkeypatch.setattr(V.Tts, "synth", lambda self, t: files[t])
    monkeypatch.setattr(V.Player, "_play", lambda self, p: played.append((p.stem, time.time())))
    pl = V.Player(voice=True, voice_volume=100)
    t0 = time.time()
    pl.say(Utterance("voice", "긴 말", prio=2, at=t0, key="a"))
    pl.say(Utterance("voice", "짧은 말", prio=2, at=t0, key="b"))
    time.sleep(0.2)
    pl.say(Utterance("voice", "붕파!", prio=P_BURST, at=time.time(), key="c"))
    time.sleep(1.6)
    pl.stop()
    names = [n for n, _ in played]
    assert names == ["long", "burst", "short"], names
    assert played[1][1] - t0 < 0.5                     # 버스트는 '긴 말'(1초)이 끝나길 안 기다림
