"""Colours and the Qt style sheet."""

BG = "#0d0f14"
PANEL = "#151821"
PANEL_2 = "#1b1f2b"
BORDER = "#262b3a"
TEXT = "#e8eaf2"
MUTED = "#8a90a6"
ACCENT = "#ff6a3d"
ACCENT_2 = "#ff3d77"
GOOD = "#3ddc84"

LANE_COLORS = {
    0: "#ff9a1f",  # kick
    1: "#ff3b4a",  # red
    2: "#ffd21f",  # yellow
    3: "#2f9bff",  # blue
    4: "#2fdc6a",  # green
}

STYLE = f"""
* {{
    font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif;
    font-size: 10pt;
    color: {TEXT};
}}
QMainWindow, QWidget#root {{ background: {BG}; }}
QWidget#panel {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QLabel#appTitle {{ font-size: 17pt; font-weight: 700; letter-spacing: 0.5px; }}
QLabel#appSubtitle {{ color: {MUTED}; font-size: 9.5pt; }}
QLabel#sectionTitle {{
    color: {MUTED}; font-size: 8.5pt; font-weight: 700; letter-spacing: 1.5px;
}}
QLabel#muted {{ color: {MUTED}; }}
QLabel#stat {{ font-size: 15pt; font-weight: 700; }}
QLabel#statLabel {{ color: {MUTED}; font-size: 8.5pt; letter-spacing: 1px; }}
QLabel#songTitle {{ font-size: 13pt; font-weight: 700; }}

QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: 9px;
    padding: 7px 10px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit#urlEdit {{ font-size: 11pt; padding: 10px 12px; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {PANEL_2}; border: 1px solid {BORDER}; selection-background-color: {ACCENT};
}}

QPushButton {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: 9px;
    padding: 7px 14px;
    font-weight: 600;
}}
QPushButton:hover {{ border-color: #3a4156; background: #222738; }}
QPushButton:pressed {{ background: #1a1e2b; }}
QPushButton:disabled {{ color: #565c70; }}
QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 {ACCENT_2});
    border: none;
    border-radius: 11px;
    padding: 12px 18px;
    font-size: 11.5pt;
    font-weight: 700;
    color: white;
}}
QPushButton#primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff7d55, stop:1 #ff5590);
}}
QPushButton#primary:disabled {{ background: #2a2f40; color: #6b7187; }}
QPushButton#danger {{ color: #ff8a8a; }}
QPushButton#flat {{ background: transparent; border: none; color: {MUTED}; padding: 4px 6px; }}
QPushButton#flat:hover {{ color: {TEXT}; }}
QPushButton#play {{
    background: {TEXT}; color: {BG}; border: none; border-radius: 18px;
    min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px; padding: 0;
    font-size: 13pt;
}}
QPushButton#play:disabled {{ background: #2a2f40; color: #6b7187; }}
QPushButton#seg {{ border-radius: 8px; padding: 5px 10px; font-weight: 600; }}
QPushButton#seg:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 5px; border: 1px solid #3a4156; background: {PANEL_2};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: none; }}

QSlider::groove:horizontal {{ height: 6px; background: {PANEL_2}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 {ACCENT_2});
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: white; width: 14px; height: 14px; margin: -4px 0; border-radius: 7px;
}}

QProgressBar {{
    background: {PANEL_2}; border: none; border-radius: 5px; height: 10px; text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    border-radius: 5px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 {ACCENT_2});
}}
QPlainTextEdit {{
    background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 9px;
    font-family: "Cascadia Mono", "Consolas", monospace; font-size: 8.5pt; color: {MUTED};
}}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2c3244; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px; }}
QMessageBox {{ background: {PANEL}; }}
"""
