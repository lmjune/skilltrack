"""소리 알림 규칙 (core/speech.py)."""
from core.speech import (P_BOSS, P_BURST, P_OFF, P_STATUS, Planner, SoundCfg, SoundQueue, Utterance, keep_phrase,
                         merge, phrase, spoken_name)

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


def test_keep_spoken_every_time_with_text():
    """반복 알림은 화면 알림과 같은 순간에, 사용자가 정한 간격 그대로 (예전처럼 20초 묶음으로 건너뛰지 않음)."""
    p = Planner()
    assert texts(p.plan([("keep", "서곡", None), ("keep", "상지", None)], cfg_all(), 100.0)) == ["상지, 서곡 꺼져 있음"]
    assert texts(p.plan([("keep", "서곡", None), ("keep", "상지", None)], cfg_all(), 110.0)) == ["상지, 서곡 꺼져 있음"]
    assert texts(p.plan([], cfg_all(), 115.0)) == []


def test_keep_many_names_shortened():
    assert keep_phrase(["a", "b", "c", "d"]) == "버프 4개 꺼져 있음"


def test_modes_effect_and_none():
    p = Planner()
    us = p.plan([("off", "a", None), ("under", "b", 30)], lambda l: SoundCfg("effect" if l == "a" else "none"), 0)
    assert [(u.kind, u.level) for u in us] == [("effect", "danger")]


def test_queue_latest_wins_and_priority():
    q = SoundQueue()
    q.push(Utterance("voice", "햄버프 30초", prio=P_STATUS, at=0))
    q.push(Utterance("voice", "마나실드 꺼짐", prio=P_STATUS, at=0.2))       # 같은 우선순위 → 최신이 대신
    q.push(Utterance("voice", "모모 빠짐", prio=P_BOSS, at=0.2))
    q.push(Utterance("voice", "붕파 적용!", prio=P_BURST, at=0.3))
    assert [q.pop(0.5).text for _ in range(3)] == ["붕파 적용!", "마나실드 꺼짐", "모모 빠짐"]
    q.push(Utterance("voice", "오래됨", prio=P_STATUS, at=0))
    assert q.pop(5.0) is None                                                # 너무 오래 기다림 → 버림


def test_merge_one_tick():
    us = [Utterance("voice", "마나실드 꺼짐", prio=P_OFF), Utterance("voice", "햄버프 30초"),
          Utterance("effect", level="warn")]
    m = merge(us, 1.0)
    assert m.kind == "voice" and m.text == "마나실드 꺼짐, 햄버프 30초" and m.prio == P_STATUS
    e = merge([Utterance("effect", level="warn"), Utterance("effect", level="danger")], 1.0)
    assert e.kind == "effect" and e.level == "danger"
    assert merge([], 1.0) is None


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


def _player(monkeypatch, tmp_path, lengths):
    import time
    import wave
    import numpy as np
    import win.voice as V
    files = {}
    for text, secs in lengths.items():
        p = tmp_path / f"{len(files)}.wav"
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
            w.writeframes(np.zeros(int(8000 * secs), np.int16).tobytes())
        files[text] = p
    played = []
    names = {v.stem: k for k, v in files.items()}
    monkeypatch.setattr(V.Tts, "synth", lambda self, t: files[t])
    monkeypatch.setattr(V.Player, "_play", lambda self, p: played.append((names[p.stem], time.time())))
    monkeypatch.setattr(V.Player, "_stop", lambda self: None)
    return V.Player(voice=True, voice_volume=100), played


def test_player_new_interrupts_same_or_higher(monkeypatch, tmp_path):
    """같거나 높은 우선순위가 오면 재생 중인 것을 끊고 바로 (밀려서 늦게 나오지 않게)."""
    import time
    pl, played = _player(monkeypatch, tmp_path, {"상태1": 1.0, "상태2": 0.3, "붕파": 0.3})
    t0 = time.time()
    pl.say(Utterance("voice", "상태1", prio=P_STATUS, at=t0))
    time.sleep(0.2)
    pl.say(Utterance("voice", "상태2", prio=P_STATUS, at=time.time()))      # 같은 우선순위 → 끊음
    time.sleep(0.15)
    pl.say(Utterance("voice", "붕파", prio=P_BURST, at=time.time()))        # 높은 우선순위 → 끊음
    time.sleep(0.6)
    pl.stop()
    assert [n for n, _ in played] == ["상태1", "상태2", "붕파"]
    assert played[1][1] - t0 < 0.4 and played[2][1] - t0 < 0.6               # 1초짜리 '상태1'을 안 기다림


def test_player_lower_waits_then_drops(monkeypatch, tmp_path):
    """낮은 우선순위는 높은 것이 끝날 때까지 기다리고, 너무 길면 버린다 (상태창 1.5초, 보스 6초)."""
    import time
    pl, played = _player(monkeypatch, tmp_path, {"붕파": 0.4, "보스1": 0.1, "긴붕파": 2.5, "상태": 0.1, "보스2": 0.1})
    pl.say(Utterance("voice", "붕파", prio=P_BURST, at=time.time()))
    time.sleep(0.1)
    pl.say(Utterance("voice", "보스1", prio=P_BOSS, at=time.time()))         # 붕파(0.4초) 끝나고 나옴
    time.sleep(0.8)
    pl.say(Utterance("voice", "긴붕파", prio=P_BURST, at=time.time()))
    time.sleep(0.1)
    pl.say(Utterance("voice", "상태", prio=P_STATUS, at=time.time()))        # 2.5초 기다려야 함 → 버림 (1.5초 한도)
    pl.say(Utterance("voice", "보스2", prio=P_BOSS, at=time.time()))         # 보스는 6초까지 기다림 → 나옴
    time.sleep(3.0)
    pl.stop()
    assert [n for n, _ in played] == ["붕파", "보스1", "긴붕파", "보스2"]


def test_player_interrupted_boss_replays(monkeypatch, tmp_path):
    """보스 알림이 막 시작했는데 상태창 알림이 끊으면, 상태창 끝나고 다시 나온다 (같은 틱에 둘 다 온 경우)."""
    import time
    pl, played = _player(monkeypatch, tmp_path, {"모모 빠짐": 1.0, "서곡 꺼짐": 0.3})
    pl.say(Utterance("voice", "모모 빠짐", prio=P_BOSS, at=time.time()))
    time.sleep(0.1)
    pl.say(Utterance("voice", "서곡 꺼짐", prio=P_STATUS, at=time.time()))
    time.sleep(1.0)
    pl.stop()
    assert [n for n, _ in played] == ["모모 빠짐", "서곡 꺼짐", "모모 빠짐"]


def test_boss_debuff_voice():
    from core.speech import boss_utterance
    modes = {"모모": "voice", "야옹": "voice", "물풍선": "effect"}.get
    u = boss_utterance([("missing", "모모", None, False), ("under", "야옹", 20, False)], modes, 1.0)
    assert u.kind == "voice" and u.text == "모모 빠짐, 야옹 20초" and u.prio == P_BOSS
    # 전투 시작 때 처음부터 없는 것도 말함 (목록에 바로 뜸). 감시 아닌 것·걸림은 조용히
    u = boss_utterance([("missing", "모모", None, True), ("missing", "기타", None, False),
                        ("found", "야옹", None, False)], modes, 1.0)
    assert u.text == "모모 빠짐"
    assert boss_utterance([("found", "야옹", None, False)], modes, 1.0) is None
    # 효과음 항목만이면 효과음 하나
    e = boss_utterance([("missing", "물풍선", None, False)], modes, 1.0)
    assert e.kind == "effect" and e.prio == P_BOSS


def test_boss_debuff_many_grouped():
    from core.speech import boss_utterance
    ev = [("missing", n, None, False) for n in ("a", "b", "c", "d")]
    assert boss_utterance(ev, lambda l: "voice", 1.0).text == "보스 디버프 4개 빠짐"


def test_boss_tracker_initial_missing_flagged():
    from core.bossbar import BarRead
    from core.bosstrack import BossTracker, DebuffWatch
    t = BossTracker([DebuffWatch("i1", "모모")])
    from types import SimpleNamespace as NS
    def frame(on):
        return BarRead(anchor=object(), slots=[NS(icon_id="i1", seconds=20, label="20", icon=None)] if on else [], strip=True)
    ev = []
    for i in range(6):
        ev += t.update(frame(False), now=float(i))
    miss = [e for e in ev if e.kind == "missing"]
    assert len(miss) == 1 and miss[0].initial                          # 원래 없던 것 → 말하지 않음 표시
    ev = []
    for i in range(6, 9):
        ev += t.update(frame(True), now=float(i))
    for i in range(9, 15):
        ev += t.update(frame(False), now=float(i))
    miss = [e for e in ev if e.kind == "missing"]
    assert len(miss) == 1 and not miss[0].initial                      # 걸려 있다가 빠짐 → 말함


def test_tracker_keep_aligned():
    """1초 차이로 꺼진 두 버프의 반복 알림이 같은 순간에 나간다 (글씨·소리 한 번에)."""
    from core.tracker import Tracker, Watch
    from types import SimpleNamespace as NS
    t = Tracker([Watch(b"a", "A", row_index=0, keep=True, keep_delay=10, keep_interval=10, alert_off=False),
                 Watch(b"b", "B", row_index=1, keep=True, keep_delay=10, keep_interval=10, alert_off=False)], debounce=1)
    def rows(a_on, b_on):
        return [NS(index=0, active=a_on, name_width=None, extended=None), NS(index=1, active=b_on, name_width=None, extended=None)]
    t.update(rows(True, True), {}, now=0.0)
    t.update(rows(False, True), {}, now=1.0)            # A 꺼짐
    t.update(rows(False, False), {}, now=2.0)           # B 1초 뒤 꺼짐
    got = []
    for i in range(30, 400):
        now = i / 10
        for e in t.update(rows(False, False), {}, now=now):
            if e.kind == "keep":
                got.append((round(now, 1), e.label))
    times = {}
    for now, label in got:
        times.setdefault(now, []).append(label)
    assert all(sorted(v) == ["A", "B"] for v in times.values()), times
    assert len(times) >= 3


def test_boss_repeat_every_20s():
    from core.speech import BossSpeaker
    sp = BossSpeaker()
    mode = lambda l: "voice"
    assert sp.plan([("missing", "모모", None, True)], ["모모"], mode, 0.0).text == "모모 빠짐"
    assert sp.plan([], ["모모"], mode, 10.0) is None
    assert sp.plan([("missing", "야옹", None, False)], ["모모", "야옹"], mode, 18.5).text == "야옹 빠짐"
    # 마지막 알림(18.5) 후 20초 → 빠져 있는 것 전부 한 문장
    assert sp.plan([], ["모모", "야옹"], mode, 20.0) is None
    assert sp.plan([], ["모모", "야옹"], mode, 38.5).text == "모모 빠짐, 야옹 빠짐"
    assert sp.plan([], ["모모", "야옹"], mode, 50.0) is None
    # 하나 걸리면 남은 것만
    assert sp.plan([("found", "모모", None, False)], ["야옹"], mode, 58.5).text == "야옹 빠짐"
    # 전부 걸리면 끝
    assert sp.plan([], [], mode, 80.0) is None
    assert sp.plan([], [], mode, 100.0) is None
