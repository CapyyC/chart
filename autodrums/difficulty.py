"""Deriving Hard / Medium / Easy drum charts from the Expert chart."""

from __future__ import annotations

from .kit import LANE_KICK, Gem
from .tempo import RESOLUTION

HALF = RESOLUTION // 2


def _metric_weight(tick: int, downbeats: set[int]) -> int:
    if tick in downbeats:
        return 4
    if tick % RESOLUTION == 0:
        return 3
    if tick % HALF == 0:
        return 2
    if tick % (RESOLUTION // 4) == 0:
        return 1
    return 0


def _chords(gems: list[Gem]) -> dict[int, list[Gem]]:
    out: dict[int, list[Gem]] = {}
    for g in gems:
        out.setdefault(g.tick, []).append(g)
    return out


def _copy(g: Gem) -> Gem:
    return Gem(g.time, g.lane, g.cymbal, g.strength, g.source, g.tick)


def _thin_lane(gems: list[Gem], min_gap: int, downbeats: set[int]) -> list[Gem]:
    """Within one lane group, drop gems closer than min_gap ticks, keeping metrically stronger ones."""
    gems = sorted(gems, key=lambda g: g.tick)
    kept: list[Gem] = []
    for g in gems:
        if kept and g.tick - kept[-1].tick < min_gap:
            if _metric_weight(g.tick, downbeats) > _metric_weight(kept[-1].tick, downbeats):
                kept[-1] = g
            continue
        kept.append(g)
    return kept


def reduce(expert: list[Gem], level: str, downbeats: set[int]) -> list[Gem]:
    gems = [_copy(g) for g in expert]
    if level == "expert":
        return gems
    kicks = [g for g in gems if g.lane == LANE_KICK]
    hands = [g for g in gems if g.lane != LANE_KICK]

    if level == "hard":
        kicks = _thin_lane(kicks, HALF, downbeats)
        # Fast hand runs (faster than 8ths) keep only the 8th-note grid; isolated 16ths survive.
        hand_ticks = sorted({g.tick for g in hands})
        dense = set()
        for a, b in zip(hand_ticks, hand_ticks[1:]):
            if b - a < HALF:
                dense.add(a)
                dense.add(b)
        hands = [g for g in hands if g.tick not in dense or g.tick % HALF == 0 or g.source == "snare"]
        hands = _thin_lane_per_lane(hands, RESOLUTION // 4, downbeats)
        return _limit(kicks + hands, max_hands=2, kick_with_hands=True)

    if level == "medium":
        hands = [g for g in hands if g.tick % HALF == 0]
        kicks = [g for g in kicks if g.tick % HALF == 0]
        kicks = _thin_lane(kicks, RESOLUTION, downbeats) if _too_dense(kicks) else kicks
        out = _limit(kicks + hands, max_hands=1, kick_with_hands=True)
        return out

    if level == "easy":
        hands = [g for g in hands if g.tick % RESOLUTION == 0]
        kicks = [g for g in kicks if g.tick % RESOLUTION == 0]
        return _limit(kicks + hands, max_hands=1, kick_with_hands=False)
    raise ValueError(level)


def _too_dense(kicks: list[Gem]) -> bool:
    ticks = sorted(g.tick for g in kicks)
    if len(ticks) < 8:
        return False
    close = sum(1 for a, b in zip(ticks, ticks[1:]) if b - a <= HALF)
    return close / len(ticks) > 0.4


def _thin_lane_per_lane(hands: list[Gem], min_gap: int, downbeats: set[int]) -> list[Gem]:
    out: list[Gem] = []
    for lane in {g.lane for g in hands}:
        out.extend(_thin_lane([g for g in hands if g.lane == lane], min_gap, downbeats))
    return out


HAND_RANK = {"snare": 6, "crash": 5, "tom_hi": 4, "tom_mid": 4, "tom_lo": 4, "ride": 3, "hihat": 2}


def _limit(gems: list[Gem], max_hands: int, kick_with_hands: bool) -> list[Gem]:
    out: list[Gem] = []
    for _tick, group in sorted(_chords(gems).items()):
        kicks = [g for g in group if g.lane == LANE_KICK]
        hands = sorted((g for g in group if g.lane != LANE_KICK),
                       key=lambda g: (-HAND_RANK.get(g.source, 1), -g.strength))[:max_hands]
        if kick_with_hands:
            out.extend(kicks[:1] + hands)
        else:
            # Easy: one gem per beat. Snare beats stay snare, otherwise prefer the kick.
            if hands and hands[0].source == "snare":
                out.append(hands[0])
            elif kicks:
                out.append(kicks[0])
            elif hands:
                out.append(hands[0])
    return sorted(out, key=lambda g: (g.tick, g.lane))
