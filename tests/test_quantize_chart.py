import numpy as np

from autodrums import chartio, difficulty, kit, quantize, tempo
from autodrums.chart import ChartData, SongMeta, make_phrases, write_chart, write_ini
from autodrums.kit import Gem
from autodrums.tempo import RESOLUTION


def _steady_map(bpm=120.0, n=200, start=0.0):
    beats = start + 60.0 / bpm * np.arange(n)
    lg = np.full(int((beats[-1] + 5) * 50), -8.0)
    for i, b in enumerate(beats):
        if i % 4 == 0:
            lg[int(round(b * 50))] = 4.0
    return tempo.build_tempo_map(beats, lg, beats.copy(), beats[-1] + 1, first_note=start + 3.0)


def test_quantize_sixteenths_and_triplets():
    tm = _steady_map()
    rng = np.random.default_rng(3)
    beat0 = tm.beat_times[tm.origin + 8]
    sixteenths = beat0 + 0.125 * np.arange(8) + rng.normal(0, 0.006, 8)
    beat1 = tm.beat_times[tm.origin + 12]
    triplets = beat1 + (0.5 / 3) * np.arange(6) + rng.normal(0, 0.006, 6)
    ticks = quantize.quantize_times(np.concatenate([sixteenths, triplets]), tm)
    assert list(ticks[:8]) == [8 * RESOLUTION + k * RESOLUTION // 4 for k in range(8)]
    assert list(ticks[8:]) == [12 * RESOLUTION + k * RESOLUTION // 3 for k in range(6)]


def _gem(tick, lane, cym, source, strength=0.8):
    return Gem(0.0, lane, cym, strength, source, tick)


def test_conflicts_resolved():
    g = [
        _gem(0, 0, False, "kick"),
        _gem(0, 1, False, "snare"),
        _gem(0, 2, True, "hihat"),
        _gem(0, 4, True, "crash"),
        _gem(480, 2, True, "hihat"),
        _gem(480, 2, False, "tom_hi"),
    ]
    out = kit.resolve_conflicts(g)
    at0 = [x for x in out if x.tick == 0]
    assert sum(1 for x in at0 if x.lane != 0) == 2  # two hands max
    assert any(x.source == "snare" for x in at0) and any(x.source == "crash" for x in at0)
    at480 = [x for x in out if x.tick == 480]
    lanes = [x.lane for x in at480]
    assert len(lanes) == len(set(lanes)) == 2  # tom moved off the hi-hat lane


def test_cluster_toms_three_pitches():
    rng = np.random.default_rng(0)
    p = np.concatenate([rng.normal(220, 5, 10), rng.normal(150, 4, 10), rng.normal(95, 3, 10)])
    lanes = kit.cluster_toms(p)
    assert set(lanes[:10]) == {kit.LANE_YELLOW}
    assert set(lanes[10:20]) == {kit.LANE_BLUE}
    assert set(lanes[20:]) == {kit.LANE_GREEN}


def test_ride_vs_crash_patterns():
    beat = 0.5
    ride = 10.0 + 0.25 * np.arange(16)          # 8th-note ride pattern
    crashes = np.array([2.0, 20.0, 30.0])        # isolated accents
    times = np.sort(np.concatenate([ride, crashes]))
    is_ride = kit.classify_cymbals(times, np.array([10.0]), np.full(len(times), beat))
    res = dict(zip(np.round(times, 3), is_ride))
    assert not res[2.0] and not res[20.0] and not res[30.0]
    assert not res[10.0]  # crash on the one with the kick
    assert all(res[round(t, 3)] for t in ride[1:])


def _expert_track():
    gems = []
    for bar in range(8):
        base = bar * 4 * RESOLUTION
        for k in range(16):  # 16th hi-hats
            gems.append(_gem(base + k * RESOLUTION // 4, 2, True, "hihat"))
        for b in (0, 2):
            gems.append(_gem(base + b * RESOLUTION, 0, False, "kick"))
            gems.append(_gem(base + b * RESOLUTION + RESOLUTION * 3 // 4, 0, False, "kick"))
        for b in (1, 3):
            gems.append(_gem(base + b * RESOLUTION, 1, False, "snare"))
    gems.append(_gem(8 * 4 * RESOLUTION, 4, True, "crash"))
    gems.append(_gem(8 * 4 * RESOLUTION, 0, False, "kick"))
    return sorted(gems, key=lambda g: (g.tick, g.lane))


def test_difficulty_reductions():
    expert = _expert_track()
    downs = set(range(0, 40 * RESOLUTION, 4 * RESOLUTION))
    hard = difficulty.reduce(expert, "hard", downs)
    medium = difficulty.reduce(expert, "medium", downs)
    easy = difficulty.reduce(expert, "easy", downs)
    assert len(expert) > len(hard) > len(medium) > len(easy) > 0
    assert all(g.tick % (RESOLUTION // 2) == 0 for g in medium)
    assert all(g.tick % RESOLUTION == 0 for g in easy)
    for track, max_hands in ((hard, 2), (medium, 1), (easy, 1)):
        by = {}
        for g in track:
            by.setdefault(g.tick, []).append(g)
        assert all(sum(1 for g in grp if g.lane != 0) <= max_hands for grp in by.values())
    by = {}
    for g in easy:
        by.setdefault(g.tick, []).append(g)
    assert all(len(grp) == 1 for grp in by.values())


def test_chart_roundtrip(tmp_path):
    tm = _steady_map()
    expert = _expert_track()
    downs = set(tm.downbeat_ticks)
    tracks = {d: difficulty.reduce(expert, d, downs) for d in ("expert", "hard", "medium", "easy")}
    data = ChartData(tempo=tm, tracks=tracks)
    make_phrases(data)
    meta = SongMeta(title='Song "X"', artist="Band", length_ms=100000, has_drum_stem=True)
    write_chart(tmp_path / "notes.chart", data, meta)
    write_ini(tmp_path / "song.ini", meta, 3)
    pc = chartio.read_chart(tmp_path / "notes.chart")
    assert pc.resolution == RESOLUTION
    assert pc.tempos[0] == (0, tm.tempos[0][1])
    assert set(pc.tracks) == {"expert", "hard", "medium", "easy"}
    got = {(g.tick, g.lane, g.cymbal) for g in pc.tracks["expert"]}
    want = {(g.tick, g.lane, g.cymbal) for g in tracks["expert"]}
    assert got == want
    assert pc.song["DrumStream"] == "drums.ogg"
    ini = (tmp_path / "song.ini").read_text()
    assert "pro_drums = True" in ini and "diff_drums = 3" in ini
    raw = (tmp_path / "notes.chart").read_text(encoding="utf-8-sig")
    assert "N 66 0" in raw  # yellow cymbal markers present


def test_tom_pitch_estimates_fundamental():
    sr = 44100
    rng = np.random.default_rng(5)
    for f0 in (90.0, 140.0, 210.0):
        t = np.arange(int(0.4 * sr)) / sr
        # pitch glides down slightly after the stick hit, plus some attack noise
        f = f0 * (1 + 0.15 * np.exp(-t * 30))
        tone = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 8)
        x = np.concatenate([np.zeros(sr // 10), tone + 0.05 * rng.standard_normal(len(t)) * np.exp(-t * 60)])
        est = kit.tom_pitch(x.astype(np.float32), sr, 0.1)
        assert abs(12 * np.log2(est / f0)) < 1.5, (f0, est)
