"""
Multi-segment progress bar.

Each segment is shown as a thin colored strip proportional to its byte range.
When there are many segments (>8) the dividers are omitted to avoid visual noise.
The filled portion of each segment uses the segment's color; unfilled is the
standard track color.
"""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QBrush, QPen
from qfluentwidgets import isDarkTheme, themeColor


# Distinct, accessible colors for up to 32 segments
_COLORS = [
    "#0078D4", "#107C10", "#FF8C00", "#8764B8",
    "#D13438", "#00B7C3", "#FFB900", "#038387",
    "#E3008C", "#744DA9", "#018574", "#00CC6A",
    "#F7630C", "#CA5010", "#0099BC", "#69797E",
    "#0063B1", "#498205", "#C19C00", "#7B2FBE",
    "#A4262C", "#00A5B0", "#B7950B", "#025E73",
    "#BF0077", "#553982", "#017A6B", "#009E49",
    "#DA3B01", "#934F25", "#006F94", "#4E5A62",
]


class SegmentedProgressBar(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(8)
        self._segments = []    # list of (progress_pct, color_str)
        self._overall  = 0.0   # single-thread fallback

    def set_segments(self, segments, overall_pct: float):
        self._overall = overall_pct
        if segments:
            self._segments = [
                (seg.progress_pct, _COLORS[seg.index % len(_COLORS)])
                for seg in segments
            ]
        else:
            self._segments = []
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W = self.width()
        H = self.height()
        R = H / 2.0

        # Track background
        track = QColor("#3A3A3A" if isDarkTheme() else "#E0E0E0")
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(track))
        p.drawRoundedRect(0, 0, W, H, R, R)

        if not self._segments:
            # Single bar — use theme color
            filled = max(0, min(int(W * self._overall / 100), W))
            if filled > 0:
                p.setBrush(QBrush(themeColor()))
                p.drawRoundedRect(0, 0, filled, H, R, R)
        else:
            n = len(self._segments)
            show_dividers = (n <= 8)

            # Draw filled portion of each segment
            for i, (pct, color_str) in enumerate(self._segments):
                if pct <= 0:
                    continue
                # Segment occupies [x0, x0+seg_w] in widget coords
                x0 = W * i / n
                seg_w = W / n
                filled_w = seg_w * pct / 100.0

                x0i = int(x0)
                fw  = max(1, int(filled_w))
                fw  = min(fw, int(seg_w))   # never exceed segment width

                c = QColor(color_str)
                p.setBrush(QBrush(c))
                p.setPen(Qt.NoPen)

                # Round the leftmost and rightmost edges of the entire bar
                if i == 0 and n == 1:
                    p.drawRoundedRect(x0i, 0, fw, H, R, R)
                elif i == 0:
                    # Left end rounded, right end square
                    p.drawRoundedRect(x0i, 0, fw + int(R), H, R, R)
                    # Cover right half of rounded rect with square fill
                    p.drawRect(x0i + int(R), 0, max(0, fw - int(R)), H)
                elif i == n - 1:
                    if fw >= int(seg_w):
                        # Full last segment — round the right end
                        rx = int(x0)
                        rw = W - rx
                        p.drawRoundedRect(rx, 0, rw, H, R, R)
                        p.drawRect(rx, 0, rw - int(R), H)
                    else:
                        p.drawRect(x0i, 0, fw, H)
                else:
                    p.drawRect(x0i, 0, fw, H)

            # Segment dividers (only when few enough to see)
            if show_dividers:
                pen = QPen(track)
                pen.setWidth(1)
                p.setPen(pen)
                for i in range(1, n):
                    x = int(W * i / n)
                    p.drawLine(x, 0, x, H)

        p.end()
