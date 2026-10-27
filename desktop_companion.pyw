"""Local Ollama desktop companion for Windows 11 (PySide6 / Qt Widgets)."""
from __future__ import annotations

import base64, functools, io, json, math, os, queue, random, re, subprocess, sys, tempfile, threading, time, uuid, wave
import ctypes
import shutil
import site
import urllib.request, urllib.parse
from datetime import datetime
from pathlib import Path

# Engine: constants, helpers and CompanionCore live in companion_core.py.
from companion_core import *  # noqa: F401,F403
from companion_core import CompanionCore
import companion_core
from PySide6.QtCore import Qt, QTimer, QSize, QRect, QRectF, QPointF, QPropertyAnimation, QEasingCurve, QVariantAnimation, QUrl, QParallelAnimationGroup, QObject, QEvent, QAbstractAnimation, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QFont, QTextCursor, QPainter, QLinearGradient, QRadialGradient, QColor, QBrush, QPen, QPainterPath, QPixmap, QIcon, QCursor, QImageReader, QDesktopServices
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QComboBox, QCheckBox, QLineEdit, QVBoxLayout, QHBoxLayout,
    QMessageBox, QFileDialog, QScrollArea, QSizePolicy, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QStyledItemDelegate, QStyleOptionViewItem,
    QGraphicsScene, QGraphicsView, QGraphicsPathItem, QDialog, QDialogButtonBox, QFormLayout, QSpinBox, QSlider, QStyle, QStyleOptionComboBox, QStylePainter,
    QToolButton, QStyleOptionToolButton, QButtonGroup, QStackedWidget, QPlainTextEdit, QInputDialog, QListWidget, QListWidgetItem, QMenu, QProgressDialog)

ICON_DIR = APP_DIR / "assets" / "icons" / "material"
# Google Material Symbols (Apache 2.0) by our icon name; the rest are drawn from paths in draw_vector_icon.
MATERIAL_ICONS = {
    "mic": "mic", "headphones": "headphones", "screen": "desktop_windows", "monitor": "desktop_windows",
    "image": "imagesmode", "chat": "chat_bubble", "settings": "settings", "refresh": "refresh", "loop": "refresh",
    "copy": "content_copy", "clone": "content_copy", "speak": "volume_up", "volume": "volume_up", "speaker": "volume_up",
    "plus": "add", "more": "more_horiz", "panel": "left_panel_close", "panel-expand": "left_panel_open",
    "file": "draft", "send": "arrow_upward",
}
_material_renderers = {}

from twitch_chat import TwitchChatDialog


MONO = {
    "bg": "#070707", "panel": "#101010", "raised": "#1a1a1a", "line": "#363636",
    "text": "#f5f5f5", "muted": "#a0a0a0", "accent": "#ffffff", "accent2": "#d8d8d8",
    "good": "#ffffff", "danger": "#ffffff", "input": "#090909", "bubble": "#191919",
}

CANVAS_THEMES = {
    "neon": {
        "name": "Неон",
        "description": "Ночной киберпанк: глубокий космос, живое северное сияние, неоновая бирюза и маджента, светящиеся карточки.",
        "window_bg": "#06050d", "panel_bg": "#0c0a18", "card_bg": "#131027",
        "control_bg": "#090813", "ui_border": "#251f48", "ui_border_strong": "#3f3580",
        "accent": "#5cf2ff", "accent_text": "#061219", "accent2": "#ff4fd8",
        "primary_bg": "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #5cf2ff, stop:1 #b388ff)",
        "primary_hover": "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #8af6ff, stop:1 #ff7be3)",
        "surface": ("#110a28", "#0a0920", "#05050f"), "grid": "#7d6cff", "grid_alpha": 6,
        "major_alpha": 13, "grain": "#cfc4ff", "grain_alpha": 40, "frame": "#5cf2ff", "frame_alpha": 70,
        "connector": "#5cf2ff", "connector_alpha": 235,
        "assistant_bg": "#151238", "assistant_border": "#3b3792",
        "user_bg": "#251040", "user_border": "#8e2f95",
        "system_bg": "#0d1830", "system_border": "#2a6488",
        "header_bg": "#1b1650", "header_border": "#5cf2ff", "role": "#dbe4ff",
        "divider": "#3b3792", "stripe": "#ff4fd8", "radius": "12px", "ui_radius": "10px",
        "message_border_width": "1px", "font_family": "Segoe UI",
        "eyebrow": "#5cf2ff", "brand": "#5cf2ff", "pattern": "#9d8cff",
        "panel_shadow": "#ff4fd8", "panel_shadow_alpha": 120,
        "scene": "neon", "flow": "#ff4fd8",
    },
    "graphite": {
        "name": "Школьная зелёная доска",
        "description": "Глубокая зелёная поверхность, меловая разметка и светлые меловые стрелки.",
        "window_bg": "#071b13", "panel_bg": "#0d261b", "card_bg": "#112f20",
        "control_bg": "#081b13", "ui_border": "#294d38", "ui_border_strong": "#52745e",
        "accent": "#c6ddca", "accent_text": "#0a2015",
        "surface": ("#17402d", "#123524", "#0d2a1d"), "grid": "#a8c4ae", "grid_alpha": 5,
        "major_alpha": 12, "grain": "#d3e1d4", "grain_alpha": 10, "frame": "#b4cdb8", "frame_alpha": 42,
        "connector": "#d5e2d5", "connector_alpha": 225,
        # Message cards should read as part of the chalkboard theme too:
        # green felt surfaces, restrained chalk outlines, and soft chalk text.
        "assistant_bg": "#214a35", "assistant_border": "#78927e",
        "user_bg": "#214a35", "user_border": "#78927e",
        "system_bg": "#214a35", "system_border": "#78927e",
        "header_bg": "#214a35", "header_border": "#78927e", "role": "#e0e9e1",
        "divider": "#78927d", "stripe": "#b4c4b7", "radius": "0px", "ui_radius": "0px", "message_border_width": "0px",
        "font_family": "Segoe UI",
    },
    "standard": {
        "name": "Стандартная",
        "description": "Привычная тёмная доска с серой сеткой и тёмными карточками.",
        "window_bg": "#070707", "panel_bg": "#101010", "card_bg": "#141414",
        "control_bg": "#090909", "ui_border": "#2b2b2b", "ui_border_strong": "#484848",
        "accent": "#ffffff", "accent_text": "#050505",
        "surface": ("#0b0b0b", "#080808", "#050505"), "grid": "#505050", "grid_alpha": 8,
        "major_alpha": 15, "grain": "#888888", "grain_alpha": 6, "frame": "#777777", "frame_alpha": 28,
        "connector": "#888888", "connector_alpha": 175,
        "assistant_bg": "#141414", "assistant_border": "#444444",
        "user_bg": "#242424", "user_border": "#3c3c3c",
        "system_bg": "#101010", "system_border": "#777777",
        "header_bg": "#1a1a1a", "header_border": "#383838", "role": "#b0b0b0",
        "divider": "#383838", "stripe": "#777777", "radius": "0px", "ui_radius": "0px",
        "message_border_width": "1px", "font_family": "Segoe UI",
    },
    "ocean": {
        "name": "Океан",
        "description": "Ночная морская доска: глубокая вода, светящиеся течения, пузырьки и карточки в оттенках бирюзы.",
        "window_bg": "#061923", "panel_bg": "#0a202b", "card_bg": "#0d2a38",
        "control_bg": "#071a24", "ui_border": "#214653", "ui_border_strong": "#397184",
        "accent": "#a6e0df", "accent_text": "#06202a",
        "surface": ("#0b3b52", "#082c42", "#061a2d"), "grid": "#77b6c3", "grid_alpha": 7,
        "major_alpha": 16, "grain": "#a2d7d9", "grain_alpha": 7,
        "frame": "#78b9c5", "frame_alpha": 50,
        "connector": "#a4e6e4", "connector_alpha": 220,
        "assistant_bg": "#0d3446", "assistant_border": "#2b6578",
        "user_bg": "#104456", "user_border": "#3b7b89",
        "system_bg": "#092b3d", "system_border": "#28596b",
        "header_bg": "#0e3c50", "header_border": "#397285", "role": "#d0f0ed",
        "divider": "#32697a", "stripe": "#9bd9dc", "radius": "0px", "ui_radius": "0px",
        "message_border_width": "1px", "font_family": "Segoe UI",
        "scene": "ocean", "flow": "#8bd6df",
    },
}


@functools.lru_cache(maxsize=24)
def _square_pattern_cells(width, height, seed):
    """Cache the static layout so animation frames only update alpha values."""
    size, pitch, margin = 8, 13, 3
    cols = max(1, (width - 2 * margin + 5) // pitch)
    rows = max(1, (height - 2 * margin + 5) // pitch)
    seed_rng = random.Random(seed)
    cluster_count = max(4, min(16, (cols * rows) // 55))
    anchors = ((0, 0), (cols - 1, 0), (0, rows - 1), (cols - 1, rows - 1))
    clusters = []
    for anchor_col, anchor_row in anchors:
        dx = 1 if anchor_col == 0 else -1
        dy = 1 if anchor_row == 0 else -1
        center_col = anchor_col + dx * seed_rng.randint(0, min(3, cols - 1))
        center_row = anchor_row + dy * seed_rng.randint(0, min(3, rows - 1))
        clusters.append((center_col, center_row, seed_rng.uniform(1.5, 3.8),
                         seed_rng.uniform(1.5, 3.8), seed_rng.uniform(0.65, 1.0)))
    for _ in range(cluster_count - len(anchors)):
        anchor_col, anchor_row = seed_rng.choice(anchors)
        dx = 1 if anchor_col == 0 else -1
        dy = 1 if anchor_row == 0 else -1
        center_col = anchor_col + dx * seed_rng.randint(0, min(4, cols - 1))
        center_row = anchor_row + dy * seed_rng.randint(0, min(4, rows - 1))
        clusters.append((center_col, center_row, seed_rng.uniform(1.5, 4.2),
                         seed_rng.uniform(1.5, 4.2), seed_rng.uniform(0.6, 0.98)))
    wall_depth = max(2.5, min(cols, rows) * 0.28)
    cells = []
    for row in range(rows):
        for col in range(cols):
            influence = 0.0
            for center_col, center_row, radius_x, radius_y, strength in clusters:
                dx, dy = (col - center_col) / radius_x, (row - center_row) / radius_y
                influence = max(influence, strength * math.exp(-0.5 * (dx * dx + dy * dy)))
            wall_distance = min(col, cols - 1 - col, row, rows - 1 - row)
            wall_pull = math.exp(-wall_distance / wall_depth)
            rng = random.Random((seed ^ (col * 73856093) ^ (row * 19349663)) & 0xFFFFFFFF)
            visibility_roll = rng.random()
            twinkle_enabled = rng.random() < 0.16
            phase = rng.uniform(0.0, math.tau) if twinkle_enabled else 0.0
            period = rng.uniform(4.0, 9.0) if twinkle_enabled else 1.0
            filled = rng.random() < 0.42 + influence * 0.24
            base_visibility = min(0.995, 0.02 + wall_pull * 0.23 + influence * 0.02)
            cells.append((margin + col * pitch, margin + row * pitch, visibility_roll,
                          base_visibility, filled, phase, period, twinkle_enabled))
    return size, tuple(cells)


def draw_random_square_pattern(painter, bounds, seed, clip_rect=None, hover_point=None,
                              hover_strength=0.0, twinkle_time=0.0, shape="square", color="#f5f5f5"):
    """Draw cached geometric placement with a soft hover ripple and shimmer."""
    size, cells = _square_pattern_cells(bounds.width(), bounds.height(), seed)
    clip = clip_rect or bounds
    tint = QColor(color)
    red, green, blue = tint.red(), tint.green(), tint.blue()
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, shape != "square")
    for local_x, local_y, visibility_roll, base_visibility, filled, phase, period, twinkle_enabled in cells:
        if (local_x + size < clip.left() or local_x > clip.right()
                or local_y + size < clip.top() or local_y > clip.bottom()):
            continue
        hover = 0.0
        if hover_point is not None and hover_strength > 0:
            dx = local_x + size / 2 - hover_point.x()
            dy = local_y + size / 2 - hover_point.y()
            distance_squared = dx * dx + dy * dy
            if distance_squared < 82.0 * 82.0:
                hover = hover_strength * (1.0 - math.sqrt(distance_squared) / 82.0) ** 2
        if visibility_roll > min(0.995, base_visibility + hover * 0.86):
            continue
        # Smoothstep the cosine phase so the existing brightness range eases
        # gently at both ends instead of appearing to tick between frames.
        if twinkle_enabled:
            pulse = 0.5 + 0.5 * math.cos((twinkle_time / period) * math.tau + phase)
            twinkle = pulse * pulse * (3.0 - 2.0 * pulse)
        else:
            twinkle = 0.0
        x, y = bounds.left() + local_x, bounds.top() + local_y
        tile = QRect(x, y, size, size)
        if filled:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(red, green, blue, min(105, 14 + int(hover * 91) + int(twinkle * 26))))
        else:
            painter.setPen(QPen(QColor(red, green, blue, min(145, 28 + int(hover * 117) + int(twinkle * 30))), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        if shape == "circle":
            painter.drawEllipse(tile.adjusted(1, 1, -1, -1))
        elif shape == "triangle":
            motif = QPainterPath()
            motif.moveTo(x + size / 2, y + 1)
            motif.lineTo(x + size - 1, y + size - 1)
            motif.lineTo(x + 1, y + size - 1)
            motif.closeSubpath()
            painter.drawPath(motif)
        else:
            painter.drawRect(tile)
    painter.restore()


class SquarePatternHover:
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._pattern_hover_point = None
        self._pattern_hover_strength = 0.0
        self._pattern_hover_target = 0.0
        self._pattern_filters_installed = False
        self._pattern_hover_animation = QVariantAnimation(self)
        self._pattern_hover_animation.setDuration(180)
        self._pattern_hover_animation.valueChanged.connect(self._set_pattern_hover_strength)
        self._square_twinkle_timer = QTimer(self)
        # 30 fps keeps the slow shimmer visually smooth without returning to
        # the expensive 60 fps full-panel repaint cadence.
        self._square_twinkle_timer.setInterval(33)
        self._square_twinkle_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._square_twinkle_timer.timeout.connect(self.update)

    def _set_pattern_hover_strength(self, value):
        self._pattern_hover_strength = float(value)
        self._update_pattern_hover_regions(self._pattern_hover_point)

    def _update_pattern_hover_regions(self, *points):
        radius = 86
        for point in points:
            if point is None:
                continue
            region = QRect(round(point.x() - radius), round(point.y() - radius),
                           radius * 2, radius * 2).intersected(self.rect())
            if not region.isEmpty():
                self.update(region)

    def _animate_pattern_hover(self, target):
        if self._pattern_hover_target == target:
            return
        self._pattern_hover_target = target
        self._pattern_hover_animation.stop()
        self._pattern_hover_animation.setStartValue(self._pattern_hover_strength)
        self._pattern_hover_animation.setEndValue(target)
        self._pattern_hover_animation.start()

    def _refresh_pattern_hover(self):
        inside = self.rect().contains(self.mapFromGlobal(QCursor.pos()))
        self._animate_pattern_hover(1.0 if inside else 0.0)

    def showEvent(self, event):
        super().showEvent(event)
        self._square_twinkle_timer.start()
        if not self._pattern_filters_installed:
            for child in self.findChildren(QWidget):
                child.setMouseTracking(True)
                child.installEventFilter(self)
            self._pattern_filters_installed = True

    def hideEvent(self, event):
        self._square_twinkle_timer.stop()
        super().hideEvent(event)

    def enterEvent(self, event):
        previous = self._pattern_hover_point
        self._pattern_hover_point = self.mapFromGlobal(QCursor.pos())
        self._animate_pattern_hover(1.0)
        self._update_pattern_hover_regions(previous, self._pattern_hover_point)
        super().enterEvent(event)

    def leaveEvent(self, event):
        QTimer.singleShot(0, self._refresh_pattern_hover)
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        previous = self._pattern_hover_point
        self._pattern_hover_point = event.position().toPoint()
        self._animate_pattern_hover(1.0)
        self._update_pattern_hover_regions(previous, self._pattern_hover_point)
        super().mouseMoveEvent(event)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseMove:
            previous = self._pattern_hover_point
            self._pattern_hover_point = self.mapFromGlobal(event.globalPosition().toPoint())
            self._animate_pattern_hover(1.0)
            self._update_pattern_hover_regions(previous, self._pattern_hover_point)
        elif event.type() == QEvent.Type.Enter:
            previous = self._pattern_hover_point
            self._pattern_hover_point = self.mapFromGlobal(QCursor.pos())
            self._animate_pattern_hover(1.0)
            self._update_pattern_hover_regions(previous, self._pattern_hover_point)
        elif event.type() == QEvent.Type.Leave:
            QTimer.singleShot(0, self._refresh_pattern_hover)
        return super().eventFilter(watched, event)


class SquareDecoratedFrame(SquarePatternHover, QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pattern_seed = random.SystemRandom().randrange(1 << 30)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        draw_random_square_pattern(painter, self.rect(), self.pattern_seed, event.rect(),
                                   self._pattern_hover_point, self._pattern_hover_strength,
                                   time.monotonic(), self._decoration_shape(), self._decoration_color())
        painter.end()

    def _decoration_shape(self):
        return getattr(self.window(), "settings", {}).get("decoration_shape", "square")

    def _decoration_color(self):
        theme_id = getattr(self.window(), "settings", {}).get("canvas_theme", "graphite")
        return CANVAS_THEMES.get(theme_id, CANVAS_THEMES["graphite"]).get("pattern", "#f5f5f5")


class SquareDecoratedWidget(SquarePatternHover, QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pattern_seed = random.SystemRandom().randrange(1 << 30)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        draw_random_square_pattern(painter, self.rect(), self.pattern_seed, event.rect(),
                                   self._pattern_hover_point, self._pattern_hover_strength,
                                   time.monotonic(), self._decoration_shape(), self._decoration_color())
        painter.end()

    def _decoration_shape(self):
        return getattr(self.window(), "settings", {}).get("decoration_shape", "square")

    def _decoration_color(self):
        theme_id = getattr(self.window(), "settings", {}).get("canvas_theme", "graphite")
        return CANVAS_THEMES.get(theme_id, CANVAS_THEMES["graphite"]).get("pattern", "#f5f5f5")


class Artboard(QWidget):
    """Plain outer application background; square motifs belong to the panels."""
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(getattr(self, "background_color", "#070707")))
        painter.end()


class ChatCanvasView(QGraphicsView):
    """Pannable chat canvas with pointer-centered Ctrl+wheel zoom."""
    userNavigated = Signal()
    workspaceMotion = Signal(float)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self._zoom = 1.0
        self._board_theme = CANVAS_THEMES["graphite"]
        self.setObjectName("chatStream")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setBackgroundBrush(QColor("#070707"))
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setCacheMode(QGraphicsView.CacheModeFlag.CacheBackground)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("")
        self._pan_press_pos = None
        self._pan_notified = False
        self._canvas_hint_text = ""
        self._zoom_hud_timer = QTimer(self)
        self._zoom_hud_timer.setSingleShot(True)
        self._zoom_hud_timer.timeout.connect(self._hide_zoom_hud)
        # The ocean scene redraws only its background and only while selected.
        # A leisurely cadence makes the water feel alive without competing with
        # card dragging or local model work.
        self._scene_motion_timer = QTimer(self)
        self._scene_motion_timer.setInterval(120)
        self._scene_motion_timer.timeout.connect(self._step_workspace_motion)
        self._scene_motion_timer.start()

    def _step_workspace_motion(self):
        phase = time.monotonic()
        self.workspaceMotion.emit(phase)
        # Only the ocean and neon scenes have animated backgrounds. Other themes
        # repaint just the short connector accents that changed in the scene.
        if self._board_theme.get("scene") in ("ocean", "neon"):
            self.resetCachedContent()
            self.viewport().update()

    def set_board_theme(self, theme):
        self._board_theme = theme
        self.viewport().update()

    def _show_zoom_hud(self):
        self._canvas_hint_text = f"{round(self._zoom * 100)}%  ·  Ctrl + колёсико"
        self._zoom_hud_timer.start(950)
        self.viewport().update()

    def _hide_zoom_hud(self):
        self._canvas_hint_text = ""
        self.viewport().update()

    def show_chat_hint(self, text, duration=1400):
        self._canvas_hint_text = str(text)
        self._zoom_hud_timer.start(duration)
        self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._canvas_hint_text:
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        label = self._canvas_hint_text
        width, height, margin = max(150, min(290, len(label) * 8 + 28)), 30, 16
        x = self.viewport().width() - width - margin
        y = self.viewport().height() - height - margin
        painter.setPen(QPen(QColor("#555555"), 1))
        painter.setBrush(QColor(24, 24, 24, 235))
        painter.drawRoundedRect(x, y, width, height, 5, 5)
        painter.setPen(QColor("#f5f5f5"))
        painter.drawText(x, y, width, height, Qt.AlignmentFlag.AlignCenter, label)
        painter.end()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.userNavigated.emit()
            factor = 1.15 if event.angleDelta().y() > 0 else (1 / 1.15)
            zoom = max(0.45, min(2.5, self._zoom * factor))
            factor = zoom / self._zoom
            if abs(factor - 1.0) > 0.001:
                self.scale(factor, factor)
                self._zoom = zoom
            event.accept()
            return
        if event.angleDelta().y() or event.angleDelta().x():
            self.userNavigated.emit()
        super().wheelEvent(event)

    def mousePressEvent(self, event):
        self._pan_press_pos = event.position().toPoint()
        self._pan_notified = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._pan_press_pos is not None and not self._pan_notified
                and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self._pan_press_pos).manhattanLength() > 4):
            self._pan_notified = True
            self.userNavigated.emit()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self._pan_press_pos = None
        self._pan_notified = False

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Double-click on the workspace must not alter its zoom.
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    @staticmethod
    def _draw_neon_scene(painter, rect, theme):
        """Slowly drifting aurora glows and twinkling stars for the neon board."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        t = time.monotonic()
        glows = (
            (theme["accent"], 700, 560, 620, 0.00, 62),
            (theme["flow"], 1650, 900, 680, 1.70, 58),
            ("#7c4dff", 1150, 300, 640, 3.10, 70),
            ("#7c4dff", 600, 1450, 700, 2.20, 60),
            (theme["accent"], 2050, 1500, 560, 4.40, 46),
        )
        for color, cx, cy, radius, phase, alpha in glows:
            x = cx + math.sin(t / 9.0 + phase) * 160
            y = cy + math.cos(t / 11.0 + phase) * 110
            pulse = 0.82 + 0.18 * math.sin(t / 4.0 + phase)
            if (x + radius < rect.left() or x - radius > rect.right()
                    or y + radius < rect.top() or y - radius > rect.bottom()):
                continue
            glow = QRadialGradient(QPointF(x, y), radius)
            inner = QColor(color); inner.setAlpha(int(alpha * pulse))
            middle = QColor(color); middle.setAlpha(int(alpha * pulse * 0.35))
            outer = QColor(color); outer.setAlpha(0)
            glow.setColorAt(0.0, inner); glow.setColorAt(0.45, middle); glow.setColorAt(1.0, outer)
            painter.setBrush(QBrush(glow))
            painter.drawEllipse(QPointF(x, y), radius, radius)
        star_step = 120
        for gx in range(math.floor(rect.left() / star_step), math.ceil(rect.right() / star_step) + 1):
            for gy in range(math.floor(rect.top() / star_step), math.ceil(rect.bottom() / star_step) + 1):
                seed = ((gx * 73856093) ^ (gy * 19349663)) & 0xFFFFFFFF
                if seed % 5:
                    continue
                sx = gx * star_step + ((seed >> 6) % 100) + 10
                sy = gy * star_step + ((seed >> 13) % 100) + 10
                twinkle = 0.5 + 0.5 * math.sin(t * (0.6 + (seed % 7) * 0.15) + seed % 31)
                star = QColor(theme["accent"] if seed % 3 else theme["flow"])
                star.setAlpha(int(40 + 150 * twinkle))
                painter.setBrush(star)
                size = 0.9 + (seed >> 20) % 3 * 0.5
                painter.drawEllipse(QPointF(sx, sy), size, size)
        painter.restore()

    def drawBackground(self, painter, rect):
        # A restrained graphite board: soft surface gradient, fine drafting
        # grid, and occasional low-contrast grain that stays fixed while panning.
        theme = self._board_theme
        surface = QLinearGradient(QPointF(0, 0), QPointF(2600, 1800))
        surface.setColorAt(0.0, QColor(theme["surface"][0]))
        surface.setColorAt(0.55, QColor(theme["surface"][1]))
        surface.setColorAt(1.0, QColor(theme["surface"][2]))
        painter.fillRect(rect, QBrush(surface))

        if theme.get("scene") == "ocean":
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            wave_time = time.monotonic() / 6.0
            flow_color = QColor(theme["flow"])
            flow_color.setAlpha(24)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for band in range(5):
                base_y = 220 + band * 330
                path = QPainterPath()
                start_x = math.floor(rect.left() / 90) * 90 - 90
                end_x = rect.right() + 90
                path.moveTo(start_x, base_y + math.sin(start_x / 210.0 + band + wave_time) * 17)
                for px in range(int(start_x + 90), int(end_x + 90), 90):
                    py = base_y + math.sin(px / 210.0 + band + wave_time) * 17
                    path.lineTo(px, py)
                painter.setPen(QPen(flow_color, 1.2, Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                painter.drawPath(path)
            bubble_pen = QColor(theme["flow"]); bubble_pen.setAlpha(30)
            painter.setPen(QPen(bubble_pen, 1.1))
            for gx in range(math.floor(rect.left() / 240), math.ceil(rect.right() / 240) + 1):
                for gy in range(math.floor(rect.top() / 190), math.ceil(rect.bottom() / 190) + 1):
                    seed = (gx * 73856093) ^ (gy * 19349663)
                    if seed % 11 == 0:
                        bx = gx * 240 + ((seed >> 4) % 150) + 30
                        by = gy * 190 + ((seed >> 9) % 110) + 30
                        radius = 2 + ((seed >> 17) % 4)
                        painter.drawEllipse(QPointF(bx, by), radius, radius)
            painter.restore()

        if theme.get("scene") == "neon":
            self._draw_neon_scene(painter, rect, theme)

        spacing = 40
        left = int(rect.left()) - int(rect.left()) % spacing
        top = int(rect.top()) - int(rect.top()) % spacing
        x = left
        while x <= rect.right():
            major = (x // spacing) % 5 == 0
            grid_color = QColor(theme["grid"])
            grid_color.setAlpha(theme["major_alpha"] if major else theme["grid_alpha"])
            painter.setPen(QPen(grid_color, 0))
            painter.drawLine(x, rect.top(), x, rect.bottom())
            x += spacing
        y = top
        while y <= rect.bottom():
            major = (y // spacing) % 5 == 0
            grid_color = QColor(theme["grid"])
            grid_color.setAlpha(theme["major_alpha"] if major else theme["grid_alpha"])
            painter.setPen(QPen(grid_color, 0))
            painter.drawLine(rect.left(), y, rect.right(), y)
            y += spacing

        # Fixed, sparse surface specks give the canvas a board-like finish
        # without a timer or per-frame random generation.
        painter.setPen(Qt.PenStyle.NoPen)
        grain_color = QColor(theme["grain"])
        grain_color.setAlpha(theme["grain_alpha"])
        painter.setBrush(grain_color)
        grain_step = 84
        gx0 = math.floor(rect.left() / grain_step)
        gy0 = math.floor(rect.top() / grain_step)
        gx1 = math.ceil(rect.right() / grain_step)
        gy1 = math.ceil(rect.bottom() / grain_step)
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                seed = (gx * 73856093) ^ (gy * 19349663)
                if seed % 7:
                    continue
                px = gx * grain_step + ((seed >> 5) % 58) + 12
                py = gy * grain_step + ((seed >> 11) % 58) + 12
                painter.drawPoint(QPointF(px, py))

        # A thin inset frame and corner fasteners are visible when zoomed out
        # far enough to see the edge of the workspace.
        board = self.sceneRect().adjusted(8, 8, -8, -8)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        frame_color = QColor(theme["frame"])
        frame_color.setAlpha(theme["frame_alpha"])
        painter.setPen(QPen(frame_color, 1))
        painter.drawRect(board)
        painter.setPen(QPen(QColor(0, 0, 0, 110), 1))
        painter.drawRect(board.adjusted(2, 2, -2, -2))
        painter.setBrush(frame_color)
        painter.setPen(Qt.PenStyle.NoPen)
        for px in (board.left() + 13, board.right() - 13):
            for py in (board.top() + 13, board.bottom() - 13):
                painter.drawEllipse(QPointF(px, py), 2.0, 2.0)


class MessageDragHeader(QWidget):
    """A full-width title strip that moves its complete message card."""
    def __init__(self, row, app):
        super().__init__(row)
        self.row = row
        self.app = app
        self.proxy = None
        self._drag_origin = None
        self._drag_proxy_start_pos = None
        self._drag_zoom = 1.0
        self._drag_moved = False
        self._last_drag_pointer = None
        self._last_pointer_move_at = 0.0
        self._tilt_target = 0.0
        self._tilt_velocity = 0.0
        self._drag_shadow = None
        self._drag_animation = None
        self._drag_original_z = None
        self._previous_viewport_update_mode = None
        self._tilt_timer = QTimer(self)
        self._tilt_timer.setInterval(16)
        self._tilt_timer.timeout.connect(self._step_tilt_physics)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Потяни за верхнюю полоску, чтобы переместить сообщение")
        self.setMinimumHeight(26)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # A new card can still be gliding into its final slot. Stop that
            # positional animation before recording the grab point, otherwise
            # its next frame races the drag and makes the card jump away.
            entry_animation = getattr(self.row, "_message_entry_animation", None)
            if entry_animation is not None and entry_animation.state() == QAbstractAnimation.State.Running:
                entry_animation.stop()
                destination = getattr(self.row, "_message_target_pos", None)
                if destination is not None and self.proxy is not None:
                    self.proxy.setPos(destination)
                    self.proxy.setScale(1.0)
                    effect = getattr(self.row, "_ui_opacity_effect", None)
                    if effect is not None:
                        effect.setOpacity(1.0)
                self.row._message_entry_animation = None
            active = getattr(self.app, "_chat_scroll_animation", None)
            if active is not None and active.state() == QAbstractAnimation.State.Running:
                active.stop(); self.app._chat_scroll_animation = None
            self._drag_origin = event.globalPosition()
            self._drag_proxy_start_pos = self.proxy.pos() if self.proxy is not None else None
            view = getattr(self.app, "chat", None)
            self._drag_zoom = max(0.01, abs(view.transform().m11())) if view is not None else 1.0
            self._last_drag_pointer = self._drag_origin
            self._drag_moved = False
            self._tilt_target = 0.0
            self._tilt_velocity = 0.0
            self._last_pointer_move_at = time.monotonic()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            screen_delta = event.globalPosition() - self._drag_origin
            if (self._drag_moved or screen_delta.manhattanLength() > 4) and self.proxy is not None:
                first_drag_move = not self._drag_moved
                if not self._drag_moved:
                    self._lift_message()
                pointer = event.globalPosition()
                if first_drag_move:
                    # Use the threshold-crossing event only to begin dragging.
                    # Establish a fresh baseline after the lift starts so its
                    # first frame can never shift the card at non-100% zoom.
                    self._drag_origin = pointer
                    self._drag_proxy_start_pos = self.proxy.pos()
                    self._last_drag_pointer = pointer
                    self._last_pointer_move_at = time.monotonic()
                else:
                    # Convert screen-pixel movement into scene units using the
                    # actual view transform, preserving the press-time anchor.
                    screen_delta = pointer - self._drag_origin
                    requested_pos = self._drag_proxy_start_pos + QPointF(
                        screen_delta.x() / self._drag_zoom,
                        screen_delta.y() / self._drag_zoom)
                    self.proxy.setPos(self.app._clamp_message_position(self.proxy, requested_pos))
                    pointer_delta = pointer - self._last_drag_pointer
                    self._last_drag_pointer = pointer
                    if pointer_delta.x():
                        self._set_tilt_from_pointer(pointer_delta.x())
                self.app._grow_canvas_for_item(self.proxy)
                self.app._update_message_connectors(self.proxy)
                self.app._canvas_latest_item = self.proxy
                self.app._pause_canvas_follow()
                self._drag_moved = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_origin is not None:
            was_dragged = self._drag_moved
            self._drag_origin = None
            self._drag_proxy_start_pos = None
            self._drag_zoom = 1.0
            self._last_drag_pointer = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            if was_dragged:
                self._land_message()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _stop_drag_animation(self):
        if self._drag_animation is not None:
            self._drag_animation.stop()
            self._drag_animation.deleteLater()
            self._drag_animation = None

    def _lift_message(self):
        if self.proxy is None:
            return
        self._stop_drag_animation()
        self._drag_original_z = self.proxy.zValue()
        scene_items = self.proxy.scene().items() if self.proxy.scene() is not None else []
        self.proxy.setZValue(max((item.zValue() for item in scene_items), default=0) + 1)
        view = getattr(self.app, "chat", None)
        if view is not None:
            self._previous_viewport_update_mode = view.viewportUpdateMode()
            view.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self._drag_shadow = QGraphicsDropShadowEffect()
        self._drag_shadow.setBlurRadius(0)
        self._drag_shadow.setOffset(0, 2)
        self._drag_shadow.setColor(QColor(0, 0, 0, 150))
        self.proxy.setGraphicsEffect(self._drag_shadow)
        animation = QParallelAnimationGroup(self)
        scale = QPropertyAnimation(self.proxy, b"scale", animation)
        zoom = max(0.45, float(getattr(getattr(self.app, "chat", None), "_zoom", 1.0)))
        lift_scale = 1.0 + 0.045 / zoom
        scale.setDuration(170); scale.setStartValue(self.proxy.scale()); scale.setEndValue(lift_scale)
        scale.setEasingCurve(QEasingCurve.Type.OutCubic); animation.addAnimation(scale)
        blur = QPropertyAnimation(self._drag_shadow, b"blurRadius", animation)
        blur.setDuration(190); blur.setStartValue(0.0); blur.setEndValue(22.0)
        blur.setEasingCurve(QEasingCurve.Type.OutCubic); animation.addAnimation(blur)
        offset = QPropertyAnimation(self._drag_shadow, b"offset", animation)
        offset.setDuration(190); offset.setStartValue(QPointF(0, 2)); offset.setEndValue(QPointF(0, 12))
        offset.setEasingCurve(QEasingCurve.Type.OutCubic); animation.addAnimation(offset)
        self._drag_animation = animation
        animation.start()

    def _set_tilt_from_pointer(self, delta_x):
        now = time.monotonic()
        elapsed = max(0.008, min(0.08, now - self._last_pointer_move_at))
        self._last_pointer_move_at = now
        horizontal_speed = delta_x / elapsed
        zoom = max(0.45, float(getattr(getattr(self.app, "chat", None), "_zoom", 1.0)))
        screen_scaled_tilt = horizontal_speed / 450.0 * 10.0
        self._tilt_target = max(-10.0 / zoom, min(10.0 / zoom, screen_scaled_tilt / zoom))
        if not self._tilt_timer.isActive():
            self._tilt_timer.start()

    def _step_tilt_physics(self):
        if self.proxy is None or not self._drag_moved:
            self._tilt_timer.stop()
            return
        now = time.monotonic()
        if now - self._last_pointer_move_at > 0.09:
            self._tilt_target = 0.0
        dt = 0.016
        angle = self.proxy.rotation()
        # A damped spring follows mouse speed and naturally settles at zero.
        acceleration = 110.0 * (self._tilt_target - angle) - 20.0 * self._tilt_velocity
        self._tilt_velocity += acceleration * dt
        angle += self._tilt_velocity * dt
        if angle > 10.0:
            angle = 10.0; self._tilt_velocity = min(0.0, self._tilt_velocity)
        elif angle < -10.0:
            angle = -10.0; self._tilt_velocity = max(0.0, self._tilt_velocity)
        if self._tilt_target == 0.0 and abs(angle) < 0.08 and abs(self._tilt_velocity) < 0.45:
            angle = 0.0
            self._tilt_velocity = 0.0
            self.proxy.setRotation(angle)
            self._tilt_timer.stop()
        else:
            self.proxy.setRotation(angle)
        self.app._update_message_connectors(self.proxy)

    def _land_message(self):
        if self.proxy is None:
            return
        self._stop_drag_animation()
        self._tilt_timer.stop()
        self._tilt_target = 0.0
        self._tilt_velocity = 0.0
        animation = QParallelAnimationGroup(self)
        scale = QPropertyAnimation(self.proxy, b"scale", animation)
        scale.setDuration(520); scale.setStartValue(self.proxy.scale()); scale.setEndValue(1.0)
        scale.setEasingCurve(QEasingCurve.Type.InOutCubic); animation.addAnimation(scale)
        rotation = QPropertyAnimation(self.proxy, b"rotation", animation)
        rotation.setDuration(520); rotation.setStartValue(self.proxy.rotation()); rotation.setEndValue(0.0)
        rotation.setEasingCurve(QEasingCurve.Type.InOutCubic); animation.addAnimation(rotation)
        shadow = self._drag_shadow
        if shadow is not None:
            blur = QPropertyAnimation(shadow, b"blurRadius", animation)
            blur.setDuration(520); blur.setStartValue(shadow.blurRadius()); blur.setEndValue(0.0)
            blur.setEasingCurve(QEasingCurve.Type.InOutCubic); animation.addAnimation(blur)
            offset = QPropertyAnimation(shadow, b"offset", animation)
            offset.setDuration(520); offset.setStartValue(shadow.offset()); offset.setEndValue(QPointF(0, 0))
            offset.setEasingCurve(QEasingCurve.Type.InOutCubic); animation.addAnimation(offset)
            animation.finished.connect(lambda effect=shadow: self._remove_drag_shadow(effect))
        self._drag_animation = animation
        animation.start()

    def _remove_drag_shadow(self, effect):
        if self.proxy is not None and self.proxy.graphicsEffect() is effect:
            # QGraphicsItem owns and deletes the installed effect when it is removed.
            self.proxy.setGraphicsEffect(None)
        if self._drag_shadow is effect:
            self._drag_shadow = None
        if self.proxy is not None and self._drag_original_z is not None:
            self.proxy.setZValue(self._drag_original_z)
            self._drag_original_z = None
        view = getattr(self.app, "chat", None)
        if view is not None and self._previous_viewport_update_mode is not None:
            view.setViewportUpdateMode(self._previous_viewport_update_mode)
            self._previous_viewport_update_mode = None
        self._drag_animation = None


class DragStripeIndicator(QWidget):
    """Diagonal grip marks shown on draggable message headers."""
    def __init__(self, parent=None, message_length=0):
        super().__init__(parent)
        self.setMinimumWidth(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(24)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.color = "#3a3a3a"

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(self.color), 1.0, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        step = 13
        count = max(1, min(128, (self.width() - 8) // step))
        for index in range(count):
            x = 4 + index * step
            painter.drawLine(x, 20, x + 8, 4)
        painter.end()


class GenerationMosaic(QWidget):
    """A restrained animated tile field shown while ComfyUI renders an image."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(278, 278)
        self._started = time.monotonic()
        self._timer = QTimer(self)
        # Keep the generation preview smooth without competing with GPU work.
        self._timer.setInterval(50)
        self._timer.timeout.connect(self.update)
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        bounds = self.rect().adjusted(8, 8, -8, -8)
        columns, rows, cell, gap = 12, 12, 16, 5
        pitch = cell + gap
        grid_width = columns * cell + (columns - 1) * gap
        grid_height = rows * cell + (rows - 1) * gap
        left = round(bounds.center().x() - grid_width / 2)
        top = round(bounds.center().y() - grid_height / 2)
        # Sweep one soft diagonal beam from the upper-right corner to the
        # lower-left, then fade it out before the next pass starts.
        cycle = (time.monotonic() - self._started) % 6.4
        phase = cycle / 6.4
        edge_fade = min(1.0, phase * 9.0, (1.0 - phase) * 9.0)
        painter.setPen(Qt.PenStyle.NoPen)
        for row in range(rows):
            for column in range(columns):
                rect = QRect(left + column * pitch, top + row * pitch, cell, cell)
                along_sweep = ((columns - 1 - column) / (columns - 1)
                               + row / (rows - 1)) / 2.0
                distance = abs(along_sweep - phase)
                beam = max(0.0, 1.0 - distance / 0.27)
                beam = beam * beam * (3.0 - 2.0 * beam) * edge_fade
                shade = round(25 + 130 * beam)
                painter.setBrush(QColor(shade, shade, shade))
                painter.drawRect(rect)
        painter.end()

def fade_in_widget(widget, duration=240, start=0.0, end=1.0, delay=0):
    effect=getattr(widget,"_ui_opacity_effect",None)
    if effect is None:
        effect=QGraphicsOpacityEffect(widget); widget.setGraphicsEffect(effect); widget._ui_opacity_effect=effect
    animation=getattr(widget,"_ui_opacity_animation",None)
    if animation is None:
        animation=QPropertyAnimation(effect,b"opacity",widget); widget._ui_opacity_animation=animation
    animation.stop(); effect.setOpacity(start); animation.setDuration(duration)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic); animation.setStartValue(start); animation.setEndValue(end)
    if delay: QTimer.singleShot(delay,animation.start)
    else: animation.start()
    return animation


class SmoothPressFeedback(QObject):
    """A small opacity pulse gives every button a consistent, soft press response."""
    def __init__(self, widget):
        super().__init__(widget)
        self.effect=QGraphicsOpacityEffect(widget); self.effect.setOpacity(1.0); widget.setGraphicsEffect(self.effect)
        self.animation=QPropertyAnimation(self.effect,b"opacity",widget); self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        widget.installEventFilter(self)

    def _animate(self, target, duration):
        self.animation.stop(); self.animation.setDuration(duration)
        self.animation.setStartValue(self.effect.opacity()); self.animation.setEndValue(target); self.animation.start()

    def eventFilter(self, watched, event):
        if event.type()==QEvent.Type.MouseButtonPress and watched.isEnabled(): self._animate(.93,85)
        elif event.type()==QEvent.Type.MouseButtonRelease: self._animate(1.0,210)
        elif event.type()==QEvent.Type.Leave and self.effect.opacity()<1.0: self._animate(1.0,210)
        return False


def add_press_feedback(widget):
    # QGraphicsOpacityEffect on native Qt buttons can leave their styled
    # background cached until hover on Windows. Keep the reliable stylesheet
    # hover/pressed states instead; animated opacity remains on larger panels.
    widget.setAttribute(Qt.WidgetAttribute.WA_Hover, True)


class IconHoverMotion(QObject):
    """Animate only a button icon, keeping the rest of the UI inexpensive."""
    def __init__(self, button, size):
        super().__init__(button)
        self.button = button
        self.size = size
        self.progress = 0.0
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(150)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._set_progress)
        button.installEventFilter(self)

    def _set_progress(self, value):
        self.progress = float(value)
        side = round(self.size + self.progress * 2.4)
        self.button.setIconSize(QSize(side, side))

    def _animate(self, target):
        self.animation.stop()
        self.animation.setStartValue(self.progress)
        self.animation.setEndValue(target)
        self.animation.start()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Enter and watched.isEnabled():
            self._animate(1.0)
        elif event.type() == QEvent.Type.Leave:
            self._animate(0.0)
        return False


def add_icon_hover_motion(button, size):
    if not hasattr(button, "_icon_hover_motion"):
        button._icon_hover_motion = IconHoverMotion(button, size)


class ToggleSwitch(QCheckBox):
    def __init__(self, checked=True, parent=None):
        super().__init__(parent)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(44, 26)
        self.on_color = QColor("#ffffff")
        self.off_color = QColor("#353535")
        self.rounded = False
        self._switch_progress=1.0 if checked else 0.0
        self.stateChanged.connect(self._animate_switch)
        self._switch_animation=QVariantAnimation(self)
        self._switch_animation.setDuration(190); self._switch_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._switch_animation.valueChanged.connect(self._set_switch_progress)

    def _animate_switch(self,state):
        self._switch_animation.stop(); self._switch_animation.setStartValue(self._switch_progress)
        self._switch_animation.setEndValue(1.0 if state else 0.0); self._switch_animation.start()

    def _set_switch_progress(self,value):
        self._switch_progress=float(value); self.update()

    def sizeHint(self):
        return QSize(44, 26)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        painter = QPainter(self)
        track = self.rect().adjusted(1, 2, -1, -2)
        painter.setPen(Qt.PenStyle.NoPen)
        t=self._switch_progress
        track_color=QColor(round(self.off_color.red()+(self.on_color.red()-self.off_color.red())*t),round(self.off_color.green()+(self.on_color.green()-self.off_color.green())*t),round(self.off_color.blue()+(self.on_color.blue()-self.off_color.blue())*t))
        painter.setBrush(track_color)
        diameter = 16
        left_x=track.left()+2; right_x=track.right()-diameter-2
        x=round(left_x+(right_x-left_x)*t)
        knob = QColor("#050505") if t >= 0.5 else QColor("#f5f5f5")
        knob_rect = QRectF(x, track.top() + (track.height() - diameter) // 2, diameter, diameter)
        if self.rounded:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if t > 0:
                halo = QColor(self.on_color); halo.setAlpha(int(70 * t))
                painter.setBrush(halo)
                painter.drawRoundedRect(QRectF(track).adjusted(-2, -2, 2, 2), track.height() / 2 + 2, track.height() / 2 + 2)
                painter.setBrush(track_color)
            painter.drawRoundedRect(QRectF(track), track.height() / 2, track.height() / 2)
            painter.setBrush(knob)
            painter.drawEllipse(knob_rect)
        else:
            painter.drawRect(track)
            painter.setBrush(knob)
            painter.drawRect(knob_rect)
        painter.end()


def draw_material_icon(painter, name, color, size):
    """Draw a Material Symbol recoloured to `color`; False if the icon has none or its file is missing."""
    filename = MATERIAL_ICONS.get(name)
    if not filename:
        return False
    key = (filename, QColor(color).name(QColor.NameFormat.HexArgb))
    renderer = _material_renderers.get(key)
    if renderer is None:
        try:
            svg = (ICON_DIR / f"{filename}.svg").read_text(encoding="utf-8")
        except OSError:
            return False
        svg = re.sub(r'fill="#[0-9a-fA-F]{3,8}"', f'fill="{QColor(color).name()}" fill-opacity="{QColor(color).alphaF():.3f}"', svg)
        renderer = _material_renderers[key] = QSvgRenderer(svg.encode("utf-8"))
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.restore()
    return True


def draw_vector_icon(painter, name, color, size=24):
    if draw_material_icon(painter, name, color, size):
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / 24.0, size / 24.0)
    pen = QPen(QColor(color), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    if name == "mic":
        painter.drawRect(9, 3, 6, 12)
        path.moveTo(6, 11); path.lineTo(6, 13); path.lineTo(8, 17); path.lineTo(12, 19)
        path.lineTo(16, 17); path.lineTo(18, 13); path.lineTo(18, 11)
        painter.drawPath(path); painter.drawLine(12, 19, 12, 22); painter.drawLine(8, 22, 16, 22)
    elif name == "headphones":
        path.moveTo(4, 13); path.lineTo(4, 11); path.cubicTo(4, 1, 20, 1, 20, 11); path.lineTo(20, 13)
        painter.drawPath(path); painter.drawRoundedRect(3, 12, 4, 7, 2, 2); painter.drawRoundedRect(17, 12, 4, 7, 2, 2)
    elif name in ("screen", "monitor"):
        painter.drawRect(3, 4, 18, 13); painter.drawLine(12, 17, 12, 21); painter.drawLine(8, 21, 16, 21)
    elif name == "sparkles":
        path.moveTo(12, 2); path.lineTo(14, 9); path.lineTo(21, 12); path.lineTo(14, 14); path.lineTo(12, 22); path.lineTo(10, 14); path.lineTo(3, 12); path.lineTo(10, 9); path.closeSubpath()
        painter.drawPath(path); painter.drawLine(19, 3, 19, 7); painter.drawLine(17, 5, 21, 5)
    elif name == "image":
        painter.drawRect(3, 4, 18, 16); painter.drawEllipse(7, 8, 3, 3)
        path.moveTo(4, 17); path.lineTo(9, 12); path.lineTo(13, 16); path.lineTo(16, 13); path.lineTo(20, 18); painter.drawPath(path)
    elif name == "chat":
        painter.drawRoundedRect(3, 4, 18, 14, 2, 2)
        path.moveTo(8, 18); path.lineTo(6, 22); path.lineTo(13, 18); painter.drawPath(path)
    elif name == "settings":
        # Eight identical, evenly spaced teeth keep the cog balanced at small sizes.
        tooth_profile = ((-22.5, 8.0), (-15.0, 8.0), (-12.0, 10.2),
                         (12.0, 10.2), (15.0, 8.0), (22.5, 8.0))
        gear_points = []
        for tooth in range(8):
            center_angle = -90 + tooth * 45
            for offset, radius in tooth_profile:
                angle = math.radians(center_angle + offset)
                gear_points.append(QPointF(12 + math.cos(angle) * radius,
                                           12 + math.sin(angle) * radius))
        path.moveTo(gear_points[0])
        for point in gear_points[1:]:
            path.lineTo(point)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawEllipse(8.5, 8.5, 7, 7)
    elif name in ("refresh", "loop"):
        path.moveTo(19, 9); path.cubicTo(17, 4, 12, 3, 8, 5); path.cubicTo(3, 7, 3, 15, 7, 18); path.cubicTo(11, 22, 18, 20, 20, 15)
        painter.drawPath(path); path = QPainterPath(); path.moveTo(15, 8); path.lineTo(20, 9); path.lineTo(21, 4); painter.drawPath(path)
    elif name == "play":
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(color)); path.moveTo(7, 4); path.lineTo(20, 12); path.lineTo(7, 20); path.closeSubpath(); painter.drawPath(path)
    elif name == "pause":
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(color)); painter.drawRoundedRect(5, 4, 5, 16, 1, 1); painter.drawRoundedRect(14, 4, 5, 16, 1, 1)
    elif name == "send":
        path.moveTo(3, 11); path.lineTo(21, 3); path.lineTo(16, 21); path.lineTo(11, 14); path.lineTo(3, 11); path.moveTo(11, 14); path.lineTo(21, 3); painter.drawPath(path)
    elif name in ("copy", "clone"):
        painter.setPen(QPen(QColor(color), 2.0, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin))
        painter.drawRect(8, 3, 12, 14)
        path.moveTo(8, 7); path.lineTo(5, 7); path.lineTo(5, 21)
        path.lineTo(17, 21); path.lineTo(17, 17)
        painter.drawPath(path)
    elif name == "retry":
        painter.setPen(QPen(QColor(color), 2.1, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        path.moveTo(15, 10); path.lineTo(20, 10); path.lineTo(20, 5)
        path.moveTo(19, 10); path.cubicTo(18, 6, 14, 4, 11, 4)
        path.cubicTo(6, 4, 3, 8, 3, 12); path.cubicTo(3, 17, 7, 20, 12, 20)
        path.cubicTo(15, 20, 18, 18, 19, 15)
        painter.drawPath(path)
    elif name == "speak":
        painter.setPen(QPen(QColor(color), 2.1, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        path.moveTo(2, 9); path.lineTo(7, 9); path.lineTo(14, 4); path.lineTo(14, 20)
        path.lineTo(7, 15); path.lineTo(2, 15); path.closeSubpath(); painter.drawPath(path)
        painter.setPen(QPen(QColor(color), 2.1, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath(); path.moveTo(16, 8); path.cubicTo(20, 10, 20, 14, 16, 16)
        path.moveTo(17, 4); path.cubicTo(24, 8, 24, 16, 17, 20)
        painter.drawPath(path)
    elif name in ("volume", "speaker"):
        path.moveTo(3, 9); path.lineTo(7, 9); path.lineTo(12, 5); path.lineTo(12, 19); path.lineTo(7, 15); path.lineTo(3, 15); path.closeSubpath(); painter.drawPath(path)
        path=QPainterPath(); path.moveTo(16, 9); path.cubicTo(19, 11, 19, 13, 16, 15); painter.drawPath(path)
        path=QPainterPath(); path.moveTo(18, 6); path.cubicTo(23, 10, 23, 14, 18, 18); painter.drawPath(path)
    elif name == "voice_wave":
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(color))
        for x, height in ((3, 7), (7, 13), (11, 19), (15, 12), (19, 6)):
            painter.drawRect(x, 12 - height // 2, 2, height)
    elif name == "merge":
        painter.drawRect(3, 5, 9, 9); painter.drawRect(12, 10, 9, 9)
        painter.drawLine(10, 12, 14, 12); painter.drawLine(12, 10, 12, 14)
    elif name == "chevron-down":
        path.moveTo(5, 8); path.lineTo(12, 15); path.lineTo(19, 8); painter.drawPath(path)
    elif name == "arrow-down":
        painter.drawLine(12, 3, 12, 19)
        painter.drawLine(6, 13, 12, 19); painter.drawLine(18, 13, 12, 19)
    elif name == "plus":
        painter.drawLine(12, 4, 12, 20); painter.drawLine(4, 12, 20, 12)
    elif name == "close":
        painter.drawLine(5, 5, 19, 19); painter.drawLine(19, 5, 5, 19)
    elif name == "more":
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(color))
        for x in (4, 10, 16):
            painter.drawRect(x, 10, 4, 4)
    elif name in ("panel", "panel-expand"):
        painter.drawRect(3, 4, 18, 16); painter.drawLine(9, 5, 9, 19)
        if name == "panel-expand":
            painter.drawLine(12, 12, 19, 12); painter.drawLine(16, 9, 19, 12); painter.drawLine(16, 15, 19, 12)
    elif name == "stop":
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(color)); painter.drawRect(6, 6, 12, 12)
    elif name == "file":
        path.moveTo(6, 3); path.lineTo(15, 3); path.lineTo(19, 7); path.lineTo(19, 21)
        path.lineTo(5, 21); path.lineTo(5, 3); path.closeSubpath(); painter.drawPath(path)
        painter.drawLine(8, 11, 16, 11); painter.drawLine(8, 15, 16, 15)
    elif name == "video":
        painter.drawRect(3, 5, 13, 14)
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(color))
        path.moveTo(9, 9); path.lineTo(14, 12); path.lineTo(9, 15); path.closeSubpath(); painter.drawPath(path)
        painter.setPen(pen); painter.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath(); path.moveTo(16, 9); path.lineTo(21, 6); path.lineTo(21, 18); path.lineTo(16, 15); painter.drawPath(path)
    elif name == "audio":
        painter.setPen(QPen(QColor(color), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap))
        for x, height in ((4, 7), (8, 13), (12, 19), (16, 11), (20, 6)):
            painter.drawLine(x, 12 - height // 2, x, 12 + height // 2)
    painter.restore()


def vector_icon(name, color, size=20):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    draw_vector_icon(painter, name, color, size)
    painter.end()
    return QIcon(pixmap)


class VectorIconWidget(QWidget):
    def __init__(self, name, color="#f5f5f5", parent=None):
        super().__init__(parent)
        self.name = name
        self.color = QColor(color)
        self._motion_progress = 0.0
        self._motion_animation = QVariantAnimation(self)
        self._motion_animation.setDuration(190)
        self._motion_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._motion_animation.valueChanged.connect(self._set_motion_progress)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def _set_motion_progress(self, value):
        self._motion_progress = float(value)
        self.update()

    def _animate_hover(self, target):
        self._motion_animation.stop()
        self._motion_animation.setStartValue(self._motion_progress)
        self._motion_animation.setEndValue(target)
        self._motion_animation.start()

    def enterEvent(self, event):
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def set_color(self, color):
        self.color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        painter.translate(center)
        painter.scale(1.0 + self._motion_progress * 0.10,
                      1.0 + self._motion_progress * 0.10)
        rotation = 24.0 if self.name == "settings" else (70.0 if self.name == "loop" else 0.0)
        painter.rotate(rotation * self._motion_progress)
        painter.translate(-center.x(), -center.y())
        painter.translate((self.width() - 20) / 2, (self.height() - 20) / 2)
        draw_vector_icon(painter, self.name, self.color.name(), 20)
        painter.end()


class VectorActionButton(QToolButton):
    """Small message action button that paints its glyph at display resolution."""
    def __init__(self, icon_name, color, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.icon_color = QColor(color)
        self._hover_progress = 0.0
        self._hover_animation = QVariantAnimation(self)
        self._hover_animation.setDuration(150)
        self._hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_animation.valueChanged.connect(self._set_hover_progress)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def set_vector_color(self, color):
        self.icon_color = QColor(color)
        self.update()

    def _set_hover_progress(self, value):
        self._hover_progress = float(value)
        self.update()

    def _animate_hover(self, target):
        self._hover_animation.stop()
        self._hover_animation.setStartValue(self._hover_progress)
        self._hover_animation.setEndValue(target)
        self._hover_animation.start()

    def enterEvent(self, event):
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event):
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.icon = QIcon()
        option.text = ""
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, option)
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        scale = 1.0 + self._hover_progress * 0.07
        painter.translate(center)
        painter.scale(scale, scale)
        painter.translate(-10, -10)
        draw_vector_icon(painter, self.icon_name, self.icon_color.name(), 20)
        painter.end()


class SelectedCheckDelegate(QStyledItemDelegate):
    """Draw a compact check beside the currently selected popup item."""
    def __init__(self, combo):
        super().__init__(combo)
        self.combo = combo

    def paint(self, painter, option, index):
        adjusted = QStyleOptionViewItem(option)
        adjusted.rect = option.rect.adjusted(24, 0, 0, 0)
        super().paint(painter, adjusted, index)
        if index.row() == self.combo.currentIndex():
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor("#ffffff"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            x, y = option.rect.left() + 8, option.rect.center().y()
            mark = QPainterPath(); mark.moveTo(x, y); mark.lineTo(x + 4, y + 4); mark.lineTo(x + 11, y - 4)
            painter.drawPath(mark)
            painter.restore()


class CheckComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.arrow_color = QColor("#f5f5f5")
        self._arrow_progress = 0.0
        self._arrow_animation = QVariantAnimation(self)
        self._arrow_animation.setDuration(145)
        self._arrow_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._arrow_animation.valueChanged.connect(self._set_arrow_progress)
        self.setItemDelegate(SelectedCheckDelegate(self))

    def _set_arrow_progress(self, value):
        self._arrow_progress = float(value)
        self.update()

    def _animate_arrow(self, target):
        self._arrow_animation.stop()
        self._arrow_animation.setStartValue(self._arrow_progress)
        self._arrow_animation.setEndValue(target)
        self._arrow_animation.start()

    def showPopup(self):
        self._animate_arrow(1.0)
        super().showPopup()

    def hidePopup(self):
        super().hidePopup()
        self._animate_arrow(0.0)

    def paintEvent(self, event):
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        arrow_control = QStyle.SubControl.SC_ComboBoxArrow
        option.subControls &= ~arrow_control
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        if not self.isEditable():
            painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)
        arrow_rect = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option, arrow_control, self)
        painter.save()
        painter.translate(arrow_rect.center())
        painter.rotate(180.0 * self._arrow_progress)
        painter.translate(-7, -7)
        draw_vector_icon(painter, "chevron-down", self.arrow_color, 14)
        painter.restore()
        painter.end()


IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")


def image_paths_from_mime(mime):
    """Return local image files carried by a clipboard or drag-and-drop payload."""
    if mime is None or not mime.hasUrls():
        return []
    return [url.toLocalFile() for url in mime.urls()
            if url.isLocalFile() and url.toLocalFile().lower().endswith(IMAGE_SUFFIXES)]


class ComposerLineEdit(QLineEdit):
    """Composer input with Up/Down request history and image paste/drop."""
    imagesProvided = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.history = []
        self._history_index = None
        self._history_draft = ""

    def remember(self, text):
        text = str(text or "").strip()
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
            del self.history[:-100]
        self._history_index = None

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Up and self.history:
            if self._history_index is None:
                self._history_draft = self.text()
                self._history_index = len(self.history)
            self._history_index = max(0, self._history_index - 1)
            self.setText(self.history[self._history_index])
            return
        if key == Qt.Key.Key_Down and self._history_index is not None:
            self._history_index += 1
            if self._history_index >= len(self.history):
                self._history_index = None
                self.setText(self._history_draft)
            else:
                self.setText(self.history[self._history_index])
            return
        if event.matches(QKeySequence.StandardKey.Paste):
            mime = QApplication.clipboard().mimeData()
            paths = image_paths_from_mime(mime)
            if not paths and mime is not None and mime.hasImage() and not mime.hasText():
                image = QApplication.clipboard().image()
                if not image.isNull():
                    folder = DATA_DIR / "pasted_images"
                    folder.mkdir(parents=True, exist_ok=True)
                    path = folder / f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}.png"
                    if image.save(str(path), "PNG"):
                        paths = [str(path)]
            if paths:
                self.imagesProvided.emit(paths)
                return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if image_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event):
        paths = image_paths_from_mime(event.mimeData())
        if paths:
            event.acceptProposedAction()
            self.imagesProvided.emit(paths)
            return
        super().dropEvent(event)


class ClickableImagePreview(QLabel):
    clicked = Signal(str)

    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.image_path = str(image_path)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Открыть изображение · колесо мыши изменяет масштаб")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.image_path)
            event.accept()
            return
        super().mousePressEvent(event)


class ImageZoomScrollArea(QScrollArea):
    def __init__(self, viewer, parent=None):
        super().__init__(parent)
        self.viewer = viewer

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta:
            self.viewer.zoom_by(1.15 if delta > 0 else 1 / 1.15, event.position().toPoint())
            event.accept()
            return
        super().wheelEvent(event)


class ImageViewerDialog(QDialog):
    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.image_path = str(image_path)
        self.original = QPixmap(self.image_path)
        self.scale = 1.0
        self.setWindowTitle(Path(self.image_path).name)
        self.setMinimumSize(560, 420)
        self.resize(980, 720)
        self.setStyleSheet("QDialog{background:#090909;color:#f5f5f5} QLabel{color:#f5f5f5} QPushButton{background:#191919;color:#fff;border:1px solid #484848;padding:8px 12px} QPushButton:hover{border-color:#fff} QScrollArea{background:#070707;border:1px solid #383838}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        controls = QHBoxLayout()
        zoom_out = QPushButton("−"); zoom_out.clicked.connect(lambda: self.zoom_by(1 / 1.2))
        zoom_in = QPushButton("+"); zoom_in.clicked.connect(lambda: self.zoom_by(1.2))
        fit = QPushButton("Вписать"); fit.clicked.connect(self.fit_image)
        self.zoom_label = QLabel("100%")
        controls.addWidget(zoom_out); controls.addWidget(zoom_in); controls.addWidget(fit)
        controls.addWidget(self.zoom_label); controls.addStretch(1)
        save = QPushButton("Сохранить как…"); save.clicked.connect(self.save_copy); controls.addWidget(save)
        layout.addLayout(controls)

        self.scroll = ImageZoomScrollArea(self)
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("background:#070707;border:0")
        self.scroll.setWidget(self.image_label)
        layout.addWidget(self.scroll, 1)
        if self.original.isNull():
            self.image_label.setText("Не удалось открыть изображение.")
        else:
            self._render_image()
            QTimer.singleShot(0, self.fit_image)

    def _render_image(self):
        size = QSize(max(1, round(self.original.width() * self.scale)),
                     max(1, round(self.original.height() * self.scale)))
        scaled = self.original.scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
        self.image_label.setPixmap(scaled)
        self.image_label.setFixedSize(scaled.size())
        self.zoom_label.setText(f"{round(self.scale * 100)}%")

    def fit_image(self):
        if self.original.isNull():
            return
        area = self.scroll.viewport().size()
        if area.width() < 2 or area.height() < 2:
            return
        self.scale = min(1.0, (area.width() - 16) / self.original.width(),
                         (area.height() - 16) / self.original.height())
        self._render_image()
        self.scroll.horizontalScrollBar().setValue(0)
        self.scroll.verticalScrollBar().setValue(0)

    def zoom_by(self, multiplier, anchor=None):
        if self.original.isNull():
            return
        old_scale = self.scale
        self.scale = max(0.1, min(8.0, self.scale * multiplier))
        if abs(self.scale - old_scale) < 1e-5:
            return
        if anchor is None:
            anchor = self.scroll.viewport().rect().center()
        viewport = self.scroll.viewport().size()
        old_offset_x = max(0, (viewport.width() - self.image_label.width()) // 2)
        old_offset_y = max(0, (viewport.height() - self.image_label.height()) // 2)
        image_x = (self.scroll.horizontalScrollBar().value() + anchor.x() - old_offset_x) / old_scale
        image_y = (self.scroll.verticalScrollBar().value() + anchor.y() - old_offset_y) / old_scale
        self._render_image()
        QTimer.singleShot(0, lambda: self._restore_zoom_anchor(image_x, image_y, anchor))

    def _restore_zoom_anchor(self, image_x, image_y, anchor):
        viewport = self.scroll.viewport().size()
        offset_x = max(0, (viewport.width() - self.image_label.width()) // 2)
        offset_y = max(0, (viewport.height() - self.image_label.height()) // 2)
        self.scroll.horizontalScrollBar().setValue(round(image_x * self.scale + offset_x - anchor.x()))
        self.scroll.verticalScrollBar().setValue(round(image_y * self.scale + offset_y - anchor.y()))

    def save_copy(self):
        if self.original.isNull():
            return
        filters = "PNG (*.png);;JPEG (*.jpg *.jpeg);;WebP (*.webp);;Все файлы (*.*)"
        target, selected_filter = QFileDialog.getSaveFileName(
            self, "Сохранить изображение", self.image_path, filters)
        if not target:
            return
        suffix = Path(target).suffix.lower()
        if not suffix:
            suffix = ".jpg" if "JPEG" in selected_filter else (".webp" if "WebP" in selected_filter else ".png")
            target += suffix
        image_format = {".jpg": "JPG", ".jpeg": "JPG", ".webp": "WEBP"}.get(suffix, "PNG")
        if not self.original.save(target, image_format):
            QMessageBox.warning(self, "Сохранение изображения", "Не удалось сохранить копию файла.")
            return
        QMessageBox.information(self, "Сохранение изображения", f"Изображение сохранено:\n{target}")


class HuggingFaceSignals(QObject):
    files_found = Signal(object)
    progress = Signal(int, str)
    finished = Signal(str, str)
    failed = Signal(str)


class GuiInvoker(QObject):
    """Blocks a worker thread until a callable has run on the Qt thread."""
    call = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.call.connect(self._run, Qt.ConnectionType.BlockingQueuedConnection)

    def _run(self, job):
        job()


class CompanionApp(QMainWindow, CompanionCore):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Компаньон · Ollama")
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        if available:
            min_width = max(560, min(1080, available.width() - 32))
            min_height = max(460, min(700, available.height() - 60))
            self.setMinimumSize(min_width, min_height)
            self.resize(min(1440, available.width() - 24), min(900, available.height() - 48))
        else:
            self.setMinimumSize(1080, 700)
            self.resize(1440, 900)
        self.setWindowOpacity(0.0)
        self.init_core(theme_ids=CANVAS_THEMES)
        self._gui_invoker = GuiInvoker(self)
        self._conversation_save_timer = QTimer(self)
        self._conversation_save_timer.setSingleShot(True)
        self._conversation_save_timer.setInterval(450)
        self._conversation_save_timer.timeout.connect(self._write_conversation_now)
        self.vars = {}
        self.switches = []
        self.icon_badges = []
        self._entrance_done=False
        self._build()
        self._apply_theme()
        self.refresh_models()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._drain_events)
        self.timer.start(120)
        self.activity_started_at=None
        self.activity_transient_until=None
        self.activity_text="Готов к работе"
        self.activity_timer=QTimer(self)
        self.activity_timer.timeout.connect(self._refresh_activity)
        # Status elapsed time changes once per second; refresh at that cadence.
        self.activity_timer.start(1000)
        if self.dialogue_items:
            restored = self.dialogue_items
            self.dialogue_items = []
            self._restore_dialogue_items(restored, self._save_conversation)
        else:
            self._append("system", "Всё готово к разговору. Подключитесь к Ollama, выберите vision-модель и нажмите «Старт».\n\nКомпаньон работает локально: слышит включённые источники, отвечает голосом и иногда комментирует происходящее на экране.")

    def after(self, ms, callback):
        QTimer.singleShot(ms, callback)

    def _build(self):
        root = Artboard(); root.setObjectName("appRoot"); self.setCentralWidget(root)
        # One continuous application shell: the bar, navigation and workspace
        # share edges instead of reading as a row of separate floating cards.
        outer = QVBoxLayout(root); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        top_bar = SquareDecoratedFrame(); top_bar.setObjectName("topBar"); top_bar.setFixedHeight(68); outer.addWidget(top_bar)
        header = QHBoxLayout(top_bar); header.setContentsMargins(18, 8, 14, 8); header.setSpacing(12)
        brand_icon = QLabel(); brand_icon.setObjectName("brandLogoHeader")
        brand_icon.setAlignment(Qt.AlignmentFlag.AlignCenter); brand_icon.setFixedSize(52, 52)
        logo = QPixmap(str(APP_DIR / "assets" / "piven_logo_flat.png"))
        if not logo.isNull():
            brand_icon.setPixmap(logo.scaled(QSize(52, 52), Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))
        header.addWidget(brand_icon)
        brand = QVBoxLayout(); brand.setContentsMargins(0, 0, 0, 0); brand.setSpacing(0); header.addLayout(brand)
        title = QLabel("PIVEN"); title.setObjectName("brandTitle"); brand.addWidget(title)
        subtitle = QLabel("COMPANION"); subtitle.setObjectName("brandSubtitle"); brand.addWidget(subtitle)
        header.addStretch(1)
        self.sidebar_toggle_btn = self._button("", "quiet")
        self.sidebar_toggle_btn.setIcon(vector_icon("panel", MONO["text"]))
        self.sidebar_toggle_btn.setIconSize(QSize(19, 19))
        add_icon_hover_motion(self.sidebar_toggle_btn, 19)
        self.sidebar_toggle_btn.setFixedSize(42, 42)
        self.sidebar_toggle_btn.setToolTip("Свернуть боковую панель · Ctrl+B")
        self.sidebar_toggle_btn.setAccessibleName("Показать или скрыть боковую панель")
        self.sidebar_toggle_btn.clicked.connect(self._toggle_sidebar)
        header.addWidget(self.sidebar_toggle_btn)
        self.settings_btn = self._button("", "quiet"); self.settings_btn.setIcon(vector_icon("settings", MONO["text"])); self.settings_btn.setIconSize(QSize(20, 20)); add_icon_hover_motion(self.settings_btn, 20); self.settings_btn.setFixedSize(42, 42); self.settings_btn.setToolTip("Настройки · Ctrl+,"); self.settings_btn.clicked.connect(self.open_settings); header.addWidget(self.settings_btn)

        content = QHBoxLayout(); content.setSpacing(0); outer.addLayout(content, 1)
        side_card = QFrame(); side_card.setObjectName("sidebar"); side_card.setMinimumWidth(220); side_card.setMaximumWidth(292); side_card.setFixedWidth(292); content.addWidget(side_card)
        self.sidebar_card = side_card
        for panel in (top_bar, side_card):
            layer = QGraphicsDropShadowEffect(panel); layer.setBlurRadius(0); layer.setOffset(4, 4); layer.setColor(QColor("#242424")); panel.setGraphicsEffect(layer)
        side_outer = QVBoxLayout(side_card); side_outer.setContentsMargins(0, 0, 0, 0); side_outer.setSpacing(0)
        side_scroll = QScrollArea(); side_scroll.setObjectName("sidebarScroll"); side_scroll.setWidgetResizable(True); side_scroll.setFrameShape(QFrame.Shape.NoFrame); side_outer.addWidget(side_scroll, 1)
        side_wrap = SquareDecoratedWidget(); side_wrap.setObjectName("sidebarContent"); side_scroll.setWidget(side_wrap)
        side = QVBoxLayout(side_wrap); side.setContentsMargins(12, 18, 12, 12); side.setSpacing(9)
        section = QLabel("01  /  СЕССИЯ"); section.setObjectName("eyebrow"); side.addWidget(section)
        session_title = QLabel("Твой компаньон"); session_title.setObjectName("sessionTitle"); side.addWidget(session_title)
        session_note = QLabel("Всегда рядом, работает локально"); session_note.setObjectName("muted"); side.addWidget(session_note)
        source_heading = QLabel("02  /  ИСТОЧНИКИ"); source_heading.setObjectName("eyebrow"); side.addWidget(source_heading)
        self._source_row(side, "mic", "Микрофон", "Твой голос", "mic", True)
        self._source_row(side, "speaker", "Звук компьютера", "Системный звук", "loopback", True)
        self._source_row(side, "monitor", "Экран", "Снимки между репликами", "screen", True)
        section2 = QLabel("03  /  ПОВЕДЕНИЕ"); section2.setObjectName("eyebrow"); side.addWidget(section2)
        self._source_row(side, "voice_wave", "Редкие комментарии", "Замечает важное на экране", "proactive", True)
        model_heading = QLabel("04  /  МОДЕЛЬ OLLAMA"); model_heading.setObjectName("eyebrow"); side.addWidget(model_heading)
        model_card = QFrame(); model_card.setObjectName("modelCard"); side.addWidget(model_card)
        model = QVBoxLayout(model_card); model.setContentsMargins(11, 11, 11, 11); model.setSpacing(8)
        model_row = QHBoxLayout(); model_row.setSpacing(6); model.addLayout(model_row)
        self.model_box = CheckComboBox(); self.model_box.setEditable(True); self.model_box.setMinimumWidth(80); self.model_box.setMinimumHeight(40); self.model_box.setPlaceholderText("Выберите модель"); model_row.addWidget(self.model_box, 1)
        if self.settings["model"]: self.model_box.setCurrentText(self.settings["model"])
        self.model_box.currentTextChanged.connect(self._update_model_label); self.model_box.currentTextChanged.connect(self._update_composer_hint)
        self.refresh_btn = self._button("", "quiet"); self.refresh_btn.setIcon(vector_icon("loop", MONO["text"])); self.refresh_btn.setIconSize(QSize(17,17)); add_icon_hover_motion(self.refresh_btn, 17); self.refresh_btn.setFixedSize(40,40); self.refresh_btn.setToolTip("Обновить список моделей"); self.refresh_btn.clicked.connect(self.refresh_models); model_row.addWidget(self.refresh_btn)
        self.hf_download_btn = self._button("Скачать GGUF с Hugging Face", "quiet")
        self.hf_download_btn.setToolTip("Скачать GGUF-файл из репозитория Hugging Face и добавить его в Ollama")
        self.hf_download_btn.clicked.connect(self.open_huggingface_downloader)
        model.addWidget(self.hf_download_btn)
        self.start_btn = self._button("Старт", "primary"); self.start_btn.setMinimumHeight(40); self.start_btn.clicked.connect(self.toggle); model.addWidget(self.start_btn)
        status_card = QFrame(); status_card.setObjectName("statusCard"); status_layout = QVBoxLayout(status_card); status_layout.setContentsMargins(12, 10, 12, 10); status_layout.setSpacing(4); side.addWidget(status_card)
        status_head = QHBoxLayout(); status_head.setSpacing(8); self.status_dot = QLabel("●"); self.status_dot.setObjectName("statusDot"); status_head.addWidget(self.status_dot)
        self.status_title = QLabel("Подключаю Ollama…"); self.status_title.setObjectName("statusTitle"); status_head.addWidget(self.status_title, 1); status_layout.addLayout(status_head)
        self.status_pill = QLabel("Проверяю локальную модель"); self.status_pill.setObjectName("status"); self.status_pill.setWordWrap(True); status_layout.addWidget(self.status_pill)
        side.addStretch(1)

        chat_card = QFrame(); chat_card.setObjectName("chatCard"); content.addWidget(chat_card, 1)
        layer = QGraphicsDropShadowEffect(chat_card); layer.setBlurRadius(0); layer.setOffset(4, 4); layer.setColor(QColor("#242424")); chat_card.setGraphicsEffect(layer)
        self._shadow_panels = (top_bar, side_card, chat_card)
        cv = QVBoxLayout(chat_card); cv.setContentsMargins(0, 0, 0, 0); cv.setSpacing(0)
        chat_head_frame = SquareDecoratedFrame(); chat_head_frame.setObjectName("chatHeader"); cv.addWidget(chat_head_frame)
        chathead = QHBoxLayout(chat_head_frame); chathead.setContentsMargins(22, 13, 20, 12); chathead.setSpacing(8)
        title_column = QVBoxLayout(); title_column.setSpacing(2); chathead.addLayout(title_column)
        self.chat_title_label = QLabel("Новый чат"); self.chat_title_label.setObjectName("sectionTitle"); self.chat_title_label.setMinimumWidth(0); title_column.addWidget(self.chat_title_label)
        self.chat_model_label = QLabel("Выберите модель Ollama"); self.chat_model_label.setObjectName("mutedSmall"); title_column.addWidget(self.chat_model_label)
        chathead.addStretch(1)
        self.chat_selector = CheckComboBox(); self.chat_selector.setObjectName("chatSelector"); self.chat_selector.setMinimumWidth(150); self.chat_selector.setMaximumWidth(240)
        self.chat_selector.setToolTip("Открыть сохранённый чат")
        self.chat_selector.currentIndexChanged.connect(self._switch_chat_by_index)
        chathead.addWidget(self.chat_selector)
        self.jump_latest_btn = self._button("", "quiet")
        self.jump_latest_btn.setIcon(vector_icon("arrow-down", MONO["text"]))
        self.jump_latest_btn.setIconSize(QSize(18, 18))
        add_icon_hover_motion(self.jump_latest_btn, 18)
        self.jump_latest_btn.setObjectName("jumpLatest")
        self.jump_latest_btn.setFixedSize(36, 36)
        self.jump_latest_btn.setToolTip("Вернуться к последнему сообщению")
        self.jump_latest_btn.setAccessibleName("Вернуться к последнему сообщению")
        self.jump_latest_btn.clicked.connect(self._return_to_latest)
        self.jump_latest_btn.hide()
        chathead.addWidget(self.jump_latest_btn)
        self.new_chat_btn = self._button("Новый чат", "secondary")
        self.new_chat_btn.setIcon(vector_icon("plus", MONO["text"]))
        self.new_chat_btn.setIconSize(QSize(16, 16))
        add_icon_hover_motion(self.new_chat_btn, 16)
        self._new_chat_full_text = "Новый чат"
        self.new_chat_btn.setToolTip("Создать новый чат · Ctrl+N")
        self.new_chat_btn.clicked.connect(self._new_chat)
        chathead.addWidget(self.new_chat_btn)
        self.chat_tools_btn = self._button("", "quiet")
        self.chat_tools_btn.setIcon(vector_icon("more", MONO["text"]))
        self.chat_tools_btn.setIconSize(QSize(18, 18))
        add_icon_hover_motion(self.chat_tools_btn, 18)
        self.chat_tools_btn.setFixedWidth(38)
        self.chat_tools_btn.setToolTip("Поиск и действия с чатами · поиск: Ctrl+K")
        self.chat_tools_btn.clicked.connect(self._show_chat_tools)
        chathead.addWidget(self.chat_tools_btn)
        self._refresh_chat_selector()

        self.chat_scene = QGraphicsScene(self); self.chat_scene.setSceneRect(0, 0, 2400, 1800)
        self.chat = ChatCanvasView(self.chat_scene); self.chat.userNavigated.connect(self._pause_canvas_follow); self.chat.workspaceMotion.connect(self._animate_workspace_connectors); cv.addWidget(self.chat, 1)
        self._canvas_next_y = 820
        self._canvas_latest_item = None
        self._canvas_proxy_by_row = {}
        self._dialogue_proxy_by_index = {}
        self._canvas_message_order = []
        self._message_connectors = []
        self._connectors_by_proxy = {}
        self._canvas_follow_latest = True
        self._generation_card_row = None
        self._generation_card_proxy = None
        self._generation_card_y = None
        self._generation_next_y = None

        self.activity_panel = QFrame(); self.activity_panel.setObjectName("thinkingCard"); activity_layout = QHBoxLayout(self.activity_panel); activity_layout.setContentsMargins(16, 8, 16, 8); activity_layout.setSpacing(10)
        self.activity_indicator = QLabel("•••"); self.activity_indicator.setObjectName("thinkingDots"); activity_layout.addWidget(self.activity_indicator)
        self._thinking_dot_frames = ("●··", "·●·", "··●", "·●·")
        self._thinking_dot_index = 0
        self._thinking_dot_timer = QTimer(self); self._thinking_dot_timer.setInterval(150)
        self._thinking_dot_timer.timeout.connect(self._animate_thinking_dots)
        activity_text = QVBoxLayout(); activity_text.setContentsMargins(0, 0, 0, 0); activity_text.setSpacing(0); activity_layout.addLayout(activity_text)
        self.activity_label = QLabel("Думаю…"); self.activity_label.setObjectName("chatActivityTitle"); activity_text.addWidget(self.activity_label)
        self.activity_detail = QLabel(""); self.activity_detail.setObjectName("chatActivityDetail"); activity_text.addWidget(self.activity_detail)
        self.activity_cancel_btn = QToolButton(); self.activity_cancel_btn.setIcon(vector_icon("stop", MONO["text"], 15)); self.activity_cancel_btn.setIconSize(QSize(15, 15)); add_icon_hover_motion(self.activity_cancel_btn, 15); self.activity_cancel_btn.setObjectName("messageAction"); self.activity_cancel_btn.setToolTip("Прервать текущее действие · Esc"); self.activity_cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor); self.activity_cancel_btn.setFixedSize(30, 30); self.activity_cancel_btn.clicked.connect(self._interrupt_current_action); activity_layout.addWidget(self.activity_cancel_btn); self.activity_cancel_btn.hide()
        self.activity_panel.setMaximumWidth(360); self.activity_panel.setFixedHeight(50); self.activity_panel.hide(); cv.addWidget(self.activity_panel, 0, Qt.AlignmentFlag.AlignLeft)
        self.reasoning_chat_row = None
        self.reasoning_chat_body = None
        self.activity_effect = QGraphicsOpacityEffect(self.activity_panel); self.activity_panel.setGraphicsEffect(self.activity_effect)
        self.activity_fade = QPropertyAnimation(self.activity_effect, b"opacity", self); self.activity_fade.setDuration(240); self.activity_fade.setEasingCurve(QEasingCurve.Type.OutCubic); self.activity_fade.finished.connect(self._finish_activity_fade)

        composer_border = QFrame(); composer_border.setObjectName("composerDivider"); cv.addWidget(composer_border)
        composer_frame = SquareDecoratedFrame(); composer_frame.setObjectName("composerSurface"); composer_column = QVBoxLayout(composer_frame); composer_column.setContentsMargins(16, 10, 16, 8); composer_column.setSpacing(6); cv.addWidget(composer_frame)
        self.composer_column = composer_column
        self.attach_preview_frame = QWidget(); preview_row = QHBoxLayout(self.attach_preview_frame); preview_row.setContentsMargins(0, 0, 0, 0); preview_row.setSpacing(6)
        self.attach_preview = QLabel(); self.attach_preview.setObjectName("mutedSmall"); self.attach_preview.setWordWrap(True); preview_row.addWidget(self.attach_preview, 1)
        self.attach_clear_btn = self._button("", "quiet"); self.attach_clear_btn.setIcon(vector_icon("close", MONO["text"], 14)); self.attach_clear_btn.setIconSize(QSize(14, 14)); add_icon_hover_motion(self.attach_clear_btn, 14); self.attach_clear_btn.setFixedSize(28, 26); self.attach_clear_btn.setToolTip("Убрать прикреплённые изображения"); self.attach_clear_btn.clicked.connect(lambda: self._clear_pending_images(announce=True)); preview_row.addWidget(self.attach_clear_btn)
        self.attach_preview_frame.hide(); composer_column.addWidget(self.attach_preview_frame)
        composer = QHBoxLayout(); composer.setContentsMargins(0, 0, 0, 0); composer.setSpacing(8); composer_column.addLayout(composer)
        self.composer_row = composer
        self.attach_btn = self._button("", "quiet"); self.attach_btn.setIcon(vector_icon("plus", MONO["text"], 18)); self.attach_btn.setIconSize(QSize(18, 18)); add_icon_hover_motion(self.attach_btn, 18); self.attach_btn.setFixedSize(42, 42); self.attach_btn.setToolTip("Прикрепить изображения · Ctrl+O, Ctrl+V или перетаскивание"); self.attach_btn.clicked.connect(self.attach_images); composer.addWidget(self.attach_btn)
        self.input = ComposerLineEdit(); self.input.imagesProvided.connect(self._add_pending_images); self.input.textChanged.connect(self._update_composer_hint); self.input.setObjectName("composerInput"); self.input.setPlaceholderText("Напиши задачу — я сам выберу, что сделать…"); self.input.setToolTip("Режим определится автоматически: разговор, работа с проектом или генерация медиа"); self.input.setMinimumHeight(48); self.input.returnPressed.connect(self.send_text); composer.addWidget(self.input, 1)
        self.thinking_box = CheckComboBox(); self.thinking_box.setObjectName("thinkingLevel"); self.thinking_box.setMinimumWidth(132); self.thinking_box.setMaximumWidth(190); self.thinking_box.setMinimumHeight(42); self.thinking_box.setToolTip("Сила размышления для выбранной модели Ollama"); self.thinking_box.currentIndexChanged.connect(self._on_thinking_level_changed); composer.addWidget(self.thinking_box)
        self.send_btn = self._button("", "primary"); self.send_btn.setIcon(vector_icon("send", "#050505")); self.send_btn.setIconSize(QSize(20,20)); add_icon_hover_motion(self.send_btn, 20); self.send_btn.setFixedSize(44,44); self.send_btn.setToolTip("Отправить запрос · действие определится автоматически"); self.send_btn.clicked.connect(self.send_text); composer.addWidget(self.send_btn)
        self.composer_hint = QLabel(); self.composer_hint.setObjectName("composerHint"); self.composer_hint.setTextFormat(Qt.TextFormat.RichText); composer_column.addWidget(self.composer_hint)
        self.chat.setAcceptDrops(False)
        self.setAcceptDrops(True)
        for keys, handler in (("Ctrl+N", self._new_chat), ("Ctrl+K", self._search_chats),
                              ("Ctrl+,", self.open_settings), ("Ctrl+B", self._toggle_sidebar),
                              ("Ctrl+L", lambda: self.input.setFocus(Qt.FocusReason.ShortcutFocusReason)),
                              ("Ctrl+O", self.attach_images), ("Esc", self._interrupt_current_action)):
            QShortcut(QKeySequence(keys), self, activated=handler)
        self._entrance_widgets = (top_bar, side_card, chat_card)
        self._thinking_lookup_inflight = set()
        self._update_model_label()
        self._apply_responsive_layout(self.width() < 900)

    def _button(self, text, kind):
        button = QPushButton(text); button.setObjectName(kind); button.setCursor(Qt.CursorShape.PointingHandCursor); add_press_feedback(button); return button

    def _toggle_sidebar(self):
        visible = not self.sidebar_card.isVisible()
        self.sidebar_card.setVisible(visible)
        self.sidebar_toggle_btn.setIcon(vector_icon("panel" if visible else "panel-expand", MONO["text"]))
        self.sidebar_toggle_btn.setToolTip(("Свернуть боковую панель" if visible else "Показать боковую панель") + " · Ctrl+B")
        if not visible:
            self.input.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "sidebar_card") or not hasattr(self, "composer_row"):
            return
        self._apply_responsive_layout(event.size().width() < 900)

    def _apply_responsive_layout(self, compact):
        if not hasattr(self, "sidebar_card") or not hasattr(self, "composer_row"):
            return
        if getattr(self, "_layout_compact", None) == compact:
            return
        self._layout_compact = compact
        if compact:
            self.sidebar_card.setFixedWidth(220)
            self.chat_title_label.setMaximumWidth(180)
            self.chat_selector.setMinimumWidth(72)
            self.chat_selector.setMaximumWidth(104)
            self.new_chat_btn.setText("")
            self.new_chat_btn.setFixedWidth(32)
            self.new_chat_btn.setStyleSheet("padding:0px;")
            self.chat_tools_btn.setFixedWidth(32)
            self.chat_tools_btn.setStyleSheet("padding:0px;")
            self.chat_model_label.hide()
            self.composer_column.setContentsMargins(10, 8, 10, 8)
            self.composer_row.setSpacing(6)
            self.attach_btn.setFixedSize(34, 38)
            self.attach_btn.setStyleSheet("padding:0px;")
            self.input.setMinimumHeight(42)
            self.thinking_box.setMinimumWidth(78)
            self.thinking_box.setMaximumWidth(108)
            self.thinking_box.setMinimumHeight(38)
            self.send_btn.setFixedSize(38, 38)
            self.send_btn.setStyleSheet("padding:0px;")
        else:
            self.sidebar_card.setMinimumWidth(220)
            self.sidebar_card.setMaximumWidth(292)
            self.sidebar_card.setFixedWidth(292)
            self.chat_title_label.setMaximumWidth(320)
            self.chat_selector.setMinimumWidth(150)
            self.chat_selector.setMaximumWidth(240)
            self.new_chat_btn.setText(self._new_chat_full_text)
            self.new_chat_btn.setMinimumWidth(0)
            self.new_chat_btn.setMaximumWidth(16777215)
            self.new_chat_btn.setStyleSheet("")
            self.chat_tools_btn.setFixedWidth(38)
            self.chat_tools_btn.setStyleSheet("")
            self.chat_model_label.show()
            self.composer_column.setContentsMargins(16, 10, 16, 8)
            self.composer_row.setSpacing(8)
            self.attach_btn.setFixedSize(42, 42)
            self.attach_btn.setStyleSheet("")
            self.input.setMinimumHeight(48)
            self.thinking_box.setMinimumWidth(132)
            self.thinking_box.setMaximumWidth(190)
            self.thinking_box.setMinimumHeight(42)
            self.send_btn.setFixedSize(44, 44)
            self.send_btn.setStyleSheet("")

    def _message_heading(self, row, title, leading=None):
        header = MessageDragHeader(row, self); header.setObjectName("messageDragHeader")
        layout = QHBoxLayout(header); layout.setContentsMargins(8, 0, 8, 0); layout.setSpacing(8)
        if leading is not None:
            leading.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            layout.addWidget(leading)
        caption = QLabel(title); caption.setObjectName("messageRole")
        caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(caption)
        layout.addWidget(DragStripeIndicator(header, getattr(row, "message_length", 0)))
        return header

    def showEvent(self,event):
        super().showEvent(event)
        if not self._entrance_done:
            self._entrance_done=True
            self._window_entrance_animation=QPropertyAnimation(self,b"windowOpacity",self); self._window_entrance_animation.setDuration(420); self._window_entrance_animation.setStartValue(0.0); self._window_entrance_animation.setEndValue(1.0); self._window_entrance_animation.setEasingCurve(QEasingCurve.Type.OutCubic); self._window_entrance_animation.start()
            for index,widget in enumerate(self._entrance_widgets):
                fade_in_widget(widget,360,delay=60+index*90)
            # Wait until the window and restored message cards have their final
            # geometry, then center the latest card in the canvas.
            QTimer.singleShot(520, self._scroll_chat_to_bottom)

    def _grow_canvas_for_item(self, item):
        scene_rect = self.chat_scene.sceneRect()
        bounds = item.sceneBoundingRect()
        width = min(6000.0, max(scene_rect.width(), bounds.right() + 160))
        # Long conversations need room to scroll past hundreds of cards. Keep
        # the workspace finite, but don't strand later messages beyond its edge.
        height = min(1_000_000.0, max(scene_rect.height(), bounds.bottom() + 160))
        if width != scene_rect.width() or height != scene_rect.height():
            self.chat_scene.setSceneRect(scene_rect.x(), scene_rect.y(), width, height)

    def _message_card_width(self, maximum):
        view = getattr(self, "chat", None)
        if view is None:
            return min(maximum, max(220, self.width() - 380))
        zoom = max(0.45, float(getattr(view, "_zoom", 1.0)))
        viewport_width = view.viewport().width()
        if viewport_width < 300:
            viewport_width = max(220, self.width() - 380)
        visible_scene_width = viewport_width / zoom
        return min(maximum, max(180, int(visible_scene_width * 0.88)))

    @staticmethod
    def _clamp_message_position(item, position):
        """Keep dragged cards inside a roomy, finite workspace."""
        bounds = item.boundingRect()
        scale = max(1.0, item.scale())
        margin = 28.0
        scene = item.scene()
        scene_rect = scene.sceneRect() if scene is not None else QRect(0, 0, 6000, 1_000_000)
        max_x = max(margin, min(6000.0, scene_rect.right()) - bounds.width() * scale - margin)
        max_y = max(margin, min(1_000_000.0, scene_rect.bottom()) - bounds.height() * scale - margin)
        return QPointF(min(max(margin, position.x()), max_x),
                       min(max(margin, position.y()), max_y))

    def _source_row(self, layout, icon, title, detail, key, value, last=False):
        row = QFrame(); row.setObjectName("sourceCard")
        h = QHBoxLayout(row); h.setContentsMargins(10, 8, 10, 8); h.setSpacing(9)
        badge = QFrame(); badge.setObjectName("iconBadge"); badge.setFixedSize(36, 36); badge_layout = QHBoxLayout(badge); badge_layout.setContentsMargins(0, 0, 0, 0); badge_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glyph = VectorIconWidget(icon); glyph.setFixedSize(21, 21); badge_layout.addWidget(glyph); h.addWidget(badge); self.icon_badges.append(glyph)
        textcol=QVBoxLayout(); textcol.setSpacing(1); h.addLayout(textcol,1)
        t=QLabel(title); t.setObjectName("rowTitle"); textcol.addWidget(t)
        d=QLabel(detail); d.setObjectName("mutedSmall"); d.setWordWrap(True); textcol.addWidget(d)
        check=ToggleSwitch(value); h.addWidget(check)
        self.vars[key]=check
        self.switches.append(check)
        layout.addWidget(row)

    def _canvas_theme_data(self):
        theme_id = self.settings.get("canvas_theme", "graphite")
        return CANVAS_THEMES.get(theme_id, CANVAS_THEMES["graphite"])

    def _style_message_bubble(self, bubble, theme=None):
        """Style graphics-scene message widgets directly, outside the window QSS tree."""
        theme = theme or self._canvas_theme_data()
        font_family = "Segoe UI"
        bubble.setStyleSheet(f"""
            QFrame#assistantBubble {{ background-color:{theme['assistant_bg']}; border:{theme.get('message_border_width', '1px')} solid {theme['assistant_border']}; border-radius:{theme['radius']}; font-family:'{font_family}'; }}
            QFrame#assistantBubble:hover {{ background-color:{theme['assistant_bg']}; border-color:{theme['role']}; }}
            QFrame#userBubble {{ background-color:{theme['user_bg']}; border:{theme.get('message_border_width', '1px')} solid {theme['user_border']}; border-radius:{theme['radius']}; font-family:'{font_family}'; }}
            QFrame#userBubble:hover {{ background-color:{theme['user_bg']}; border-color:{theme['role']}; }}
            QFrame#systemBubble {{ background-color:{theme['system_bg']}; border:{theme.get('message_border_width', '1px')} solid {theme['system_border']}; border-radius:{theme['radius']}; font-family:'{font_family}'; }}
            QFrame#systemBubble:hover {{ border-color:{theme['role']}; }}
            QWidget#messageDragHeader {{ background-color:{theme['header_bg']}; border:0; border-radius:0px; font-family:'{font_family}'; }}
            QLabel#messageRole {{ color:{theme['role']}; font-family:'{font_family}'; }}
            QLabel#messageBody {{ color:#f3f4ef; font-family:'{font_family}'; }}
            QFrame#messageDivider {{ background-color:{theme['divider']}; border:0; }}
            QPlainTextEdit#reasoningContent {{ color:{theme['role']}; background-color:{theme['header_bg']}; border:1px solid {theme['header_border']}; selection-background-color:{theme['divider']}; font-family:'{font_family}'; }}
            QToolButton#messageAction {{ background:transparent; border:0; }}
            QToolButton#messageActionIcon {{ background:transparent; border:1px solid transparent; border-radius:0px; padding:0px; }}
            QToolButton#messageActionIcon:hover {{ background:{theme['header_bg']}; border-color:{theme['header_border']}; }}
            QToolButton#messageActionIcon:pressed {{ background:{theme['assistant_bg']}; border-color:{theme['role']}; }}
            QLabel#mutedSmall {{ font-family:'{font_family}'; }}
        """)
        action_color = theme["role"]
        for button in bubble.findChildren(QToolButton, "messageActionIcon"):
            if isinstance(button, VectorActionButton):
                button.set_vector_color(action_color)

    def _apply_theme(self):
        canvas_theme = self._canvas_theme_data()
        p = MONO
        root = self.centralWidget()
        if root:
            root.background_color = canvas_theme.get("window_bg", "#070707")
            root.update()
        for switch in getattr(self, "switches", []):
            switch.on_color = QColor(canvas_theme["accent"])
            switch.off_color = QColor(canvas_theme["ui_border_strong"])
            switch.rounded = canvas_theme.get("ui_radius", "0px") != "0px"
            switch.update()
        shadow_color = QColor(canvas_theme.get("panel_shadow", "#242424"))
        shadow_color.setAlpha(canvas_theme.get("panel_shadow_alpha", 255))
        for panel in getattr(self, "_shadow_panels", ()):
            effect = panel.graphicsEffect()
            if isinstance(effect, QGraphicsDropShadowEffect):
                effect.setColor(shadow_color)
        for combo in self.findChildren(CheckComboBox):
            combo.arrow_color = QColor(canvas_theme["role"])
            combo.update()
        for glyph in getattr(self, "icon_badges", []):
            glyph.set_color(canvas_theme["role"])
        self._refresh_settings_nav_icons()
        for name in ("refresh_btn", "settings_btn", "send_btn", "sidebar_toggle_btn",
                     "jump_latest_btn", "new_chat_btn", "chat_tools_btn", "attach_btn",
                     "attach_clear_btn", "activity_cancel_btn"):
            button = getattr(self, name, None)
            if button is not None:
                icon_name = {
                    "refresh_btn": "loop", "settings_btn": "settings", "send_btn": "send",
                    "sidebar_toggle_btn": "panel" if self.sidebar_card.isVisible() else "panel-expand",
                    "jump_latest_btn": "arrow-down", "new_chat_btn": "plus", "chat_tools_btn": "more",
                    "attach_btn": "plus", "attach_clear_btn": "close", "activity_cancel_btn": "stop",
                }[name]
                icon_color = canvas_theme["accent_text"] if name in ("send_btn", "jump_latest_btn") else canvas_theme["role"]
                button.setIcon(vector_icon(icon_name, icon_color))
        if hasattr(self, "chat_model_label"):
            self.chat_model_label.setText(self.model_box.currentText().strip() or "Выберите модель Ollama")
        self.setStyleSheet("""
            QMainWindow, QDialog { background:#070707; }
            QWidget { color:#f5f5f5; font-family:'Segoe UI'; font-size:9pt; }
            QLabel { background:transparent; border:0; }
            QFrame#topBar, QFrame#sidebar, QFrame#chatCard, QFrame#settingsNav,
            QFrame#settingsCard, QFrame#sourceCard, QFrame#modelCard, QFrame#statusCard {
                background:#101010; border:1px solid #2b2b2b; border-radius:0px;
            }
            QFrame#sidebar { border-right:1px solid #3b3b3b; }
            QFrame#chatCard { border-left:1px solid #3b3b3b; }
            QFrame#chatHeader { background:#121212; border:0; border-bottom:1px solid #2b2b2b; border-radius:0px; }
            QFrame#thinkingCard { background:#131313; border:1px solid #303030; border-left:2px solid #8c8c8c; border-radius:0px; }
            QFrame#composerSurface { background:#0d0d0d; border:0; border-top:1px solid #353535; border-radius:0px; }
            QFrame#sourceCard { background:#121212; border-color:#292929; }
            QFrame#sourceCard:hover { background:#181818; border-color:#626262; }
            QFrame#modelCard { background:#121212; border-color:#363636; }
            QFrame#statusCard { background:#111111; border-color:#303030; }
            QFrame#iconBadge { background:#1a1a1a; border:1px solid #343434; border-radius:0px; }
            QFrame#composerDivider { background:#353535; max-height:1px; min-height:1px; border:0; }
            QWidget#sidebarContent { background:transparent; }
            QWidget#settingsContent { background:#090909; }
            QGraphicsView#chatStream { background:#070707; border:0; }
            QScrollArea#sidebarScroll, QScrollArea#chatScroll, QScrollArea#settingsScroll { background:transparent; border:0; }
            QLabel#brandTitle { color:#ffffff; font-family:'Segoe UI'; font-size:16pt; font-weight:700; letter-spacing:1px; }
            QLabel#brandSubtitle { color:#a0a0a0; font-size:7pt; font-weight:700; letter-spacing:1.6px; }
            QLabel#settingsWindowTitle { font-family:'Segoe UI'; font-size:12pt; font-weight:700; padding:4px 3px; }
            QLabel#settingsTitle { font-family:'Segoe UI'; font-size:19pt; font-weight:700; }
            QLabel#settingsNavTitle { font-family:'Segoe UI'; font-size:14pt; font-weight:700; }
            QLabel#settingsConnection { color:#ffffff; background:#1b1b1b; border:1px solid #454545; border-radius:0px; padding:8px 10px; font-size:8pt; }
            QLabel#eyebrow { font-family:'Segoe UI'; font-size:8pt; font-weight:600; letter-spacing:1.4px; color:#a0a0a0; margin-top:5px; }
            QLabel#muted, QLabel#mutedSmall { color:#a0a0a0; }
            QLabel#muted { font-size:9pt; font-family:'Segoe UI'; }
            QLabel#mutedSmall { font-size:8pt; font-family:'Segoe UI'; }
            QLabel#sectionTitle { font-family:'Segoe UI'; font-size:14pt; font-weight:700; }
            QLabel#sessionTitle { font-family:'Segoe UI'; font-size:14pt; font-weight:700; padding-top:2px; }
            QLabel#rowTitle { font-family:'Segoe UI'; font-size:9pt; font-weight:600; }
            QFrame#localPill, QLabel#activityPill { background:#1c1c1c; color:#f5f5f5; border:1px solid #3c3c3c; border-radius:0px; padding:7px 10px; font-size:8pt; font-weight:650; }
            QLabel#onlineDot, QLabel#statusDot, QLabel#statusTitle, QLabel#localText { color:#ffffff; }
            QLabel#onlineDot, QLabel#statusDot { font-size:8pt; }
            QLabel#statusTitle { font-size:9pt; font-weight:650; }
            QLabel#status { color:#a0a0a0; font-size:8pt; font-family:'Segoe UI'; }
            QLabel#localText { font-size:8pt; font-weight:600; }
            QLabel#chatActivityTitle { color:#ffffff; font-size:9pt; font-weight:650; }
            QLabel#chatActivityDetail { color:#a0a0a0; font-size:8pt; }
            QLabel#thinkingDots { color:#ffffff; font-size:14pt; font-weight:700; }
            QPlainTextEdit#reasoningContent { color:#c5c5c5; font-size:8pt; background:transparent; border:0; padding:0; selection-background-color:#555555; }
            QComboBox, QLineEdit, QSpinBox, QPlainTextEdit { background:#090909; color:#f5f5f5; border:1px solid #454545; border-radius:0px; padding:9px 12px; selection-background-color:#555555; font-family:'Segoe UI'; }
            QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QPlainTextEdit:focus { border:1px solid #ffffff; }
            QComboBox#chatSelector { background:#111111; border-color:#383838; padding-left:10px; min-height:34px; }
            QComboBox#chatSelector:hover { border-color:#777777; }
            QLineEdit#composerInput { background:#121212; border-color:#353535; padding:10px 14px; font-size:9pt; }
            QLineEdit#composerInput:focus { background:#171717; border-color:#d6d6d6; }
            QComboBox#thinkingLevel { background:#111111; border-color:#484848; padding-left:10px; }
            QComboBox#thinkingLevel:hover { border-color:#777777; }
            QComboBox { padding-right:36px; }
            QComboBox::drop-down { subcontrol-origin:padding; subcontrol-position:top right; right:1px; top:1px; width:30px; border:0; border-left:1px solid #454545; border-radius:0px; }
            QComboBox::down-arrow { image:none; width:0px; height:0px; border:0; }
            QComboBox QAbstractItemView { background:#101010; color:#f5f5f5; border:1px solid #555555; border-radius:0px; outline:0; selection-background-color:#303030; padding:4px; }
            QComboBox QAbstractItemView::item { min-height:28px; padding:6px 10px; border-radius:0px; }
            QGroupBox { color:#f5f5f5; font-weight:650; border:1px solid #454545; border-radius:0px; margin-top:10px; padding:14px 12px 10px; }
            QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 5px; background:#101010; }
            QSlider::groove:horizontal { height:5px; background:#383838; border-radius:0px; }
            QSlider::sub-page:horizontal { background:#d8d8d8; border-radius:0px; }
            QSlider::handle:horizontal { width:14px; margin:-5px 0; border-radius:0px; background:#ffffff; }
            QCheckBox { spacing:8px; }
            QCheckBox::indicator { width:16px; height:16px; border-radius:0px; border:1px solid #777777; background:#090909; }
            QCheckBox::indicator:checked { background:#ffffff; border-color:#ffffff; }
            QPushButton, QToolButton { font-family:'Segoe UI'; }
            QPushButton { border:1px solid #484848; border-radius:0px; padding:9px 14px; font-weight:650; background:#191919; color:#ffffff; }
            QPushButton:hover { background:#282828; border-color:#ffffff; }
            QPushButton:pressed { background:#383838; }
            QPushButton:disabled { background:#151515; color:#777777; border-color:#303030; }
            QPushButton#primary { font-family:'Segoe UI'; font-weight:600; background:#ffffff; color:#050505; border:1px solid #ffffff; }
            QPushButton#primary:hover { background:#dedede; }
            QPushButton#primary:pressed { background:#bfbfbf; }
            QPushButton#secondary { background:#202020; color:#f5f5f5; border:1px solid #5a5a5a; }
            QPushButton#secondary:hover { background:#2a2a2a; border-color:#c0c0c0; }
            QPushButton#secondary:pressed { background:#303030; }
            QPushButton#quiet { background:#181818; color:#ffffff; border:1px solid #444444; }
            QPushButton#quiet:hover { border-color:#ffffff; }
            QPushButton#jumpLatest { background:#252525; border-color:#666666; font-size:15pt; font-weight:500; }
            QPushButton#jumpLatest:hover { background:#333333; border-color:#ffffff; }
            QPushButton#settingsNavButton { background:#101010; color:#bdbdbd; border:1px solid #303030; text-align:left; padding:8px 10px; font-size:8pt; }
            QPushButton#settingsNavButton:hover { background:#202020; border-color:#777777; }
            QPushButton#settingsNavButton:checked { background:#ffffff; color:#050505; border:1px solid #ffffff; }
            QFrame#assistantBubble { background:#141414; border:1px solid #444444; border-radius:0px; }
            QFrame#assistantBubble:hover { background:#191919; border-color:#888888; }
            QFrame#userBubble { background:#242424; border:1px solid #3c3c3c; border-radius:0px; }
            QFrame#userBubble:hover { background:#2a2a2a; border-color:#777777; }
            QFrame#systemBubble { background:#101010; border:1px solid #777777; border-radius:0px; }
            QFrame#systemBubble:hover { border-color:#b0b0b0; }
            QFrame#messageDivider { background:#383838; max-height:1px; min-height:1px; border:0; }
            QLabel#messageRole { font-family:'Segoe UI'; color:#b0b0b0; font-size:7pt; font-weight:700; letter-spacing:1px; }
            QWidget#messageDragHeader { background:#1a1a1a; border-bottom:1px solid #b8b8b8; }
            QWidget#messageDragHeader:hover { background:#202020; }
            QLabel#messageBody { color:#f5f5f5; font-size:10pt; }
            QLabel#messageImagePreview { background:#090909; border:1px solid #505050; border-radius:0px; }
            QLabel#messageImagePreview:hover { border-color:#ffffff; }
            QToolButton#messageAction { background:transparent; border:0; border-radius:0px; padding:3px; }
            QToolButton#messageAction:hover { background:#303030; }
            QScrollBar:horizontal { background:transparent; height:8px; margin:2px; }
            QScrollBar::handle:horizontal { background:#505050; border-radius:0px; min-width:24px; }
            QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal { width:0; }
            QScrollBar:vertical { background:transparent; width:10px; margin:4px; }
            QScrollBar::handle:vertical { background:#505050; border-radius:0px; min-height:24px; }
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
        """)
        self.setStyleSheet(self.styleSheet() + f"""
            QMainWindow, QDialog {{ background:{canvas_theme['window_bg']}; }}
            QWidget#appRoot {{ background:{canvas_theme['window_bg']}; }}
            QWidget#settingsContent, QStackedWidget {{ background:{canvas_theme['window_bg']}; }}
            QFrame#settingsNav {{ background:{canvas_theme['panel_bg']}; border-color:{canvas_theme['ui_border']}; }}
            QFrame#topBar, QFrame#sidebar, QFrame#chatCard, QFrame#settingsNav,
            QFrame#settingsCard {{ background:{canvas_theme['panel_bg']}; border-color:{canvas_theme['ui_border']}; border-radius:{canvas_theme.get('ui_radius', '10px')}; }}
            QFrame#sidebar {{ border-right-color:{canvas_theme['ui_border_strong']}; }}
            QFrame#chatCard {{ border-left-color:{canvas_theme['ui_border_strong']}; }}
            QFrame#chatHeader {{ background:{canvas_theme['panel_bg']}; border-bottom-color:{canvas_theme['ui_border']}; border-top-left-radius:{canvas_theme.get('ui_radius', '10px')}; border-top-right-radius:{canvas_theme.get('ui_radius', '10px')}; }}
            QFrame#sourceCard, QFrame#modelCard, QFrame#statusCard,
            QFrame#thinkingCard {{ background:{canvas_theme['card_bg']}; border-color:{canvas_theme['ui_border']}; border-radius:{canvas_theme.get('ui_radius', '10px')}; }}
            QFrame#sourceCard:hover {{ background:{canvas_theme['panel_bg']}; border-color:{canvas_theme['ui_border_strong']}; }}
            QFrame#iconBadge {{ background:{canvas_theme['panel_bg']}; border-color:{canvas_theme['ui_border_strong']}; border-radius:{canvas_theme.get('ui_radius', '10px')}; }}
            QFrame#composerSurface {{ background:{canvas_theme['panel_bg']}; border-top-color:{canvas_theme['ui_border_strong']}; border-bottom-left-radius:{canvas_theme.get('ui_radius', '10px')}; border-bottom-right-radius:{canvas_theme.get('ui_radius', '10px')}; }}
            QFrame#composerDivider {{ background:{canvas_theme['ui_border_strong']}; }}
            QComboBox, QLineEdit, QSpinBox, QPlainTextEdit {{ border-radius:{canvas_theme.get('ui_radius', '10px')}; }}
            QComboBox, QLineEdit, QSpinBox, QPlainTextEdit {{ background:{canvas_theme['control_bg']}; color:{canvas_theme['role']}; border-color:{canvas_theme['ui_border_strong']}; selection-background-color:{canvas_theme['divider']}; }}
            QComboBox::drop-down {{ border-left-color:{canvas_theme['ui_border_strong']}; }}
            QComboBox QAbstractItemView {{ background:{canvas_theme['panel_bg']}; color:{canvas_theme['role']}; border-color:{canvas_theme['ui_border_strong']}; selection-background-color:{canvas_theme['card_bg']}; }}
            QLineEdit#composerInput, QComboBox#chatSelector, QComboBox#thinkingLevel {{ background:{canvas_theme['control_bg']}; border-color:{canvas_theme['ui_border_strong']}; border-radius:{canvas_theme.get('ui_radius', '10px')}; }}
            QLineEdit#composerInput:focus, QComboBox#chatSelector:focus, QComboBox#thinkingLevel:focus {{ border-color:{canvas_theme['accent']}; }}
            QPushButton {{ border-radius:{canvas_theme.get('ui_radius', '10px')}; color:{canvas_theme['role']}; background:{canvas_theme['card_bg']}; border-color:{canvas_theme['ui_border_strong']}; }}
            QPushButton#primary {{ background:{canvas_theme['accent']}; color:{canvas_theme['accent_text']}; border-color:{canvas_theme['accent']}; }}
            QPushButton#primary:hover {{ background:{canvas_theme['accent']}; border-color:#ffffff; }}
            QPushButton#jumpLatest {{ background:{canvas_theme['accent']}; color:{canvas_theme['accent_text']}; border-color:{canvas_theme['accent']}; }}
            QPushButton#jumpLatest:hover {{ background:{canvas_theme['panel_bg']}; color:{canvas_theme['role']}; border-color:{canvas_theme['accent']}; }}
            QPushButton#secondary, QPushButton#quiet {{ background:{canvas_theme['card_bg']}; border-color:{canvas_theme['ui_border_strong']}; }}
            QPushButton#secondary:hover, QPushButton#quiet:hover {{ background:{canvas_theme['panel_bg']}; border-color:{canvas_theme['accent']}; }}
            QPushButton#settingsNavButton {{ background:{canvas_theme['card_bg']}; color:{canvas_theme['role']}; border-color:{canvas_theme['ui_border']}; }}
            QPushButton#settingsNavButton:hover {{ background:{canvas_theme['panel_bg']}; border-color:{canvas_theme['accent']}; }}
            QPushButton#settingsNavButton:checked {{ background:{canvas_theme['accent']}; color:{canvas_theme['accent_text']}; border-color:{canvas_theme['accent']}; }}
            QCheckBox {{ color:{canvas_theme['role']}; }}
            QCheckBox::indicator {{ background:{canvas_theme['control_bg']}; border-color:{canvas_theme['ui_border_strong']}; }}
            QCheckBox::indicator:checked {{ background:{canvas_theme['accent']}; border-color:{canvas_theme['accent']}; }}
            QSlider::groove:horizontal {{ background:{canvas_theme['ui_border_strong']}; }}
            QSlider::sub-page:horizontal {{ background:{canvas_theme['accent']}; }}
            QSlider::handle:horizontal {{ background:{canvas_theme['accent']}; }}
            QLabel#settingsTitle, QLabel#settingsWindowTitle, QLabel#settingsNavTitle {{ color:{canvas_theme['role']}; }}
            QLabel#eyebrow, QLabel#muted, QLabel#mutedSmall {{ color:{canvas_theme['role']}; }}
            QLabel#eyebrow {{ color:{canvas_theme.get('eyebrow', canvas_theme['role'])}; }}
            QLabel#composerHint {{ font-size:8pt; padding:0 2px; }}
            QWidget#settingsNavHost, QScrollArea#settingsScroll > QWidget#qt_scrollarea_viewport {{ background:transparent; }}
            QLabel#brandTitle, QLabel#statusDot {{ color:{canvas_theme.get('brand', '#ffffff')}; }}
            QPushButton#primary, QPushButton#jumpLatest, QPushButton#settingsNavButton:checked {{ background:{canvas_theme.get('primary_bg', canvas_theme['accent'])}; border:0; }}
            QPushButton#primary:hover {{ background:{canvas_theme.get('primary_hover', canvas_theme['accent'])}; }}
            QComboBox QAbstractItemView {{ border-radius:{canvas_theme.get('ui_radius', '0px')}; }}
            QScrollBar::handle:horizontal, QScrollBar::handle:vertical {{ background:{canvas_theme['ui_border_strong']}; border-radius:{'4px' if canvas_theme.get('ui_radius', '0px') != '0px' else '0px'}; }}
            QScrollBar::handle:horizontal:hover, QScrollBar::handle:vertical:hover {{ background:{canvas_theme['accent']}; }}
        """)
        self.setStyleSheet(self.styleSheet() + f"""
            QFrame#assistantBubble {{ background:{canvas_theme['assistant_bg']}; border:1px solid {canvas_theme['assistant_border']}; border-radius:{canvas_theme['radius']}; }}
            QFrame#assistantBubble:hover {{ background:{canvas_theme['assistant_bg']}; border-color:{canvas_theme['role']}; }}
            QFrame#userBubble {{ background:{canvas_theme['user_bg']}; border:1px solid {canvas_theme['user_border']}; border-radius:{canvas_theme['radius']}; }}
            QFrame#userBubble:hover {{ background:{canvas_theme['user_bg']}; border-color:{canvas_theme['role']}; }}
            QFrame#systemBubble {{ background:{canvas_theme['system_bg']}; border:1px solid {canvas_theme['system_border']}; border-radius:{canvas_theme['radius']}; }}
            QFrame#systemBubble:hover {{ border-color:{canvas_theme['role']}; }}
            QFrame#messageDivider {{ background:{canvas_theme['divider']}; }}
            QLabel#messageRole {{ color:{canvas_theme['role']}; }}
            QWidget#messageDragHeader {{ background:{canvas_theme['header_bg']}; border-bottom:1px solid {canvas_theme['header_border']}; border-top-left-radius:{canvas_theme['radius']}; border-top-right-radius:{canvas_theme['radius']}; }}
            QWidget#messageDragHeader:hover {{ background:{canvas_theme['header_bg']}; }}
            QLabel#messageImagePreview {{ border-color:{canvas_theme['assistant_border']}; }}
        """)
        if hasattr(self, "chat"):
            self.chat.set_board_theme(canvas_theme)
            self.chat.scene().update()
        # Graphics proxy widgets are not descendants in the normal QWidget
        # stylesheet tree. Apply the selected palette to each existing card.
        for row in getattr(self, "_canvas_proxy_by_row", {}):
            bubble = row.findChild(QFrame, "assistantBubble") or row.findChild(QFrame, "userBubble") or row.findChild(QFrame, "systemBubble")
            if bubble is not None:
                self._style_message_bubble(bubble, canvas_theme)
                for stripes in bubble.findChildren(DragStripeIndicator):
                    stripes.color = canvas_theme.get("stripe", canvas_theme["role"])
                    stripes.update()
        connector = QColor(canvas_theme["connector"])
        connector.setAlpha(canvas_theme["connector_alpha"])
        for _, _, line_item, arrow_item in getattr(self, "_message_connectors", []):
            line_item.setPen(QPen(connector, 1.45, Qt.PenStyle.SolidLine,
                                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            arrow_item.setPen(QPen(connector, 1.2, Qt.PenStyle.SolidLine,
                                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            arrow_item.setBrush(connector)
        if hasattr(self, "_message_connectors"):
            self._update_message_connectors()
        self._update_composer_hint()

    def open_twitch_chat(self, channel=None):
        if not self._integration_enabled("twitch"):
            QMessageBox.information(self, APP_NAME, "Интеграция Twitch выключена. Включи её в Настройки → Интеграции.")
            return
        dialog = TwitchChatDialog(self, self.settings, self._save_settings,
                                  self._canvas_theme_data().get("accent", "#ffffff"))
        if channel is not None:
            dialog.channel.setText(str(channel).strip().lstrip("#"))
        dialog.exec()

    def open_settings(self):
        previous_canvas_theme = self.settings.get("canvas_theme", "graphite")
        previous_decoration_shape = self.settings.get("decoration_shape", "square")
        previous_integrations_enabled = dict(self.settings.get("integrations_enabled", {}))
        dialog = QDialog(self)
        dialog.setWindowTitle("PIVEN · Настройки")
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        if available:
            min_width = max(560, min(860, available.width() - 32))
            min_height = max(460, min(680, available.height() - 60))
            dialog.setMinimumSize(min_width, min_height)
            dialog.resize(max(min_width, min(1000, available.width() - 24)), max(min_height, min(780, available.height() - 48)))
        else:
            dialog.resize(1000, 780)
            dialog.setMinimumSize(860, 680)
        dialog.setWindowOpacity(0.0)
        outer = QVBoxLayout(dialog); outer.setContentsMargins(18, 16, 18, 16); outer.setSpacing(12)
        page_title = QLabel("PIVEN  /  Настройки"); page_title.setObjectName("settingsWindowTitle"); outer.addWidget(page_title)
        main = QHBoxLayout(); main.setSpacing(14); outer.addLayout(main, 1)

        nav = QFrame(); nav.setObjectName("settingsNav"); nav.setFixedWidth(250); main.addWidget(nav)
        nav_layout = QVBoxLayout(nav); nav_layout.setContentsMargins(15, 18, 15, 14); nav_layout.setSpacing(7)
        nav_heading = QLabel("Настройки"); nav_heading.setObjectName("settingsNavTitle"); nav_layout.addWidget(nav_heading); nav_layout.addSpacing(10)
        nav_scroll = QScrollArea(); nav_scroll.setObjectName("settingsScroll"); nav_scroll.setWidgetResizable(True); nav_scroll.setFrameShape(QFrame.Shape.NoFrame)
        nav_buttons_host = QWidget(); nav_buttons_host.setObjectName("settingsNavHost"); nav_items_layout = QVBoxLayout(nav_buttons_host); nav_items_layout.setContentsMargins(0, 0, 0, 0); nav_items_layout.setSpacing(7)
        nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        nav_scroll.setWidget(nav_buttons_host); nav_layout.addWidget(nav_scroll, 1)

        content_column = QVBoxLayout(); content_column.setContentsMargins(0, 0, 0, 0); content_column.setSpacing(9); main.addLayout(content_column, 1)
        page_titles = ("Голос и микрофон", "Экран", "Промпт", "Код", "Темы", "Интеграции", "Навыки")
        title = QLabel(page_titles[0]); title.setObjectName("settingsTitle"); content_column.addWidget(title)
        intro = QLabel("Настрой компаньона под себя"); intro.setObjectName("muted"); content_column.addWidget(intro)
        pages = QStackedWidget(); content_column.addWidget(pages, 1)
        page_effect=QGraphicsOpacityEffect(pages); pages.setGraphicsEffect(page_effect)
        page_layouts = []
        for _ in page_titles:
            page = QWidget(); page.setObjectName("settingsContent")
            page_layout = QVBoxLayout(page); page_layout.setContentsMargins(0, 6, 4, 8); page_layout.setSpacing(12)
            page_scroll = QScrollArea(); page_scroll.setObjectName("settingsScroll"); page_scroll.setWidgetResizable(True); page_scroll.setFrameShape(QFrame.Shape.NoFrame); page_scroll.setWidget(page)
            pages.addWidget(page_scroll); page_layouts.append(page_layout)

        voice_group = QFrame(); voice_group.setObjectName("settingsCard"); page_layouts[0].addWidget(voice_group)
        voice_layout = QVBoxLayout(voice_group); voice_layout.setContentsMargins(16, 14, 16, 14); voice_layout.setSpacing(9)
        voice_label = QLabel("ГОЛОС"); voice_label.setObjectName("eyebrow"); voice_layout.addWidget(voice_label)
        voice_title = QLabel("Голос компаньона"); voice_title.setObjectName("rowTitle"); voice_layout.addWidget(voice_title)
        voice_check = QCheckBox("Озвучивать ответы компаньона"); voice_check.setChecked(self.speech_enabled); voice_layout.addWidget(voice_check)
        voice_row = QHBoxLayout(); voice_row.setSpacing(8); voice_layout.addLayout(voice_row)
        voice_box = CheckComboBox(); voice_box.addItem("Русский · Qwen3-TTS", "Russian"); voice_box.setCurrentIndex(max(0, voice_box.findData(self.settings.get("voice", "Russian")))); voice_box.setToolTip("Установленный локальный голос Qwen3-TTS"); voice_row.addWidget(voice_box, 1)
        test_voice = self._button("Проверить", "quiet"); test_voice.clicked.connect(lambda: threading.Thread(target=self._speak, args=("Проверка русской озвучки.",), daemon=True).start()); voice_row.addWidget(test_voice)

        screen_group = QFrame(); screen_group.setObjectName("settingsCard"); page_layouts[1].addWidget(screen_group)
        screen_form = QFormLayout(screen_group); screen_form.setContentsMargins(16, 14, 16, 14); screen_form.setHorizontalSpacing(18); screen_form.setVerticalSpacing(10)
        screen_label = QLabel("НАБЛЮДЕНИЕ ЗА ЭКРАНОМ"); screen_label.setObjectName("eyebrow"); screen_form.addRow(screen_label)
        interval_box = QSpinBox(); interval_box.setRange(10, 600); interval_box.setSingleStep(5); interval_box.setSuffix(" секунд"); interval_box.setValue(self.screen_interval_seconds); interval_box.setToolTip("Интервал между снимками экрана, пока включено наблюдение")
        screen_form.addRow("Интервал снимков", interval_box)

        mic_group = QFrame(); mic_group.setObjectName("settingsCard"); page_layouts[0].addWidget(mic_group)
        mic_form = QFormLayout(mic_group); mic_form.setContentsMargins(16, 14, 16, 14); mic_form.setHorizontalSpacing(18); mic_form.setVerticalSpacing(9)
        mic_label = QLabel("МИКРОФОН"); mic_label.setObjectName("eyebrow"); mic_form.addRow(mic_label)
        mic_box = CheckComboBox(); mic_box.addItem("По умолчанию Windows", "")
        try:
            import soundcard as sc
            microphones = sc.all_microphones(include_loopback=False); seen_names = set()
            for microphone in microphones:
                name = str(microphone.name)
                if name not in seen_names: mic_box.addItem(name, name); seen_names.add(name)
            if self.mic_device and self.mic_device not in seen_names: mic_box.addItem(f"{self.mic_device} · недоступен", self.mic_device)
        except Exception as e:
            log(f"microphone enumeration error: {e}"); mic_box.addItem("Список устройств недоступен", self.mic_device)
        mic_box.setCurrentIndex(max(0, mic_box.findData(self.mic_device))); mic_form.addRow("Устройство", mic_box)
        sensitivity_row = QHBoxLayout(); sensitivity = QSlider(Qt.Orientation.Horizontal); sensitivity.setRange(1, 100); sensitivity.setValue(self.mic_sensitivity)
        sensitivity_value = QLabel(f"{self.mic_sensitivity}%"); sensitivity_value.setMinimumWidth(42); sensitivity.valueChanged.connect(lambda value: sensitivity_value.setText(f"{value}%")); sensitivity_row.addWidget(sensitivity, 1); sensitivity_row.addWidget(sensitivity_value); mic_form.addRow("Чувствительность", sensitivity_row)
        mic_note = QLabel("Изменения устройства применятся после паузы и повторного запуска захвата."); mic_note.setObjectName("mutedSmall"); mic_note.setWordWrap(True); mic_form.addRow(mic_note)
        if self.running: mic_box.setEnabled(False); sensitivity.setEnabled(False)

        prompt_card = QFrame(); prompt_card.setObjectName("settingsCard"); page_layouts[2].addWidget(prompt_card)
        prompt_layout = QVBoxLayout(prompt_card); prompt_layout.setContentsMargins(16, 14, 16, 14); prompt_layout.setSpacing(9)
        prompt_label = QLabel("ОБЩИЕ ИНСТРУКЦИИ"); prompt_label.setObjectName("eyebrow"); prompt_layout.addWidget(prompt_label)
        prompt_description = QLabel("Один системный промпт передаётся каждой выбранной модели Ollama."); prompt_description.setObjectName("mutedSmall"); prompt_description.setWordWrap(True); prompt_layout.addWidget(prompt_description)
        prompt_editor = QPlainTextEdit(); prompt_editor.setObjectName("systemPromptEditor"); prompt_editor.setPlainText(self.settings["system_prompt"]); prompt_editor.setPlaceholderText("Опиши, как должен отвечать компаньон…"); prompt_editor.setMinimumHeight(280); prompt_layout.addWidget(prompt_editor)
        project_group = QFrame(); project_group.setObjectName("settingsCard"); page_layouts[3].addWidget(project_group)
        project_form = QFormLayout(project_group); project_form.setContentsMargins(16, 14, 16, 14); project_form.setHorizontalSpacing(18); project_form.setVerticalSpacing(10)
        project_label = QLabel("ЛОКАЛЬНЫЙ АГЕНТ РАЗРАБОТКИ"); project_label.setObjectName("eyebrow"); project_form.addRow(project_label)
        project_path_row = QHBoxLayout(); project_path_box = QLineEdit(self.settings.get("project_root", str(APP_DIR))); project_path_box.setPlaceholderText("Папка проекта"); project_path_row.addWidget(project_path_box, 1)
        project_browse = self._button("Обзор…", "quiet"); project_path_row.addWidget(project_browse); project_form.addRow("Рабочая папка", project_path_row)
        def choose_project_root():
            selected = QFileDialog.getExistingDirectory(dialog, "Выберите папку проекта", project_path_box.text() or str(APP_DIR))
            if selected: project_path_box.setText(selected)
        project_browse.clicked.connect(choose_project_root)
        project_note = QLabel("Когда запрос касается кода или файлов проекта, приложение автоматически запускает агента. Он работает только в выбранной папке, а команды ограничены проверками проекта."); project_note.setObjectName("mutedSmall"); project_note.setWordWrap(True); project_form.addRow(project_note)

        themes_group = QFrame(); themes_group.setObjectName("settingsCard"); page_layouts[4].addWidget(themes_group)
        themes_layout = QVBoxLayout(themes_group); themes_layout.setContentsMargins(16, 14, 16, 16); themes_layout.setSpacing(11)
        themes_label = QLabel("ТЕМА РАБОЧЕГО ПРОСТРАНСТВА"); themes_label.setObjectName("eyebrow"); themes_layout.addWidget(themes_label)
        canvas_theme_box = CheckComboBox()
        canvas_theme_box.setObjectName("themeSelector")
        for theme_id, theme_data in CANVAS_THEMES.items():
            canvas_theme_box.addItem(theme_data["name"], theme_id)
        canvas_theme_box.setCurrentIndex(max(0, canvas_theme_box.findData(self.settings.get("canvas_theme", "graphite"))))
        themes_layout.addWidget(canvas_theme_box)
        theme_description = QLabel(); theme_description.setObjectName("mutedSmall"); theme_description.setWordWrap(True); themes_layout.addWidget(theme_description)
        shape_label = QLabel("ФОРМА АНИМИРОВАННЫХ ДЕТАЛЕЙ"); shape_label.setObjectName("eyebrow"); themes_layout.addWidget(shape_label)
        motif_box = CheckComboBox(); motif_box.setObjectName("motifSelector")
        for shape, label in (("square", "Квадраты"), ("circle", "Круги"), ("triangle", "Треугольники")):
            motif_box.addItem(label, shape)
        motif_box.setCurrentIndex(max(0, motif_box.findData(previous_decoration_shape)))
        themes_layout.addWidget(motif_box)

        class CanvasThemePreview(QWidget):
            def __init__(self, palette, parent=None):
                super().__init__(parent)
                self.theme_palette = palette
                self.motif_shape = "square"
                self.setMinimumHeight(190)
                self.setMaximumHeight(230)

            def set_palette(self, palette):
                self.theme_palette = palette
                self.update()

            def set_shape(self, shape):
                self.motif_shape = shape
                self.update()

            def paintEvent(self, event):
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                bounds = self.rect().adjusted(1, 1, -1, -1)
                palette = self.theme_palette
                gradient = QLinearGradient(bounds.topLeft(), bounds.bottomRight())
                for stop, color in zip((0.0, 0.55, 1.0), palette["surface"]):
                    gradient.setColorAt(stop, QColor(color))
                painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(gradient); painter.drawRoundedRect(bounds, 7, 7)
                painter.save()
                painter.translate(bounds.topLeft())
                painter.scale(bounds.width() / 560.0, bounds.height() / 190.0)
                preview_grid = QColor(palette["grid"]); preview_grid.setAlpha(22)
                painter.setPen(QPen(preview_grid, 1))
                for gx in range(24, 560, 32):
                    painter.drawLine(gx, 0, gx, 190)
                for gy in range(24, 190, 32):
                    painter.drawLine(0, gy, 560, gy)
                if palette.get("scene") == "ocean":
                    flow = QColor(palette["flow"]); flow.setAlpha(70)
                    painter.setPen(QPen(flow, 1.4))
                    for band in range(3):
                        wave = QPainterPath(QPointF(0, 52 + band * 52))
                        for px in range(20, 581, 20):
                            wave.lineTo(px, 52 + band * 52 + math.sin(px / 56 + band) * 7)
                        painter.drawPath(wave)
                if palette.get("scene") == "neon":
                    painter.setPen(Qt.PenStyle.NoPen)
                    for color, cx, cy, radius in ((palette["accent"], 120, 60, 150), (palette["flow"], 430, 140, 160)):
                        glow = QRadialGradient(QPointF(cx, cy), radius)
                        inner = QColor(color); inner.setAlpha(60)
                        outer = QColor(color); outer.setAlpha(0)
                        glow.setColorAt(0.0, inner); glow.setColorAt(1.0, outer)
                        painter.setBrush(QBrush(glow))
                        painter.drawEllipse(QPointF(cx, cy), radius, radius)
                cards = (QRect(26, 28, 152, 65), QRect(192, 108, 174, 64), QRect(382, 36, 150, 68))
                colors = ((palette["assistant_bg"], palette["assistant_border"]),
                          (palette["user_bg"], palette["user_border"]),
                          (palette["system_bg"], palette["system_border"]))
                connector = QColor(palette["connector"]); connector.setAlpha(palette["connector_alpha"])
                painter.setPen(QPen(connector, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                for index in range(2):
                    a, b = cards[index], cards[index + 1]
                    start = QPointF(a.center().x(), a.bottom())
                    end = QPointF(b.center().x(), b.top())
                    path = QPainterPath(start)
                    path.cubicTo(QPointF(start.x(), start.y() + 18), QPointF(end.x(), end.y() - 18), end)
                    painter.drawPath(path)
                    painter.setBrush(connector); painter.setPen(Qt.PenStyle.NoPen)
                    arrow = QPainterPath(QPointF(end.x(), end.y()))
                    arrow.lineTo(QPointF(end.x() - 3, end.y() - 6)); arrow.lineTo(QPointF(end.x() + 3, end.y() - 6)); arrow.closeSubpath()
                    painter.drawPath(arrow)
                    painter.setPen(QPen(connector, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                for index, (card, color_pair) in enumerate(zip(cards, colors)):
                    fill, border = color_pair
                    if palette.get("message_border_width") == "0px":
                        painter.setPen(Qt.PenStyle.NoPen)
                    else:
                        painter.setPen(QPen(QColor(border), 1))
                    painter.setBrush(QColor(fill))
                    radius = int(palette["radius"].replace("px", ""))
                    if radius:
                        painter.drawRoundedRect(card, radius, radius)
                    else:
                        painter.drawRect(card)
                    painter.setPen(QColor(palette["role"]))
                    painter.drawText(card.adjusted(10, 7, -8, -34), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                     ("КОМПАНЬОН", "ВЫ", "СИСТЕМА")[index])
                    painter.setPen(QPen(QColor(border), 1))
                    painter.drawLine(card.left() + 10, card.bottom() - 17, card.right() - 12, card.bottom() - 17)
                    painter.drawLine(card.left() + 10, card.bottom() - 10, card.left() + 82, card.bottom() - 10)
                painter.setPen(QPen(QColor(palette["role"]), 1.1))
                painter.setBrush(QColor(palette["role"]))
                for index, x in enumerate((470, 490, 510, 530)):
                    y = 164
                    shape = self.motif_shape
                    if shape == "circle":
                        painter.drawEllipse(QRect(x, y, 8, 8))
                    elif shape == "triangle":
                        motif = QPainterPath(QPointF(x + 4, y))
                        motif.lineTo(x + 8, y + 8); motif.lineTo(x, y + 8); motif.closeSubpath()
                        painter.drawPath(motif)
                    else:
                        painter.drawRect(x, y, 8, 8)
                painter.restore()
                painter.end()

        theme_preview = CanvasThemePreview(CANVAS_THEMES.get(self.settings.get("canvas_theme"), CANVAS_THEMES["graphite"]))
        theme_preview.set_shape(motif_box.currentData() or "square")
        themes_layout.addWidget(theme_preview)
        def preview_canvas_theme(index):
            theme_id = canvas_theme_box.itemData(index)
            theme_data = CANVAS_THEMES.get(theme_id, CANVAS_THEMES["graphite"])
            theme_description.setText(theme_data["description"])
            theme_preview.set_palette(theme_data)
            theme_preview.set_shape(motif_box.currentData() or "square")
            # Apply to the actual board immediately; the preview alone made
            # theme selection look like it was not doing anything.
            if self.settings.get("canvas_theme") != theme_id:
                self.settings["canvas_theme"] = theme_id
                self._apply_theme()
        canvas_theme_box.currentIndexChanged.connect(preview_canvas_theme)
        def preview_motif_shape(index):
            shape = motif_box.itemData(index) or "square"
            theme_preview.set_shape(shape)
            if self.settings.get("decoration_shape") != shape:
                self.settings["decoration_shape"] = shape
                self._apply_theme()
        motif_box.currentIndexChanged.connect(preview_motif_shape)
        preview_canvas_theme(canvas_theme_box.currentIndex())

        integrations_group = QFrame(); integrations_group.setObjectName("settingsCard"); page_layouts[5].addWidget(integrations_group)
        integrations_layout = QVBoxLayout(integrations_group); integrations_layout.setContentsMargins(16, 14, 16, 16); integrations_layout.setSpacing(9)
        integrations_label = QLabel("ПРОГРАММЫ И ПОДКЛЮЧЕНИЯ"); integrations_label.setObjectName("eyebrow"); integrations_layout.addWidget(integrations_label)
        integration_enabled = dict(self.settings.get("integrations_enabled", {}))
        integration_switches = {}

        def save_integration_state(name, enabled, state_label):
            integration_enabled[name] = bool(enabled)
            self.settings["integrations_enabled"] = dict(integration_enabled)
            state_label.setText("Включена" if enabled else "Выключена")

        def make_integration_row(key, name, detail, icon_name, open_settings_callback):
            row = QFrame(); row.setObjectName("settingsCard")
            row_layout = QHBoxLayout(row); row_layout.setContentsMargins(12, 9, 12, 9); row_layout.setSpacing(10)
            icon = VectorIconWidget(icon_name, self._canvas_theme_data()["role"]); icon.setFixedSize(25, 25); row_layout.addWidget(icon)
            text_column = QVBoxLayout(); text_column.setSpacing(2); row_layout.addLayout(text_column, 1)
            title_button = QPushButton(name); title_button.setObjectName("integrationTitle"); title_button.setCursor(Qt.CursorShape.PointingHandCursor); title_button.setStyleSheet("text-align:left; border:0; padding:0; background:transparent; font-weight:700;")
            title_button.clicked.connect(open_settings_callback); text_column.addWidget(title_button)
            detail_label = QLabel(detail); detail_label.setObjectName("mutedSmall"); detail_label.setWordWrap(True); text_column.addWidget(detail_label)
            state = QLabel("Включена" if integration_enabled.get(key, True) else "Выключена"); state.setObjectName("mutedSmall"); state.setMinimumWidth(72); row_layout.addWidget(state)
            switch = ToggleSwitch(integration_enabled.get(key, True)); switch.on_color = QColor(self._canvas_theme_data()["accent"]); switch.off_color = QColor(self._canvas_theme_data()["ui_border_strong"])
            switch.toggled.connect(lambda checked, key=key, state=state: save_integration_state(key, checked, state))
            row_layout.addWidget(switch); integration_switches[key] = switch
            integrations_layout.addWidget(row)

        def make_integration_settings_window(name, build_contents):
            window = QDialog(dialog); window.setWindowTitle(f"PIVEN · {name}"); window.setMinimumWidth(500); window.resize(620, 330)
            window.setStyleSheet(dialog.styleSheet())
            layout = QVBoxLayout(window); layout.setContentsMargins(20, 18, 20, 18); layout.setSpacing(12)
            heading = QLabel(name); heading.setObjectName("settingsTitle"); layout.addWidget(heading)
            build_contents(layout, window)
            buttons_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
            buttons_box.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
            buttons_box.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
            buttons_box.accepted.connect(window.accept); buttons_box.rejected.connect(window.reject); layout.addWidget(buttons_box)
            return window

        def open_ollama_settings():
            def contents(layout, window):
                note = QLabel("Ollama — локальный движок Компаньона."); note.setObjectName("mutedSmall"); note.setWordWrap(True); layout.addWidget(note)
                form = QFormLayout(); form.addRow("Движок", QLabel(f"llama.cpp, {llama_backend.BASE_URL}")); form.addRow("Выбранная модель", QLabel(self.model_box.currentText().strip() or "Не выбрана")); layout.addLayout(form)
                refresh = self._button("Обновить список моделей", "quiet"); refresh.clicked.connect(self.refresh_models); layout.addWidget(refresh)
                info = QLabel("Переключатель на странице интеграций приостанавливает обращения Компаньона к Ollama."); info.setObjectName("mutedSmall"); info.setWordWrap(True); layout.addWidget(info)
            make_integration_settings_window("Ollama", contents).exec()

        def open_comfy_settings():
            def contents(layout, window):
                form = QFormLayout(); form.setVerticalSpacing(10)
                url_box = QLineEdit(self.settings.get("comfy_url", "http://127.0.0.1:8188")); form.addRow("Адрес ComfyUI", url_box)
                path_row = QHBoxLayout(); workflow_box = QLineEdit(self.settings.get("comfy_workflow", str(COMFY_DEFAULT_WORKFLOW))); path_row.addWidget(workflow_box, 1)
                browse = self._button("Выбрать…", "quiet")
                def browse_workflow():
                    selected, _ = QFileDialog.getOpenFileName(window, "Выберите API workflow ComfyUI", workflow_box.text() or str(APP_DIR), "JSON (*.json);;Все файлы (*.*)")
                    if selected: workflow_box.setText(selected)
                browse.clicked.connect(browse_workflow); path_row.addWidget(browse); form.addRow("Workflow", path_row); layout.addLayout(form)
                note = QLabel("Для генерации изображений нужен API workflow ComfyUI в формате JSON."); note.setObjectName("mutedSmall"); note.setWordWrap(True); layout.addWidget(note)
                window._values = (url_box, workflow_box)
            window = make_integration_settings_window("ComfyUI", contents)
            if window.exec() == QDialog.DialogCode.Accepted:
                url_box, workflow_box = window._values
                self.settings["comfy_url"] = url_box.text().strip() or "http://127.0.0.1:8188"
                self.settings["comfy_workflow"] = workflow_box.text().strip() or str(COMFY_DEFAULT_WORKFLOW)
                self._save_settings()

        def open_twitch_settings():
            def contents(layout, window):
                channel_box = QLineEdit(self.settings.get("twitch_channel", "")); channel_box.setPlaceholderText("Название Twitch-канала"); layout.addWidget(channel_box)
                note = QLabel("OAuth-токен вводится в окне отправки и не сохраняется. Лимит: 20 секунд между сообщениями, 3 в час, 10 в сутки."); note.setObjectName("mutedSmall"); note.setWordWrap(True); layout.addWidget(note)
                open_chat = self._button("Открыть окно отправки", "quiet"); open_chat.clicked.connect(lambda: self.open_twitch_chat(channel_box.text())); layout.addWidget(open_chat)
                window._channel_box = channel_box
            window = make_integration_settings_window("Twitch", contents)
            if window.exec() == QDialog.DialogCode.Accepted:
                self.settings["twitch_channel"] = window._channel_box.text().strip().lstrip("#")
                self._save_settings()

        make_integration_row("ollama", "Ollama", "Локальные языковые модели", "sparkles", open_ollama_settings)
        make_integration_row("comfyui", "ComfyUI", "Генерация изображений и медиа", "image", open_comfy_settings)
        make_integration_row("twitch", "Twitch", "Сообщения в чат с подтверждением", "chat", open_twitch_settings)

        skills_group = QFrame(); skills_group.setObjectName("settingsCard"); page_layouts[6].addWidget(skills_group)
        skills_layout = QVBoxLayout(skills_group); skills_layout.setContentsMargins(16, 14, 16, 16); skills_layout.setSpacing(10)
        skills_heading = QLabel("НАВЫКИ"); skills_heading.setObjectName("eyebrow"); skills_layout.addWidget(skills_heading)
        skill_items = (
            ("Работа с компьютером", "Управляет приложениями и окнами, находит и изменяет файлы, использует консоль, проверяет проект и ищет информацию в интернете по прямой просьбе."),
            ("Создание презентаций", "Готовит содержательную презентацию и сохраняет её в формате PowerPoint, чтобы её можно было скачать или открыть."),
        )
        for skill_name, skill_description in skill_items:
            skill_row = QFrame(); skill_row.setObjectName("settingsCard")
            skill_row_layout = QHBoxLayout(skill_row); skill_row_layout.setContentsMargins(12, 12, 12, 12); skill_row_layout.setSpacing(12)
            skill_icon = VectorIconWidget("monitor" if skill_name.startswith("Работа") else "sparkles", self._canvas_theme_data()["role"]); skill_icon.setFixedSize(28, 28); skill_row_layout.addWidget(skill_icon, 0, Qt.AlignmentFlag.AlignTop)
            skill_text = QVBoxLayout(); skill_text.setSpacing(4); skill_row_layout.addLayout(skill_text, 1)
            skill_title = QLabel(skill_name); skill_title.setObjectName("rowTitle"); skill_text.addWidget(skill_title)
            skill_note = QLabel(skill_description); skill_note.setObjectName("mutedSmall"); skill_note.setWordWrap(True); skill_text.addWidget(skill_note)
            skills_layout.addWidget(skill_row)

        for page_layout in page_layouts: page_layout.addStretch(1)

        nav_items = (("voice_wave", "Голос и микрофон", "Озвучивание и входной звук"), ("monitor", "Экран", "Частота снимков"), ("settings", "Промпт", "Инструкция для всех моделей"), ("settings", "Код", "Локальный агент разработки"), ("monitor", "Темы", "Доска, карточки и стрелки"), ("settings", "Интеграции", "Ollama, ComfyUI и Twitch"), ("voice_wave", "Навыки", "Компьютер и презентации"))
        nav_group = QButtonGroup(dialog); nav_group.setExclusive(True)
        self._settings_nav_buttons = []
        for index, (icon_name, name, detail) in enumerate(nav_items):
            nav_button = QPushButton(f"{name}\n{detail}"); nav_button.setObjectName("settingsNavButton"); nav_button.setProperty("themeIcon", icon_name); nav_button.setIcon(vector_icon(icon_name, MONO["text"])); nav_button.setIconSize(QSize(20, 20)); nav_button.setCheckable(True); nav_button.setCursor(Qt.CursorShape.PointingHandCursor); nav_button.setMinimumHeight(58); add_press_feedback(nav_button); nav_group.addButton(nav_button); nav_items_layout.addWidget(nav_button)
            self._settings_nav_buttons.append(nav_button)
            nav_button.setChecked(index == 0)
            def switch_page(checked=False,index=index,label=name):
                if index==pages.currentIndex(): return
                active=getattr(dialog,"_page_switch_animation",None)
                if active is not None: active.stop()
                fade=QPropertyAnimation(page_effect,b"opacity",dialog); fade.setDuration(130); fade.setStartValue(page_effect.opacity()); fade.setEndValue(.42); fade.setEasingCurve(QEasingCurve.Type.InOutCubic)
                dialog._page_switch_animation=fade
                def finish_switch():
                    pages.setCurrentIndex(index); title.setText(label)
                    reveal=QPropertyAnimation(page_effect,b"opacity",dialog); reveal.setDuration(240); reveal.setStartValue(page_effect.opacity()); reveal.setEndValue(1.0); reveal.setEasingCurve(QEasingCurve.Type.OutCubic)
                    dialog._page_switch_animation=reveal; reveal.start()
                fade.finished.connect(finish_switch); fade.start()
            nav_button.clicked.connect(switch_page)
        nav_group.buttonClicked.connect(lambda *_: self._refresh_settings_nav_icons())
        self._refresh_settings_nav_icons()
        nav_items_layout.addStretch(1)
        connection = QLabel("●  Ollama подключена"); connection.setObjectName("settingsConnection"); nav_layout.addWidget(connection)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить"); buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        add_press_feedback(buttons.button(QDialogButtonBox.StandardButton.Save)); add_press_feedback(buttons.button(QDialogButtonBox.StandardButton.Cancel))
        def close_settings(result):
            opening=getattr(dialog,"_open_animation",None)
            if opening is not None: opening.stop()
            animation=QPropertyAnimation(dialog,b"windowOpacity",dialog); animation.setDuration(190); animation.setStartValue(dialog.windowOpacity()); animation.setEndValue(0.0); animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
            dialog._close_animation=animation; animation.finished.connect(lambda: dialog.done(result)); animation.start()
        buttons.accepted.connect(lambda: close_settings(QDialog.DialogCode.Accepted)); buttons.rejected.connect(lambda: close_settings(QDialog.DialogCode.Rejected)); outer.addWidget(buttons)
        def fade_dialog_in():
            animation=QPropertyAnimation(dialog,b"windowOpacity",dialog); animation.setDuration(280); animation.setStartValue(dialog.windowOpacity()); animation.setEndValue(1.0); animation.setEasingCurve(QEasingCurve.Type.OutCubic); dialog._open_animation=animation; animation.start()
        QTimer.singleShot(0,fade_dialog_in)
        self._settings_dialog_open = True
        settings_opened_at = time.monotonic()
        result = dialog.exec()
        self._settings_dialog_open = False
        if self.activity_transient_until is not None:
            self.activity_transient_until += time.monotonic() - settings_opened_at
        self._refresh_activity()
        if result != QDialog.DialogCode.Accepted:
            # Cancel restores the theme that was active before opening settings.
            if (self.settings.get("canvas_theme") != previous_canvas_theme
                    or self.settings.get("decoration_shape") != previous_decoration_shape):
                self.settings["canvas_theme"] = previous_canvas_theme
                self.settings["decoration_shape"] = previous_decoration_shape
                self._apply_theme()
            self.settings["integrations_enabled"] = previous_integrations_enabled
            self._settings_nav_buttons = []
            return

        old_mic = (self.mic_device, self.mic_sensitivity)
        old_integrations_enabled = dict(self.settings.get("integrations_enabled", {}))
        self.settings.update({
            "system_prompt": prompt_editor.toPlainText().strip() or COMPANION_SYSTEM_PROMPT,
            "speech_enabled": voice_check.isChecked(),
            "voice": voice_box.currentData() or "Russian",
            "screen_interval": interval_box.value(),
            "mic_device": mic_box.currentData() or "",
            "mic_sensitivity": sensitivity.value(),
            "project_root": project_path_box.text().strip() or str(APP_DIR),
            "canvas_theme": canvas_theme_box.currentData() or "graphite",
            "decoration_shape": motif_box.currentData() or "square",
            "integrations_enabled": dict(integration_enabled),
        })
        self.speech_enabled = self.settings["speech_enabled"]
        self.screen_interval_seconds = self.settings["screen_interval"]
        self.mic_device = self.settings["mic_device"]
        self.mic_sensitivity = self.settings["mic_sensitivity"]
        self.messages[0]["content"] = self._effective_system_prompt(self.settings["system_prompt"])
        self._apply_theme()
        self._save_settings()
        if old_integrations_enabled.get("ollama", True) and not integration_enabled.get("ollama", True):
            self.pending_text_prompts.clear()
            if self.busy:
                self.action_cancel.set()
            if self.running:
                self.stop_event.set()
                self._set_start("Останавливаю…", False)
                self._set_status("Ollama отключена · останавливаю сессию")
        if self.running and old_mic != (self.mic_device, self.mic_sensitivity):
            self.events.put(("activity", "Новые настройки микрофона применятся после паузы"))

        self._settings_nav_buttons = []

    def _refresh_settings_nav_icons(self):
        theme = self._canvas_theme_data()
        for button in getattr(self, "_settings_nav_buttons", ()):
            icon_name = button.property("themeIcon")
            if icon_name:
                color = theme["accent_text"] if button.isChecked() else theme["role"]
                button.setIcon(vector_icon(icon_name, color))

    def _create_message_connector(self, source, target):
        item = QGraphicsPathItem()
        item.setZValue(-1)
        theme = self._canvas_theme_data()
        stroke = QColor(theme["connector"])
        stroke.setAlpha(theme["connector_alpha"])
        item.setPen(QPen(stroke, 1.45, Qt.PenStyle.SolidLine,
                         Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        self.chat_scene.addItem(item)
        # A sparse dashed accent travels over the stable connector. It gives
        # the workspace a sense of flow without moving message positions.
        pulse = QGraphicsPathItem()
        pulse.setZValue(-0.98)
        pulse_color = QColor(stroke); pulse_color.setAlpha(max(55, stroke.alpha() // 2))
        pulse_pen = QPen(pulse_color, 2.0, Qt.PenStyle.CustomDashLine,
                         Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        pulse_pen.setDashPattern([1.0, 12.0])
        pulse.setPen(pulse_pen)
        self.chat_scene.addItem(pulse)
        item._motion_pulse = pulse
        arrow = QGraphicsPathItem()
        arrow.setZValue(-0.99)
        arrow.setPen(QPen(stroke, 1.2, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        arrow.setBrush(stroke)
        self.chat_scene.addItem(arrow)
        connector = (source, target, item, arrow)
        self._message_connectors.append(connector)
        self._connectors_by_proxy.setdefault(id(source), []).append(connector)
        self._connectors_by_proxy.setdefault(id(target), []).append(connector)
        return item

    def _register_message_proxy(self, proxy):
        # Set the transform pivot while the item is still at its neutral scale
        # and angle. Changing it at lift time can visually shift an already
        # transformed card, especially when the canvas is zoomed.
        proxy.setTransformOriginPoint(proxy.boundingRect().center())
        previous = self._canvas_message_order[-1] if self._canvas_message_order else None
        if self._canvas_message_order:
            self._create_message_connector(previous, proxy)
        self._canvas_message_order.append(proxy)
        self._update_message_connectors(proxy)

    def _remove_message_connector(self, connector):
        if connector in self._message_connectors:
            self._message_connectors.remove(connector)
        source, target, item, arrow = connector
        for proxy in (source, target):
            proxy_key = id(proxy)
            links = self._connectors_by_proxy.get(proxy_key)
            if links is not None:
                if connector in links:
                    links.remove(connector)
                if not links:
                    self._connectors_by_proxy.pop(proxy_key, None)
        if item.scene() is self.chat_scene:
            self.chat_scene.removeItem(item)
        pulse = getattr(item, "_motion_pulse", None)
        if pulse is not None and pulse.scene() is self.chat_scene:
            self.chat_scene.removeItem(pulse)
        if arrow.scene() is self.chat_scene:
            self.chat_scene.removeItem(arrow)

    def _unregister_message_proxy(self, proxy):
        try:
            index = self._canvas_message_order.index(proxy)
        except ValueError:
            index = -1
        previous = self._canvas_message_order[index - 1] if index > 0 else None
        following = self._canvas_message_order[index + 1] if index >= 0 and index + 1 < len(self._canvas_message_order) else None
        # Each card touches at most two connectors. Removing/rebuilding the full
        # chain here made chat restore and dragging increasingly expensive.
        for connector in list(self._connectors_by_proxy.get(id(proxy), ())):
            self._remove_message_connector(connector)
        if index >= 0:
            self._canvas_message_order.pop(index)
        if previous is not None and following is not None:
            self._create_message_connector(previous, following)
            self._update_message_connectors(previous)

    def _show_generation_card(self, prompt):
        if self._generation_card_row is not None:
            return
        card_width = self._message_card_width(440)
        row = QWidget(); row.setObjectName("messageRow"); row.setFixedWidth(card_width)
        if isinstance(prompt, tuple):
            media_kind, prompt_text = prompt
        else:
            media_kind, prompt_text = "image", prompt
        media_title = {"image": "ИЗОБРАЖЕНИЯ", "video": "ВИДЕО", "audio": "АУДИО"}.get(media_kind, "МЕДИА")
        row.message_length = len(str(prompt_text))
        row_layout = QHBoxLayout(row); row_layout.setContentsMargins(0, 0, 0, 0)
        bubble = QFrame(); bubble.setObjectName("assistantBubble"); bubble.setFixedWidth(card_width)
        layout = QVBoxLayout(bubble); layout.setContentsMargins(18, 16, 18, 16); layout.setSpacing(10)
        heading = self._message_heading(row, f"ИДЁТ ГЕНЕРАЦИЯ · {media_title}")
        layout.addWidget(heading)
        detail = QLabel("Локальная модель собирает изображение" if media_kind == "image" and not isinstance(prompt, tuple) else "Локальная модель выполняет генерацию")
        detail.setObjectName("mutedSmall"); detail.setProperty("generationDetail", True); detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(detail)
        mosaic = GenerationMosaic(bubble); layout.addWidget(mosaic, 0, Qt.AlignmentFlag.AlignCenter)
        row_layout.addStretch(1); row_layout.addWidget(bubble); row_layout.addStretch(1)
        row.adjustSize(); row.resize(row.sizeHint())
        proxy = self.chat_scene.addWidget(row)
        self._canvas_proxy_by_row[row] = proxy
        for header in row.findChildren(MessageDragHeader):
            header.proxy = proxy
        scene_width = self.chat_scene.sceneRect().width()
        card_y = self._canvas_next_y
        proxy.setPos(max(20, (scene_width - proxy.boundingRect().width()) / 2), card_y)
        self._generation_card_row = row
        self._generation_card_proxy = proxy
        self._generation_card_y = card_y
        self._generation_next_y = card_y + max(110, row.height()) + 24
        self._register_message_proxy(proxy)
        self._grow_canvas_for_item(proxy)
        self._canvas_next_y = self._generation_next_y
        self._canvas_latest_item = proxy
        fade_in_widget(row, 300, start=0.0)
        QTimer.singleShot(0, self._scroll_chat_to_bottom)

    def _finish_generation_card(self):
        row = self._generation_card_row
        proxy = self._generation_card_proxy
        if row is None or proxy is None:
            return
        mosaic = row.findChild(GenerationMosaic)
        if mosaic is not None:
            mosaic.stop()
        self._unregister_message_proxy(proxy)
        self._canvas_proxy_by_row.pop(row, None)
        if self._canvas_latest_item is proxy:
            self._canvas_latest_item = None
        self._canvas_next_y = self._generation_card_y
        self.chat_scene.removeItem(proxy)
        proxy.deleteLater()
        row.deleteLater()
        self._generation_card_row = None
        self._generation_card_proxy = None
        self._generation_card_y = None
        self._generation_next_y = None

    def _update_message_connectors(self, proxy=None, *_):
        connectors = self._message_connectors if proxy is None else self._connectors_by_proxy.get(id(proxy), ())
        for source, target, item, arrow in tuple(connectors):
            if source.scene() is not self.chat_scene or target.scene() is not self.chat_scene:
                item.setPath(QPainterPath())
                getattr(item, "_motion_pulse", item).setPath(QPainterPath())
                arrow.setPath(QPainterPath())
                continue
            a = source.sceneBoundingRect()
            b = target.sceneBoundingRect()
            delta = b.center() - a.center()
            length = math.hypot(delta.x(), delta.y())
            if length < 12 or a.intersects(b):
                item.setPath(QPainterPath())
                getattr(item, "_motion_pulse", item).setPath(QPainterPath())
                arrow.setPath(QPainterPath())
                continue
            ux, uy = delta.x() / length, delta.y() / length

            def edge_scale(rect, x, y):
                half_w, half_h = rect.width() / 2, rect.height() / 2
                sx = half_w / abs(x) if abs(x) > 1e-6 else float("inf")
                sy = half_h / abs(y) if abs(y) > 1e-6 else float("inf")
                return min(sx, sy)

            start_scale = edge_scale(a, ux, uy)
            end_scale = edge_scale(b, ux, uy)
            start = QPointF(a.center().x() + ux * start_scale,
                            a.center().y() + uy * start_scale)
            tip = QPointF(b.center().x() - ux * end_scale,
                          b.center().y() - uy * end_scale)
            span_x, span_y = tip.x() - start.x(), tip.y() - start.y()
            span = math.hypot(span_x, span_y)
            if span < 8:
                item.setPath(QPainterPath())
                getattr(item, "_motion_pulse", item).setPath(QPainterPath())
                arrow.setPath(QPainterPath())
                continue
            # Base the curve on the actual free gap between card edges. Center
            # distance can be large even when the visible gap is only a few px.
            vx, vy = -uy, ux
            bend = min(12.0, span * 0.07) if span >= 56 else 0.0
            control_distance = span * 0.30
            control_1 = QPointF(start.x() + ux * control_distance + vx * bend,
                                start.y() + uy * control_distance + vy * bend)
            control_2 = QPointF(tip.x() - ux * control_distance + vx * bend,
                                tip.y() - uy * control_distance + vy * bend)
            arrow_length = 8.0
            base = QPointF(tip.x() - ux * arrow_length,
                           tip.y() - uy * arrow_length)
            wing_a = QPointF(base.x() + vx * 3.8, base.y() + vy * 3.8)
            wing_b = QPointF(base.x() - vx * 3.8, base.y() - vy * 3.8)
            path = QPainterPath(start)
            if bend:
                path.cubicTo(control_1, control_2, base)
            else:
                path.lineTo(base)
            item.setPath(path)
            getattr(item, "_motion_pulse", item).setPath(path)
            arrow_path = QPainterPath(tip)
            arrow_path.lineTo(wing_a)
            arrow_path.lineTo(wing_b)
            arrow_path.closeSubpath()
            arrow.setPath(arrow_path)

    def _reveal_message_connector(self, proxy):
        """Reveal a new link after landing, growing it from about send-button size."""
        view = getattr(self, "chat", None)
        zoom = max(0.01, abs(view.transform().m11())) if view is not None else 1.0
        for _source, _target, line, arrow in tuple(self._connectors_by_proxy.get(id(proxy), ())):
            path = line.path()
            if path.isEmpty():
                # Keep it available for a later drag that separates overlapping cards.
                line.setVisible(True)
                pulse = getattr(line, "_motion_pulse", None)
                if pulse is not None:
                    pulse.setVisible(True)
                arrow.setVisible(True)
                continue
            pulse = getattr(line, "_motion_pulse", None)
            start = path.pointAtPercent(0.0)
            bounds = path.boundingRect()
            span = math.hypot(bounds.width(), bounds.height())
            initial_scale = min(1.0, max(0.025, 44.0 / (zoom * max(1.0, span))))
            parts = tuple(item for item in (line, pulse, arrow) if item is not None)
            for item in parts:
                item.setTransformOriginPoint(start)
                item.setScale(initial_scale)
                item.setVisible(True)
            animation = QVariantAnimation(self)
            animation.setDuration(360)
            animation.setStartValue(initial_scale)
            animation.setEndValue(1.0)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.valueChanged.connect(
                lambda value, items=parts: [item.setScale(float(value)) for item in items])
            animation.finished.connect(
                lambda items=parts, current=animation: (
                    [item.setScale(1.0) for item in items], current.deleteLater()))
            animation.start()

    def _animate_workspace_connectors(self, phase):
        """Advance the tiny flow marks on existing links only.

        Animate only links that touch the viewport. Long saved chats can hold
        hundreds of cards, and updating off-screen graphics items every frame
        adds work without changing anything the user can see.
        """
        theme = self._canvas_theme_data()
        color = QColor(theme["connector"])
        color.setAlpha(max(50, theme["connector_alpha"] // 2))
        pen = QPen(color, 2.0, Qt.PenStyle.CustomDashLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        pen.setDashPattern([1.0, 12.0])
        pen.setDashOffset(-(phase * 4.0))
        viewport_rect = self.chat.mapToScene(self.chat.viewport().rect()).boundingRect()
        for _, _, item, arrow in tuple(getattr(self, "_message_connectors", ())):
            pulse = getattr(item, "_motion_pulse", None)
            if pulse is None:
                continue
            if not item.sceneBoundingRect().intersects(viewport_rect):
                continue
            pulse.setPen(pen)
            arrow.setOpacity(0.84 + 0.16 * (0.5 + 0.5 * math.sin(phase * 1.4)))

    def _save_presentation_copy(self, source_path):
        source = Path(source_path)
        if not source.is_file():
            QMessageBox.warning(self, APP_NAME, "Файл презентации не найден.")
            return
        downloads = Path.home() / "Downloads"
        default_dir = downloads if downloads.is_dir() else Path.home()
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить презентацию",
            str(default_dir / source.name),
            "Презентация PowerPoint (*.pptx)",
        )
        if not target:
            return
        destination = Path(target)
        if destination.suffix.lower() != ".pptx":
            destination = destination.with_suffix(".pptx")
        try:
            shutil.copy2(source, destination)
        except OSError as error:
            QMessageBox.warning(self, APP_NAME, f"Не удалось сохранить презентацию:\n{error}")
            return
        QMessageBox.information(self, APP_NAME, f"Презентация сохранена:\n{destination}")

    def _animate_sent_card(self, row, proxy, target_pos):
        """Fly a blank, button-sized tile from Send, then crossfade in the real card."""
        overlay_parent = self.centralWidget()
        screen_side = 44
        button_center = self.send_btn.mapTo(overlay_parent, self.send_btn.rect().center())
        start = QPointF(button_center.x() - screen_side / 2, button_center.y() - screen_side / 2)
        start_rect = QRectF(start.x(), start.y(), screen_side, screen_side)
        theme = self._canvas_theme_data()

        # The real card waits at its final position while the empty tile travels.
        for _source, _target, line, arrow in self._connectors_by_proxy.get(id(proxy), ()):
            line.setVisible(False)
            pulse = getattr(line, "_motion_pulse", None)
            if pulse is not None:
                pulse.setVisible(False)
            arrow.setVisible(False)
        effect = QGraphicsOpacityEffect(row)
        row.setGraphicsEffect(effect)
        row._ui_opacity_effect = effect
        effect.setOpacity(0.0)
        proxy.setPos(target_pos)
        proxy.setScale(1.0)
        proxy.widget().setEnabled(False)

        # Keep the flight in a transparent overlay spanning both the canvas
        # and composer, so it visibly starts on the send button before entering the board.
        ghost = QFrame(overlay_parent)
        ghost.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        ghost.setStyleSheet(
            f"QFrame {{ background:{theme['user_bg']}; border:1px solid {theme['user_border']}; }}"
        )
        ghost.setGeometry(round(start.x()), round(start.y()), screen_side, screen_side)
        ghost.show()
        ghost.raise_()
        ghost_effect = QGraphicsOpacityEffect(ghost)
        ghost.setGraphicsEffect(ghost_effect)
        ghost_effect.setOpacity(1.0)
        card_bounds = proxy.boundingRect()
        card_top_left = self.chat.viewport().mapTo(
            overlay_parent, self.chat.mapFromScene(proxy.mapToScene(card_bounds.topLeft()))
        )
        card_bottom_right = self.chat.viewport().mapTo(
            overlay_parent, self.chat.mapFromScene(proxy.mapToScene(card_bounds.bottomRight()))
        )
        end_rect = QRectF(QPointF(card_top_left), QPointF(card_bottom_right)).normalized()

        flight = QVariantAnimation(self)
        flight.setDuration(470)
        flight.setStartValue(0.0)
        flight.setEndValue(1.0)
        flight.setEasingCurve(QEasingCurve.Type.OutCubic)

        def move_tile(value):
            progress = float(value)
            rect = QRectF(
                start_rect.x() + (end_rect.x() - start_rect.x()) * progress,
                start_rect.y() + (end_rect.y() - start_rect.y()) * progress,
                start_rect.width() + (end_rect.width() - start_rect.width()) * progress,
                start_rect.height() + (end_rect.height() - start_rect.height()) * progress,
            )
            ghost.setGeometry(round(rect.x()), round(rect.y()), max(1, round(rect.width())), max(1, round(rect.height())))

        flight.valueChanged.connect(move_tile)

        def dissolve_tile():
            crossfade = QParallelAnimationGroup(self)
            fade = QVariantAnimation(crossfade)
            fade.setDuration(360)
            fade.setStartValue(1.0)
            fade.setEndValue(0.0)
            fade.setEasingCurve(QEasingCurve.Type.OutCubic)
            fade.valueChanged.connect(lambda value, opacity=ghost_effect: opacity.setOpacity(float(value)))
            crossfade.addAnimation(fade)
            reveal = QPropertyAnimation(effect, b"opacity", crossfade)
            reveal.setDuration(360)
            reveal.setStartValue(0.0)
            reveal.setEndValue(1.0)
            reveal.setEasingCurve(QEasingCurve.Type.OutCubic)
            crossfade.addAnimation(reveal)

            def finish():
                ghost.deleteLater()
                proxy.setPos(target_pos)
                proxy.widget().setEnabled(True)
                row._message_entry_animation = None
                self._update_message_connectors(proxy)
                self._reveal_message_connector(proxy)
                crossfade.deleteLater()

            crossfade.finished.connect(finish)
            row._message_entry_animation = crossfade
            flight.deleteLater()
            crossfade.start()

        flight.finished.connect(dissolve_tile)
        row._message_target_pos = target_pos
        row._message_entry_animation = flight
        flight.start()

    def _append(self, who, text, images=None, persist=True):
        text = str(text)
        if isinstance(images, (str, Path)):
            images = [str(images)]
        elif isinstance(images, (list, tuple)):
            images = [str(path) for path in images if path]
        else:
            images = []
        if not hasattr(self, "dialogue_items"):
            self.dialogue_items = []
        self.dialogue_items.append({"role": who, "text": text, "images": images})
        active_chat = self._active_chat()
        if active_chat and who == "user" and active_chat.get("title") in ("Новый чат", "Старый чат"):
            words = " ".join(text.split())
            title = words[:42].rsplit(" ", 1)[0] if len(words) > 42 and " " in words[:42] else words[:42]
            active_chat["title"] = title + ("…" if len(words) > len(title) else "") or "Новый чат"
            self._refresh_chat_selector()
        if len(self.dialogue_items) > 500:
            self.dialogue_items = self.dialogue_items[-500:]
            self._trim_oldest_dialogue_card()
        role_names = {"user": "ВЫ", "assistant": "КОМПАНЬОН · ТОЛЬКО ЧТО",
                      "system": "СИСТЕМА", "computer": "ЗВУК ПК"}
        bubble_name = {"user": "userBubble", "assistant": "assistantBubble",
                       "system": "systemBubble", "computer": "userBubble"}.get(who, "systemBubble")
        row = QWidget(); row.setObjectName("messageRow")
        row.message_length = len(text)
        row_layout = QHBoxLayout(row); row_layout.setContentsMargins(0, 0, 0, 0); row_layout.setSpacing(0)
        bubble = QFrame(); bubble.setObjectName(bubble_name)
        self._style_message_bubble(bubble)
        width = self._message_card_width(720 if who == "assistant" else 560)
        bubble.setMaximumWidth(width)
        body_layout = QVBoxLayout(bubble); body_layout.setContentsMargins(16, 13, 16, 12); body_layout.setSpacing(7)
        if who == "assistant":
            avatar = VectorIconWidget("merge", MONO["good"]); avatar.setFixedSize(19, 19)
            body_layout.addWidget(self._message_heading(row, role_names[who], avatar))
        else:
            body_layout.addWidget(self._message_heading(row, role_names.get(who, who.upper())))
        for stripes in bubble.findChildren(DragStripeIndicator):
            stripes.color = self._canvas_theme_data().get("stripe", self._canvas_theme_data()["role"])
        if images:
            image_row = QHBoxLayout(); image_row.setSpacing(7)
            for image_path in images[:4]:
                media_suffix = Path(image_path).suffix.lower()
                if media_suffix in (".mp4", ".webm", ".wav", ".mp3", ".flac", ".ogg"):
                    is_video = media_suffix in (".mp4", ".webm")
                    media_button = QPushButton(("Открыть видео · " if is_video else "Открыть аудио · ") + Path(image_path).name)
                    media_button.setIcon(vector_icon("video" if is_video else "audio", MONO["text"], 16))
                    media_button.setIconSize(QSize(16, 16))
                    media_button.setObjectName("messageAction")
                    media_button.setToolTip(str(image_path))
                    media_button.clicked.connect(lambda checked=False, p=str(image_path): QDesktopServices.openUrl(QUrl.fromLocalFile(p)))
                    image_row.addWidget(media_button, 0, Qt.AlignmentFlag.AlignLeft)
                    continue
                if media_suffix in (".pptx", ".pdf", ".docx", ".xlsx"):
                    file_label = "Открыть презентацию" if media_suffix == ".pptx" else "Открыть документ"
                    media_button = QPushButton(f"{file_label} · {Path(image_path).name}")
                    media_button.setIcon(vector_icon("file", MONO["text"], 16))
                    media_button.setIconSize(QSize(16, 16))
                    media_button.setObjectName("messageAction")
                    media_button.setToolTip(str(image_path))
                    media_button.clicked.connect(lambda checked=False, p=str(image_path): QDesktopServices.openUrl(QUrl.fromLocalFile(p)))
                    image_row.addWidget(media_button, 0, Qt.AlignmentFlag.AlignLeft)
                    if media_suffix == ".pptx":
                        download_button = QPushButton("↓ Скачать презентацию")
                        download_button.setObjectName("messageAction")
                        download_button.setToolTip("Сохранить копию презентации в выбранную папку")
                        download_button.clicked.connect(
                            lambda checked=False, p=str(image_path): self._save_presentation_copy(p))
                        image_row.addWidget(download_button, 0, Qt.AlignmentFlag.AlignLeft)
                    continue
                preview = ClickableImagePreview(image_path); preview.setObjectName("messageImagePreview"); preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
                preview.clicked.connect(self._open_image_viewer)
                image_size = QSize(480, 360) if who == "assistant" else QSize(144, 108)
                preview.setMaximumSize(image_size)
                reader = QImageReader(str(image_path))
                original_size = reader.size()
                if original_size.isValid():
                    reader.setScaledSize(original_size.scaled(image_size, Qt.AspectRatioMode.KeepAspectRatio))
                pixmap = QPixmap.fromImage(reader.read())
                if not pixmap.isNull():
                    preview.setPixmap(pixmap)
                    preview.setMinimumSize(min(image_size.width(), pixmap.width()), min(image_size.height(), pixmap.height()))
                else:
                    preview.setText(f"Не удалось показать превью\n{Path(image_path).name}")
                    preview.setToolTip(str(image_path))
                    log(f"Generated/attached image preview could not be loaded: {image_path}")
                image_row.addWidget(preview, 0, Qt.AlignmentFlag.AlignLeft)
            if len(images) > 4:
                more = QLabel(f"+{len(images)-4}"); more.setObjectName("mutedSmall"); image_row.addWidget(more)
            body_layout.addLayout(image_row)
        if text:
            body = QLabel(text); body.setObjectName("messageBody"); body.setWordWrap(True); body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); body_layout.addWidget(body)

        if who == "assistant":
            separator = QFrame(); separator.setObjectName("messageDivider"); separator.setFixedHeight(1); body_layout.addWidget(separator)
            actions = QHBoxLayout(); actions.setContentsMargins(0, 0, 0, 0); actions.setSpacing(5)
            action_id = getattr(self, "_next_action_id", 0) + 1; self._next_action_id = action_id
            if not hasattr(self, "_chat_actions"): self._chat_actions = {}
            self._chat_actions[action_id] = text
            row._chat_action_id = action_id
            for icon_name, action, tooltip in (("clone", "copy", "Копировать"), ("speak", "speak", "Озвучить"), ("retry", "retry", "Повторить ответ")):
                button = VectorActionButton(icon_name, self._canvas_theme_data()["role"]); button.setObjectName("messageActionIcon"); button.setProperty("action", action); button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setAccessibleName(tooltip); button.setFixedSize(32, 30); button.setToolTip(tooltip); add_press_feedback(button)
                button.clicked.connect(lambda checked=False, a=action, i=action_id: self._chat_action(a, i)); actions.addWidget(button)
            actions.addStretch(1)
            timestamp = QLabel(datetime.now().strftime("%H:%M")); timestamp.setObjectName("mutedSmall"); actions.addWidget(timestamp)
            body_layout.addLayout(actions)

        if who == "user":
            row_layout.addStretch(1); row_layout.addWidget(bubble, 0, Qt.AlignmentFlag.AlignRight)
        elif who == "system":
            row_layout.addWidget(bubble, 1)
        else:
            row_layout.addWidget(bubble, 0, Qt.AlignmentFlag.AlignLeft); row_layout.addStretch(1)
        row.adjustSize()
        row.resize(row.sizeHint())
        proxy = self.chat_scene.addWidget(row)
        self._canvas_proxy_by_row[row] = proxy
        self._dialogue_proxy_by_index[len(self.dialogue_items) - 1] = proxy
        for header in row.findChildren(MessageDragHeader):
            header.proxy = proxy
        scene_width = self.chat_scene.sceneRect().width()
        send_connector_extra_gap = 0.0
        if who == "user" and not self._loading_chat and self._canvas_message_order:
            zoom = max(0.01, abs(self.chat.transform().m11()))
            # Leave enough room for the new connector to grow from a 44 px
            # send-button-sized segment to roughly twice that length.
            send_connector_extra_gap = max(0.0, 88.0 / zoom - 24.0)
        proxy.setPos(max(20, (scene_width - proxy.boundingRect().width()) / 2),
                     self._canvas_next_y + send_connector_extra_gap)
        self._register_message_proxy(proxy)
        self._grow_canvas_for_item(proxy)
        self._canvas_next_y += max(110, row.height()) + 24 + send_connector_extra_gap
        self._canvas_latest_item = proxy
        # Keep the current follow/pan mode for every new message. In particular,
        # sending a message must not override a manual workspace position.
        if not self._loading_chat:
            target_pos = proxy.pos()
            if who == "user":
                if self._canvas_follow_latest:
                    self._scroll_chat_to_bottom(animate=False)
                self._animate_sent_card(row, proxy, target_pos)
            else:
                fade_in_widget(row, 320, start=0.0)
                proxy.setPos(target_pos + QPointF(0, 14))
                row._message_entry_animation = QPropertyAnimation(proxy, b"pos", proxy)
                row._message_entry_animation.setDuration(320)
                row._message_entry_animation.setStartValue(proxy.pos())
                row._message_entry_animation.setEndValue(target_pos)
                row._message_entry_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
                row._message_entry_animation.valueChanged.connect(
                    lambda _value, p=proxy: self._update_message_connectors(p))
                row._message_entry_animation.start()
                QTimer.singleShot(0, self._scroll_chat_to_bottom)
        if persist and not self._loading_chat:
            self._save_conversation()

    def _trim_oldest_dialogue_card(self):
        proxy = self._dialogue_proxy_by_index.pop(0, None)
        if proxy is not None:
            row = proxy.widget()
            if row is not None:
                action_id = getattr(row, "_chat_action_id", None)
                if action_id is not None:
                    getattr(self, "_chat_actions", {}).pop(action_id, None)
                self._canvas_proxy_by_row.pop(row, None)
            self._unregister_message_proxy(proxy)
            if proxy.scene() is self.chat_scene:
                self.chat_scene.removeItem(proxy)
            proxy.deleteLater()
            if row is not None:
                row.deleteLater()
        self._dialogue_proxy_by_index = {
            index - 1: item for index, item in self._dialogue_proxy_by_index.items() if index > 0
        }

    def _restore_dialogue_items(self, items, on_complete=None):
        """Render history in short batches so switching a large chat keeps the UI responsive."""
        self._chat_restore_generation = getattr(self, "_chat_restore_generation", 0) + 1
        generation = self._chat_restore_generation
        valid_roles = {"user", "assistant", "system", "computer"}
        if not isinstance(items, (list, tuple)):
            items = []
        queue_items = [item for item in items if isinstance(item, dict) and item.get("role") in valid_roles][-500:]
        self._loading_chat = True
        for name in ("chat_selector", "new_chat_btn", "chat_tools_btn", "input", "send_btn", "attach_btn"):
            control = getattr(self, name, None)
            if control is not None:
                control.setEnabled(False)
        offset = 0

        def render_batch():
            nonlocal offset
            if generation != self._chat_restore_generation:
                return
            batch_end = min(len(queue_items), offset + 24)
            for item in queue_items[offset:batch_end]:
                self._append(item.get("role", "system"), item.get("text", ""), item.get("images") or None, persist=False)
            offset = batch_end
            if offset < len(queue_items):
                QTimer.singleShot(8, render_batch)
                return
            if not self.dialogue_items:
                self._append("system", "Всё готово к разговору. Подключитесь к Ollama, выберите vision-модель и нажмите «Старт».\n\nКомпаньон работает локально: слышит включённые источники, отвечает голосом и иногда комментирует происходящее на экране.", persist=False)
            self._loading_chat = False
            for name in ("chat_selector", "new_chat_btn", "chat_tools_btn", "input", "send_btn", "attach_btn"):
                control = getattr(self, name, None)
                if control is not None:
                    control.setEnabled(True)
            self._update_message_connectors()
            QTimer.singleShot(0, self._scroll_chat_to_bottom)
            if on_complete is not None:
                on_complete()

        QTimer.singleShot(8, render_batch)

    def _open_image_viewer(self, image_path):
        viewer = ImageViewerDialog(image_path, self)
        viewer.exec()

    def _refresh_chat_selector(self):
        selector = getattr(self, "chat_selector", None)
        if selector is None:
            return
        selector.blockSignals(True)
        selector.clear()
        for chat in sorted(self.chats, key=lambda item: bool(item.get("pinned")), reverse=True):
            selector.addItem(chat.get("title") or "Новый чат", chat.get("id"))
        selector.setCurrentIndex(max(0, selector.findData(self.active_chat_id)))
        selector.blockSignals(False)
        active = self._active_chat()
        title = str((active.get("title") or "Новый чат") if active else "Новый чат")
        self.chat_title_label.setText(title if len(title) <= 36 else title[:35].rstrip() + "…")
        self.chat_title_label.setToolTip(title)

    def _switch_chat_by_index(self, index):
        if self._loading_chat:
            return
        if index < 0 or index >= self.chat_selector.count():
            return
        chat_id = self.chat_selector.itemData(index)
        if chat_id and chat_id != self.active_chat_id:
            if self.busy:
                self.chat.show_chat_hint("Дождитесь завершения текущего действия перед переключением чата")
                self._refresh_chat_selector()
                return
            self._switch_chat(str(chat_id))

    def _switch_chat(self, chat_id, on_restored=None):
        target = next((chat for chat in self.chats if chat.get("id") == chat_id), None)
        if target is None:
            return
        self._save_conversation()
        self.active_chat_id = chat_id
        self._refresh_chat_selector()
        restored_items = [item for item in target.get("items", []) if isinstance(item, dict)]
        self.dialogue_items = []
        active_scroll = getattr(self, "_chat_scroll_animation", None)
        if active_scroll is not None and active_scroll.state() == QAbstractAnimation.State.Running:
            active_scroll.stop()
            self._chat_scroll_animation = None
        self._canvas_follow_latest = True
        self.messages = [{"role": "system", "content": self._effective_system_prompt(self.settings["system_prompt"])}]
        self.messages.extend({"role": item["role"], "content": str(item.get("content", ""))}
                             for item in target.get("messages", [])
                             if isinstance(item, dict) and item.get("role") in ("user", "assistant"))
        self.chat_scene.clear()
        self.chat_scene.setSceneRect(0, 0, 2400, 1800)
        self._canvas_next_y = 820
        self._canvas_latest_item = None
        self._canvas_proxy_by_row = {}
        self._dialogue_proxy_by_index = {}
        self._canvas_message_order = []
        self._message_connectors = []
        self._connectors_by_proxy = {}
        self._generation_card_row = None
        self._generation_card_proxy = None
        self._generation_card_y = None
        self._generation_next_y = None
        self.reasoning_chat_row = None
        self.reasoning_chat_body = None
        self._chat_actions = {}
        self._next_action_id = 0
        self.jump_latest_btn.hide()
        self.chat.verticalScrollBar().setValue(0)
        self.chat.horizontalScrollBar().setValue(0)
        self._restore_dialogue_items(
            restored_items,
            lambda callback=on_restored: self._finish_chat_restore(callback),
        )

    def _finish_chat_restore(self, on_restored=None):
        self._refresh_chat_selector()
        self._save_conversation()
        if on_restored is not None:
            on_restored()

    def _new_chat(self):
        if self.busy:
            self.chat.show_chat_hint("Сначала дождитесь завершения текущего действия")
            return
        self._save_conversation()
        chat = {"id": uuid.uuid4().hex, "title": "Новый чат", "items": [], "messages": []}
        self.chats.append(chat)
        self._switch_chat(chat["id"])

    def _show_chat_tools(self):
        menu = QMenu(self)
        menu.addAction("Сбросить масштаб и перейти к последнему", self._reset_canvas_view)
        menu.addSeparator()
        menu.addAction("Найти в чатах…", self._search_chats)
        menu.addAction("Переименовать чат…", self._rename_chat)
        active = self._active_chat()
        if active:
            menu.addAction("Открепить чат" if active.get("pinned") else "Закрепить чат",
                           self._toggle_chat_pin)
        menu.addAction("Экспортировать чат…", self._export_chat)
        menu.addSeparator()
        menu.addAction("Удалить чат…", self._delete_chat)
        menu.exec(self.chat_tools_btn.mapToGlobal(self.chat_tools_btn.rect().bottomLeft()))

    def _reset_canvas_view(self):
        self.chat.resetTransform()
        self.chat._zoom = 1.0
        self._canvas_follow_latest = True
        if self._canvas_latest_item is not None:
            self.chat.centerOn(self._canvas_latest_item)
        else:
            self.chat.centerOn(self.chat_scene.sceneRect().center())
        self.jump_latest_btn.hide()
        self.chat._show_zoom_hud()

    def _rename_chat(self):
        chat = self._active_chat()
        if not chat:
            return
        title, accepted = QInputDialog.getText(self, "Переименовать чат", "Название:", text=chat.get("title", "Новый чат"))
        title = title.strip()
        if accepted and title:
            chat["title"] = title[:80]
            self._refresh_chat_selector()
            self._save_conversation()

    def _toggle_chat_pin(self):
        chat = self._active_chat()
        if chat:
            chat["pinned"] = not bool(chat.get("pinned"))
            self._refresh_chat_selector()
            self._save_conversation()

    def _delete_chat(self):
        chat = self._active_chat()
        if not chat or self.busy:
            if self.busy:
                self.chat.show_chat_hint("Дождитесь завершения текущего действия перед удалением чата")
            return
        answer = QMessageBox.question(self, "Удалить чат", f"Удалить «{chat.get('title', 'Новый чат')}» вместе с историей?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.chats = [item for item in self.chats if item.get("id") != self.active_chat_id]
        self.active_chat_id = ""
        if not self.chats:
            self.chats.append({"id": uuid.uuid4().hex, "title": "Новый чат", "items": [], "messages": []})
        self._switch_chat(self.chats[0].get("id"))

    def _export_chat(self):
        chat = self._active_chat()
        if not chat:
            return
        safe_name = re.sub(r'[<>:"/\\|?*]+', "_", chat.get("title") or "Чат").strip(" .") or "Чат"
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Экспортировать чат", f"{safe_name}.md",
            "Markdown (*.md);;Текстовый файл (*.txt)")
        if not path:
            return
        markdown = (selected_filter.startswith("Markdown") if selected_filter
                    else Path(path).suffix.lower() == ".md")
        expected_suffix = ".md" if markdown else ".txt"
        destination_path = Path(path)
        if destination_path.suffix.lower() != expected_suffix:
            destination_path = destination_path.with_suffix(expected_suffix)
        try:
            destination_path.write_text(self.export_chat_text(chat.get("id"), markdown), encoding="utf-8")
            self.chat.show_chat_hint("Чат экспортирован")
        except Exception as error:
            QMessageBox.warning(self, "Экспорт чата", f"Не удалось сохранить файл:\n{error}")

    def _search_chats(self):
        if self.busy:
            self.chat.show_chat_hint("Дождитесь завершения текущего действия перед поиском")
            return
        query, accepted = QInputDialog.getText(self, "Поиск по чатам", "Найти текст:")
        query = query.strip()
        if not accepted or not query:
            return
        results = []
        needle = query.casefold()
        for chat in self.chats:
            for index, entry in enumerate(chat.get("items", [])):
                text = str(entry.get("text", ""))
                position = text.casefold().find(needle)
                if position < 0:
                    continue
                start, end = max(0, position - 55), min(len(text), position + len(query) + 85)
                excerpt = " ".join(text[start:end].split())
                if start:
                    excerpt = "…" + excerpt
                if end < len(text):
                    excerpt += "…"
                results.append((chat, index, entry, excerpt))
        if not results:
            QMessageBox.information(self, "Поиск по чатам", "Совпадений не найдено.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Результаты поиска · {len(results)}")
        dialog.resize(620, 420)
        layout = QVBoxLayout(dialog)
        listing = QListWidget(dialog)
        for chat, index, entry, excerpt in results:
            role = {"user": "Вы", "assistant": "Компаньон", "system": "Система", "computer": "Звук ПК"}.get(entry.get("role"), "Сообщение")
            item = QListWidgetItem(f"{chat.get('title', 'Чат')} · {role}\n{excerpt}")
            item.setData(Qt.ItemDataRole.UserRole, (chat.get("id"), index))
            listing.addItem(item)
        layout.addWidget(listing)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        listing.itemDoubleClicked.connect(lambda *_: dialog.accept())
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted or listing.currentItem() is None:
            return
        chat_id, message_index = listing.currentItem().data(Qt.ItemDataRole.UserRole)
        if chat_id != self.active_chat_id:
            self._switch_chat(chat_id, lambda idx=message_index: self._jump_to_dialogue_item(idx))
        else:
            self._jump_to_dialogue_item(message_index)

    def _jump_to_dialogue_item(self, index):
        proxy = self._dialogue_proxy_by_index.get(index)
        if proxy is not None and proxy.scene() is self.chat_scene:
            self._pause_canvas_follow()
            self.chat.centerOn(proxy)

    def _chat_action(self, action, action_id):
        try: text = self._chat_actions.get(int(action_id))
        except (ValueError, AttributeError): return
        if not text: return
        if action == "copy":
            QApplication.clipboard().setText(text); self._set_status("Ответ скопирован")
            self._set_activity("Ответ скопирован")
            self.chat.show_chat_hint("Ответ скопирован")
        elif action == "speak":
            self._set_activity("Запускает Qwen3-TTS")
            self.chat.show_chat_hint("Запускаю озвучивание")
            threading.Thread(target=self._speak, args=(text,), daemon=True).start()
        elif action == "retry":
            self._set_activity("Повторяю запрос")
            self.chat.show_chat_hint("Повторяю ответ")
            self._retry_last_answer()

    def _retry_last_answer(self):
        if self.retry_last_answer(self.model_box.currentText().strip()):
            self._set_activity("Думает")

    def _set_status(self, text):
        status_changed = self.status_pill.text() != text
        if status_changed:
            self.status_pill.setText(text)
        low=text.lower(); p=MONO
        color=p["good"] if ("актив" in low or "подключена" in low) else (p["danger"] if ("ошиб" in low or "недоступ" in low) else p["muted"])
        if "подключена" in low:
            short = "Ollama подключена"
        elif "недоступ" in low or "ошиб" in low:
            short = "Нет подключения"
        elif "актив" in low:
            short = "Компаньон активен"
        elif "останов" in low or "пауза" in low:
            short = "Компаньон на паузе"
        else:
            short = "Связь с Ollama"
        if self.status_title.text() != short:
            self.status_title.setText(short)
        title_style=f"color:{color};font-size:9pt;font-weight:650"
        dot_style=f"color:{color};font-size:8pt"
        pill_style=f"color:{p['muted']};background:transparent;border:0;padding:0;font-size:8pt"
        if self.status_title.styleSheet() != title_style:
            self.status_title.setStyleSheet(title_style)
        if self.status_dot.styleSheet() != dot_style:
            self.status_dot.setStyleSheet(dot_style)
        if self.status_pill.styleSheet() != pill_style:
            self.status_pill.setStyleSheet(pill_style)
        if status_changed:
            fade_in_widget(self.status_pill,160,0.72,1.0)

    def _append_reasoning(self, text):
        text=str(text).strip()
        if not text: return
        if len(text) > 5000: text="…" + text[-5000:]
        created=False
        if self.reasoning_chat_row is None:
            created=True
            row=QWidget(); row.setObjectName("messageRow")
            row_layout=QHBoxLayout(row); row_layout.setContentsMargins(0,0,0,0); row_layout.setSpacing(0)
            bubble=QFrame(); bubble.setObjectName("assistantBubble"); bubble.setMaximumWidth(self._message_card_width(720))
            self._style_message_bubble(bubble)
            layout=QVBoxLayout(bubble); layout.setContentsMargins(16,12,16,12); layout.setSpacing(7)
            layout.addWidget(self._message_heading(row, "РАССУЖДЕНИЕ"))
            self.reasoning_chat_body=QPlainTextEdit(); self.reasoning_chat_body.setObjectName("reasoningContent"); self.reasoning_chat_body.setReadOnly(True); self.reasoning_chat_body.setMaximumHeight(190); self.reasoning_chat_body.setMinimumHeight(66); self.reasoning_chat_body.setFrameShape(QFrame.Shape.NoFrame); layout.addWidget(self.reasoning_chat_body)
            row_layout.addWidget(bubble,0,Qt.AlignmentFlag.AlignLeft); row_layout.addStretch(1)
            row.adjustSize(); row.resize(row.sizeHint())
            proxy = self.chat_scene.addWidget(row)
            self._canvas_proxy_by_row[row] = proxy
            for header in row.findChildren(MessageDragHeader):
                header.proxy = proxy
            scene_width = self.chat_scene.sceneRect().width()
            proxy.setPos(max(20, (scene_width - proxy.boundingRect().width()) / 2), self._canvas_next_y)
            self._register_message_proxy(proxy)
            self._grow_canvas_for_item(proxy)
            self._canvas_next_y += max(110, row.height()) + 24
            self._canvas_latest_item = proxy; self.reasoning_chat_row=row
            row.adjustSize(); target_height=max(78,row.sizeHint().height())
            effect=QGraphicsOpacityEffect(row); row.setGraphicsEffect(effect); effect.setOpacity(0.0); row.setMaximumHeight(0)
            animation=QParallelAnimationGroup(self); row._reasoning_animation=animation
            fade=QPropertyAnimation(effect,b"opacity",animation); fade.setDuration(320); fade.setStartValue(0.0); fade.setEndValue(1.0); fade.setEasingCurve(QEasingCurve.Type.OutCubic); animation.addAnimation(fade)
            grow=QPropertyAnimation(row,b"maximumHeight",animation); grow.setDuration(380); grow.setStartValue(0); grow.setEndValue(target_height); grow.setEasingCurve(QEasingCurve.Type.OutCubic); animation.addAnimation(grow)
            grow.valueChanged.connect(lambda _value, p=proxy: self._update_message_connectors(p))
            animation.finished.connect(lambda r=row,e=effect: (r.setMaximumHeight(16777215),e.setOpacity(1.0)))
            animation.start()
        self.reasoning_chat_body.setPlainText(text)
        self.reasoning_chat_body.moveCursor(QTextCursor.MoveOperation.End)
        self.reasoning_chat_body.ensureCursorVisible()
        QTimer.singleShot(0, self._update_message_connectors)
        if created and self._canvas_follow_latest:
            QTimer.singleShot(0, self._scroll_chat_to_bottom)

    def _return_to_latest(self):
        if self._loading_chat or self._canvas_latest_item is None:
            return
        self._canvas_follow_latest = True
        self.jump_latest_btn.hide()
        QTimer.singleShot(0, self._scroll_chat_to_bottom)

    def _pause_canvas_follow(self):
        self._canvas_follow_latest = False
        self.jump_latest_btn.show()
        active=getattr(self,"_chat_scroll_animation",None)
        if active is not None and active.state()==QAbstractAnimation.State.Running:
            active.stop()
            self._chat_scroll_animation=None

    def _scroll_chat_to_bottom(self, animate=True):
        if self._canvas_follow_latest:
            self.jump_latest_btn.hide()
        if self._loading_chat or not self._canvas_follow_latest or self._canvas_latest_item is None:
            return
        item=self._canvas_latest_item
        item_center=item.sceneBoundingRect().center()
        scene_view_center=self.chat.mapToScene(self.chat.viewport().rect().center())
        hbar=self.chat.horizontalScrollBar(); vbar=self.chat.verticalScrollBar()
        target_h=max(hbar.minimum(),min(hbar.maximum(),hbar.value()+item_center.x()-scene_view_center.x()))
        target_v=max(vbar.minimum(),min(vbar.maximum(),vbar.value()+item_center.y()-scene_view_center.y()))
        if not animate:
            active=getattr(self,"_chat_scroll_animation",None)
            if active is not None and active.state()==QAbstractAnimation.State.Running:
                active.stop()
                self._chat_scroll_animation=None
            hbar.setValue(round(target_h)); vbar.setValue(round(target_v))
            return
        active=getattr(self,"_chat_scroll_animation",None)
        if active is not None and active.state()==QAbstractAnimation.State.Running:
            self._chat_h_animation.setEndValue(target_h); self._chat_v_animation.setEndValue(target_v); return
        if abs(target_h-hbar.value())<3 and abs(target_v-vbar.value())<3:
            return
        group=QParallelAnimationGroup(self)
        self._chat_h_animation=QPropertyAnimation(hbar,b"value",group); self._chat_h_animation.setDuration(320); self._chat_h_animation.setStartValue(hbar.value()); self._chat_h_animation.setEndValue(target_h); self._chat_h_animation.setEasingCurve(QEasingCurve.Type.OutCubic); group.addAnimation(self._chat_h_animation)
        self._chat_v_animation=QPropertyAnimation(vbar,b"value",group); self._chat_v_animation.setDuration(320); self._chat_v_animation.setStartValue(vbar.value()); self._chat_v_animation.setEndValue(target_v); self._chat_v_animation.setEasingCurve(QEasingCurve.Type.OutCubic); group.addAnimation(self._chat_v_animation)
        self._chat_scroll_animation=group
        group.finished.connect(lambda a=group: setattr(self,"_chat_scroll_animation",None) if getattr(self,"_chat_scroll_animation",None) is a else None)
        group.start()

    def _remove_reasoning_animated(self):
        row=self.reasoning_chat_row
        if row is None: return
        self.reasoning_chat_row=None; self.reasoning_chat_body=None
        opening=getattr(row,"_reasoning_animation",None)
        if opening is not None: opening.stop()
        row.setMinimumHeight(0); row.setMaximumHeight(max(1,row.height()))
        effect=row.graphicsEffect()
        if not isinstance(effect,QGraphicsOpacityEffect):
            effect=QGraphicsOpacityEffect(row); row.setGraphicsEffect(effect)
        fade_out=QParallelAnimationGroup(self); row._reasoning_remove_animation=fade_out
        fade=QPropertyAnimation(effect,b"opacity",fade_out); fade.setDuration(420); fade.setStartValue(effect.opacity()); fade.setEndValue(0.0); fade.setEasingCurve(QEasingCurve.Type.InOutCubic); fade_out.addAnimation(fade)
        collapse=QPropertyAnimation(row,b"maximumHeight",fade_out); collapse.setDuration(460); collapse.setStartValue(row.height()); collapse.setEndValue(0); collapse.setEasingCurve(QEasingCurve.Type.InOutCubic); fade_out.addAnimation(collapse)
        def finish():
            proxy = self._canvas_proxy_by_row.pop(row, None)
            if proxy is not None:
                self._unregister_message_proxy(proxy)
                if self._canvas_latest_item is proxy:
                    self._canvas_latest_item = None
                self.chat_scene.removeItem(proxy)
                proxy.deleteLater()
        fade_out.finished.connect(finish); fade_out.start()

    def _set_activity(self, text):
        self.activity_text=text
        low=text.lower()
        timed=any(marker in low for marker in (
            "думает", "аудиозахват на паузе", "смотрит на экран", "ждёт ответа",
            "обдумывает", "генерирует", "запускает", "распознаёт", "готовит",
            "говорит", "останавливается", "останавливает", "отправляет", "загружает workflow",
            "comfyui генерирует", "освобождает память", "устанавливает", "устанавливаю", "обновляет список", "проверяет подключение", "агент",
        ))
        self.activity_started_at=time.monotonic() if timed else None
        idle=any(marker in low for marker in ("слушает", "готов к работе", "пауза", "захват остановлен"))
        self.activity_transient_until=(time.monotonic()+2.4) if not timed and not idle else None
        self._refresh_activity()

    def _animate_thinking_dots(self):
        self._thinking_dot_index = (self._thinking_dot_index + 1) % len(self._thinking_dot_frames)
        self.activity_indicator.setText(self._thinking_dot_frames[self._thinking_dot_index])

    def _refresh_activity(self):
        low=self.activity_text.lower()
        p=MONO
        if (self.activity_transient_until is not None and not getattr(self, "_settings_dialog_open", False)
                and time.monotonic() >= self.activity_transient_until):
            self.activity_transient_until=None
            self.activity_text="Слушает" if self.running else "Готов к работе"
            low=self.activity_text.lower()
        if "не удалось" in low or "ошиб" in low or "не получилось" in low:
            title,detail="Ошибка","Подробности показаны в чате"
        elif "агент" in low:
            title,detail="Работаю с проектом","Изучаю файлы и выполняю задачу"
        elif "освобождает память" in low:
            title,detail="Готовлю видеопамять","Выгружаю остальные локальные модели"
        elif "comfyui генерирует" in low or "изображение" in low and any(word in low for word in ("генер", "созда")):
            title,detail="Создаю изображение","Локальная модель выполняет генерацию"
        elif "загружает workflow" in low:
            title,detail="Подготавливаю изображение","Загружаю workflow в ComfyUI"
        elif "отправляет запрос в comfyui" in low:
            title,detail="Отправляю запрос","Передаю описание в ComfyUI"
        elif "генерирует" in low:
            title,detail="Печатает","Ollama генерирует ответ"
        elif "добавлено в очередь" in low:
            title,detail="В очереди","Отвечу после текущего ответа"
        elif "аудиозахват на паузе" in low:
            title,detail="Думаю","Микрофон и системный звук выключены до ответа"
        elif "обдумывает" in low or "думает" in low or "ждёт ответа" in low:
            title,detail="Думаю","Аудиозахват на паузе до ответа"
        elif "смотрит на экран" in low:
            title,detail="Изучаю экран","Ищу важные детали"
        elif "обновляет список моделей" in low:
            title,detail="Обновляю модели","Проверяю Ollama"
        elif "устанавливает аудиокомпонент" in low:
            title,detail="Устанавливаю аудио","Это может занять несколько минут"
        elif "останавливает" in low or "останавливается" in low:
            title,detail=("Останавливаю","Прерываю текущий запрос") if "действие" in low else ("Останавливаюсь…","Завершаю захват аудио")
        elif "ответ получен" in low:
            title,detail="Ответ готов",""
        elif "запрос прерван" in low or "озвучивание прервано" in low:
            title,detail="Действие прервано",""
        elif "изображение готово" in low:
            title,detail="Изображение готово",""
        elif "копирован" in low:
            title,detail="Скопировано","Ответ помещён в буфер обмена"
        elif "прикреплен" in low or "изображени" in low and "добавлен" in low:
            title,detail="Вложение обновлено",""
        elif "вложени" in low and "удален" in low:
            title,detail="Вложения удалены",""
        elif "настройки" in low:
            title,detail="Настройки открыты",""
        elif "повторяю запрос" in low:
            title,detail="Повторяю ответ",""
        elif "аудиокомпонент установлен" in low:
            title,detail="Аудио готово","Можно запускать компаньона"
        elif "cuda подключён" in low:
            title,detail="Распознавание подключено","Parakeet готов к работе"
        elif "пауза" in low or "захват остановлен" in low:
            title,detail="На паузе","Захват источников остановлен"
        elif "готов к работе" in low:
            title,detail="Готов к работе","Выбери действие или отправь сообщение"
        elif "запускает parakeet" in low:
            title,detail="Запускаю распознавание","Подключаю локальный Parakeet на CUDA"
        elif "comfyui" in low and "запускает локальный" in low:
            title,detail="Запускаю ComfyUI","Подготавливаю генерацию изображения"
        elif "голосовой запрос на изображение" in low:
            title,detail="Понял запрос на изображение","Передаю описание в ComfyUI"
        elif "распознаёт речь" in low:
            title,detail="Распознаю речь","Parakeet обрабатывает аудио на GPU"
        elif "говорит · qwen3-tts" in low:
            title,detail="Говорю",""
        elif "готовит русскую речь" in low or "запускает qwen3-tts" in low:
            title,detail="Готовлю голос",""
        elif "слушает микрофон" in low:
            title,detail="Слушаю…","Микрофон активен"
        elif "слушает звук пк" in low:
            title,detail="Слушаю…","Слежу за звуком компьютера"
        elif "слушает" in low:
            title,detail="Слушаю…","Жду, когда ты заговоришь"
        else:
            title,detail=("Слушаю","Жду, когда ты заговоришь") if self.running else ("Готов к работе","Выбери действие или отправь сообщение")
        if self.activity_label.text() != title:
            self.activity_label.setText(title)
        if self.activity_started_at is not None:
            elapsed=max(0,int(time.monotonic()-self.activity_started_at))
            timer=f"{elapsed//60:02d}:{elapsed%60:02d}"
            detail=f"{detail} · {timer}" if detail else timer
        if self.activity_detail.text() != detail:
            self.activity_detail.setText(detail)
        label_style = f"color:{p['text']};font-size:9pt;font-weight:650;background:transparent;border:0;padding:0"
        detail_style = f"color:{p['muted']};font-size:8pt;background:transparent;border:0;padding:0"
        if self.activity_label.styleSheet() != label_style:
            self.activity_label.setStyleSheet(label_style)
        if self.activity_detail.styleSheet() != detail_style:
            self.activity_detail.setStyleSheet(detail_style)
        is_thinking=bool(self.busy) or any(word in low for word in (
            "дума", "ждёт ответа", "генерир", "распозна", "запускает", "готовит",
            "говорит", "ошиб", "останавливается", "останавливает", "отправляет", "загружает workflow",
            "освобождает память", "устанавливает", "устанавливаю", "обновляет список", "проверяет подключение", "агент",
        ))
        is_transient=self.activity_transient_until is not None
        if self.activity_cancel_btn.isVisible() != is_thinking:
            self.activity_cancel_btn.setVisible(is_thinking)
        indicator_style = f"color:{p['accent']};font-size:13pt;font-weight:700;background:transparent;border:0"
        if self.activity_indicator.styleSheet() != indicator_style:
            self.activity_indicator.setStyleSheet(indicator_style)
        if not is_thinking and not is_transient:
            self._thinking_dot_timer.stop()
            if self.activity_indicator.text() != "•••":
                self.activity_indicator.setText("•••")
            if self.activity_panel.isVisible():
                self.activity_fade.stop(); self.activity_fade.setDuration(190)
                self.activity_fade.setStartValue(self.activity_effect.opacity()); self.activity_fade.setEndValue(0.0); self.activity_fade.start()
            return
        if not is_thinking:
            self._thinking_dot_timer.stop()
            if self.activity_indicator.text() != "✓":
                self.activity_indicator.setText("✓")
        elif not self._thinking_dot_timer.isActive():
            self._thinking_dot_index = 0
            self.activity_indicator.setText(self._thinking_dot_frames[0])
            self._thinking_dot_timer.start()
        if not self.activity_panel.isVisible(): self.activity_panel.show()
        if self.activity_effect.opacity()<1.0:
            self.activity_fade.stop(); self.activity_fade.setDuration(260)
            self.activity_fade.setStartValue(self.activity_effect.opacity()); self.activity_fade.setEndValue(1.0); self.activity_fade.start()

    def _finish_activity_fade(self):
        if self.activity_started_at is None and self.activity_effect.opacity() <= 0.01:
            self.activity_panel.hide()

    def _interrupt_current_action(self):
        if self.interrupt_current_action():
            self.chat.show_chat_hint("Останавливаю текущий запрос")

    def _in_gui_thread(self, function):
        """Run a dialog-showing hook on the Qt thread even when a worker asks for it."""
        if threading.current_thread() is threading.main_thread():
            return function()
        outcome = {}
        def job():
            try: outcome["value"] = function()
            except BaseException as error: outcome["error"] = error
        self._gui_invoker.call.emit(job)
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("value")

    def _schedule_conversation_write(self):
        self._conversation_save_timer.start()

    def _cancel_scheduled_conversation_write(self):
        self._conversation_save_timer.stop()

    def _confirm_download(self, url, destination):
        return self._in_gui_thread(lambda: QMessageBox.question(
            self, APP_NAME,
            f"Разрешить скачать этот файл?\n\nАдрес: {url}\nСохранить в: {destination}\n\n"
            "Скачивание начнётся только после подтверждения. Существующий файл не будет перезаписан.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes)

    def _run_approved_download(self, item, screenshot_size, display_size):
        return self._in_gui_thread(lambda: self._download_with_progress(item, screenshot_size, display_size))

    def _download_with_progress(self, item, screenshot_size, display_size):
        cancel_event = threading.Event()
        item["_cancel_event"] = cancel_event
        outcome = {}
        finished = threading.Event()

        def download():
            try:
                outcome["result"] = execute_computer_action(item, screenshot_size, display_size)
            except Exception as error:
                outcome["error"] = error
            finally:
                finished.set()

        dialog = QProgressDialog("Скачиваю файл…", "Отмена", 0, 0, self)
        dialog.setWindowTitle(APP_NAME)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setMinimumDuration(0)
        poll = QTimer(dialog)
        dialog.canceled.connect(cancel_event.set)

        def check_download():
            if dialog.wasCanceled() and not cancel_event.is_set():
                cancel_event.set()
                dialog.setLabelText("Останавливаю скачивание…")
                dialog.setCancelButton(None)
            if finished.is_set():
                dialog.accept()

        poll.timeout.connect(check_download)
        worker = threading.Thread(target=download, daemon=True)
        worker.start()
        poll.start(100)
        dialog.exec()
        if not finished.is_set():
            cancel_event.set()
            dialog.setLabelText("Останавливаю скачивание…")
            dialog.setCancelButton(None)
            dialog.show()
            while not finished.is_set():
                QApplication.processEvents()
                time.sleep(0.05)
            dialog.hide()
        poll.stop()
        worker.join()
        if "error" in outcome:
            if isinstance(outcome["error"], InterruptedError):
                return "Скачивание отменено пользователем."
            raise outcome["error"]
        return outcome.get("result", "Скачивание остановлено.")

    def _set_start(self, text, enabled=True, danger=False):
        self.start_btn.setText(text); self.start_btn.setEnabled(enabled)
        p=MONO
        if danger: self.start_btn.setStyleSheet("font-family:'Segoe UI';background:#101010;color:#ffffff;border:1px solid #ffffff;border-radius:0px;padding:10px 16px;font-weight:700")
        else: self.start_btn.setStyleSheet("")

    def open_huggingface_downloader(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Скачать модель с Hugging Face")
        dialog.setMinimumWidth(560)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        intro = QLabel("Введи название модели: результаты появятся автоматически. Выбери репозиторий — GGUF-файлы загрузятся сами, рекомендуемый вариант будет выбран автоматически.")
        intro.setWordWrap(True)
        intro.setObjectName("mutedSmall")
        layout.addWidget(intro)

        search_row = QHBoxLayout()
        search_box = QLineEdit()
        search_box.setPlaceholderText("Поиск моделей · например Qwen")
        search_row.addWidget(search_box, 1)
        layout.addLayout(search_row)
        models_list = QListWidget()
        models_list.setMaximumHeight(150)
        models_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        layout.addWidget(models_list)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)
        repo_box = QLineEdit()
        repo_box.setPlaceholderText("Выбери результат или введи author/model")
        repo_box.setToolTip("Можно выбрать результат поиска или вставить ID репозитория вручную.")
        form.addRow("Репозиторий", repo_box)
        token_box = QLineEdit()
        token_box.setPlaceholderText("Необязательно · нужен для закрытых моделей")
        token_box.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Токен HF", token_box)
        files_box = CheckComboBox()
        files_box.setMinimumHeight(38)
        files_box.setEnabled(False)
        form.addRow("Файл GGUF", files_box)
        model_name_box = QLineEdit()
        model_name_box.setPlaceholderText("например: qwen3-4b-q4_k_m")
        form.addRow("Имя в Ollama", model_name_box)
        layout.addLayout(form)

        detail = QLabel("Скачивание идёт напрямую с Hugging Face. Файл останется в локальной папке приложения.")
        detail.setWordWrap(True)
        detail.setObjectName("mutedSmall")
        layout.addWidget(detail)

        def populate_model_results(models):
            models_list.clear()
            for model_info in models:
                repo_id = str(model_info.get("id") or model_info.get("modelId") or "")
                if not repo_id:
                    continue
                downloads = model_info.get("downloads")
                likes = model_info.get("likes")
                stats = []
                if isinstance(downloads, int):
                    stats.append(f"↓ {downloads:,}".replace(",", " "))
                if isinstance(likes, int):
                    stats.append(f"★ {likes:,}".replace(",", " "))
                gated = " · 🔒" if model_info.get("gated") else ""
                label = repo_id + ("   ·   " + "   ·   ".join(stats) if stats else "") + gated
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, repo_id)
                item.setToolTip("https://huggingface.co/" + repo_id)
                models_list.addItem(item)
            if models_list.count():
                detail.setText(f"Найдено GGUF-репозиториев: {models_list.count()}. Выбери модель — список файлов загрузится автоматически.")
            else:
                detail.setText("По этому запросу не нашлось GGUF-моделей. Попробуй другое название.")

        search_state = {"generation": 0}

        def search_models():
            search_timer.stop()
            query = search_box.text().strip()
            if len(query) < 2:
                QMessageBox.information(dialog, "Поиск Hugging Face", "Введи хотя бы два символа для поиска.")
                return
            search_state["generation"] += 1
            generation = search_state["generation"]
            models_list.clear()
            detail.setText("Ищу модели на Hugging Face…")
            signals = HuggingFaceSignals(dialog)

            def found(models):
                if generation != search_state["generation"] or query != search_box.text().strip():
                    return
                populate_model_results(models)

            def failed(message):
                if generation != search_state["generation"] or query != search_box.text().strip():
                    return
                detail.setText("Не удалось выполнить поиск.")
                QMessageBox.warning(dialog, "Поиск Hugging Face", message)

            signals.files_found.connect(found)
            signals.failed.connect(failed)
            token = token_box.text().strip()

            def search():
                try:
                    params = urllib.parse.urlencode([
                        ("search", query), ("filter", "gguf"), ("sort", "downloads"),
                        ("direction", "-1"), ("limit", "40"),
                        ("expand[]", "downloads"), ("expand[]", "likes"),
                        ("expand[]", "siblings"),
                    ])
                    request = urllib.request.Request(
                        "https://huggingface.co/api/models?" + params,
                        headers={"User-Agent": "PIVEN-Companion/1.0",
                                 **({"Authorization": f"Bearer {token}"} if token else {})})
                    with urllib.request.urlopen(request, timeout=45) as response:
                        results = json.loads(response.read().decode("utf-8"))
                    if not isinstance(results, list):
                        raise RuntimeError("Hugging Face вернул неожиданный формат результатов.")
                    if not results:
                        fallback_params = urllib.parse.urlencode([
                            ("search", query), ("sort", "downloads"), ("direction", "-1"),
                            ("limit", "100"), ("expand[]", "downloads"),
                            ("expand[]", "likes"), ("expand[]", "siblings"),
                        ])
                        fallback_request = urllib.request.Request(
                            "https://huggingface.co/api/models?" + fallback_params,
                            headers={"User-Agent": "PIVEN-Companion/1.0",
                                     **({"Authorization": f"Bearer {token}"} if token else {})})
                        with urllib.request.urlopen(fallback_request, timeout=45) as response:
                            candidates = json.loads(response.read().decode("utf-8"))
                        results = [model for model in candidates if isinstance(model, dict)
                                   and any(str(file.get("rfilename", file.get("path", ""))).lower().endswith(".gguf")
                                           for file in model.get("siblings", []) if isinstance(file, dict))]
                    signals.files_found.emit(results)
                except urllib.error.HTTPError as error:
                    try:
                        body = error.read().decode("utf-8", errors="replace")[:600]
                    except Exception:
                        body = str(error)
                    signals.failed.emit(f"Hugging Face HTTP {error.code}: {body or error.reason}")
                except Exception as error:
                    signals.failed.emit(str(error))

            threading.Thread(target=search, daemon=True).start()

        search_timer = QTimer(dialog)
        search_timer.setSingleShot(True)
        search_timer.setInterval(450)

        def schedule_model_search(text):
            search_timer.stop()
            search_state["generation"] += 1  # Discard an older response while the user keeps typing.
            normalized = text.strip()
            if len(normalized) < 2:
                models_list.clear()
                detail.setText("Введи минимум два символа для поиска.")
                return
            detail.setText("Поиск начнётся после паузы в наборе…")
            search_timer.start()

        search_timer.timeout.connect(search_models)
        search_box.textChanged.connect(schedule_model_search)

        buttons = QHBoxLayout()
        download_button = self._button("Скачать и добавить в Ollama", "primary")
        download_button.setEnabled(False)
        close_button = self._button("Закрыть", "quiet")
        buttons.addWidget(download_button, 1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        close_button.clicked.connect(dialog.reject)
        search_box.returnPressed.connect(lambda: search_models())

        def model_selected(item):
            files_box.clear()
            files_box.setEnabled(False)
            download_button.setEnabled(False)
            if item is None:
                return
            repo_id = item.data(Qt.ItemDataRole.UserRole)
            if repo_id:
                repo_box.setText(str(repo_id))
                find_gguf_files()

        models_list.currentItemChanged.connect(lambda current, previous: model_selected(current))

        def suggested_model_name():
            record = files_box.currentData()
            if not isinstance(record, dict):
                return ""
            repo_tail = repo_box.text().strip().split("/")[-1]
            stem = Path(record.get("path", "model.gguf")).stem
            raw = f"{repo_tail}-{stem}".lower()
            return re.sub(r"[^a-z0-9._-]+", "-", raw).strip("-._")[:64] or "hf-model"

        def populate_files(records):
            files_box.clear()
            for record in records:
                path = record.get("path", "")
                size = record.get("size") or (record.get("lfs") or {}).get("size")
                size_text = f" · {size / (1024 ** 3):.2f} ГБ" if isinstance(size, (int, float)) and size > 0 else ""
                files_box.addItem(path + size_text, record)
            files_box.setEnabled(bool(records))
            download_button.setEnabled(bool(records))
            if records:
                model_name_box.setText(suggested_model_name())
                detail.setText(f"Найдено GGUF-файлов: {len(records)}. Рекомендуемый файл выбран автоматически; при желании смени квантизацию.")
            else:
                detail.setText("В этом репозитории не найдено файлов GGUF.")

        def find_gguf_files():
            repo_id = repo_box.text().strip().strip("/")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo_id):
                QMessageBox.warning(dialog, "Hugging Face", "Введи ID репозитория в формате автор/модель.")
                return
            detail.setText("Ищу GGUF-файлы в репозитории…")
            signals = HuggingFaceSignals(dialog)

            def found(records):
                populate_files(records)

            def failed(message):
                detail.setText("Не удалось получить список файлов.")
                QMessageBox.warning(dialog, "Hugging Face", message)

            signals.files_found.connect(found)
            signals.failed.connect(failed)
            token = token_box.text().strip()

            def fetch():
                try:
                    encoded_repo = urllib.parse.quote(repo_id, safe="/")
                    # Expanded tree responses are capped at 50 entries by HF;
                    # requesting 1000 alongside expand=true returns HTTP 400.
                    url = f"https://huggingface.co/api/models/{encoded_repo}/tree/main?recursive=true&limit=1000"
                    headers = {"User-Agent": "PIVEN-Companion/1.0"}
                    if token:
                        headers["Authorization"] = f"Bearer {token}"
                    request = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(request, timeout=40) as response:
                        records = json.loads(response.read().decode("utf-8"))
                    if not isinstance(records, list):
                        raise RuntimeError("Hugging Face вернул неожиданный список файлов.")
                    ggufs = [item for item in records if isinstance(item, dict)
                             and item.get("type") == "file"
                             and str(item.get("path", "")).lower().endswith(".gguf")]
                    ggufs.sort(key=lambda item: (
                        0 if "q4_k_m" in item.get("path", "").lower() else 1,
                        str(item.get("path", "")).lower()))
                    signals.files_found.emit(ggufs)
                except urllib.error.HTTPError as error:
                    try:
                        body = error.read().decode("utf-8", errors="replace")[:600]
                    except Exception:
                        body = str(error)
                    signals.failed.emit(f"Hugging Face HTTP {error.code}: {body or error.reason}")
                except Exception as error:
                    signals.failed.emit(str(error))

            threading.Thread(target=fetch, daemon=True).start()

        def start_download():
            repo_id = repo_box.text().strip().strip("/")
            record = files_box.currentData()
            model_tag = model_name_box.text().strip().lower()
            if not isinstance(record, dict):
                QMessageBox.warning(dialog, "Hugging Face", "Сначала выбери файл GGUF.")
                return
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", model_tag):
                QMessageBox.warning(dialog, "Имя модели", "Используй латинские буквы, цифры, точку, дефис или подчёркивание.")
                return
            if self.running or self.busy:
                QMessageBox.warning(dialog, APP_NAME, "Сначала останови текущую задачу.")
                return

            relative_parts = str(record.get("path", "")).replace("\\", "/").split("/")
            if not relative_parts or any(part in ("", ".", "..") for part in relative_parts):
                QMessageBox.warning(dialog, "Hugging Face", "Путь к файлу из репозитория некорректен.")
                return

            token = token_box.text().strip()
            destination_root = DATA_DIR / "huggingface_models" / repo_id.replace("/", "--")
            destination = destination_root.joinpath(*relative_parts)
            progress = QProgressDialog("Подключаюсь к Hugging Face…", "Отмена", 0, 100, dialog)
            progress.setWindowTitle("Загрузка модели")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)
            progress.setAutoClose(False)
            progress.setAutoReset(False)
            cancel_event = threading.Event()
            progress.canceled.connect(cancel_event.set)
            signals = HuggingFaceSignals(self)

            def update_progress(value, message):
                progress.setLabelText(message)
                progress.setValue(max(0, min(100, value)))
                if value >= 70:
                    progress.setCancelButton(None)

            def completed(local_path, final_tag):
                progress.close()
                download_button.setEnabled(True)
                self.model_box.setEditText(final_tag)
                self.refresh_models()
                QMessageBox.information(dialog, "Модель готова",
                    f"Модель добавлена в Ollama: {final_tag}\n\nФайл: {local_path}")

            def download_failed(message):
                progress.close()
                download_button.setEnabled(True)
                QMessageBox.critical(dialog, "Не удалось скачать модель", message)

            signals.progress.connect(update_progress)
            signals.finished.connect(completed)
            signals.failed.connect(download_failed)

            def transfer_and_import():
                partial = destination.with_name(destination.name + ".download")
                try:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    expected = record.get("size") or (record.get("lfs") or {}).get("size")
                    if not (destination.is_file() and isinstance(expected, (int, float))
                            and destination.stat().st_size == expected):
                        file_path = "/".join(urllib.parse.quote(part, safe="") for part in relative_parts)
                        url = f"https://huggingface.co/{urllib.parse.quote(repo_id, safe='/')}/resolve/main/{file_path}?download=true"
                        headers = {"User-Agent": "PIVEN-Companion/1.0"}
                        if token:
                            headers["Authorization"] = f"Bearer {token}"
                        request = urllib.request.Request(url, headers=headers)
                        with urllib.request.urlopen(request, timeout=60) as response:
                            total_header = response.headers.get("Content-Length")
                            total = int(total_header) if total_header and total_header.isdigit() else int(expected or 0)
                            received = 0
                            with partial.open("wb") as output:
                                while True:
                                    if cancel_event.is_set():
                                        raise InterruptedError("Загрузка отменена.")
                                    chunk = response.read(8 * 1024 * 1024)
                                    if not chunk:
                                        break
                                    output.write(chunk)
                                    received += len(chunk)
                                    percent = int(received * 68 / total) if total else 5
                                    size_text = f"{received / (1024 ** 3):.2f} ГБ"
                                    if total:
                                        size_text += f" / {total / (1024 ** 3):.2f} ГБ"
                                    signals.progress.emit(percent, f"Скачиваю с Hugging Face · {size_text}")
                        if isinstance(expected, (int, float)) and expected > 0 and received != expected:
                            raise RuntimeError(f"Размер скачанного файла не совпадает с Hugging Face: {received} из {int(expected)} байт.")
                        os.replace(partial, destination)
                    # llama.cpp loads the GGUF straight from this folder; there is no import step.
                    signals.progress.emit(100, "Модель готова")
                    signals.finished.emit(str(destination), destination.stem)
                except Exception as error:
                    try:
                        partial.unlink(missing_ok=True)
                    except Exception:
                        pass
                    signals.failed.emit(str(error))

            download_button.setEnabled(False)
            dialog._hf_download_thread = threading.Thread(target=transfer_and_import, daemon=True)
            dialog._hf_download_thread.start()
            progress.exec()

        repo_box.editingFinished.connect(lambda: find_gguf_files()
            if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo_box.text().strip()) else None)
        download_button.clicked.connect(start_download)
        dialog.exec()

    def refresh_models(self):
        if not self._integration_enabled("ollama"):
            self.events.put(("status", "Локальная модель выключена"))
            return
        self.events.put(("activity", "Обновляет список моделей"))
        def work():
            try:
                self.events.put(("models", list_models()))
                problem = backend_problem()
                if problem: self.events.put(("status", problem))
            except Exception as e: self.events.put(("status", f"Не удалось прочитать папку моделей: {e}")); log(f"model list error: {e}")
        threading.Thread(target=work,daemon=True).start()

    def _update_model_label(self,*args):
        model = self.model_box.currentText().strip()
        if model != self.settings.get("model", ""):
            self.settings["model"] = model
            self._save_settings()
        if hasattr(self,"chat_model_label"):
            self.chat_model_label.setText(model or "Выберите модель Ollama")
        if hasattr(self, "thinking_box"):
            self._populate_thinking_selector(model)

    @staticmethod
    def _thinking_value_label(value):
        if value is False: return "Выключено"
        if value is True: return "Включено"
        names = {"low": "Низкая", "medium": "Средняя", "high": "Высокая",
                 "max": "Максимальная", "xhigh": "Очень высокая", "minimal": "Минимальная"}
        return f"{names.get(value, str(value))} · {value}"

    def _populate_thinking_selector(self, model):
        box = self.thinking_box
        box.blockSignals(True)
        box.clear()
        if not model:
            box.addItem("Выбери модель", "__auto__")
            box.setEnabled(False)
            box.blockSignals(False)
            return

        cached = self.settings.get("thinking_capabilities", {}).get(model)
        if cached is None:
            box.addItem("Загружаю уровни…", "__auto__")
            box.setEnabled(False)
            box.blockSignals(False)
            if model not in self._thinking_lookup_inflight:
                self._thinking_lookup_inflight.add(model)
                def lookup():
                    try:
                        values, default = model_thinking(model)
                        result = (model, values, default, "")
                    except Exception as error:
                        result = (model, None, None, str(error))
                    self.events.put(("thinking_capabilities", result))
                threading.Thread(target=lookup, daemon=True).start()
            return

        values = cached.get("values", [])
        default = cached.get("default")
        default_note = f" · {self._thinking_value_label(default)}" if default is not None else ""
        box.addItem(f"Авто{default_note}", "__auto__")
        supported_values = values if values != [False] else []
        for value in supported_values:
            box.addItem(self._thinking_value_label(value), value)
        saved_level = self.settings.get("thinking_levels", {}).get(model, "__auto__")
        if saved_level != "__auto__" and saved_level not in supported_values:
            saved_level = "__auto__"
            self.settings.setdefault("thinking_levels", {})[model] = saved_level
            OLLAMA_THINK_LEVELS[model] = saved_level
            self._save_settings()
        index = box.findData(saved_level)
        box.setCurrentIndex(index if index >= 0 else 0)
        box.setEnabled(bool(supported_values))
        box.setToolTip(f"Уровни этой модели загружены из Ollama и сохранены. Модель: {model}")
        box.blockSignals(False)

    def _on_thinking_level_changed(self, index):
        model = self.model_box.currentText().strip()
        if not model or index < 0:
            return
        value = self.thinking_box.currentData()
        value = "__auto__" if value is None else value
        self.settings.setdefault("thinking_levels", {})[model] = value
        OLLAMA_THINK_LEVELS[model] = value
        self._save_settings()

    def _drain_events(self):
        if self._loading_chat:
            return
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=="models":
                    self._ollama_models_loaded = True
                    current=self.model_box.currentText().strip() or self.settings.get("model", "")
                    available_models = set(value)
                    stale_models = (set(self.settings.get("thinking_capabilities", {}))
                                    | set(self.settings.get("thinking_levels", {}))) - available_models
                    for stale_model in stale_models:
                        self.settings.get("thinking_capabilities", {}).pop(stale_model, None)
                        self.settings.get("thinking_levels", {}).pop(stale_model, None)
                        OLLAMA_THINK_LEVELS.pop(stale_model, None)
                    if stale_models:
                        self._save_settings()
                    self.model_box.blockSignals(True); self.model_box.clear(); self.model_box.addItems(value)
                    if current in available_models: self.model_box.setCurrentText(current)
                    elif value: self.model_box.setCurrentText(value[0])
                    else: self.model_box.setCurrentText("")
                    self.model_box.blockSignals(False)
                    self._update_model_label()
                    if value:
                        self._set_status(f"Ollama подключена · моделей: {len(value)}")
                    self._set_activity("Слушает" if self.running else "Готов к работе")
                elif kind=="thinking_capabilities":
                    model, values, default, error = value
                    self._thinking_lookup_inflight.discard(model)
                    if error:
                        log(f"thinking capability lookup failed for {model}: {error}")
                        if self.model_box.currentText().strip() == model:
                            self.thinking_box.blockSignals(True)
                            self.thinking_box.clear(); self.thinking_box.addItem("Авто · недоступно", "__auto__")
                            self.thinking_box.setEnabled(False)
                            self.thinking_box.setToolTip(f"Не удалось получить уровни модели {model}: {error}")
                            self.thinking_box.blockSignals(False)
                    elif not self._ollama_models_loaded or self.model_box.findText(model) >= 0:
                        self.settings.setdefault("thinking_capabilities", {})[model] = {
                            "values": values, "default": default,
                        }
                        self._save_settings()
                        if self.model_box.currentText().strip() == model:
                            self._populate_thinking_selector(model)
                elif kind=="status":
                    self._set_status(value)
                    status_text=str(value).lower()
                    if any(word in status_text for word in ("недоступна", "ошибка", "устанавливаю аудиокомпонент", "аудиокомпонент установлен", "cuda подключён")):
                        self._set_activity(value if "ошибка" not in status_text and "недоступна" not in status_text else "Ошибка подключения Ollama")
                elif kind=="reasoning_clear":
                    self.reasoning_chat_row=None; self.reasoning_chat_body=None
                elif kind=="reasoning": self._append_reasoning(value)
                elif kind=="reasoning_remove": self._remove_reasoning_animated()
                elif kind=="activity": self._set_activity(value)
                elif kind=="generation_started": self._show_generation_card(value)
                elif kind=="generation_progress":
                    if self._generation_card_row is not None:
                        detail = next((label for label in self._generation_card_row.findChildren(QLabel)
                                       if label.property("generationDetail")), None)
                        if detail is not None and value:
                            detail.setText(str(value))
                elif kind=="message":
                    role,content,voice=value
                    if role=="assistant": self._set_activity("Ответ получен")
                    self._append(role,content)
                    if role=="assistant": self._remove_reasoning_animated()
                    if voice: threading.Thread(target=self._speak,args=(content,),daemon=True).start()
                elif kind=="computer_action":
                    action, screenshot_size, display_size = value[:3]
                    request_text = str(value[3]) if len(value) > 3 else ""
                    try:
                        result = self._execute_computer_actions(action, screenshot_size, display_size, request_text)
                        self._set_activity("Действие на компьютере выполнено")
                    except Exception as error:
                        result = f"Не удалось выполнить действие на компьютере: {error}"
                        self._set_activity("Ошибка действия на компьютере")
                        log(f"computer skill action error: {error}")
                    self._append("system", result)
                    self.messages.append({"role": "assistant", "content": result})
                    self._save_conversation()
                elif kind=="generated_image":
                    try:
                        image_path = Path(value)
                        if not image_path.is_file():
                            raise FileNotFoundError(f"Не найден сохранённый файл: {image_path}")
                        self._finish_generation_card()
                        self._append("assistant", "Изображение создано через ComfyUI.", [str(image_path)])
                        self._set_activity("Изображение готово")
                        if not self._canvas_follow_latest:
                            self.chat.show_chat_hint("Изображение создано · результат добавлен в поле")
                    except Exception as error:
                        log(f"Generated image display error: {error}")
                        self._finish_generation_card()
                        self._set_activity("Изображение готово, файл сохранён")
                        try:
                            self._append("system", f"Изображение создано, но превью не удалось добавить. Файл: {value}")
                        except Exception as fallback_error:
                            log(f"Generated image fallback message error: {fallback_error}")
                elif kind=="presentation_created":
                    path = Path(value)
                    self._append("assistant", f"Презентация готова · {path.name}", [str(path)])
                    self._set_activity("Презентация создана")
                elif kind=="error": self._finish_generation_card(); self._set_activity("Ошибка"); self._append("system",value); self._remove_reasoning_animated()
                elif kind=="action_interrupted": self._finish_generation_card(); self._set_activity("Запрос прерван"); self._remove_reasoning_animated()
                elif kind=="request_done":
                    self._save_conversation()
                    self.busy=False
                    self._update_composer_hint()
                    if self.pending_text_prompts:
                        text,model,images,image_paths=self.pending_text_prompts.pop(0)
                        self.busy=True; self.selected_model=model
                        self._append("user",text,image_paths)
                        self.events.put(("activity","Думает · отвечает на сообщение из очереди"))
                        threading.Thread(target=self.ask_model,args=(text,images or None,self.speech_enabled),daemon=True).start()
                elif kind=="asr": self.handle_transcript(value, self.model_box.currentText().strip())
                elif kind=="stopped": self.running=False; self._set_start("Старт")
                elif kind=="capture_failed": self._reset_running()
        except queue.Empty: pass

    def toggle(self):
        if self.running:
            self.stop_event.set(); self._set_start("Останавливаю…",False); self._set_status("Останавливаю захват…"); self.events.put(("activity","Останавливается")); return
        if not self._integration_enabled("ollama"):
            QMessageBox.information(self, APP_NAME, "Интеграция Ollama выключена. Включи её в Настройки → Интеграции.")
            return
        if self.capture_thread and self.capture_thread.is_alive(): self._set_status("Завершается предыдущий аудиоблок…"); return
        model=self.model_box.currentText().strip()
        if not model: QMessageBox.warning(self,APP_NAME,"Сначала выберите модель Ollama."); return
        enabled=lambda key:self.vars[key].isChecked()
        if not any(enabled(x) for x in ("mic","loopback","screen")): QMessageBox.warning(self,APP_NAME,"Включите микрофон, звук компьютера или наблюдение за экраном."); return
        if enabled("mic") or enabled("loopback"):
            try: import soundcard
            except Exception:
                if QMessageBox.question(self,APP_NAME,"Для захвата микрофона и звука компьютера не хватает soundcard. Установить его сейчас в фоне?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes: threading.Thread(target=self.install_audio,daemon=True).start()
                return
        problem = backend_problem()
        if problem: QMessageBox.critical(self,APP_NAME,problem); return
        self.stop_event.clear(); self.running=True; self.selected_model=model
        self.capture_options=(enabled("mic"),enabled("loopback"),enabled("screen"),enabled("proactive"))
        self._set_start("Пауза",danger=True); self._set_status("Активен · речь и звук ПК, экран в паузах")
        self.events.put(("activity","Запускается")); self._append("system","Компаньон включён. Скажите что-нибудь или продолжайте заниматься своими делами.")
        self.capture_thread=threading.Thread(target=self.capture_loop,daemon=True); self.capture_thread.start()

    def dragEnterEvent(self, event):
        if image_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()
            self.chat.show_chat_hint("Отпусти, чтобы прикрепить изображение")

    def dropEvent(self, event):
        paths = image_paths_from_mime(event.mimeData())
        if paths:
            event.acceptProposedAction()
            self._add_pending_images(paths)

    def _update_composer_hint(self, *_):
        hint = getattr(self, "composer_hint", None)
        if hint is None:
            return
        theme = self._canvas_theme_data()
        accent, muted = theme["accent"], theme["role"]
        text = self.input.text().strip()
        images = len(self.pending_images)
        if not text and not images:
            hint.setText(f"<span style='color:{muted}'>Enter — отправить · ↑ — прошлый запрос · "
                         "Ctrl+V или перетаскивание — картинка · Esc — стоп · Ctrl+K — поиск по чатам</span>")
            return
        route = self._detect_composer_route(text, has_images=bool(images))
        labels = {
            "presentation": "Презентация PowerPoint",
            "image": "Генерация изображения · ComfyUI",
            "video": "Видео пока не поддерживается",
            "audio": "Аудио пока не поддерживается",
        }
        if route == "code":
            folder = Path(self.settings.get("project_root", str(APP_DIR))).name or "проект"
            label = f"Агент кода · папка «{folder}»"
        elif route == "chat" and images:
            label = f"Вопрос по изображениям ({images})" if images > 1 else "Вопрос по изображению"
        elif route == "chat" and self._is_computer_request(text):
            label = "Управление компьютером"
        else:
            label = labels.get(route, "Разговор с моделью")
        notes = []
        integration = "comfyui" if route == "image" else "ollama"
        if not self._integration_enabled(integration):
            notes.append(f"{'ComfyUI' if integration == 'comfyui' else 'Ollama'} выключена в настройках")
        elif route != "image" and not self.model_box.currentText().strip():
            notes.append("сначала выбери модель")
        elif self.busy:
            notes.append("в очередь — сейчас идёт другой запрос" if route == "chat" else "дождись конца текущего действия")
        suffix = f"<span style='color:{muted}'> · {' · '.join(notes)}</span>" if notes else ""
        hint.setText(f"<span style='color:{muted}'>Режим: </span><b style='color:{accent}'>{label}</b>{suffix}")

    def attach_images(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Выберите изображения", "", "Изображения (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff)")
        self._add_pending_images(paths)

    def _add_pending_images(self, paths):
        if not paths: return
        for path in paths:
            if path not in self.pending_images: self.pending_images.append(path)
        self.attach_preview.setText("Прикреплено: " + ", ".join(Path(path).name for path in self.pending_images))
        if not self.attach_preview_frame.isVisible():
            self.attach_preview_frame.show(); fade_in_widget(self.attach_preview_frame,240,start=0.0)
        else:
            effect=getattr(self.attach_preview_frame,"_ui_opacity_effect",None)
            if effect is not None and effect.opacity()<0.99: fade_in_widget(self.attach_preview_frame,220,start=effect.opacity(),end=1.0)
        self.attach_btn.setToolTip(f"Прикреплено изображений: {len(self.pending_images)} · нажмите, чтобы добавить ещё")
        self._set_activity(f"Прикреплено изображений: {len(self.pending_images)}")
        self._update_composer_hint()
        self.input.setFocus(Qt.FocusReason.OtherFocusReason)

    def _clear_pending_images(self, announce=False):
        had_images=bool(self.pending_images)
        self.pending_images.clear()
        self.attach_preview.clear()
        if self.attach_preview_frame.isVisible():
            effect=getattr(self.attach_preview_frame,"_ui_opacity_effect",None); start=effect.opacity() if effect else 1.0
            animation=fade_in_widget(self.attach_preview_frame,190,start=start,end=0.0)
            animation.finished.connect(lambda: self.attach_preview_frame.hide() if not self.pending_images else None)
        self.attach_btn.setToolTip("Прикрепить изображения")
        if had_images and announce: self._set_activity("Вложения удалены")
        self._update_composer_hint()

    def send_text(self):
        text=self.input.text().strip()
        image_paths=list(self.pending_images)
        if not text and not image_paths:return
        self.input.remember(text)
        route = self._detect_composer_route(text, has_images=bool(image_paths))
        if route == "image" and not self._integration_enabled("comfyui"):
            QMessageBox.information(self, APP_NAME, "Интеграция ComfyUI выключена. Включи её в Настройки → Интеграции.")
            return
        if route != "image" and not self._integration_enabled("ollama"):
            QMessageBox.information(self, APP_NAME, "Интеграция Ollama выключена. Включи её в Настройки → Интеграции.")
            return
        if route == "presentation":
            if self.busy:
                QMessageBox.information(self, APP_NAME, "Дождитесь завершения текущего действия, затем создайте презентацию.")
                return
            model = self.model_box.currentText().strip()
            if not model:
                QMessageBox.warning(self, APP_NAME, "Сначала выберите модель Ollama.")
                return
            self.input.clear()
            self._append("user", text)
            self.action_cancel.clear()
            self._active_ollama_response = None
            self.busy = True
            self.selected_model = model
            self.events.put(("activity", "Собирает презентацию · готовит содержание"))
            threading.Thread(target=self._run_presentation_agent, args=(text, model), daemon=True).start()
            return
        if route == "code":
            if self.busy:
                QMessageBox.information(self, APP_NAME, "Дождитесь завершения текущего действия перед запуском агента кода.")
                return
            model = self.model_box.currentText().strip()
            if not model:
                QMessageBox.warning(self, APP_NAME, "Сначала выберите модель Ollama.")
                return
            project_root = Path(self.settings.get("project_root", str(APP_DIR))).expanduser()
            if not project_root.is_dir():
                QMessageBox.warning(self, APP_NAME, "Рабочая папка проекта не найдена. Выберите её в Настройки → Код.")
                return
            self.input.clear()
            self._append("user", text)
            self.action_cancel.clear()
            self._active_ollama_response = None
            self.busy = True
            self.selected_model = model
            self.events.put(("activity", "Распознал задачу по проекту · агент изучает файлы"))
            threading.Thread(target=self._run_coding_agent, args=(text, model, str(project_root)), daemon=True).start()
            return
        if route in ("image", "video", "audio"):
            if self.busy:
                QMessageBox.information(self, APP_NAME, "Дождитесь завершения текущего действия, затем отправьте запрос на генерацию."); return
            if route != "image":
                QMessageBox.information(self, APP_NAME, "Сейчас через ComfyUI подключена генерация изображений. Для видео и аудио нужен отдельный workflow.")
                return
            workflow_path = Path(self.settings.get("comfy_workflow", str(COMFY_DEFAULT_WORKFLOW))).expanduser()
            if not workflow_path.is_file():
                QMessageBox.warning(self, APP_NAME, "Не найден workflow ComfyUI. Укажи JSON-файл в Настройки → Интеграции → ComfyUI."); return
            self.input.clear()
            self._append("user",text)
            self.events.put(("activity", "Распознал запрос на изображение · запускает ComfyUI"))
            self._start_image_generation(text)
            return
        model=self.model_box.currentText().strip()
        if not model:QMessageBox.warning(self,APP_NAME,"Сначала выберите модель Ollama."); return
        if not text:
            text = "Посмотри на эти изображения и коротко расскажи, что на них." if len(image_paths) > 1 else "Посмотри на это изображение и коротко расскажи, что на нём."
        try:
            image_data=[encode_chat_image(path) for path in image_paths]
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Не удалось подготовить изображение: {e}"); return
        self.input.clear()
        if self.busy:
            self.pending_text_prompts.append((text,model,image_data,image_paths))
            self._clear_pending_images()
            self.events.put(("activity","Сообщение добавлено в очередь"))
            return
        self._append("user",text,image_paths)
        self._clear_pending_images()
        self.action_cancel.clear()
        self._active_ollama_response = None
        self.busy=True; self.selected_model=model; self.events.put(("activity","Думает"))
        threading.Thread(target=self.ask_model,args=(text,image_data or None,self.speech_enabled),daemon=True).start()

    def _reset_running(self):
        self.running=False; self._set_start("Старт"); self._set_status("Захват остановлен")

    def closeEvent(self,event):
        self.shutdown()
        event.accept()


def main():
    app=QApplication(sys.argv); app.setApplicationName(APP_NAME); app.setFont(QFont("Segoe UI",10))
    if not acquire_instance_lock():
        QMessageBox.information(None, APP_NAME, "Компаньон уже открыт (обычное или веб-окно). Закрой его, чтобы не перезаписать чаты.")
        return
    window=CompanionApp(); window.show(); sys.exit(app.exec())


if __name__=="__main__":main()
