"""A Clone Hero-style note highway that previews a pro drums chart."""

from __future__ import annotations

import bisect

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)
from PySide6.QtWidgets import QWidget

from .theme import LANE_COLORS

# Pad lanes (1..4) across the highway; the kick spans the full width.
PAD_LANES = [1, 2, 3, 4]


class HighwayWidget(QWidget):
    seekRequested = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 360)
        self.gems = []            # list of (time, lane, cymbal, in_star_power)
        self.times: list[float] = []
        self.bar_times: list[float] = []
        self.beat_times: list[float] = []
        self.now = 0.0
        self.window = 1.7         # seconds of chart visible
        self.flash = {lane: -10.0 for lane in range(5)}
        self.placeholder = "Your chart preview will appear here"
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    # ------------------------------------------------------------ data
    def set_chart(self, gems, bar_times, beat_times):
        self.gems = sorted(gems, key=lambda g: g[0])
        self.times = [g[0] for g in self.gems]
        self.bar_times = list(bar_times)
        self.beat_times = list(beat_times)
        self.now = 0.0
        self.update()

    def clear(self, message: str | None = None):
        self.set_chart([], [], [])
        if message:
            self.placeholder = message

    def set_time(self, t: float):
        prev = self.now
        self.now = t
        if t > prev and t - prev < 0.25:
            lo = bisect.bisect_right(self.times, prev)
            hi = bisect.bisect_right(self.times, t)
            for g in self.gems[lo:hi]:
                self.flash[g[1]] = t
        self.update()

    def set_speed(self, speed: float):
        self.window = 1.7 / max(speed, 0.25)
        self.update()

    def wheelEvent(self, ev):
        if not self.gems:
            return
        step = -ev.angleDelta().y() / 120.0 * 0.25 * self.window
        self.seekRequested.emit(max(0.0, self.now - step))

    # ------------------------------------------------------- geometry
    def _geom(self):
        w, h = self.width(), self.height()
        hw_w = min(w * 0.82, h * 0.9)
        cx = w / 2
        strike_y = h - 70
        far_y = 26
        return cx, hw_w, strike_y, far_y

    def _project(self, z: float):
        """z: 0 at the strikeline .. 1 at the far end. Returns (y, scale)."""
        cx, hw_w, strike_y, far_y = self._geom()
        c = 1.0
        s = c / (c + z * 1.25)
        s_far = c / (c + 1.25)
        y = far_y + (strike_y - far_y) * (s - s_far) / (1 - s_far)
        return y, s

    def _lane_x(self, lane_pos: float, scale: float) -> float:
        cx, hw_w, _, _ = self._geom()
        return cx + (lane_pos - 0.5) * hw_w * scale

    # ---------------------------------------------------------- paint
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, QColor("#0a0c11"))
        bg.setColorAt(1, QColor("#11141c"))
        p.fillRect(self.rect(), bg)

        cx, hw_w, strike_y, far_y = self._geom()
        y_far, s_far = self._project(1.0)
        y_near, s_near = self._project(-0.06)
        # Highway body
        body = QPainterPath()
        body.moveTo(self._lane_x(0, s_far), y_far)
        body.lineTo(self._lane_x(1, s_far), y_far)
        body.lineTo(self._lane_x(1, s_near), y_near + 30)
        body.lineTo(self._lane_x(0, s_near), y_near + 30)
        body.closeSubpath()
        grad = QLinearGradient(0, y_far, 0, strike_y)
        grad.setColorAt(0, QColor(20, 23, 33, 40))
        grad.setColorAt(0.25, QColor(24, 27, 39, 235))
        grad.setColorAt(1, QColor(30, 34, 49, 255))
        p.fillPath(body, grad)

        # Lane dividers
        for k in range(5):
            pos = k / 4
            pen = QPen(QColor(255, 255, 255, 38 if k in (0, 4) else 22), 1.4 if k in (0, 4) else 1)
            p.setPen(pen)
            p.drawLine(QPointF(self._lane_x(pos, s_far), y_far), QPointF(self._lane_x(pos, s_near), y_near + 30))

        # Beat and bar lines
        def draw_line(t, alpha, width):
            z = (t - self.now) / self.window
            if -0.06 <= z <= 1.0:
                y, s = self._project(z)
                fade = min(1.0, (1.0 - z) * 4)
                p.setPen(QPen(QColor(255, 255, 255, int(alpha * fade)), width * s))
                p.drawLine(QPointF(self._lane_x(0, s), y), QPointF(self._lane_x(1, s), y))

        lo = bisect.bisect_left(self.beat_times, self.now - 0.2)
        for t in self.beat_times[lo:]:
            if t > self.now + self.window:
                break
            draw_line(t, 34, 1.2)
        lo = bisect.bisect_left(self.bar_times, self.now - 0.2)
        for t in self.bar_times[lo:]:
            if t > self.now + self.window:
                break
            draw_line(t, 95, 2.4)

        # Strikeline targets
        self._draw_targets(p, strike_y)

        # Gems, far to near
        if self.gems:
            lo = bisect.bisect_left(self.times, self.now - 0.08)
            hi = bisect.bisect_right(self.times, self.now + self.window)
            visible = self.gems[lo:hi]
            for g in reversed(visible):
                if g[1] == 0:
                    self._draw_kick(p, g)
            for g in reversed(visible):
                if g[1] != 0:
                    self._draw_pad(p, g)
        else:
            p.setPen(QColor(138, 144, 166))
            f = p.font()
            f.setPointSizeF(11)
            p.setFont(f)
            p.drawText(QRectF(0, h * 0.42, w, 40), Qt.AlignCenter, self.placeholder)

        # Top fade
        fade = QLinearGradient(0, 0, 0, y_far + 70)
        fade.setColorAt(0, QColor(10, 12, 17, 255))
        fade.setColorAt(1, QColor(10, 12, 17, 0))
        p.fillRect(QRectF(0, 0, w, y_far + 70), fade)
        p.end()

    def _draw_targets(self, p: QPainter, strike_y: float):
        _, s = self._project(0)
        # kick bar
        kick_col = QColor(LANE_COLORS[0])
        age = self.now - self.flash[0]
        glow = max(0.0, 1.0 - age / 0.15) if age >= 0 else 0.0
        kick_col.setAlpha(int(70 + 150 * glow))
        p.setPen(QPen(kick_col, 3 * s))
        p.drawLine(QPointF(self._lane_x(0.01, s), strike_y), QPointF(self._lane_x(0.99, s), strike_y))
        lane_w = self._geom()[1] * s / 4
        for i, lane in enumerate(PAD_LANES):
            x = self._lane_x((i + 0.5) / 4, s)
            r = lane_w * 0.36
            col = QColor(LANE_COLORS[lane])
            age = self.now - self.flash[lane]
            glow = max(0.0, 1.0 - age / 0.15) if age >= 0 else 0.0
            if glow > 0:
                rg = QRadialGradient(QPointF(x, strike_y), r * 2.2)
                c2 = QColor(col)
                c2.setAlpha(int(150 * glow))
                rg.setColorAt(0, c2)
                rg.setColorAt(1, QColor(0, 0, 0, 0))
                p.setBrush(QBrush(rg))
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(x, strike_y), r * 2.2, r * 1.3)
            p.setBrush(QColor(12, 14, 20))
            ring = QColor(col)
            ring.setAlpha(150 + int(105 * glow))
            p.setPen(QPen(ring, max(2.0, r * 0.18)))
            p.drawEllipse(QPointF(x, strike_y), r, r * 0.62)

    def _draw_kick(self, p: QPainter, g):
        z = (g[0] - self.now) / self.window
        y, s = self._project(max(z, -0.06))
        col = QColor("#7fe3ff") if g[3] else QColor(LANE_COLORS[0])
        hgt = 7 * s + 2
        rect = QRectF(self._lane_x(0.02, s), y - hgt / 2, self._lane_x(0.98, s) - self._lane_x(0.02, s), hgt)
        grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
        grad.setColorAt(0, col.lighter(135))
        grad.setColorAt(1, col.darker(130))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(rect, hgt / 2, hgt / 2)

    def _draw_pad(self, p: QPainter, g):
        t, lane, cym, sp = g
        z = (t - self.now) / self.window
        y, s = self._project(max(z, -0.06))
        lane_w = self._geom()[1] * s / 4
        x = self._lane_x((PAD_LANES.index(lane) + 0.5) / 4, s)
        col = QColor("#7fe3ff") if sp else QColor(LANE_COLORS[lane])
        p.setPen(Qt.NoPen)
        if cym:
            # Cymbal: a flatter, lighter gem with a bright rim (CH style).
            rw, rh = lane_w * 0.36, lane_w * 0.15
            shadow = QColor(0, 0, 0, 120)
            p.setBrush(shadow)
            p.drawEllipse(QPointF(x, y + rh * 0.55), rw, rh)
            grad = QRadialGradient(QPointF(x, y - rh * 0.3), rw * 1.1)
            grad.setColorAt(0, col.lighter(170))
            grad.setColorAt(0.7, col)
            grad.setColorAt(1, col.darker(140))
            p.setBrush(QBrush(grad))
            p.setPen(QPen(QColor(255, 255, 255, 210), max(1.2, 2.2 * s)))
            p.drawEllipse(QPointF(x, y), rw, rh)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 170))
            p.drawEllipse(QPointF(x, y - rh * 0.05), rw * 0.18, rh * 0.32)
        else:
            # Tom/snare: a chunky rounded gem.
            gw, gh = lane_w * 0.78, lane_w * 0.30
            rect = QRectF(x - gw / 2, y - gh / 2, gw, gh)
            p.setBrush(QColor(0, 0, 0, 130))
            p.drawRoundedRect(rect.translated(0, gh * 0.25), gh / 2, gh / 2)
            grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
            grad.setColorAt(0, col.lighter(150))
            grad.setColorAt(0.45, col)
            grad.setColorAt(1, col.darker(160))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(rect, gh / 2, gh / 2)
            p.setBrush(QColor(255, 255, 255, 60))
            inner = rect.adjusted(gw * 0.12, gh * 0.14, -gw * 0.12, -gh * 0.55)
            p.drawRoundedRect(inner, inner.height() / 2, inner.height() / 2)


def chart_to_preview(parsed, difficulty: str):
    """Convert a ParsedChart into (gems, bar_times, beat_times) for the widget."""
    gems = parsed.tracks.get(difficulty) or parsed.tracks.get("expert") or []
    sp = parsed.star_power.get(difficulty) or parsed.star_power.get("expert") or []
    sp_ranges = [(a, a + b) for a, b in sp]

    def in_sp(tick):
        return any(a <= tick < b for a, b in sp_ranges)

    items = [(g.time, g.lane, g.cymbal, in_sp(g.tick)) for g in gems]
    end_tick = (gems[-1].tick if gems else 0) + parsed.resolution * 16
    bars = [parsed.seconds(t) for t in parsed.bar_ticks(end_tick)]
    beats = [parsed.seconds(t) for t in range(0, end_tick, parsed.resolution)]
    return items, bars, beats
