"""The AutoDrums main window."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QSlider,
                               QVBoxLayout, QWidget)

from .. import __version__, chartio, download, models
from ..pipeline import STEPS, Options, generate
from ..settings import Settings
from .highway import HighwayWidget, chart_to_preview
from .theme import GOOD, MUTED

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except Exception:  # pragma: no cover - multimedia backend missing
    QMediaPlayer = None
    QAudioOutput = None


# ------------------------------------------------------------------ workers

class ChartWorker(QObject):
    progress = Signal(str, str, float, float)
    log = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, source: str, opts: Options):
        super().__init__()
        self.source = source
        self.opts = opts
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            missing = models.missing_models()
            if missing:
                self.progress.emit("models", "Downloading AI models (first run only)", 0.0, 0.0)
                total = sum(m.size for m in missing)
                done = 0
                for spec in missing:
                    def cb(_msg, frac, spec=spec, done=done):
                        self.progress.emit("models", "Downloading AI models (first run only)",
                                           (done + frac * spec.size) / total, 0.0)
                    models.ensure_model(spec.key, cb)
                    done += spec.size
            result = generate(self.source, self.opts, self.progress.emit, lambda: self._cancel, self.log.emit)
            self.finished.emit(result)
        except InterruptedError:
            self.failed.emit("Cancelled.")
        except Exception as exc:  # report anything to the UI
            self.log.emit(traceback.format_exc())
            self.failed.emit(str(exc) or exc.__class__.__name__)


class MetadataWorker(QObject):
    done = Signal(dict)

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def run(self):
        try:
            self.done.emit(download.fetch_metadata(self.url))
        except Exception:
            self.done.emit({})


class UpdateWorker(QObject):
    done = Signal(str)

    def run(self):
        try:
            self.done.emit("Downloader updated to " + download.update_downloader())
        except Exception as exc:
            self.done.emit(f"Update failed: {exc}")


def run_in_background(worker) -> threading.Thread:
    """Run worker.run() in a daemon thread; its Qt signals are delivered to the GUI thread.

    Daemon threads never keep the app alive or abort it on exit, unlike a running QThread.
    """
    t = threading.Thread(target=worker.run, daemon=True)
    t.start()
    return t


# ------------------------------------------------------------------ widgets

def section_title(text: str) -> QLabel:
    lab = QLabel(text.upper())
    lab.setObjectName("sectionTitle")
    return lab


class StepRow(QWidget):
    def __init__(self, label: str):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        self.icon = QLabel("○")
        self.icon.setFixedWidth(18)
        self.icon.setAlignment(Qt.AlignCenter)
        self.label = QLabel(label)
        self.pct = QLabel("")
        self.pct.setObjectName("muted")
        lay.addWidget(self.icon)
        lay.addWidget(self.label, 1)
        lay.addWidget(self.pct)
        self.set_state("pending")

    def set_state(self, state: str, frac: float | None = None):
        if state == "pending":
            self.icon.setText("○")
            self.icon.setStyleSheet(f"color: {MUTED};")
            self.label.setStyleSheet(f"color: {MUTED};")
            self.pct.setText("")
        elif state == "active":
            self.icon.setText("●")
            self.icon.setStyleSheet("color: #ff6a3d;")
            self.label.setStyleSheet("color: white; font-weight: 600;")
            self.pct.setText(f"{int(frac * 100)}%" if frac is not None else "")
        elif state == "done":
            self.icon.setText("✓")
            self.icon.setStyleSheet(f"color: {GOOD}; font-weight: 700;")
            self.label.setStyleSheet("color: #c8ccda;")
            self.pct.setText("")
        elif state == "skipped":
            self.icon.setText("–")
            self.icon.setStyleSheet(f"color: {MUTED};")
            self.label.setStyleSheet(f"color: {MUTED}; text-decoration: line-through;")
            self.pct.setText("")


class Panel(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("panel")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(18, 16, 18, 16)
        self.lay.setSpacing(10)


class Stat(QWidget):
    def __init__(self, label: str):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.value = QLabel("–")
        self.value.setObjectName("stat")
        cap = QLabel(label.upper())
        cap.setObjectName("statLabel")
        lay.addWidget(self.value)
        lay.addWidget(cap)


# ------------------------------------------------------------------ window

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.setWindowTitle(f"AutoDrums {__version__} – Clone Hero Pro Drums Autocharter")
        self.resize(1240, 800)
        self.setMinimumSize(980, 680)
        self.busy = False
        self.worker: ChartWorker | None = None
        self.meta_busy = False
        self._keep: list[QObject] = []
        self.chart_folder: Path | None = None
        self.parsed = None
        self.duration = 0.0

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 16, 20, 18)
        outer.setSpacing(14)
        outer.addLayout(self._header())
        body = QHBoxLayout()
        body.setSpacing(16)
        outer.addLayout(body, 1)
        body.addWidget(self._left_panel(), 0)
        body.addWidget(self._right_panel(), 1)

        self._setup_audio()
        self.anim = QTimer(self)
        self.anim.setInterval(16)
        self.anim.timeout.connect(self._tick)
        self.clock = QElapsedTimer()
        self.clock_base = 0.0
        self._apply_settings()
        self._update_generate_enabled()

    # ---------------------------------------------------------------- layout
    def _header(self):
        lay = QHBoxLayout()
        logo = QLabel()
        icon = QApplication.windowIcon()
        if not icon.isNull():
            logo.setPixmap(icon.pixmap(40, 40))
        lay.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(0)
        t = QLabel("AutoDrums")
        t.setObjectName("appTitle")
        st = QLabel("Paste a YouTube link and get a Clone Hero pro drums chart.")
        st.setObjectName("appSubtitle")
        col.addWidget(t)
        col.addWidget(st)
        lay.addLayout(col)
        lay.addStretch(1)
        self.open_chart_btn = QPushButton("Open existing chart…")
        self.open_chart_btn.clicked.connect(self._open_existing)
        lay.addWidget(self.open_chart_btn)
        return lay

    def _left_panel(self):
        panel = Panel()
        panel.setFixedWidth(400)
        lay = panel.lay

        lay.addWidget(section_title("Song"))
        self.url_edit = QLineEdit()
        self.url_edit.setObjectName("urlEdit")
        self.url_edit.setPlaceholderText("https://www.youtube.com/watch?v=…  or an audio file")
        self.url_edit.textChanged.connect(self._source_changed)
        self.url_edit.returnPressed.connect(self._start)
        row = QHBoxLayout()
        row.addWidget(self.url_edit, 1)
        browse = QPushButton("File…")
        browse.setToolTip("Chart an audio file from your computer (mp3, wav, flac, ogg, m4a…)")
        browse.clicked.connect(self._browse_audio)
        row.addWidget(browse)
        lay.addLayout(row)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("auto")
        self.artist_edit = QLineEdit()
        self.artist_edit.setPlaceholderText("auto")
        grid.addWidget(QLabel("Title"), 0, 0)
        grid.addWidget(self.title_edit, 0, 1)
        grid.addWidget(QLabel("Artist"), 1, 0)
        grid.addWidget(self.artist_edit, 1, 1)
        lay.addLayout(grid)

        lay.addSpacing(6)
        lay.addWidget(section_title("Save to"))
        out_row = QHBoxLayout()
        self.out_edit = QLineEdit()
        self.out_edit.setToolTip("Your Clone Hero Songs folder (or a subfolder of it)")
        out_row.addWidget(self.out_edit, 1)
        out_btn = QPushButton("…")
        out_btn.setFixedWidth(40)
        out_btn.clicked.connect(self._browse_out)
        out_row.addWidget(out_btn)
        lay.addLayout(out_row)

        lay.addSpacing(6)
        lay.addWidget(section_title("Options"))
        self.sep_check = QCheckBox("Isolate drums (most accurate, slower)")
        self.sep_check.setToolTip(
            "Separates the drums from the music with an AI model. Improves detection and writes a\n"
            "drums.ogg stem so the drums cut out when you miss, like official charts.")
        lay.addWidget(self.sep_check)
        sens_row = QHBoxLayout()
        sens_lab = QLabel("Sensitivity")
        sens_lab.setToolTip("Higher finds quieter hits (ghost notes); lower keeps only clear hits.")
        sens_row.addWidget(sens_lab)
        self.sens_slider = QSlider(Qt.Horizontal)
        self.sens_slider.setRange(0, 100)
        self.sens_value = QLabel("")
        self.sens_value.setFixedWidth(64)
        self.sens_value.setObjectName("muted")
        self.sens_slider.valueChanged.connect(self._sens_changed)
        sens_row.addWidget(self.sens_slider, 1)
        sens_row.addWidget(self.sens_value)
        lay.addLayout(sens_row)

        self.adv_btn = QPushButton("Advanced ▸")
        self.adv_btn.setObjectName("flat")
        self.adv_btn.setCursor(Qt.PointingHandCursor)
        self.adv_btn.clicked.connect(self._toggle_advanced)
        lay.addWidget(self.adv_btn, 0, Qt.AlignLeft)
        self.adv = QWidget()
        al = QGridLayout(self.adv)
        al.setContentsMargins(0, 0, 0, 0)
        al.setVerticalSpacing(8)
        al.addWidget(QLabel("Charter name"), 0, 0)
        self.charter_edit = QLineEdit()
        al.addWidget(self.charter_edit, 0, 1)
        al.addWidget(QLabel("Browser cookies"), 1, 0)
        self.cookies_combo = QComboBox()
        self.cookies_combo.addItems(["Off", "chrome", "edge", "firefox", "brave", "opera", "vivaldi"])
        self.cookies_combo.setToolTip("Use your browser's YouTube login for age-restricted or blocked videos.")
        al.addWidget(self.cookies_combo, 1, 1)
        self.n32_check = QCheckBox("Allow 32nd notes")
        al.addWidget(self.n32_check, 2, 0, 1, 2)
        upd = QPushButton("Update YouTube downloader")
        upd.setToolTip("Fetch the newest yt-dlp if YouTube downloads stop working.")
        upd.clicked.connect(self._update_downloader)
        self.update_btn = upd
        al.addWidget(upd, 3, 0, 1, 2)
        self.adv.setVisible(False)
        lay.addWidget(self.adv)

        lay.addStretch(1)
        self.gen_btn = QPushButton("Generate Chart")
        self.gen_btn.setObjectName("primary")
        self.gen_btn.setCursor(Qt.PointingHandCursor)
        self.gen_btn.clicked.connect(self._start)
        lay.addWidget(self.gen_btn)

        self.steps_box = QWidget()
        sl = QVBoxLayout(self.steps_box)
        sl.setContentsMargins(0, 4, 0, 0)
        sl.setSpacing(2)
        self.step_rows: dict[str, StepRow] = {}
        self.step_rows["models"] = StepRow("Downloading AI models")
        sl.addWidget(self.step_rows["models"])
        for key, label, _ in STEPS:
            self.step_rows[key] = StepRow(label)
            sl.addWidget(self.step_rows[key])
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        sl.addSpacing(6)
        sl.addWidget(self.progress)
        prow = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        prow.addWidget(self.status, 1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.clicked.connect(self._cancel)
        prow.addWidget(self.cancel_btn)
        sl.addLayout(prow)
        self.steps_box.setVisible(False)
        lay.addWidget(self.steps_box)

        self.log_btn = QPushButton("Show details ▸")
        self.log_btn.setObjectName("flat")
        self.log_btn.clicked.connect(self._toggle_log)
        lay.addWidget(self.log_btn, 0, Qt.AlignLeft)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(140)
        self.log_view.setVisible(False)
        lay.addWidget(self.log_view)
        return panel

    def _right_panel(self):
        panel = Panel()
        lay = panel.lay
        top = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(0)
        self.song_label = QLabel("No chart yet")
        self.song_label.setObjectName("songTitle")
        self.folder_label = QLabel("Generate a chart or open an existing one to preview it here.")
        self.folder_label.setObjectName("muted")
        col.addWidget(self.song_label)
        col.addWidget(self.folder_label)
        top.addLayout(col, 1)
        self.diff_group = QButtonGroup(self)
        self.diff_group.setExclusive(True)
        for name in ("Expert", "Hard", "Medium", "Easy"):
            b = QPushButton(name)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setProperty("diff", name.lower())
            self.diff_group.addButton(b)
            top.addWidget(b)
        self.diff_group.buttonClicked.connect(self._diff_changed)
        lay.addLayout(top)

        self.highway = HighwayWidget()
        self.highway.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.highway.seekRequested.connect(self._seek)
        lay.addWidget(self.highway, 1)

        transport = QHBoxLayout()
        self.play_btn = QPushButton("▶")
        self.play_btn.setObjectName("play")
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.clicked.connect(self._toggle_play)
        transport.addWidget(self.play_btn)
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setObjectName("muted")
        self.time_label.setFixedWidth(92)
        transport.addWidget(self.time_label)
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.sliderMoved.connect(lambda v: self._seek(v / 1000 * self.duration))
        transport.addWidget(self.seek_slider, 1)
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["0.5×", "0.75×", "1×"])
        self.speed_combo.setCurrentIndex(2)
        self.speed_combo.setToolTip("Playback speed")
        self.speed_combo.currentIndexChanged.connect(self._rate_changed)
        transport.addWidget(self.speed_combo)
        lay.addLayout(transport)

        mix = QHBoxLayout()
        mix.addWidget(QLabel("Drums"))
        self.drums_vol = QSlider(Qt.Horizontal)
        self.drums_vol.setRange(0, 100)
        self.drums_vol.valueChanged.connect(self._volumes_changed)
        mix.addWidget(self.drums_vol, 1)
        mix.addSpacing(12)
        mix.addWidget(QLabel("Music"))
        self.song_vol = QSlider(Qt.Horizontal)
        self.song_vol.setRange(0, 100)
        self.song_vol.valueChanged.connect(self._volumes_changed)
        mix.addWidget(self.song_vol, 1)
        mix.addSpacing(12)
        mix.addWidget(QLabel("Note speed"))
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(50, 200)
        self.speed_slider.valueChanged.connect(lambda v: self.highway.set_speed(v / 100))
        mix.addWidget(self.speed_slider, 1)
        lay.addLayout(mix)

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background: #262b3a;")
        lay.addWidget(line)
        stats = QHBoxLayout()
        self.stat_bpm = Stat("BPM")
        self.stat_notes = Stat("Notes (Expert)")
        self.stat_diff = Stat("Difficulty")
        self.stat_len = Stat("Length")
        for s in (self.stat_bpm, self.stat_notes, self.stat_diff, self.stat_len):
            stats.addWidget(s)
        stats.addStretch(1)
        self.folder_btn = QPushButton("Open song folder")
        self.folder_btn.clicked.connect(self._open_folder)
        self.folder_btn.setEnabled(False)
        stats.addWidget(self.folder_btn)
        lay.addLayout(stats)
        self._set_transport_enabled(False)
        return panel

    # ---------------------------------------------------------------- settings
    def _apply_settings(self):
        s = self.settings
        self.out_edit.setText(s.output_dir)
        self.charter_edit.setText(s.charter)
        self.sep_check.setChecked(s.separate_drums)
        self.sens_slider.setValue(int(round(s.sensitivity * 100)))
        self._sens_changed(self.sens_slider.value())
        self.n32_check.setChecked(s.allow_32nds)
        idx = self.cookies_combo.findText(s.cookies_browser) if s.cookies_browser else 0
        self.cookies_combo.setCurrentIndex(max(idx, 0))
        self.drums_vol.setValue(s.drums_volume)
        self.song_vol.setValue(s.song_volume)
        self.speed_slider.setValue(int(s.note_speed * 100))
        for b in self.diff_group.buttons():
            b.setChecked(b.property("diff") == s.preview_difficulty)

    def _store_settings(self):
        s = self.settings
        s.output_dir = self.out_edit.text().strip()
        s.charter = self.charter_edit.text().strip() or "AutoDrums"
        s.separate_drums = self.sep_check.isChecked()
        s.sensitivity = self.sens_slider.value() / 100
        s.allow_32nds = self.n32_check.isChecked()
        s.cookies_browser = "" if self.cookies_combo.currentIndex() == 0 else self.cookies_combo.currentText()
        s.drums_volume = self.drums_vol.value()
        s.song_volume = self.song_vol.value()
        s.note_speed = self.speed_slider.value() / 100
        checked = self.diff_group.checkedButton()
        s.preview_difficulty = checked.property("diff") if checked else "expert"
        s.save()

    def closeEvent(self, ev):
        self._store_settings()
        if self.worker:
            self.worker.cancel()
        self.shutdown_audio()
        super().closeEvent(ev)

    def shutdown_audio(self):
        """Tear down the media players while Qt is still fully alive (avoids crashes at exit)."""
        self.anim.stop()
        for player, _ in getattr(self, "players", []):
            player.stop()
            player.setSource(QUrl())

    # ---------------------------------------------------------------- inputs
    def _sens_changed(self, v: int):
        label = "Default" if 45 <= v <= 55 else ("More notes" if v > 55 else "Fewer notes")
        self.sens_value.setText(label)

    def _toggle_advanced(self):
        vis = not self.adv.isVisible()
        self.adv.setVisible(vis)
        self.adv_btn.setText("Advanced ▾" if vis else "Advanced ▸")

    def _toggle_log(self):
        vis = not self.log_view.isVisible()
        self.log_view.setVisible(vis)
        self.log_btn.setText("Hide details ▾" if vis else "Show details ▸")

    def _browse_audio(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a song", str(Path.home()),
            "Audio/Video (*.mp3 *.wav *.flac *.ogg *.opus *.m4a *.aac *.wma *.mp4 *.mkv *.webm);;All files (*)")
        if path:
            self.url_edit.setText(path)

    def _browse_out(self):
        path = QFileDialog.getExistingDirectory(self, "Clone Hero songs folder", self.out_edit.text())
        if path:
            self.out_edit.setText(path)

    def _source_changed(self, text: str):
        self._update_generate_enabled()
        text = text.strip()
        if download.is_url(text) and ("youtu" in text or "soundcloud" in text):
            if self.meta_busy:
                return
            self.meta_busy = True
            worker = MetadataWorker(text)
            self._keep.append(worker)
            worker.done.connect(self._metadata_ready)
            run_in_background(worker)

    def _metadata_ready(self, info: dict):
        self.meta_busy = False
        if not info:
            return
        if not self.title_edit.text():
            self.title_edit.setPlaceholderText(info.get("title") or "auto")
        if not self.artist_edit.text():
            self.artist_edit.setPlaceholderText(info.get("artist") or "auto")

    def _update_generate_enabled(self):
        self.gen_btn.setEnabled(bool(self.url_edit.text().strip()) and not self.busy)

    def _update_downloader(self):
        self.update_btn.setEnabled(False)
        self.update_btn.setText("Updating…")
        worker = UpdateWorker()
        self._keep.append(worker)
        worker.done.connect(self._update_done)
        run_in_background(worker)

    def _update_done(self, msg: str):
        self.update_btn.setEnabled(True)
        self.update_btn.setText("Update YouTube downloader")
        QMessageBox.information(self, "AutoDrums", msg)

    # ---------------------------------------------------------------- generate
    def _start(self):
        source = self.url_edit.text().strip().strip('"')
        if not source or self.busy:
            return
        out = self.out_edit.text().strip()
        if not out:
            QMessageBox.warning(self, "AutoDrums", "Choose where to save the chart first.")
            return
        self._store_settings()
        self._stop_playback()
        opts = Options(
            output_dir=Path(out),
            title=self.title_edit.text(),
            artist=self.artist_edit.text(),
            charter=self.settings.charter,
            separate_drums=self.settings.separate_drums,
            sensitivity=self.settings.sensitivity,
            allow_32nds=self.settings.allow_32nds,
            cookies_browser=self.settings.cookies_browser or None,
        )
        for key, row in self.step_rows.items():
            row.set_state("pending")
            row.setVisible(key != "models")
        if not opts.separate_drums:
            self.step_rows["separate"].set_state("skipped")
        self.progress.setValue(0)
        self.status.setText("Starting…")
        self.steps_box.setVisible(True)
        self.cancel_btn.setEnabled(True)
        self.log_view.clear()

        self.worker = ChartWorker(source, opts)
        self.worker.progress.connect(self._on_progress)
        self.worker.log.connect(self._on_log)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.busy = True
        self._update_generate_enabled()
        run_in_background(self.worker)
        self.highway.clear("Charting… the preview appears when it's done")

    def _cancel(self):
        if self.worker:
            self.worker.cancel()
            self.status.setText("Cancelling…")
            self.cancel_btn.setEnabled(False)

    def _on_progress(self, key: str, label: str, frac: float, overall: float):
        if key == "models":
            row = self.step_rows["models"]
            row.setVisible(True)
            row.set_state("active", frac)
            self.status.setText(label)
            return
        if self.step_rows["models"].isVisible():
            self.step_rows["models"].set_state("done")
        order = [k for k, _, _ in STEPS]
        if key == "done":
            for k in order:
                if self.step_rows[k].icon.text() != "–":
                    self.step_rows[k].set_state("done")
            self.progress.setValue(1000)
            return
        idx = order.index(key)
        for k in order[:idx]:
            if self.step_rows[k].icon.text() != "–":
                self.step_rows[k].set_state("done")
        self.step_rows[key].set_state("active", frac)
        self.progress.setValue(int(overall * 1000))
        self.status.setText(label + "…")

    def _on_log(self, text: str):
        self.log_view.appendPlainText(text)

    def _on_failed(self, msg: str):
        self.busy = False
        self._update_generate_enabled()
        self.status.setText("")
        self.cancel_btn.setEnabled(False)
        self.highway.clear("No chart")
        if msg != "Cancelled.":
            QMessageBox.critical(self, "AutoDrums", msg)
        else:
            self.status.setText("Cancelled.")

    def _on_finished(self, result):
        self.busy = False
        self._update_generate_enabled()
        self.cancel_btn.setEnabled(False)
        self.status.setText(f"Done in {result.elapsed:.0f} s – saved to {result.folder.name}")
        self._on_log(f"Saved to {result.folder}")
        self.load_chart_folder(result.folder, difficulty=result.difficulty)
        QApplication.alert(self)

    # ---------------------------------------------------------------- preview
    def _open_existing(self):
        start = self.out_edit.text() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Open a chart", start, "Clone Hero chart (notes.chart)")
        if path:
            self.load_chart_folder(Path(path).parent)

    def load_chart_folder(self, folder: Path, difficulty: int | None = None):
        chart = folder / "notes.chart"
        if not chart.is_file():
            QMessageBox.warning(self, "AutoDrums", "That folder has no notes.chart (only .chart files can be previewed).")
            return
        try:
            self.parsed = chartio.read_chart(chart)
        except Exception as exc:
            QMessageBox.warning(self, "AutoDrums", f"Could not read the chart: {exc}")
            return
        self.chart_folder = folder
        ini = {}
        ini_path = folder / "song.ini"
        if ini_path.is_file():
            for line in ini_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    ini[k.strip().lower()] = v.strip()
        title = ini.get("name") or self.parsed.song.get("Name", folder.name)
        artist = ini.get("artist") or self.parsed.song.get("Artist", "")
        self.song_label.setText(f"{title}" + (f"  ·  {artist}" if artist else ""))
        self.folder_label.setText(str(folder))
        self.folder_btn.setEnabled(True)
        exp = self.parsed.tracks.get("expert", [])
        bpms = [b / 1000 for _, b in self.parsed.tempos]
        self.stat_bpm.value.setText(f"{bpms[0]:.0f}" + ("*" if len(set(round(b) for b in bpms)) > 1 else "") if bpms else "–")
        self.stat_bpm.setToolTip("* the tempo changes during the song" if len(bpms) > 1 else "")
        self.stat_notes.value.setText(str(len(exp)))
        diff = difficulty if difficulty is not None else ini.get("diff_drums", "–")
        self.stat_diff.value.setText(f"{diff}/6" if str(diff).lstrip("-").isdigit() else "–")
        length_ms = int(ini.get("song_length", "0") or 0)
        self.duration = length_ms / 1000 if length_ms else (exp[-1].time + 3 if exp else 0)
        self.stat_len.value.setText(f"{int(self.duration // 60)}:{int(self.duration % 60):02d}")
        self._refresh_preview()
        self._load_audio(folder)

    def _diff_changed(self, *_):
        self._refresh_preview()

    def _refresh_preview(self):
        if not self.parsed:
            return
        btn = self.diff_group.checkedButton()
        diff = btn.property("diff") if btn else "expert"
        gems, bars, beats = chart_to_preview(self.parsed, diff)
        now = self.highway.now
        self.highway.set_chart(gems, bars, beats)
        self.highway.set_time(now)
        self.highway.set_speed(self.speed_slider.value() / 100)

    # ---------------------------------------------------------------- audio
    def _setup_audio(self):
        self.players = []
        if QMediaPlayer is None:
            return
        for _ in range(2):
            player = QMediaPlayer(self)
            out = QAudioOutput(self)
            player.setAudioOutput(out)
            self.players.append((player, out))
        self.players[0][0].playbackStateChanged.connect(self._state_changed)

    def _load_audio(self, folder: Path):
        self._stop_playback()
        self.audio_files = []
        if not self.players:
            self._set_transport_enabled(bool(self.parsed))
            return
        song = next((folder / n for n in ("song.ogg", "song.opus", "song.mp3", "song.wav") if (folder / n).is_file()), None)
        drums = next((folder / n for n in ("drums.ogg", "drums.opus", "drums.mp3", "drums.wav") if (folder / n).is_file()), None)
        self.has_drum_stem = drums is not None
        sources = [song, drums]
        for (player, _), src in zip(self.players, sources):
            player.setSource(QUrl.fromLocalFile(str(src)) if src else QUrl())
        self._volumes_changed()
        self._rate_changed()
        self._set_transport_enabled(song is not None)

    def _set_transport_enabled(self, on: bool):
        for w in (self.play_btn, self.seek_slider, self.speed_combo):
            w.setEnabled(on)

    def _volumes_changed(self, *_):
        if not self.players:
            return
        song_v = self.song_vol.value() / 100
        drum_v = self.drums_vol.value() / 100
        self.players[0][1].setVolume(song_v)
        self.players[1][1].setVolume(drum_v)

    def _rate_changed(self, *_):
        rate = [0.5, 0.75, 1.0][self.speed_combo.currentIndex()]
        for player, _ in self.players:
            player.setPlaybackRate(rate)
        self.clock_base = self._media_time()
        self.clock.restart()

    def _media_time(self) -> float:
        if not self.players:
            return self.highway.now
        return self.players[0][0].position() / 1000.0

    def _toggle_play(self):
        if not self.players:
            return
        main = self.players[0][0]
        if main.playbackState() == QMediaPlayer.PlayingState:
            for player, _ in self.players:
                player.pause()
        else:
            pos = main.position()
            for player, _ in self.players:
                if not player.source().isEmpty():
                    player.setPosition(pos)
                    player.play()

    def _state_changed(self, state):
        playing = state == QMediaPlayer.PlayingState
        self.play_btn.setText("❚❚" if playing else "▶")
        if playing:
            self.clock_base = self._media_time()
            self.clock.restart()
            self.anim.start()
        else:
            self.anim.stop()
            self.highway.set_time(self._media_time())

    def _stop_playback(self):
        for player, _ in getattr(self, "players", []):
            player.stop()

    def _seek(self, t: float):
        t = max(0.0, min(t, self.duration or t))
        for player, _ in self.players:
            if not player.source().isEmpty():
                player.setPosition(int(t * 1000))
        self.clock_base = t
        self.clock.restart()
        self.highway.now = t
        self.highway.update()
        self._update_time_label(t)

    def _tick(self):
        rate = [0.5, 0.75, 1.0][self.speed_combo.currentIndex()]
        media = self._media_time()
        est = self.clock_base + self.clock.elapsed() / 1000.0 * rate
        # Follow the player's clock smoothly; re-anchor if they drift apart.
        if abs(est - media) > 0.08:
            self.clock_base, est = media, media
            self.clock.restart()
        if len(self.players) > 1 and not self.players[1][0].source().isEmpty():
            drift = self.players[1][0].position() / 1000.0 - media
            if abs(drift) > 0.06:
                self.players[1][0].setPosition(int(media * 1000))
        self.highway.set_time(est)
        self._update_time_label(est)
        if self.duration and not self.seek_slider.isSliderDown():
            self.seek_slider.setValue(int(est / self.duration * 1000))

    def _update_time_label(self, t: float):
        d = self.duration
        self.time_label.setText(f"{int(t // 60)}:{int(t % 60):02d} / {int(d // 60)}:{int(d % 60):02d}")

    def _open_folder(self):
        if not self.chart_folder:
            return
        if sys.platform == "win32":
            os.startfile(str(self.chart_folder))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(self.chart_folder)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.chart_folder)))

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Space and self.play_btn.isEnabled() and not self.url_edit.hasFocus():
            self._toggle_play()
            return
        super().keyPressEvent(ev)

