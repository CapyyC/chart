import numpy as np

from autodrums import tempo
from autodrums.tempo import RESOLUTION


def _logits_for(beats, meter, n_frames, phase=0):
    """Fake downbeat logits: strong at every `meter`-th beat."""
    lg = np.full(n_frames, -8.0)
    for i, b in enumerate(beats):
        if (i - phase) % meter == 0:
            f = int(round(b * 50))
            if 0 <= f < n_frames:
                lg[f] = 4.0
    return lg


def test_constant_tempo_gives_single_bpm():
    rng = np.random.default_rng(0)
    true = 1.3 + 0.5 * np.arange(300)  # 120 BPM
    tracked = true + rng.normal(0, 0.008, len(true))
    lg = _logits_for(true, 4, int(160 * 50))
    tm = tempo.build_tempo_map(tracked, lg, true.copy(), 155.0, first_note=1.3)
    assert len(tm.tempos) == 1
    assert abs(tm.tempos[0][1] - 120000) < 150
    assert tm.time_sigs[0][1] == 4
    # Notes on the true beats land within a few ms in chart time.
    for b in true[::17]:
        tick = round(tm.tick_of_beat(tm.beat_position(b)))
        assert abs(tm.chart_seconds(tick) - (b + tm.pad)) < 0.012


def test_lead_in_and_bar_aligned_start():
    true = 0.4 + 0.5 * np.arange(200)
    lg = _logits_for(true, 4, 120 * 50, phase=1)  # first downbeat is the 2nd beat
    tm = tempo.build_tempo_map(true, lg, true.copy(), 100.0, first_note=0.4)
    assert tm.pad >= 2.0  # room before the first note
    # tick 0 is a bar line and the first tracked downbeat sits on a bar line too
    first_down_tick = round(tm.tick_of_beat(tm.beat_position(true[1])))
    assert first_down_tick % (4 * RESOLUTION) == 0


def test_tempo_change_detected():
    a = 1.0 + 0.5 * np.arange(120)            # 120 BPM
    b = a[-1] + 0.4 * np.arange(1, 150)       # 150 BPM
    beats = np.concatenate([a, b])
    tm = tempo.build_tempo_map(beats, _logits_for(beats, 4, 140 * 50), beats.copy(), 121.0, 1.0)
    bpms = sorted({round(m / 1000) for _, m in tm.tempos})
    assert 120 in bpms and 150 in bpms
    assert len(tm.tempos) <= 4


def test_half_time_section_is_normalised():
    a = 1.0 + 0.5 * np.arange(60)
    half = a[-1] + 1.0 * np.arange(1, 16)  # tracker drops to half time
    c = half[-1] + 0.5 * np.arange(1, 60)
    beats = np.concatenate([a, half, c])
    cleaned, _ = tempo.clean_beats(beats)
    ibi = np.diff(cleaned)
    assert np.all(np.abs(ibi - 0.5) < 0.05)


def test_displaced_beat_is_repaired():
    beats = 1.0 + 0.5 * np.arange(80)
    beats[40] -= 0.22  # one wildly misplaced beat
    cleaned, w = tempo.clean_beats(beats)
    assert len(cleaned) == 80
    assert abs(cleaned[40] - (1.0 + 0.5 * 40)) < 0.01
    assert w[40] < 1.0


def test_three_four_meter():
    beats = 1.0 + 0.6 * np.arange(150)
    tm = tempo.build_tempo_map(beats, _logits_for(beats, 3, 100 * 50), beats.copy(), 92.0, 1.0)
    assert tm.time_sigs[0][1] == 3
    assert len(tm.time_sigs) == 1


def test_chart_seconds_matches_beat_grid():
    rng = np.random.default_rng(1)
    beats = np.cumsum(0.45 + 0.05 * np.sin(np.arange(200) / 15.0)) + 2.0  # drifting tempo
    beats += rng.normal(0, 0.003, len(beats))
    tm = tempo.build_tempo_map(beats, _logits_for(beats, 4, 110 * 50), beats.copy(), 100.0, 2.0)
    errs = []
    for b in beats[5:-5]:
        tick = tm.tick_of_beat(tm.beat_position(b))
        errs.append(abs(tm.chart_seconds(tick) - (b + tm.pad)))
    assert np.median(errs) < 0.012
