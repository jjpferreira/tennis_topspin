#!/usr/bin/env python3
"""
Tennis Shot Simulator + BLE Live Monitor (KY-003)

On launch, auto-discovery scans for the real BLE sensor (name TENNIS_KY003*
or advertised tennis service UUID). Simulation stays active until a device
connects. CONNECT SENSOR retries discovery manually.
"""

from __future__ import annotations

import asyncio
import csv
import json
import math
import random
import struct
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF, QRadialGradient
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# BLE UUIDs (must match firmware)
TENNIS_SERVICE_UUID = "7f4af201-1fb5-459e-8fcc-c5c9c331914b"  # advertised; ble_constants.h
SENSOR_STATE_UUID = "7be5483e-36e1-4688-b7f5-ea07361b26a1"
HIT_COUNT_UUID = "7be5483e-36e1-4688-b7f5-ea07361b26a2"
RATE_X10_UUID = "7be5483e-36e1-4688-b7f5-ea07361b26a3"
COMMAND_UUID = "7be5483e-36e1-4688-b7f5-ea07361b26a4"
IMPACT_UUID = "7be5483e-36e1-4688-b7f5-ea07361b26a5"
NAME_PREFIX = "TENNIS_KY003"
BLE_DISCOVER_TIMEOUT_S = 5.0
AUTO_DISCOVER_ON_START = True
STREAM_ARM_COMMAND = "STREAM:ON"
STREAM_DISARM_COMMAND = "STREAM:OFF"
STREAM_KEEPALIVE_COMMAND = "PING"
STREAM_KEEPALIVE_INTERVAL_S = 1.2
PING_HEALTH_TIMEOUT_S = 2.5
PING_ACK_SUBSTRING = "PONG"
LIVE_STREAM_STALE_TIMEOUT_S = 3.5
LIVE_STREAM_RECOVERY_COOLDOWN_S = 4.0
PROFILE_STORE_FILE = "student_profiles.json"
MAX_SESSIONS_PER_STUDENT = 40
CAL_GET_COMMAND = "CAL:GET"
CAL_SAVE_COMMAND = "CAL:SAVE"
CAL_RESET_COMMAND = "CAL:RESET"
COMPETITION_CONFIG_FILE = "competition_profiles.json"

# Competition levels from beginner to pro
DEFAULT_COMPETITION_PROFILES: dict[str, dict[str, float]] = {
    "Newbie": {
        "target_speed": 40.0,
        "target_spin": 900.0,
        "target_consistency": 48.0,
        "target_fast_pct": 12.0,
        "target_impact": 32.0,
        "sim_speed_min": 24.0,
        "sim_speed_max": 56.0,
        "sim_spin_min": 350.0,
        "sim_spin_max": 1400.0,
        "sim_land_sigma_x": 1.65,
        "sim_land_sigma_y": 2.0,
        "sim_land_center_y": 6.8,
        "sim_red_min": 14.0,
        "sim_red_max": 46.0,
        "sim_impact_abs": 58.0,
        "live_speed_min": 24.0,
        "live_speed_max": 68.0,
        "live_speed_base": 22.0,
        "live_rate_mul": 3.1,
        "live_red_mul": 0.08,
        "live_spin_min": 400.0,
        "live_spin_max": 1800.0,
        "live_spin_base": 450.0,
        "live_spin_rate_mul": 88.0,
        "live_spin_impact_mul": 8.0,
        "live_arm_abs": 45.0,
    },
    "Competitive": {
        "target_speed": 59.0,
        "target_spin": 1850.0,
        "target_consistency": 67.0,
        "target_fast_pct": 36.0,
        "target_impact": 52.0,
        "sim_speed_min": 44.0,
        "sim_speed_max": 78.0,
        "sim_spin_min": 900.0,
        "sim_spin_max": 2600.0,
        "sim_land_sigma_x": 1.25,
        "sim_land_sigma_y": 1.55,
        "sim_land_center_y": 7.2,
        "sim_red_min": 34.0,
        "sim_red_max": 72.0,
        "sim_impact_abs": 44.0,
        "live_speed_min": 38.0,
        "live_speed_max": 86.0,
        "live_speed_base": 33.0,
        "live_rate_mul": 3.9,
        "live_red_mul": 0.12,
        "live_spin_min": 850.0,
        "live_spin_max": 3000.0,
        "live_spin_base": 850.0,
        "live_spin_rate_mul": 112.0,
        "live_spin_impact_mul": 10.0,
        "live_arm_abs": 41.0,
    },
    "Professional": {
        "target_speed": 74.0,
        "target_spin": 2450.0,
        "target_consistency": 82.0,
        "target_fast_pct": 62.0,
        "target_impact": 68.0,
        "sim_speed_min": 58.0,
        "sim_speed_max": 88.0,
        "sim_spin_min": 1650.0,
        "sim_spin_max": 3250.0,
        "sim_land_sigma_x": 0.95,
        "sim_land_sigma_y": 1.2,
        "sim_land_center_y": 7.8,
        "sim_red_min": 52.0,
        "sim_red_max": 86.0,
        "sim_impact_abs": 32.0,
        "live_speed_min": 46.0,
        "live_speed_max": 96.0,
        "live_speed_base": 44.0,
        "live_rate_mul": 4.7,
        "live_red_mul": 0.16,
        "live_spin_min": 1200.0,
        "live_spin_max": 3600.0,
        "live_spin_base": 1320.0,
        "live_spin_rate_mul": 138.0,
        "live_spin_impact_mul": 12.0,
        "live_arm_abs": 38.0,
    },
}
DEFAULT_COMPETITION_LEVEL = "Competitive"


def _norm_uuid(u: str) -> str:
    return u.replace("-", "").lower()


def _adv_has_tennis_service(adv: AdvertisementData | None) -> bool:
    if not adv or not adv.service_uuids:
        return False
    want = _norm_uuid(TENNIS_SERVICE_UUID)
    return any(_norm_uuid(x) == want for x in adv.service_uuids)


def _device_local_name(device: BLEDevice, adv: AdvertisementData | None) -> str | None:
    if device.name:
        return device.name
    if adv and adv.local_name:
        return adv.local_name
    return None


def _tennis_device_rank(device: BLEDevice, adv: AdvertisementData | None) -> int:
    """Prefer firmware-like advertisers (service UUID) over name-only matches."""
    nm = _device_local_name(device, adv)
    name_ok = bool(nm and nm.startswith(NAME_PREFIX))
    svc_ok = _adv_has_tennis_service(adv)
    rssi = adv.rssi if adv is not None else -999
    if name_ok and svc_ok:
        return 400 + rssi
    if svc_ok:
        return 300 + rssi
    if name_ok:
        return 200 + rssi
    return 0


def _best_tennis_from_adv_map(adv_map: dict[str, tuple[BLEDevice, AdvertisementData]]) -> BLEDevice | None:
    best = None
    best_rank = -10_000
    for _addr, pair in adv_map.items():
        d, adv = pair
        r = _tennis_device_rank(d, adv)
        if r > best_rank:
            best_rank = r
            best = d
    return best


def shot_color(speed: float) -> QColor:
    if speed > 70:
        return QColor("#ff4747")
    if speed >= 50:
        return QColor("#ffd43a")
    if speed >= 30:
        return QColor("#2ed36d")
    return QColor("#4aa3ff")


@dataclass
class Telemetry:
    state: int = 0
    count: int = 0
    rate_x10: int = 0
    ts: float = 0.0


@dataclass
class Shot:
    idx: int
    timestamp: str
    speed: float
    arm_angle: float
    spin: int
    landing_x: float
    landing_y: float
    impact_x: int = 0
    impact_y: int = 0
    impact_redness: int = 0


@dataclass
class SessionSummary:
    student: str
    started_at: str
    shot_count: int
    avg_speed: float
    avg_spin: float
    consistency: int
    fast_pct: float
    avg_impact_redness: float


class MetricSlider(QWidget):
    def __init__(self, label: str, min_v: float, max_v: float, unit: str = ""):
        super().__init__()
        self.label = label
        self.min_v = min_v
        self.max_v = max_v
        self.unit = unit
        self.value = min_v
        self.color = QColor("#8ee76a")
        self.setMinimumHeight(48)

    def set_value(self, value: float, color_hex: str):
        self.value = max(self.min_v, min(self.max_v, value))
        self.color = QColor(color_hex)
        self.update()

    def paintEvent(self, event):  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        p.setPen(QColor("#b8cbe0"))
        p.drawText(0, 14, self.label)

        p.setPen(QColor("#e8f0fd"))
        p.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        p.drawText(rect.width() - 120, 18, f"{self.value:.1f}")
        p.setFont(QFont("Arial", 9))
        p.setPen(QColor("#8ca3bc"))
        p.drawText(rect.width() - 35, 18, self.unit)

        y = 30
        x0, x1 = 2, rect.width() - 4
        p.setPen(QPen(QColor("#2f4c6a"), 3))
        p.drawLine(x0, y, x1, y)

        ratio = (self.value - self.min_v) / max(self.max_v - self.min_v, 1e-6)
        xk = x0 + ratio * (x1 - x0)
        p.setPen(QPen(self.color, 3))
        p.drawLine(x0, y, int(xk), y)
        p.setBrush(self.color)
        p.setPen(QPen(QColor("#d6e5f9"), 1))
        p.drawEllipse(QPointF(xk, y), 5.5, 5.5)

        p.setPen(QColor("#5f7793"))
        p.setFont(QFont("Arial", 8))
        p.drawText(0, 44, f"{self.min_v:g}")
        p.drawText(rect.width() - 28, 44, f"{self.max_v:g}")


class DonutWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(118)
        self.dist = {"slow": 0.0, "med": 0.0, "fast": 0.0}

    def set_distribution(self, slow: float, med: float, fast: float):
        self.dist = {"slow": slow, "med": med, "fast": fast}
        self.update()

    def paintEvent(self, event):  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height()
        rect = QRectF(10, 10, h - 20, h - 20)
        p.setPen(QPen(QColor("#1f3550"), 12))
        p.drawArc(rect, 0, 360 * 16)

        parts = [
            (self.dist["slow"], QColor("#4aa3ff")),
            (self.dist["med"], QColor("#ffd43a")),
            (self.dist["fast"], QColor("#ff4747")),
        ]
        start = 90 * 16
        for frac, color in parts:
            span = -int(max(frac, 0.0) * 360 * 16)
            p.setPen(QPen(color, 12))
            p.drawArc(rect, start, span)
            start += span


class CourtWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.shots: list[Shot] = []
        self.setMinimumHeight(438)

    def set_shots(self, shots: list[Shot]):
        self.shots = shots[-45:]  # keep cleaner like target
        self.update()

    def paintEvent(self, event):  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Stadium background
        bg = QLinearGradient(0, 0, 0, self.height())
        bg.setColorAt(0.0, QColor("#07172d"))
        bg.setColorAt(0.45, QColor("#0a1e37"))
        bg.setColorAt(1.0, QColor("#0b233f"))
        p.fillRect(self.rect(), bg)

        margin = 20
        court = QRectF(margin, margin + 14, self.width() - margin * 2, self.height() - margin * 2 - 22)
        fl, fr, bl, br = self._court_corners(court)

        # Grass strip around court
        grass = QPolygonF([
            QPointF(fl.x() - 42, fl.y() + 10),
            QPointF(fr.x() + 42, fr.y() + 10),
            QPointF(br.x() + 58, br.y() + 32),
            QPointF(bl.x() - 58, bl.y() + 32),
        ])
        gg = QLinearGradient(court.left(), court.bottom(), court.left(), court.bottom() + 40)
        gg.setColorAt(0.0, QColor("#274f26"))
        gg.setColorAt(1.0, QColor("#3b7b2f"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(gg)
        p.drawPolygon(grass)

        # Court surface
        surf = QPolygonF([fl, fr, br, bl])
        cg = QLinearGradient(court.left(), court.bottom(), court.right(), court.top())
        cg.setColorAt(0.0, QColor("#234773"))
        cg.setColorAt(1.0, QColor("#2d5f9b"))
        p.setBrush(cg)
        p.setPen(QPen(QColor("#d8e4f5"), 2))
        p.drawPolygon(surf)

        # Court lines (full-court proportions)
        p.setPen(QPen(QColor("#e5edf8"), 2))
        net_l = self._map_norm(court, -1.0, 0.5)
        net_r = self._map_norm(court, 1.0, 0.5)
        p.drawLine(net_l, net_r)
        # singles sidelines within doubles
        p.drawLine(self._map_norm(court, -0.75, 0.0), self._map_norm(court, -0.75, 1.0))
        p.drawLine(self._map_norm(court, 0.75, 0.0), self._map_norm(court, 0.75, 1.0))
        # service lines
        p.drawLine(self._map_norm(court, -0.75, 0.231), self._map_norm(court, 0.75, 0.231))
        p.drawLine(self._map_norm(court, -0.75, 0.769), self._map_norm(court, 0.75, 0.769))
        # center service line
        p.drawLine(self._map_norm(court, 0.0, 0.231), self._map_norm(court, 0.0, 0.769))

        # Net with texture
        net_poly = QPolygonF([
            QPointF(net_l.x(), net_l.y() - 5),
            QPointF(net_r.x(), net_r.y() - 5),
            QPointF(net_r.x(), net_r.y() + 13),
            QPointF(net_l.x(), net_l.y() + 13),
        ])
        p.setBrush(QColor(16, 26, 40, 170))
        p.setPen(QPen(QColor("#e3edf9"), 1))
        p.drawPolygon(net_poly)
        p.setPen(QPen(QColor(220, 230, 240, 70), 1))
        for i in range(0, int(net_r.x() - net_l.x()), 9):
            x = net_l.x() + i
            p.drawLine(QPointF(x, net_l.y() - 4), QPointF(x, net_l.y() + 12))

        p.setPen(QColor("#b3c4da"))
        p.drawText(int(court.center().x() - 52), int(court.top() - 6), "OPPONENT SIDE")
        p.drawText(int(court.center().x() - 28), int(court.bottom() + 16), "YOUR SIDE")

        origin = self._map_norm(court, 0.0, 0.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(origin, 6.6, 6.6)

        # Trajectories
        for s in self.shots:
            end = self._landing_to_point(court, s.landing_x, s.landing_y)
            ctrl = QPointF(
                (origin.x() + end.x()) * 0.5 + (s.arm_angle * 0.19),
                min(origin.y(), end.y()) - 54 - min(s.spin * 0.006, 18),
            )
            path = QPainterPath(origin)
            path.quadTo(ctrl, end)
            color = shot_color(s.speed)
            c = QColor(color)
            c.setAlpha(225)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(c, 1.8, Qt.PenStyle.DashLine if s.idx % 2 == 0 else Qt.PenStyle.SolidLine))
            p.drawPath(path)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(end, 3.6, 3.6)
            if s.impact_redness > 0:
                glow = QColor("#ff3b3b")
                glow.setAlpha(40 + int(1.7 * s.impact_redness))
                p.setBrush(glow)
                p.drawEllipse(end, 6.6, 6.6)

        # Legend
        legend_x = int(court.right() - 88)
        legend_y = int(court.top() + 12)
        p.fillRect(QRectF(legend_x, legend_y, 78, 94), QColor(7, 16, 32, 205))
        p.setPen(QColor("#dfe9f8"))
        p.setFont(QFont("Arial", 8))
        p.drawText(legend_x + 10, legend_y + 14, "SPEED")
        yy = legend_y + 27
        for txt, col in [("> 70", "#ff4747"), ("50 - 70", "#ffd43a"), ("30 - 50", "#2ed36d"), ("< 30", "#4aa3ff")]:
            p.setBrush(QColor(col))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(legend_x + 12, yy), 3.6, 3.6)
            p.setPen(QColor("#c7d5e9"))
            p.drawText(legend_x + 22, yy + 4, txt)
            yy += 16

    @staticmethod
    def _court_corners(court: QRectF):
        # Stronger convergence like reference UI.
        fl = QPointF(court.left() + court.width() * 0.02, court.bottom() - court.height() * 0.03)
        fr = QPointF(court.right() - court.width() * 0.02, court.bottom() - court.height() * 0.03)
        bl = QPointF(court.left() + court.width() * 0.23, court.top() + court.height() * 0.13)
        br = QPointF(court.right() - court.width() * 0.23, court.top() + court.height() * 0.13)
        return fl, fr, bl, br

    @staticmethod
    def _map_norm(court: QRectF, u: float, v: float) -> QPointF:
        # u in [-1,1], v in [0,1] from near baseline (0) to far baseline (1).
        fl, fr, bl, br = CourtWidget._court_corners(court)
        uu = max(0.0, min((u + 1.0) * 0.5, 1.0))
        vv = max(0.0, min(v, 1.0))
        near = QPointF(fl.x() + (fr.x() - fl.x()) * uu, fl.y() + (fr.y() - fl.y()) * uu)
        far = QPointF(bl.x() + (br.x() - bl.x()) * uu, bl.y() + (br.y() - bl.y()) * uu)
        return QPointF(near.x() + (far.x() - near.x()) * vv, near.y() + (far.y() - near.y()) * vv)

    @staticmethod
    def _landing_to_point(court: QRectF, x_m: float, y_m: float) -> QPointF:
        # x_m: singles coordinates [-4.115, +4.115]
        # y_m: distance from net to opponent baseline [0..11.885] in this app model.
        u = max(-0.75, min(0.75, x_m / 5.485))
        v = 0.5 + max(0.0, min(y_m / 23.77, 0.5))
        return CourtWidget._map_norm(court, u, v)


class HeatmapWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.shots: list[Shot] = []
        self.setMinimumHeight(178)

    def set_shots(self, shots: list[Shot]):
        self.shots = shots[-120:]
        self.update()

    def paintEvent(self, event):  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#071224"))

        # Vertical mini-court perspective (to match original design).
        margin = 14
        zone = QRectF(margin, margin + 6, self.width() - margin * 2, self.height() - margin * 2 - 6)
        fl, fr, bl, br = self._mini_court_corners(zone)

        surf = QPolygonF([fl, fr, br, bl])
        cg = QLinearGradient(zone.left(), zone.bottom(), zone.right(), zone.top())
        cg.setColorAt(0.0, QColor("#173e70"))
        cg.setColorAt(1.0, QColor("#2a5f99"))
        p.setBrush(cg)
        p.setPen(QPen(QColor("#dbe8f7"), 1.6))
        p.drawPolygon(surf)

        # Main court guides.
        p.setPen(QPen(QColor("#dce7f4"), 1.35))
        p.drawLine(self._map_point(fl, fr, bl, br, -1.0, 0.5), self._map_point(fl, fr, bl, br, 1.0, 0.5))  # net
        p.drawLine(self._map_point(fl, fr, bl, br, -0.75, 0.0), self._map_point(fl, fr, bl, br, -0.75, 1.0))
        p.drawLine(self._map_point(fl, fr, bl, br, 0.75, 0.0), self._map_point(fl, fr, bl, br, 0.75, 1.0))
        p.drawLine(self._map_point(fl, fr, bl, br, -0.75, 0.231), self._map_point(fl, fr, bl, br, 0.75, 0.231))
        p.drawLine(self._map_point(fl, fr, bl, br, -0.75, 0.769), self._map_point(fl, fr, bl, br, 0.75, 0.769))
        p.drawLine(self._map_point(fl, fr, bl, br, 0.0, 0.231), self._map_point(fl, fr, bl, br, 0.0, 0.769))

        # Soft vignette for closer visual parity.
        vig = QRadialGradient(zone.center(), max(zone.width(), zone.height()) * 0.55)
        vig.setColorAt(0.55, QColor(0, 0, 0, 0))
        vig.setColorAt(1.0, QColor(0, 0, 0, 90))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(vig)
        p.drawPolygon(surf)

        for s in self.shots:
            pt = self._heatmap_point(fl, fr, bl, br, s.landing_x, s.landing_y)
            color = shot_color(s.speed)
            for r, alpha in ((20, 22), (12, 50), (6, 95)):
                c = QColor(color)
                c.setAlpha(alpha)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(c)
                p.drawEllipse(pt, r, r)

    @staticmethod
    def _mini_court_corners(zone: QRectF):
        fl = QPointF(zone.left() + zone.width() * 0.04, zone.bottom() - zone.height() * 0.06)
        fr = QPointF(zone.right() - zone.width() * 0.04, zone.bottom() - zone.height() * 0.06)
        bl = QPointF(zone.left() + zone.width() * 0.28, zone.top() + zone.height() * 0.10)
        br = QPointF(zone.right() - zone.width() * 0.28, zone.top() + zone.height() * 0.10)
        return fl, fr, bl, br

    @staticmethod
    def _map_point(fl: QPointF, fr: QPointF, bl: QPointF, br: QPointF, u: float, v: float) -> QPointF:
        uu = max(0.0, min((u + 1.0) * 0.5, 1.0))
        vv = max(0.0, min(v, 1.0))
        near = QPointF(fl.x() + (fr.x() - fl.x()) * uu, fl.y() + (fr.y() - fl.y()) * uu)
        far = QPointF(bl.x() + (br.x() - bl.x()) * uu, bl.y() + (br.y() - bl.y()) * uu)
        return QPointF(near.x() + (far.x() - near.x()) * vv, near.y() + (far.y() - near.y()) * vv)

    @staticmethod
    def _heatmap_point(fl: QPointF, fr: QPointF, bl: QPointF, br: QPointF, x_m: float, y_m: float) -> QPointF:
        # Keep same semantic as main court:
        # x_m in [-4.115, +4.115], y_m in [0, 11.885] from net to opponent baseline.
        u = max(-0.75, min(0.75, x_m / 5.485))
        # Opponent half only => map from net line (0.5) to far baseline (1.0).
        v = 0.5 + max(0.0, min(y_m / 11.885, 1.0)) * 0.5
        return HeatmapWidget._map_point(fl, fr, bl, br, u, v)


class TennisBallImpactWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.impact_x = 0
        self.impact_y = 0
        self.impact_redness = 0
        self.setMinimumHeight(178)

    def set_impact(self, impact_x: int, impact_y: int, impact_redness: int):
        self.impact_x = max(-100, min(100, int(impact_x)))
        self.impact_y = max(-100, min(100, int(impact_y)))
        self.impact_redness = max(0, min(100, int(impact_redness)))
        self.update()

    def paintEvent(self, event):  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#071224"))

        size = min(self.width(), self.height()) - 24
        size = max(size, 70)
        ball_rect = QRectF(
            (self.width() - size) * 0.5,
            (self.height() - size) * 0.5,
            size,
            size,
        )

        ball_grad = QRadialGradient(
            ball_rect.center().x() - size * 0.2,
            ball_rect.center().y() - size * 0.24,
            size * 0.65,
        )
        ball_grad.setColorAt(0.0, QColor("#f6ff95"))
        ball_grad.setColorAt(0.62, QColor("#dcf15f"))
        ball_grad.setColorAt(1.0, QColor("#95b63a"))
        p.setPen(QPen(QColor("#d8e88d"), 1.5))
        p.setBrush(ball_grad)
        p.drawEllipse(ball_rect)

        p.setBrush(Qt.BrushStyle.NoBrush)
        seam_pen = QPen(QColor("#f5ffd7"), 2.2)
        p.setPen(seam_pen)
        p.drawArc(ball_rect.adjusted(size * 0.1, size * 0.06, -size * 0.18, -size * 0.06), 70 * 16, 225 * 16)
        p.drawArc(ball_rect.adjusted(size * 0.18, size * 0.06, -size * 0.1, -size * 0.06), 245 * 16, 225 * 16)

        nx = self.impact_x / 100.0
        ny = self.impact_y / 100.0
        cx = ball_rect.center().x() + nx * (size * 0.34)
        cy = ball_rect.center().y() - ny * (size * 0.34)
        radius = size * (0.04 + self.impact_redness * 0.0007)
        radius = max(radius, 5.0)

        if self.impact_redness > 0:
            glow = QColor("#ff4040")
            glow.setAlpha(40 + int(1.8 * self.impact_redness))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QPointF(cx, cy), radius * 1.9, radius * 1.9)

        core = QColor("#ff2d2d")
        core.setAlpha(130 + int(1.2 * self.impact_redness))
        p.setPen(QPen(QColor("#ffd6d6"), 1.0))
        p.setBrush(core)
        p.drawEllipse(QPointF(cx, cy), radius, radius)

        p.setPen(QColor("#c5d8eb"))
        p.setFont(QFont("Arial", 8))
        p.drawText(10, self.height() - 10, f"Impact {self.impact_x:+d}, {self.impact_y:+d} | Redness {self.impact_redness:d}%")


class CalibrationWizardPreviewWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._mode: str | None = None
        self._last_x = 0
        self._last_y = 0
        self._last_redness = 0
        self.setMinimumHeight(175)

    def set_mode(self, mode: str | None):
        self._mode = mode if mode in {"soft", "hard"} else None
        self.update()

    def set_last_hit(self, impact_x: int, impact_y: int, impact_redness: int):
        self._last_x = max(-100, min(100, int(impact_x)))
        self._last_y = max(-100, min(100, int(impact_y)))
        self._last_redness = max(0, min(100, int(impact_redness)))
        self.update()

    def paintEvent(self, event):  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#071224"))

        size = min(self.width(), self.height()) - 28
        size = max(size, 88)
        ball_rect = QRectF(
            (self.width() - size) * 0.5,
            (self.height() - size) * 0.5,
            size,
            size,
        )

        ball_grad = QRadialGradient(
            ball_rect.center().x() - size * 0.2,
            ball_rect.center().y() - size * 0.24,
            size * 0.65,
        )
        ball_grad.setColorAt(0.0, QColor("#f6ff95"))
        ball_grad.setColorAt(0.62, QColor("#dcf15f"))
        ball_grad.setColorAt(1.0, QColor("#95b63a"))
        p.setPen(QPen(QColor("#d8e88d"), 1.5))
        p.setBrush(ball_grad)
        p.drawEllipse(ball_rect)

        # Recommended calibration zone overlay.
        target_radius = size * (0.15 if self._mode == "soft" else 0.11)
        target_color = QColor("#78d8ff" if self._mode == "soft" else "#ff9b66")
        target_color.setAlpha(120 if self._mode else 55)
        p.setBrush(target_color)
        p.setPen(QPen(QColor("#e8f7ff" if self._mode == "soft" else "#ffe9d6"), 1.2))
        p.drawEllipse(ball_rect.center(), target_radius, target_radius)

        nx = self._last_x / 100.0
        ny = self._last_y / 100.0
        cx = ball_rect.center().x() + nx * (size * 0.34)
        cy = ball_rect.center().y() - ny * (size * 0.34)
        hit_r = size * (0.04 + self._last_redness * 0.0007)
        hit_r = max(hit_r, 5.0)
        if self._last_redness > 0:
            glow = QColor("#ff4040")
            glow.setAlpha(35 + int(1.8 * self._last_redness))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QPointF(cx, cy), hit_r * 1.8, hit_r * 1.8)
        p.setPen(QPen(QColor("#ffd6d6"), 1.0))
        p.setBrush(QColor("#ff2d2d"))
        p.drawEllipse(QPointF(cx, cy), hit_r, hit_r)

        p.setPen(QColor("#c5d8eb"))
        p.setFont(QFont("Arial", 8))
        mode_txt = "IDLE"
        if self._mode == "soft":
            mode_txt = "SOFT CAPTURE: aim smooth center contacts"
        elif self._mode == "hard":
            mode_txt = "HARD CAPTURE: aim center with full power"
        p.drawText(10, self.height() - 10, mode_txt)


class StatsBIWindow(QWidget):
    def __init__(self, dashboard: "TennisDashboard"):
        super().__init__()
        self.dashboard = dashboard
        self.setWindowTitle("Tennis Stats BI")
        self.resize(980, 620)
        self._profile_switching = False

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(220)
        self.level_combo = QComboBox()
        self.level_combo.setMinimumWidth(160)
        self.level_combo.addItems(list(self.dashboard._competition_profiles.keys()))
        self.btn_new_profile = QPushButton("NEW STUDENT")
        self.btn_save_session = QPushButton("SAVE SESSION")
        self.btn_compare = QPushButton("COMPARE LAST 2")
        row.addWidget(QLabel("Student Profile"))
        row.addWidget(self.profile_combo, 1)
        row.addWidget(QLabel("Competition Level"))
        row.addWidget(self.level_combo, 0)
        row.addWidget(self.btn_new_profile)
        row.addWidget(self.btn_save_session)
        row.addWidget(self.btn_compare)
        root.addLayout(row)

        self.lbl_profile_meta = QLabel("Profile: -")
        self.lbl_profile_meta.setObjectName("SmallMuted")
        root.addWidget(self.lbl_profile_meta)

        self.lbl_snapshot = QLabel("Current session snapshot: 0 shots")
        self.lbl_snapshot.setObjectName("SmallMuted")
        root.addWidget(self.lbl_snapshot)

        elite_box = QFrame()
        elite_box.setObjectName("Panel")
        elite_lay = QVBoxLayout(elite_box)
        elite_lay.setContentsMargins(10, 8, 10, 8)
        elite_lay.setSpacing(4)
        elite_lay.addWidget(QLabel("TOP QUALITY ALIGNMENT"))
        self.lbl_elite_score = QLabel("Alignment score: 0%")
        self.lbl_elite_score.setObjectName("SmallMuted")
        self.lbl_elite_speed = QLabel("Speed vs target: 0.0 / 0.0 mph")
        self.lbl_elite_spin = QLabel("Spin vs target: 0 / 0 rpm")
        self.lbl_elite_cons = QLabel("Consistency vs target: 0 / 0%")
        self.lbl_elite_fast = QLabel("Fast shots vs target: 0 / 0%")
        self.lbl_elite_impact = QLabel("Impact quality vs target: 0 / 0%")
        for lbl in (
            self.lbl_elite_speed,
            self.lbl_elite_spin,
            self.lbl_elite_cons,
            self.lbl_elite_fast,
            self.lbl_elite_impact,
        ):
            lbl.setObjectName("SmallMuted")
        elite_lay.addWidget(self.lbl_elite_score)
        elite_lay.addWidget(self.lbl_elite_speed)
        elite_lay.addWidget(self.lbl_elite_spin)
        elite_lay.addWidget(self.lbl_elite_cons)
        elite_lay.addWidget(self.lbl_elite_fast)
        elite_lay.addWidget(self.lbl_elite_impact)
        root.addWidget(elite_box)

        comp_box = QFrame()
        comp_box.setObjectName("Panel")
        comp_lay = QVBoxLayout(comp_box)
        comp_lay.setContentsMargins(10, 8, 10, 8)
        comp_lay.setSpacing(4)
        self.lbl_compare_header = QLabel("Save at least 2 sessions to compare.")
        self.lbl_compare_header.setObjectName("SmallMuted")
        self.lbl_compare_speed = QLabel("Avg speed Δ   +0.0 mph")
        self.lbl_compare_spin = QLabel("Avg spin Δ    +0 rpm")
        self.lbl_compare_cons = QLabel("Consistency Δ +0%")
        self.lbl_compare_impact = QLabel("Impact Δ      +0.0%")
        for lbl in (self.lbl_compare_speed, self.lbl_compare_spin, self.lbl_compare_cons, self.lbl_compare_impact):
            lbl.setObjectName("SmallMuted")
            comp_lay.addWidget(lbl)
        comp_lay.insertWidget(0, self.lbl_compare_header)
        root.addWidget(comp_box)

        self.sessions_table = QTableWidget(0, 7)
        self.sessions_table.setHorizontalHeaderLabels(
            ["STARTED", "SHOTS", "AVG SPEED", "AVG SPIN", "CONSISTENCY", "FAST %", "IMPACT %"]
        )
        self.sessions_table.verticalHeader().setVisible(False)
        self.sessions_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.sessions_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.sessions_table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.sessions_table, 1)

        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        self.level_combo.currentTextChanged.connect(self._on_level_changed)
        self.btn_new_profile.clicked.connect(self.dashboard._create_profile)
        self.btn_save_session.clicked.connect(self.dashboard._save_current_session)
        self.btn_compare.clicked.connect(self.dashboard._refresh_comparison_labels)

    def _on_profile_changed(self, name: str):
        if self._profile_switching:
            return
        self.dashboard._on_profile_selected(name)

    def _on_level_changed(self, level: str):
        if self._profile_switching or not level:
            return
        self.dashboard._set_competition_level(level)

    def refresh(self):
        names = sorted(self.dashboard._profiles.keys())
        self._profile_switching = True
        self.profile_combo.clear()
        self.profile_combo.addItems(names)
        self.profile_combo.setCurrentText(self.dashboard._current_student)
        self.level_combo.clear()
        self.level_combo.addItems(list(self.dashboard._competition_profiles.keys()))
        self.level_combo.setCurrentText(self.dashboard._competition_level)
        self._profile_switching = False

        sessions = self.dashboard._profiles.get(self.dashboard._current_student, [])
        self.lbl_profile_meta.setText(
            f"Profile: {self.dashboard._current_student} | Sessions saved: {len(sessions)}"
        )

        current_summary = self.dashboard._session_metrics_from_shots(self.dashboard.shots)
        self.lbl_snapshot.setText(
            "Current session snapshot: "
            f"{current_summary.shot_count} shots | avg {current_summary.avg_speed:.1f} mph | "
            f"spin {current_summary.avg_spin:.0f} rpm | consistency {current_summary.consistency}%"
        )
        elite = self.dashboard._elite_alignment_for_summary(current_summary)
        profile = self.dashboard._current_competition_profile()
        self.lbl_elite_score.setText(f"Alignment score ({self.dashboard._competition_level}): {elite['score']:.0f}%")
        self.lbl_elite_speed.setText(
            f"Speed vs target: {current_summary.avg_speed:.1f} / {profile['target_speed']:.1f} mph"
        )
        self.lbl_elite_spin.setText(
            f"Spin vs target: {current_summary.avg_spin:.0f} / {profile['target_spin']:.0f} rpm"
        )
        self.lbl_elite_cons.setText(
            f"Consistency vs target: {current_summary.consistency:.0f} / {profile['target_consistency']:.0f}%"
        )
        self.lbl_elite_fast.setText(
            f"Fast shots vs target: {current_summary.fast_pct:.1f} / {profile['target_fast_pct']:.0f}%"
        )
        self.lbl_elite_impact.setText(
            f"Impact quality vs target: {current_summary.avg_impact_redness:.1f} / {profile['target_impact']:.0f}%"
        )

        header, d_speed, d_spin, d_cons, d_imp = self.dashboard._comparison_strings()
        self.lbl_compare_header.setText(header)
        self.lbl_compare_speed.setText(d_speed)
        self.lbl_compare_spin.setText(d_spin)
        self.lbl_compare_cons.setText(d_cons)
        self.lbl_compare_impact.setText(d_imp)

        rows = list(reversed(sessions[-24:]))
        self.sessions_table.setRowCount(len(rows))
        for r, s in enumerate(rows):
            vals = [
                str(s.get("started_at", "-")),
                str(s.get("shot_count", 0)),
                f"{float(s.get('avg_speed', 0.0)):.1f} mph",
                f"{float(s.get('avg_spin', 0.0)):.0f} rpm",
                f"{float(s.get('consistency', 0.0)):.0f}%",
                f"{float(s.get('fast_pct', 0.0)):.1f}%",
                f"{float(s.get('avg_impact_redness', 0.0)):.1f}%",
            ]
            for c, v in enumerate(vals):
                self.sessions_table.setItem(r, c, QTableWidgetItem(v))

class SettingsWindow(QWidget):
    def __init__(self, dashboard: "TennisDashboard"):
        super().__init__()
        self.dashboard = dashboard
        self.setWindowTitle("Tennis Settings")
        self.resize(760, 520)
        self._capture_mode: str | None = None
        self._capture_target = 8
        self._soft_samples: list[dict] = []
        self._hard_samples: list[dict] = []
        self._suggested_impact_mg_100: int | None = None
        self._suggested_contact_full_scale_mg: int | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        self.settings_tabs = QTabWidget()
        self.settings_tabs.setObjectName("SettingsTabs")
        root.addWidget(self.settings_tabs, 1)

        cal_tab = QWidget()
        cal_tab_lay = QVBoxLayout(cal_tab)
        cal_tab_lay.setContentsMargins(0, 0, 0, 0)
        cal_tab_lay.setSpacing(8)
        self.settings_tabs.addTab(cal_tab, "Calibration")

        wiz_tab = QWidget()
        wiz_tab_lay = QVBoxLayout(wiz_tab)
        wiz_tab_lay.setContentsMargins(0, 0, 0, 0)
        wiz_tab_lay.setSpacing(8)
        self.settings_tabs.addTab(wiz_tab, "Wizard")

        comp_tab = QWidget()
        comp_tab_lay = QVBoxLayout(comp_tab)
        comp_tab_lay.setContentsMargins(0, 0, 0, 0)
        comp_tab_lay.setSpacing(8)
        self.settings_tabs.addTab(comp_tab, "Competition Profiles")

        cal_box = QFrame()
        cal_box.setObjectName("Panel")
        cal_lay = QVBoxLayout(cal_box)
        cal_lay.setContentsMargins(10, 8, 10, 8)
        cal_lay.setSpacing(6)
        cal_lay.addWidget(QLabel("IMPACT CALIBRATION (FIRMWARE)"))
        cal_grid = QGridLayout()
        cal_grid.setHorizontalSpacing(8)
        cal_grid.setVerticalSpacing(4)
        self.cal_counts_input = QLineEdit("410.0")
        self.cal_impact_input = QLineEdit("4200")
        self.cal_contact_input = QLineEdit("1500")
        cal_grid.addWidget(QLabel("Counts per G"), 0, 0)
        cal_grid.addWidget(self.cal_counts_input, 0, 1)
        cal_grid.addWidget(QLabel("mg @ 100%"), 1, 0)
        cal_grid.addWidget(self.cal_impact_input, 1, 1)
        cal_grid.addWidget(QLabel("contact full-scale mg"), 2, 0)
        cal_grid.addWidget(self.cal_contact_input, 2, 1)
        cal_lay.addLayout(cal_grid)
        cal_btns = QHBoxLayout()
        self.btn_cal_load = QPushButton("LOAD FW")
        self.btn_cal_apply = QPushButton("APPLY RAM")
        self.btn_cal_save = QPushButton("SAVE TO FW")
        self.btn_cal_reset = QPushButton("RESET DEFAULTS")
        cal_btns.addWidget(self.btn_cal_load)
        cal_btns.addWidget(self.btn_cal_apply)
        cal_btns.addWidget(self.btn_cal_save)
        cal_btns.addWidget(self.btn_cal_reset)
        cal_lay.addLayout(cal_btns)
        self.lbl_cal_status = QLabel("Calibration ready.")
        self.lbl_cal_status.setObjectName("SmallMuted")
        cal_lay.addWidget(self.lbl_cal_status)
        cal_tab_lay.addWidget(cal_box)
        cal_tab_lay.addStretch(1)

        wiz_box = QFrame()
        wiz_box.setObjectName("Panel")
        wiz_lay = QVBoxLayout(wiz_box)
        wiz_lay.setContentsMargins(10, 8, 10, 8)
        wiz_lay.setSpacing(6)
        wiz_lay.addWidget(QLabel("CALIBRATION WIZARD (GUIDED)"))
        self.lbl_wizard_help = QLabel(
            "1) Capture soft hits, 2) capture hard hits, 3) apply suggested values."
        )
        self.lbl_wizard_help.setObjectName("SmallMuted")
        wiz_lay.addWidget(self.lbl_wizard_help)
        self.wiz_preview = CalibrationWizardPreviewWidget()
        wiz_lay.addWidget(self.wiz_preview)
        wiz_btns = QHBoxLayout()
        self.btn_wiz_soft = QPushButton("1) CAPTURE SOFT")
        self.btn_wiz_hard = QPushButton("2) CAPTURE HARD")
        self.btn_wiz_apply = QPushButton("3) APPLY SUGGESTED")
        wiz_btns.addWidget(self.btn_wiz_soft)
        wiz_btns.addWidget(self.btn_wiz_hard)
        wiz_btns.addWidget(self.btn_wiz_apply)
        wiz_lay.addLayout(wiz_btns)
        self.lbl_wiz_status = QLabel("Wizard idle.")
        self.lbl_wiz_status.setObjectName("SmallMuted")
        self.lbl_wiz_soft = QLabel("Soft set: not captured")
        self.lbl_wiz_soft.setObjectName("SmallMuted")
        self.lbl_wiz_hard = QLabel("Hard set: not captured")
        self.lbl_wiz_hard.setObjectName("SmallMuted")
        self.lbl_wiz_suggest = QLabel("Suggested: pending")
        self.lbl_wiz_suggest.setObjectName("SmallMuted")
        wiz_lay.addWidget(self.lbl_wiz_status)
        wiz_lay.addWidget(self.lbl_wiz_soft)
        wiz_lay.addWidget(self.lbl_wiz_hard)
        wiz_lay.addWidget(self.lbl_wiz_suggest)
        wiz_tab_lay.addWidget(wiz_box)
        wiz_tab_lay.addStretch(1)

        comp_box = QFrame()
        comp_box.setObjectName("Panel")
        comp_lay = QVBoxLayout(comp_box)
        comp_lay.setContentsMargins(10, 8, 10, 8)
        comp_lay.setSpacing(6)
        comp_lay.addWidget(QLabel("COMPETITION PROFILE SETTINGS"))
        comp_row = QHBoxLayout()
        self.comp_profile_combo = QComboBox()
        self.comp_profile_combo.addItems(list(self.dashboard._competition_profiles.keys()))
        comp_row.addWidget(QLabel("Edit level"))
        comp_row.addWidget(self.comp_profile_combo, 1)
        comp_lay.addLayout(comp_row)

        grouped_row = QHBoxLayout()
        grouped_row.setSpacing(8)
        self.comp_targets_table = self._new_comp_table()
        self.comp_sim_table = self._new_comp_table()
        self.comp_live_table = self._new_comp_table()
        grouped_row.addWidget(self._wrap_comp_group("Targets", self.comp_targets_table), 1)
        grouped_row.addWidget(self._wrap_comp_group("Simulation", self.comp_sim_table), 1)
        grouped_row.addWidget(self._wrap_comp_group("Live", self.comp_live_table), 1)
        comp_lay.addLayout(grouped_row, 1)
        comp_btns = QHBoxLayout()
        self.btn_comp_apply = QPushButton("APPLY LEVEL")
        self.btn_comp_save = QPushButton("SAVE CONFIG FILE")
        self.btn_comp_reset = QPushButton("RESET DEFAULTS")
        comp_btns.addWidget(self.btn_comp_apply)
        comp_btns.addWidget(self.btn_comp_save)
        comp_btns.addWidget(self.btn_comp_reset)
        comp_lay.addLayout(comp_btns)
        self.lbl_comp_status = QLabel("Competition profile editor ready.")
        self.lbl_comp_status.setObjectName("SmallMuted")
        comp_lay.addWidget(self.lbl_comp_status)
        comp_tab_lay.addWidget(comp_box, 1)

        self.btn_cal_load.clicked.connect(self.dashboard._request_firmware_calibration)
        self.btn_cal_apply.clicked.connect(self._apply_calibration_from_inputs)
        self.btn_cal_save.clicked.connect(self.dashboard._save_firmware_calibration)
        self.btn_cal_reset.clicked.connect(self.dashboard._reset_firmware_calibration)
        self.btn_wiz_soft.clicked.connect(lambda: self._start_capture("soft"))
        self.btn_wiz_hard.clicked.connect(lambda: self._start_capture("hard"))
        self.btn_wiz_apply.clicked.connect(self._apply_suggested)
        self.comp_profile_combo.currentTextChanged.connect(self._refresh_competition_editor)
        self.btn_comp_apply.clicked.connect(self._apply_competition_editor_changes)
        self.btn_comp_save.clicked.connect(self._save_competition_editor_changes)
        self.btn_comp_reset.clicked.connect(self._reset_competition_editor_defaults)
        self._refresh_competition_editor(self.comp_profile_combo.currentText())

    def _apply_calibration_from_inputs(self):
        self.dashboard._apply_firmware_calibration_from_ui(
            self.cal_counts_input.text(),
            self.cal_impact_input.text(),
            self.cal_contact_input.text(),
        )

    def set_calibration_values(self, counts_per_g: float, impact_mg_100: int, contact_full_scale_mg: int):
        self.cal_counts_input.setText(f"{counts_per_g:.2f}")
        self.cal_impact_input.setText(str(int(impact_mg_100)))
        self.cal_contact_input.setText(str(int(contact_full_scale_mg)))

    def set_calibration_status(self, text: str):
        self.lbl_cal_status.setText(text)

    def refresh(self):
        current = self.comp_profile_combo.currentText() or self.dashboard._competition_level
        self.comp_profile_combo.blockSignals(True)
        self.comp_profile_combo.clear()
        self.comp_profile_combo.addItems(list(self.dashboard._competition_profiles.keys()))
        self.comp_profile_combo.setCurrentText(current)
        self.comp_profile_combo.blockSignals(False)
        self._refresh_competition_editor(self.comp_profile_combo.currentText())

    def _refresh_competition_editor(self, level: str):
        profile = self.dashboard._competition_profiles.get(level)
        if not profile:
            self.comp_targets_table.setRowCount(0)
            self.comp_sim_table.setRowCount(0)
            self.comp_live_table.setRowCount(0)
            return
        self._populate_comp_group_table(
            self.comp_targets_table,
            profile,
            ("target_",),
        )
        self._populate_comp_group_table(
            self.comp_sim_table,
            profile,
            ("sim_",),
        )
        self._populate_comp_group_table(
            self.comp_live_table,
            profile,
            ("live_",),
        )

    def _apply_competition_editor_changes(self) -> bool:
        level = self.comp_profile_combo.currentText().strip()
        profile = self.dashboard._competition_profiles.get(level)
        if not level or profile is None:
            self.lbl_comp_status.setText("Select a competition level first.")
            return False
        updated: dict[str, float] = {}
        for table in (self.comp_targets_table, self.comp_sim_table, self.comp_live_table):
            ok, values_or_error = self._collect_comp_group_values(table)
            if not ok:
                self.lbl_comp_status.setText(str(values_or_error))
                return False
            updated.update(values_or_error)
        self.dashboard._competition_profiles[level].update(updated)
        self.dashboard._sanitize_competition_profiles()
        self.dashboard._refresh_competition_toggle()
        self.dashboard._refresh_comparison_labels()
        if self.dashboard._stats_window is not None:
            self.dashboard._stats_window.refresh()
        self._refresh_competition_editor(level)
        self.lbl_comp_status.setText(f"Applied changes to {level}. Save file to persist.")
        return True

    def _save_competition_editor_changes(self):
        if not self._apply_competition_editor_changes():
            return
        self.dashboard._save_competition_profiles_config()
        self.lbl_comp_status.setText(
            f"Saved competition profiles to {self.dashboard._competition_config_path.name}."
        )

    def _reset_competition_editor_defaults(self):
        self.dashboard._competition_profiles = {
            lvl: vals.copy() for lvl, vals in DEFAULT_COMPETITION_PROFILES.items()
        }
        self.dashboard._sanitize_competition_profiles()
        self.dashboard._save_competition_profiles_config()
        self.dashboard._set_competition_level(self.dashboard._competition_level)
        if self.dashboard._stats_window is not None:
            self.dashboard._stats_window.refresh()
        self.comp_profile_combo.clear()
        self.comp_profile_combo.addItems(list(self.dashboard._competition_profiles.keys()))
        self.comp_profile_combo.setCurrentText(self.dashboard._competition_level)
        self._refresh_competition_editor(self.comp_profile_combo.currentText())
        self.lbl_comp_status.setText("Competition profile defaults restored and saved.")

    @staticmethod
    def _new_comp_table() -> QTableWidget:
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Setting", "Value"])
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    @staticmethod
    def _wrap_comp_group(title: str, table: QTableWidget) -> QFrame:
        box = QFrame()
        box.setObjectName("Panel")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)
        hdr = QLabel(title)
        hdr.setObjectName("PanelTitle")
        lay.addWidget(hdr)
        lay.addWidget(table, 1)
        return box

    @staticmethod
    def _display_profile_key(key: str) -> str:
        for pref in ("target_", "sim_", "live_"):
            if key.startswith(pref):
                key = key[len(pref):]
                break
        return key.replace("_", " ").upper()

    def _populate_comp_group_table(
        self,
        table: QTableWidget,
        profile: dict[str, float],
        prefixes: tuple[str, ...],
    ):
        keys = sorted(k for k in profile.keys() if any(k.startswith(pref) for pref in prefixes))
        table.setRowCount(len(keys))
        for idx, key in enumerate(keys):
            key_item = QTableWidgetItem(self._display_profile_key(key))
            key_item.setData(Qt.ItemDataRole.UserRole, key)
            key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(idx, 0, key_item)
            table.setItem(idx, 1, QTableWidgetItem(f"{float(profile[key]):.3f}"))

    @staticmethod
    def _collect_comp_group_values(table: QTableWidget) -> tuple[bool, dict[str, float] | str]:
        updated: dict[str, float] = {}
        for row in range(table.rowCount()):
            key_item = table.item(row, 0)
            val_item = table.item(row, 1)
            if key_item is None or val_item is None:
                continue
            raw_key = key_item.data(Qt.ItemDataRole.UserRole)
            key = str(raw_key) if isinstance(raw_key, str) else key_item.text().strip().lower().replace(" ", "_")
            try:
                updated[key] = float(val_item.text().strip())
            except ValueError:
                label = key_item.text().strip()
                return False, f"Invalid numeric value for '{label}'."
        return True, updated

    def _start_capture(self, mode: str):
        if mode == "soft":
            self._soft_samples = []
            self.lbl_wiz_soft.setText("Soft set: capturing...")
            self.lbl_wiz_status.setText(f"Capture {self._capture_target} soft hits now.")
            self.lbl_wizard_help.setText("Soft capture: hit around center with controlled pace.")
        else:
            self._hard_samples = []
            self.lbl_wiz_hard.setText("Hard set: capturing...")
            self.lbl_wiz_status.setText(f"Capture {self._capture_target} hard hits now.")
            self.lbl_wizard_help.setText("Hard capture: hit around center with stronger acceleration.")
        self._capture_mode = mode
        self.wiz_preview.set_mode(mode)

    @staticmethod
    def _mag(e: dict) -> float:
        return float(e.get("mag_mg", 0.0))

    @staticmethod
    def _p90(values: list[float]) -> float:
        if not values:
            return 0.0
        sv = sorted(values)
        idx = min(len(sv) - 1, max(0, int(round((len(sv) - 1) * 0.9))))
        return sv[idx]

    def _update_wizard_summary(self):
        if self._soft_samples:
            soft_mag = sum(self._mag(x) for x in self._soft_samples) / len(self._soft_samples)
            self.lbl_wiz_soft.setText(f"Soft set: {len(self._soft_samples)} hits | avg mag {soft_mag:.0f} mg")
        if self._hard_samples:
            hard_mag = sum(self._mag(x) for x in self._hard_samples) / len(self._hard_samples)
            self.lbl_wiz_hard.setText(f"Hard set: {len(self._hard_samples)} hits | avg mag {hard_mag:.0f} mg")

        if self._soft_samples and self._hard_samples:
            hard_p90 = self._p90([self._mag(x) for x in self._hard_samples])
            lateral_pool = [
                max(abs(float(e.get("x_mg", 0.0))), abs(float(e.get("y_mg", 0.0))))
                for e in (self._soft_samples + self._hard_samples)
            ]
            lateral_p90 = self._p90(lateral_pool)
            self._suggested_impact_mg_100 = int(max(600, hard_p90 / 0.95))
            self._suggested_contact_full_scale_mg = int(max(250, lateral_p90 * 1.15))
            self.lbl_wiz_suggest.setText(
                "Suggested: "
                f"mg@100={self._suggested_impact_mg_100}, "
                f"contact={self._suggested_contact_full_scale_mg}"
            )

    def on_impact_event(self, event: dict):
        self.wiz_preview.set_last_hit(
            int(event.get("impact_x", 0)),
            int(event.get("impact_y", 0)),
            int(event.get("redness", 0)),
        )
        if self._capture_mode is None:
            return
        target = self._soft_samples if self._capture_mode == "soft" else self._hard_samples
        if len(target) >= self._capture_target:
            return
        target.append(event)
        remaining = self._capture_target - len(target)
        if remaining > 0:
            self.lbl_wiz_status.setText(
                f"{self._capture_mode.title()} capture: {remaining} hit(s) remaining..."
            )
            return
        self.lbl_wiz_status.setText(f"{self._capture_mode.title()} capture complete.")
        self._capture_mode = None
        self.wiz_preview.set_mode(None)
        self.lbl_wizard_help.setText(
            "Capture complete for this step. Continue with the next capture or apply suggestion."
        )
        self._update_wizard_summary()

    def _apply_suggested(self):
        if self._suggested_impact_mg_100 is None or self._suggested_contact_full_scale_mg is None:
            self.lbl_wiz_status.setText("Capture soft + hard sets first.")
            return
        self.cal_impact_input.setText(str(self._suggested_impact_mg_100))
        self.cal_contact_input.setText(str(self._suggested_contact_full_scale_mg))
        self._apply_calibration_from_inputs()
        self.lbl_wiz_status.setText("Applied suggested calibration to firmware RAM.")
        self.lbl_wizard_help.setText("Suggested calibration applied. Save to firmware when ready.")


class TennisBleWorker(QObject):
    connected = pyqtSignal(bool, str)
    telemetry = pyqtSignal(int, int, int)
    impact = pyqtSignal(int, int, int, int, int, int, int)
    command_rx = pyqtSignal(str)
    status = pyqtSignal(str)
    ble_handshake = pyqtSignal(bool)  # True when connect-time PING got PONG from firmware

    def __init__(self):
        super().__init__()
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: BleakClient | None = None
        self._target_address: str | None = None
        self._pending_cmd_ack: asyncio.Future[str] | None = None

    def stop(self):
        self._running = False
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._disconnect(), self._loop)

    def request_reset(self):
        self.request_command("RESET")

    def request_command(self, text: str):
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._write_command(text), self._loop)

    def run(self):
        self._running = True
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        finally:
            try:
                self._loop.run_until_complete(self._disconnect())
            except Exception:
                pass
            self._loop.close()

    async def _main(self):
        while self._running:
            try:
                device = await self._find_device()
                if not device:
                    self.connected.emit(False, "")
                    self.status.emit("No tennis BLE sensor found, rescanning...")
                    await asyncio.sleep(1.5)
                    continue
                self._target_address = device.address
                self.status.emit(f"Connecting to {device.name} ({device.address})")
                self._client = BleakClient(device)
                await self._client.connect()
                await self._client.start_notify(SENSOR_STATE_UUID, self._on_state)
                await self._client.start_notify(HIT_COUNT_UUID, self._on_count)
                await self._client.start_notify(RATE_X10_UUID, self._on_rate)
                await self._client.start_notify(IMPACT_UUID, self._on_impact)
                await self._client.start_notify(COMMAND_UUID, self._on_command_notify)
                ping_ok = await self._await_command_ack(
                    STREAM_KEEPALIVE_COMMAND, PING_ACK_SUBSTRING, PING_HEALTH_TIMEOUT_S
                )
                self.ble_handshake.emit(ping_ok)
                self.connected.emit(True, device.address)
                if ping_ok:
                    self.status.emit("Connected — health check OK (PONG). Live streaming.")
                else:
                    self.status.emit(
                        "Connected — no PONG before timeout (flash newer firmware?). Live streaming."
                    )
                while self._running and self._client and self._client.is_connected:
                    await asyncio.sleep(0.2)
            except Exception as exc:
                self.status.emit(f"BLE worker error: {exc}")
            finally:
                await self._disconnect()
                self.connected.emit(False, self._target_address or "")
                if self._running:
                    await asyncio.sleep(1.0)

    async def _find_device(self):
        # 1) OS may filter to peripherals that advertise our service (fast on CoreBluetooth).
        filtered = await BleakScanner.discover(
            timeout=BLE_DISCOVER_TIMEOUT_S,
            return_adv=True,
            service_uuids=[TENNIS_SERVICE_UUID],
        )
        picked = _best_tennis_from_adv_map(filtered)
        if picked:
            return picked

        # 2) Full passive scan: match local name OR advertised service UUID (name often None on macOS).
        full = await BleakScanner.discover(timeout=BLE_DISCOVER_TIMEOUT_S, return_adv=True)
        picked = _best_tennis_from_adv_map(full)
        if picked:
            return picked

        # 3) Legacy path if the stack omits advertisement parsing.
        devices = await BleakScanner.discover(timeout=BLE_DISCOVER_TIMEOUT_S)
        for d in devices:
            nm = _device_local_name(d, None)
            if nm and nm.startswith(NAME_PREFIX):
                return d
        return None

    async def _disconnect(self):
        pending = self._pending_cmd_ack
        if pending and not pending.done():
            pending.cancel()
        self._pending_cmd_ack = None
        if self._client:
            try:
                if self._client.is_connected:
                    await self._client.disconnect()
            except Exception:
                pass
        self._client = None

    async def _await_command_ack(self, cmd: str, ack_needle: str, timeout_s: float) -> bool:
        if not self._client or not self._client.is_connected:
            return False
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._pending_cmd_ack = fut
        try:
            await self._client.write_gatt_char(COMMAND_UUID, cmd.encode("utf-8"), response=False)
            payload = await asyncio.wait_for(fut, timeout=timeout_s)
            return ack_needle.upper() in payload.upper()
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return False
        finally:
            self._pending_cmd_ack = None

    async def _write_command(self, text: str):
        if not self._client or not self._client.is_connected:
            return
        try:
            await self._client.write_gatt_char(COMMAND_UUID, text.encode("utf-8"), response=False)
            if text != STREAM_KEEPALIVE_COMMAND:
                self.status.emit(f"Sent command: {text}")
        except Exception as exc:
            self.status.emit(f"Command failed: {exc}")

    def _on_command_notify(self, _sender, data: bytearray):
        try:
            s = bytes(data).decode("utf-8", errors="replace").strip()
        except Exception:
            s = ""
        if s:
            self.command_rx.emit(s)
        pending = self._pending_cmd_ack
        if pending and not pending.done() and s:
            try:
                pending.set_result(s)
            except asyncio.InvalidStateError:
                pass

    def _on_state(self, _sender, data: bytearray):
        if len(data) >= 1:
            self.telemetry.emit(int(data[0]), -1, -1)

    def _on_count(self, _sender, data: bytearray):
        if len(data) >= 4:
            self.telemetry.emit(-1, int(struct.unpack("<I", bytes(data[:4]))[0]), -1)

    def _on_rate(self, _sender, data: bytearray):
        if len(data) >= 2:
            self.telemetry.emit(-1, -1, int(struct.unpack("<H", bytes(data[:2]))[0]))

    def _on_impact(self, _sender, data: bytearray):
        if len(data) >= 13:
            hit_count, x_mg, y_mg, z_mg, intensity, contact_x, contact_y = struct.unpack("<IhhhBbb", bytes(data[:13]))
            self.impact.emit(hit_count, x_mg, y_mg, z_mg, intensity, contact_x, contact_y)


class TennisDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TENNIS SHOT SIMULATOR")
        self.resize(1280, 760)

        self.telemetry = Telemetry()
        self.shots: list[Shot] = []
        self.mode = "SIMULATION"
        self.simulation_enabled = True
        self.paused = False
        self.play_queue = 0

        self._thread: QThread | None = None
        self._worker: TennisBleWorker | None = None
        self._last_keepalive_sent = 0.0
        self._last_stream_recovery = 0.0
        self._impact_by_hit_count: dict[int, tuple[int, int, int]] = {}
        self._last_impact_reading = (0, 0, 0)
        self._profile_store_path = Path(__file__).resolve().with_name(PROFILE_STORE_FILE)
        self._competition_config_path = Path(__file__).resolve().with_name(COMPETITION_CONFIG_FILE)
        self._profiles: dict[str, list[dict]] = {}
        self._competition_profiles: dict[str, dict[str, float]] = {
            lvl: vals.copy() for lvl, vals in DEFAULT_COMPETITION_PROFILES.items()
        }
        self._competition_levels_by_student: dict[str, str] = {}
        self._current_student = "Student 1"
        self._competition_level = DEFAULT_COMPETITION_LEVEL
        self._session_started_at = datetime.now().isoformat(timespec="seconds")
        self._active_session_saved = False
        self._stats_window: StatsBIWindow | None = None
        self._settings_window: SettingsWindow | None = None
        self._fw_calibration = {
            "counts_per_g": 410.0,
            "impact_mg_100": 4200,
            "contact_full_scale_mg": 1500,
        }

        self._build_ui()
        self._apply_style()
        self._load_competition_profiles_config()
        self._load_profiles()
        self._refresh_profile_ui()
        self._refresh_comparison_labels()

        self.sim_timer = QTimer(self)
        self.sim_timer.timeout.connect(self._simulation_tick)
        self.sim_timer.start(1100)

        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self._refresh_ui)
        self.ui_timer.start(80)
        self.live_guard_timer = QTimer(self)
        self.live_guard_timer.timeout.connect(self._live_stream_guard)
        self.live_guard_timer.start(500)

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._tick_clock)
        self.clock_timer.start(1000)
        self._tick_clock()

        if AUTO_DISCOVER_ON_START:
            # Match Ghost-style UX: begin discovery shortly after launch.
            QTimer.singleShot(500, self._auto_start_discovery)

    def _build_ui(self):
        root = QWidget(self)
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # Header
        header = QFrame()
        header.setObjectName("Header")
        hh = QHBoxLayout(header)
        hh.setContentsMargins(10, 6, 10, 6)
        hh.setSpacing(10)

        # Logo dot + title
        logo = QLabel("●")
        logo.setStyleSheet("color:#91d14f; font-size:20px;")
        hh.addWidget(logo)
        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        self.title = QLabel("TENNIS SHOT SIMULATOR")
        self.title.setObjectName("MainTitle")
        self.subtitle = QLabel("Project E.C.H.O")
        self.subtitle.setObjectName("Subtitle")
        title_col.addWidget(self.title)
        title_col.addWidget(self.subtitle)
        hh.addLayout(title_col)
        hh.addStretch(1)

        self.level_chip = QPushButton("LEVEL\nCOMPETITIVE")
        self.level_chip.setObjectName("ChipLevel")
        self.level_chip.setMinimumWidth(120)
        self.level_chip.clicked.connect(self._cycle_competition_level)
        self.level_chip.setToolTip("Click to change level")
        hh.addWidget(self.level_chip)

        self.mode_chip = QLabel("MODE\nSIMULATION")
        self.mode_chip.setObjectName("ChipOk")
        self.mode_chip.setMinimumWidth(95)
        self.sensors_chip = QLabel("SENSORS\nDISCONNECTED")
        self.sensors_chip.setObjectName("ChipErr")
        self.sensors_chip.setMinimumWidth(95)
        self.link_chip = QLabel("HANDSHAKE\n—")
        self.link_chip.setObjectName("ChipMuted")
        self.link_chip.setMinimumWidth(102)
        self.clock_lbl = QLabel("--:--:--\n--- --, ----")
        self.clock_lbl.setObjectName("ClockLabel")
        self.clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.clock_lbl.setMinimumWidth(120)
        hh.addWidget(self.mode_chip)
        hh.addWidget(self.sensors_chip)
        hh.addWidget(self.link_chip)
        hh.addWidget(self.clock_lbl)
        outer.addWidget(header)

        body = QHBoxLayout()
        body.setSpacing(8)
        outer.addLayout(body, 1)

        # Left rail
        left_col = QVBoxLayout()
        left_col.setSpacing(8)
        body.addLayout(left_col, 0)

        self.left_current = self._panel("CURRENT SHOT")
        self.ms_speed = MetricSlider("Ball Speed", 10, 120, "mph")
        self.ms_angle = MetricSlider("Arm Angle", -90, 90, "°")
        self.ms_spin = MetricSlider("Spin Rate", 0, 4000, "rpm")
        self.left_current.layout().addWidget(self.ms_speed)
        self.left_current.layout().addWidget(self.ms_angle)
        self.left_current.layout().addWidget(self.ms_spin)
        self.lbl_impact_xy = QLabel("Impact Offset      +0, +0")
        self.lbl_impact_red = QLabel("Impact Redness     0%")
        self.lbl_impact_xy.setObjectName("SmallMuted")
        self.lbl_impact_red.setObjectName("SmallMuted")
        self.left_current.layout().addWidget(self.lbl_impact_xy)
        self.left_current.layout().addWidget(self.lbl_impact_red)
        left_col.addWidget(self.left_current)

        self.left_pred = self._panel("PREDICTED LANDING")
        self.lbl_land_x = QLabel("X (Cross Court)   0.00 m")
        self.lbl_land_y = QLabel("Y (Down Court)    0.00 m")
        self.left_pred.layout().addWidget(self.lbl_land_x)
        self.left_pred.layout().addWidget(self.lbl_land_y)
        left_col.addWidget(self.left_pred)

        self.left_stats = self._panel("SHOT STATISTICS")
        top_stats = QHBoxLayout()
        self.stat_total = self._mini_stat("Total Shots", "0")
        self.stat_avg = self._mini_stat("Avg. Speed", "0.0 mph")
        self.stat_cons = self._mini_stat("Consistency", "0%")
        top_stats.addWidget(self.stat_total)
        top_stats.addWidget(self.stat_avg)
        top_stats.addWidget(self.stat_cons)
        self.left_stats.layout().addLayout(top_stats)
        breakdown = QLabel("Shots by Speed Range\n\n● Slow (< 40 mph)\n● Medium (40-70 mph)\n● Fast (> 70 mph)")
        breakdown.setObjectName("SmallMuted")
        self.left_stats.layout().addWidget(breakdown)
        donut_row = QHBoxLayout()
        self.donut = DonutWidget()
        donut_row.addWidget(self.donut)
        self.lbl_dist = QLabel("25%\n50%\n25%")
        self.lbl_dist.setObjectName("SmallMuted")
        donut_row.addWidget(self.lbl_dist)
        self.left_stats.layout().addLayout(donut_row)
        left_col.addWidget(self.left_stats, 1)

        left_actions = QHBoxLayout()
        self.btn_clear = QPushButton("CLEAR SHOTS")
        self.btn_export = QPushButton("EXPORT DATA")
        left_actions.addWidget(self.btn_clear)
        left_actions.addWidget(self.btn_export)
        left_col.addLayout(left_actions)

        # Right side
        right_col = QVBoxLayout()
        right_col.setSpacing(8)
        body.addLayout(right_col, 1)

        self.court_panel = self._panel("VIRTUAL TENNIS COURT")
        # top-right utility icons in panel header area
        icons = QHBoxLayout()
        icons.addStretch(1)
        icon_specs = [
            ("📊", "Open Students & Stats", self._open_stats_screen),
            ("⚙", "Open Settings (Calibration)", self._open_settings_screen),
            ("⤢", "Fullscreen view (coming soon)", None),
        ]
        for glyph, tooltip, callback in icon_specs:
            b = QPushButton(glyph)
            b.setObjectName("IconBtn")
            b.setFixedSize(30, 22)
            b.setToolTip(tooltip)
            if callback is not None:
                b.clicked.connect(callback)
            icons.addWidget(b)
        self.court_panel.layout().addLayout(icons)
        self.court_widget = CourtWidget()
        self.court_panel.layout().addWidget(self.court_widget)
        right_col.addWidget(self.court_panel, 3)

        lower = QHBoxLayout()
        lower.setSpacing(8)
        right_col.addLayout(lower, 2)

        self.heat_panel = self._panel("SHOT DISTRIBUTION (HEATMAP)")
        self.heat_widget = HeatmapWidget()
        self.heat_panel.layout().addWidget(self.heat_widget)
        lower.addWidget(self.heat_panel, 2)

        self.impact_panel = self._panel("TENNIS BALL IMPACT SIMULATOR")
        self.impact_widget = TennisBallImpactWidget()
        self.impact_panel.layout().addWidget(self.impact_widget)
        lower.addWidget(self.impact_panel, 1)

        self.history_panel = self._panel("SHOT HISTORY")
        self.history_table = QTableWidget(0, 7)
        self.history_table.setHorizontalHeaderLabels(
            ["#", "TIME", "SPEED (mph)", "ARM ANGLE", "LANDING (X,Y)", "SPIN", "IMPACT"]
        )
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_panel.layout().addWidget(self.history_table)
        lower.addWidget(self.history_panel, 2)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.btn_connect = QPushButton("CONNECT SENSOR")
        self.btn_connect.setObjectName("SecondaryBtn")
        self.btn_new = QPushButton("NEW RANDOM SHOT")
        self.btn_new.setObjectName("PrimaryBtn")
        self.btn_play10 = QPushButton("PLAY 10 SHOTS")
        self.btn_play10.setObjectName("SecondaryBtn")
        self.btn_pause = QPushButton("PAUSE")
        self.btn_pause.setObjectName("SecondaryBtn")
        self.btn_reset_session = QPushButton("RESET SESSION")
        self.btn_reset_session.setObjectName("SecondaryBtn")
        self.btn_disconnect = QPushButton("DISCONNECT")
        self.btn_disconnect.setObjectName("SecondaryBtn")
        for btn in (
            self.btn_connect,
            self.btn_new,
            self.btn_play10,
            self.btn_pause,
            self.btn_reset_session,
            self.btn_disconnect,
        ):
            bottom.addWidget(btn)
        outer.addLayout(bottom)

        self.statusBar().showMessage(
            "Simulation active until a real TENNIS_KY003 sensor is found (auto-scan on) or you press CONNECT SENSOR."
        )

        self.btn_connect.clicked.connect(self.start_worker)
        self.btn_disconnect.clicked.connect(self.stop_worker)
        self.btn_new.clicked.connect(self._add_simulated_shot)
        self.btn_play10.clicked.connect(self._queue_10_shots)
        self.btn_pause.clicked.connect(self._toggle_pause)
        self.btn_reset_session.clicked.connect(self._reset_session)
        self.btn_clear.clicked.connect(self._clear_shots)
        self.btn_export.clicked.connect(self._export_csv)

    def _auto_start_discovery(self):
        if self._thread and self._thread.isRunning():
            return
        self.statusBar().showMessage("Auto-discovery enabled: scanning for tennis BLE sensor...")
        self.start_worker()

    def _reset_link_badge(self):
        self.link_chip.setText("HANDSHAKE\n—")
        self.link_chip.setObjectName("ChipMuted")
        self.link_chip.style().polish(self.link_chip)

    def _panel(self, title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Panel")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)
        lbl = QLabel(title)
        lbl.setObjectName("PanelTitle")
        lay.addWidget(lbl)
        return frame

    def _mini_stat(self, title: str, value: str) -> QFrame:
        box = QFrame()
        box.setObjectName("MiniStat")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("MiniStatTitle")
        v = QLabel(value)
        v.setObjectName("MiniStatValue")
        lay.addWidget(t)
        lay.addWidget(v)
        box._value_label = v  # type: ignore[attr-defined]
        return box

    def _load_profiles(self):
        if not self._profile_store_path.exists():
            self._profiles = {self._current_student: []}
            self._competition_levels_by_student = {self._current_student: DEFAULT_COMPETITION_LEVEL}
            self._save_profiles()
            return
        try:
            payload = json.loads(self._profile_store_path.read_text(encoding="utf-8"))
            raw_profiles = payload.get("profiles", {})
            raw_levels = payload.get("competition_levels", {})
            if isinstance(raw_profiles, dict):
                clean_profiles: dict[str, list[dict]] = {}
                for name, sessions in raw_profiles.items():
                    if not isinstance(name, str):
                        continue
                    if not isinstance(sessions, list):
                        continue
                    clean_profiles[name] = [s for s in sessions if isinstance(s, dict)]
                self._profiles = clean_profiles or {self._current_student: []}
            else:
                self._profiles = {self._current_student: []}
            if isinstance(raw_levels, dict):
                levels: dict[str, str] = {}
                for k, v in raw_levels.items():
                    if isinstance(k, str) and isinstance(v, str) and v in self._competition_profiles:
                        levels[k] = v
                self._competition_levels_by_student = levels
            else:
                self._competition_levels_by_student = {}
        except (OSError, json.JSONDecodeError):
            self._profiles = {self._current_student: []}
            self._competition_levels_by_student = {}
        if self._current_student not in self._profiles:
            self._current_student = sorted(self._profiles.keys())[0]
        for name in self._profiles:
            if name not in self._competition_levels_by_student:
                self._competition_levels_by_student[name] = DEFAULT_COMPETITION_LEVEL
        self._competition_level = self._competition_levels_by_student.get(
            self._current_student, DEFAULT_COMPETITION_LEVEL
        )
        if self._competition_level not in self._competition_profiles:
            self._competition_level = DEFAULT_COMPETITION_LEVEL

    def _load_competition_profiles_config(self):
        self._competition_profiles = {
            lvl: vals.copy() for lvl, vals in DEFAULT_COMPETITION_PROFILES.items()
        }
        if not self._competition_config_path.exists():
            return
        try:
            payload = json.loads(self._competition_config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        for level, defaults in DEFAULT_COMPETITION_PROFILES.items():
            candidate = payload.get(level)
            if not isinstance(candidate, dict):
                continue
            for key, default_val in defaults.items():
                raw = candidate.get(key, default_val)
                if isinstance(raw, (int, float)):
                    self._competition_profiles[level][key] = float(raw)
        self._sanitize_competition_profiles()

    def _save_competition_profiles_config(self):
        self._sanitize_competition_profiles()
        self._competition_config_path.write_text(
            json.dumps(self._competition_profiles, indent=2),
            encoding="utf-8",
        )

    def _sanitize_competition_profiles(self):
        for level, defaults in DEFAULT_COMPETITION_PROFILES.items():
            current = self._competition_profiles.setdefault(level, {})
            for key, default_val in defaults.items():
                v = current.get(key, default_val)
                if not isinstance(v, (int, float)):
                    current[key] = float(default_val)
                else:
                    current[key] = float(v)
            for min_key, max_key in (
                ("sim_speed_min", "sim_speed_max"),
                ("sim_spin_min", "sim_spin_max"),
                ("live_speed_min", "live_speed_max"),
                ("live_spin_min", "live_spin_max"),
            ):
                if current[min_key] > current[max_key]:
                    current[min_key], current[max_key] = current[max_key], current[min_key]
            if current["sim_impact_abs"] < 1:
                current["sim_impact_abs"] = defaults["sim_impact_abs"]
            if current["live_arm_abs"] < 1:
                current["live_arm_abs"] = defaults["live_arm_abs"]

    def _save_profiles(self):
        payload = {
            "profiles": self._profiles,
            "competition_levels": self._competition_levels_by_student,
        }
        self._profile_store_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _refresh_profile_ui(self):
        names = sorted(self._profiles.keys())
        if not names:
            self._profiles[self._current_student] = []
            names = [self._current_student]
        if self._current_student not in self._profiles:
            self._current_student = names[0]
        for n in names:
            if n not in self._competition_levels_by_student:
                self._competition_levels_by_student[n] = DEFAULT_COMPETITION_LEVEL
        self._competition_level = self._competition_levels_by_student.get(
            self._current_student, DEFAULT_COMPETITION_LEVEL
        )
        if self._competition_level not in self._competition_profiles:
            self._competition_level = DEFAULT_COMPETITION_LEVEL
        self._refresh_competition_toggle()
        if self._stats_window is not None:
            self._stats_window.refresh()

    def _refresh_competition_toggle(self):
        if not hasattr(self, "level_chip"):
            return
        short = {
            "Newbie": "NEWBIE",
            "Competitive": "COMPETITIVE",
            "Professional": "PRO",
        }.get(self._competition_level, self._competition_level.upper())
        self.level_chip.setText(f"LEVEL\n{short}")
        palette = {
            "Newbie": {
                "border": "#2b5f8f",
                "bg": "#0a2943",
                "hover": "#10375a",
                "fg": "#8fd0ff",
            },
            "Competitive": {
                "border": "#8a6a2a",
                "bg": "#2a2210",
                "hover": "#3a2c12",
                "fg": "#ffd78a",
            },
            "Professional": {
                "border": "#2a6c54",
                "bg": "#05291f",
                "hover": "#083629",
                "fg": "#8ff0af",
            },
        }.get(
            self._competition_level,
            {
                "border": "#2a6c54",
                "bg": "#05291f",
                "hover": "#083629",
                "fg": "#8ff0af",
            },
        )
        self.level_chip.setStyleSheet(
            f"""
            QPushButton {{
                border: 1px solid {palette['border']};
                border-radius: 7px;
                padding: 6px;
                font-size: 10px;
                font-weight: 800;
                color: {palette['fg']};
                background: {palette['bg']};
            }}
            QPushButton:hover {{
                background: {palette['hover']};
            }}
            """
        )

    def _cycle_competition_level(self):
        levels = list(self._competition_profiles.keys())
        if not levels:
            return
        try:
            idx = levels.index(self._competition_level)
        except ValueError:
            idx = 0
        next_level = levels[(idx + 1) % len(levels)]
        self._set_competition_level(next_level)

    def _on_profile_selected(self, name: str):
        if not name:
            return
        if name != self._current_student and self.shots and not self._active_session_saved:
            self._save_current_session()
        self._current_student = name
        self._competition_level = self._competition_levels_by_student.get(
            self._current_student, DEFAULT_COMPETITION_LEVEL
        )
        self._refresh_profile_ui()
        self._refresh_comparison_labels()
        self.statusBar().showMessage(f"Loaded profile: {name}")

    def _create_profile(self):
        name, ok = QInputDialog.getText(self, "Create Student Profile", "Student name:")
        if not ok:
            return
        cleaned = name.strip()
        if not cleaned:
            return
        if cleaned not in self._profiles:
            self._profiles[cleaned] = []
            self._competition_levels_by_student[cleaned] = DEFAULT_COMPETITION_LEVEL
            self._save_profiles()
        self._current_student = cleaned
        self._competition_level = self._competition_levels_by_student.get(
            self._current_student, DEFAULT_COMPETITION_LEVEL
        )
        self._refresh_profile_ui()
        self._refresh_comparison_labels()
        self.statusBar().showMessage(f"Profile ready: {cleaned}")

    @staticmethod
    def _session_metrics_from_shots(shots: list[Shot]) -> SessionSummary:
        total = len(shots)
        avg_speed = sum(s.speed for s in shots) / total if total else 0.0
        avg_spin = sum(s.spin for s in shots) / total if total else 0.0
        fast_pct = (sum(1 for s in shots if s.speed > 70) * 100.0 / total) if total else 0.0
        avg_red = sum(s.impact_redness for s in shots) / total if total else 0.0
        consistency = 0
        if total >= 2:
            sx = _stddev([s.landing_x for s in shots])
            sy = _stddev([s.landing_y for s in shots])
            sv = _stddev([s.speed for s in shots])
            consistency = int(max(0, min(99, 100.0 - (sx * 10.0 + sy * 5.3 + sv * 0.72))))
        return SessionSummary(
            student="",
            started_at=datetime.now().isoformat(timespec="seconds"),
            shot_count=total,
            avg_speed=avg_speed,
            avg_spin=avg_spin,
            consistency=consistency,
            fast_pct=fast_pct,
            avg_impact_redness=avg_red,
        )

    @staticmethod
    def _fmt_delta(delta: float, suffix: str = "") -> str:
        return f"{delta:+.1f}{suffix}"

    def _current_competition_profile(self) -> dict[str, float]:
        return self._competition_profiles.get(
            self._competition_level, self._competition_profiles[DEFAULT_COMPETITION_LEVEL]
        )

    def _set_competition_level(self, level: str):
        if level not in self._competition_profiles:
            return
        self._competition_level = level
        self._competition_levels_by_student[self._current_student] = level
        self._save_profiles()
        self._refresh_profile_ui()
        self.statusBar().showMessage(f"Competition level set to {level} for {self._current_student}.")

    @staticmethod
    def _ratio_score(actual: float, target: float) -> float:
        if target <= 1e-6:
            return 0.0
        v = (actual / target) * 100.0
        return max(0.0, min(v, 120.0))

    def _elite_alignment_for_summary(self, summary: SessionSummary) -> dict[str, float]:
        prof = self._current_competition_profile()
        speed_score = self._ratio_score(summary.avg_speed, prof["target_speed"])
        spin_score = self._ratio_score(summary.avg_spin, prof["target_spin"])
        consistency_score = self._ratio_score(float(summary.consistency), prof["target_consistency"])
        fast_score = self._ratio_score(summary.fast_pct, prof["target_fast_pct"])
        impact_score = self._ratio_score(summary.avg_impact_redness, prof["target_impact"])
        score = (
            speed_score * 0.30
            + spin_score * 0.24
            + consistency_score * 0.22
            + fast_score * 0.14
            + impact_score * 0.10
        )
        return {
            "score": max(0.0, min(score, 120.0)),
            "speed": speed_score,
            "spin": spin_score,
            "consistency": consistency_score,
            "fast": fast_score,
            "impact": impact_score,
        }

    def _set_calibration_status(self, text: str):
        if self._settings_window is not None:
            self._settings_window.set_calibration_status(text)

    def _refresh_calibration_ui(self):
        if self._settings_window is not None:
            self._settings_window.set_calibration_values(
                self._fw_calibration["counts_per_g"],
                int(self._fw_calibration["impact_mg_100"]),
                int(self._fw_calibration["contact_full_scale_mg"]),
            )

    def _send_worker_command(self, text: str) -> bool:
        if not self._worker:
            self.statusBar().showMessage("Sensor not connected.")
            return False
        self._worker.request_command(text)
        return True

    def _request_firmware_calibration(self):
        if self._send_worker_command(CAL_GET_COMMAND):
            self._set_calibration_status("Requested calibration from firmware...")

    def _apply_firmware_calibration_from_ui(self, counts_txt: str, impact_txt: str, contact_txt: str):
        try:
            counts_per_g = float(counts_txt)
            impact_mg_100 = int(float(impact_txt))
            contact_full_scale_mg = int(float(contact_txt))
        except ValueError:
            self._set_calibration_status("Calibration values invalid.")
            return

        if counts_per_g < 50.0 or impact_mg_100 < 100 or contact_full_scale_mg < 100:
            self._set_calibration_status("Calibration values out of range.")
            return

        cmd = f"CAL:SET:{counts_per_g:.2f},{impact_mg_100},{contact_full_scale_mg}"
        if self._send_worker_command(cmd):
            self._set_calibration_status("Applied calibration in firmware RAM.")

    def _save_firmware_calibration(self):
        if self._send_worker_command(CAL_SAVE_COMMAND):
            self._set_calibration_status("Saving calibration to firmware NVS...")

    def _reset_firmware_calibration(self):
        if self._send_worker_command(CAL_RESET_COMMAND):
            self._set_calibration_status("Resetting calibration to defaults...")

    def _on_command_rx(self, text: str):
        if text.startswith("CAL:CFG:"):
            raw = text[len("CAL:CFG:"):]
            parts = raw.split(",")
            if len(parts) == 3:
                try:
                    self._fw_calibration["counts_per_g"] = float(parts[0])
                    self._fw_calibration["impact_mg_100"] = int(parts[1])
                    self._fw_calibration["contact_full_scale_mg"] = int(parts[2])
                    self._refresh_calibration_ui()
                    self._set_calibration_status("Firmware calibration loaded.")
                except ValueError:
                    self._set_calibration_status("Firmware calibration parse error.")
            return
        if text.startswith("CAL:SAVE:"):
            self._set_calibration_status("Calibration saved to firmware." if text.endswith("OK") else "Calibration save failed.")
            return
        if text.startswith("CAL:RESET:"):
            self._set_calibration_status("Calibration reset in firmware." if text.endswith("OK") else "Calibration reset failed.")
            return
        if text.startswith("CAL:SET:"):
            self._set_calibration_status("Calibration applied." if text.endswith("OK") else "Calibration apply failed.")

    def _refresh_comparison_labels(self):
        if self._stats_window is not None:
            self._stats_window.refresh()

    def _comparison_strings(self) -> tuple[str, str, str, str, str]:
        sessions = self._profiles.get(self._current_student, [])
        if len(sessions) < 2:
            return (
                "Save at least 2 sessions to compare.",
                "Avg speed Δ   +0.0 mph",
                "Avg spin Δ    +0 rpm",
                "Consistency Δ +0%",
                "Impact Δ      +0.0%",
            )
        prev = sessions[-2]
        latest = sessions[-1]
        return (
            f"{latest.get('started_at', 'latest')} vs {prev.get('started_at', 'previous')}",
            "Avg speed Δ   "
            + self._fmt_delta(float(latest.get("avg_speed", 0.0)) - float(prev.get("avg_speed", 0.0)), " mph"),
            "Avg spin Δ    "
            + self._fmt_delta(float(latest.get("avg_spin", 0.0)) - float(prev.get("avg_spin", 0.0)), " rpm"),
            "Consistency Δ "
            + self._fmt_delta(float(latest.get("consistency", 0.0)) - float(prev.get("consistency", 0.0)), "%"),
            "Impact Δ      "
            + self._fmt_delta(
                float(latest.get("avg_impact_redness", 0.0)) - float(prev.get("avg_impact_redness", 0.0)),
                "%",
            ),
        )

    def _open_stats_screen(self):
        if self._stats_window is None:
            self._stats_window = StatsBIWindow(self)
            self._stats_window.setStyleSheet(self.styleSheet())
        self._stats_window.refresh()
        self._stats_window.show()
        self._stats_window.raise_()
        self._stats_window.activateWindow()

    def _open_settings_screen(self):
        if self._settings_window is None:
            self._settings_window = SettingsWindow(self)
            self._settings_window.setStyleSheet(self.styleSheet())
        self._refresh_calibration_ui()
        self._settings_window.refresh()
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()
        if self.mode == "LIVE" and self._worker:
            self._request_firmware_calibration()

    def _save_current_session(self):
        if not self.shots:
            self.statusBar().showMessage("No shots to save for this session.")
            return
        summary = self._session_metrics_from_shots(self.shots)
        summary.student = self._current_student
        summary.started_at = self._session_started_at
        entry = {
            "student": summary.student,
            "competition_level": self._competition_level,
            "started_at": summary.started_at,
            "shot_count": summary.shot_count,
            "avg_speed": round(summary.avg_speed, 2),
            "avg_spin": round(summary.avg_spin, 2),
            "consistency": summary.consistency,
            "fast_pct": round(summary.fast_pct, 2),
            "avg_impact_redness": round(summary.avg_impact_redness, 2),
        }
        sessions = self._profiles.setdefault(self._current_student, [])
        if (
            self._active_session_saved
            and sessions
            and sessions[-1].get("started_at") == self._session_started_at
        ):
            sessions[-1] = entry
        else:
            sessions.append(entry)
        if len(sessions) > MAX_SESSIONS_PER_STUDENT:
            self._profiles[self._current_student] = sessions[-MAX_SESSIONS_PER_STUDENT:]
        self._save_profiles()
        self._active_session_saved = True
        self._refresh_profile_ui()
        self._refresh_comparison_labels()
        self.statusBar().showMessage(
            f"Saved session for {self._current_student}: {summary.shot_count} shots, {summary.avg_speed:.1f} mph avg."
        )

    def _apply_style(self):
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #040d1a; color: #d8e4f3; font-family: Arial; }
            #Header { background: #041126; border: 1px solid #0d2b4a; border-radius: 7px; }
            #MainTitle { color: #eef5ff; font-size: 18px; font-weight: 800; letter-spacing: 0.8px; }
            #Subtitle { color: #8cd27d; font-size: 11px; }
            #Panel { background: #08172d; border: 1px solid #103559; border-radius: 7px; }
            #PanelTitle { color: #31e46a; font-size: 12px; font-weight: 800; }
            #MiniStat { background: #0a1b34; border: 1px solid #1a3e64; border-radius: 6px; }
            #MiniStatTitle { color: #9db5ce; font-size: 10px; }
            #MiniStatValue { color: #e9f2ff; font-size: 15px; font-weight: 800; }
            #SmallMuted { color: #a1b5cc; font-size: 10px; }
            #ChipOk, #ChipErr, #ChipMuted, #ChipLinkOk, #ChipLinkWarn {
                border: 1px solid #1f4368; border-radius: 7px; padding: 6px;
                font-size: 10px; font-weight: 800; qproperty-alignment: AlignCenter;
            }
            #ChipOk { color: #8ff0af; }
            #ChipErr { color: #ff7f7f; }
            #ChipMuted { color: #7a8fa8; border-color: #223952; }
            #ChipLinkOk { color: #b8f7ff; border-color: #2a9db8; background: #062a35; }
            #ChipLinkWarn { color: #ffd78a; border-color: #8a6a2a; background: #2a2210; }
            #ClockLabel { color: #d8e5f7; font-size: 11px; font-weight: 600; }
            QPushButton {
                background: #103154; border: 1px solid #255784; border-radius: 7px;
                padding: 8px 10px; color: #d6e8fb; font-weight: 800; font-size: 11px;
            }
            QPushButton:hover { background: #17406c; }
            QComboBox {
                background: #0a1b34;
                border: 1px solid #2a5278;
                border-radius: 6px;
                padding: 4px 8px;
                color: #d6e8fb;
                min-height: 24px;
            }
            QComboBox QAbstractItemView {
                background: #0a1b34;
                color: #d6e8fb;
                selection-background-color: #17406c;
            }
            #ChipLevel {
                border-radius: 7px;
                padding: 6px;
                font-size: 10px;
                font-weight: 800;
            }
            QPushButton#PrimaryBtn {
                background: #2f7d2b; border: 1px solid #4da24a; color: #f1fff0;
            }
            QPushButton#PrimaryBtn:hover { background: #3e9a39; }
            QPushButton#IconBtn {
                background: #0d2d50; border: 1px solid #2d5886; border-radius: 5px;
                padding: 0px; font-size: 12px;
            }
            QTabWidget::pane {
                border: 1px solid #1a3f66;
                background: #061427;
                border-radius: 7px;
                top: -1px;
            }
            QTabBar::tab {
                background: #0a1f38;
                border: 1px solid #1a3f66;
                border-bottom: none;
                color: #9bb7d3;
                padding: 6px 12px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 10px;
                font-weight: 700;
            }
            QTabBar::tab:selected {
                background: #103154;
                color: #dbeaff;
            }
            QTabBar::tab:hover:!selected {
                background: #12375d;
                color: #c7dcf5;
            }
            QTableWidget {
                background: #061427;
                alternate-background-color: #0a1a33;
                border: 1px solid #1a3f66;
                gridline-color: #17395e;
                font-size: 11px;
            }
            QHeaderView::section {
                background: #0d2d4f;
                color: #c1d0e4;
                border: 1px solid #1a3f66;
                padding: 4px;
                font-size: 10px;
                font-weight: 800;
            }
            """
        )

    def _tick_clock(self):
        now = datetime.now()
        self.clock_lbl.setText(now.strftime("%I:%M:%S %p\n%b %d, %Y"))

    def _simulation_tick(self):
        if self.paused:
            return
        if self.play_queue > 0:
            self._add_simulated_shot()
            self.play_queue -= 1
            return
        if self.simulation_enabled:
            self._add_simulated_shot()

    def _queue_10_shots(self):
        self.play_queue = 10

    def _toggle_pause(self):
        self.paused = not self.paused
        self.btn_pause.setText("RESUME" if self.paused else "PAUSE")

    def _clear_shots(self):
        if self.shots and not self._active_session_saved:
            self._save_current_session()
        self._reset_local_session_data()
        self.statusBar().showMessage("Shot history cleared.")

    def _reset_local_session_data(self):
        self.shots.clear()
        self.telemetry.count = 0
        self.telemetry.rate_x10 = 0
        self.telemetry.state = 0
        self.play_queue = 0
        self._impact_by_hit_count.clear()
        self._last_impact_reading = (0, 0, 0)
        self._session_started_at = datetime.now().isoformat(timespec="seconds")
        self._active_session_saved = False
        self._refresh_ui(force=True)

    def _reset_session(self):
        if self.shots and not self._active_session_saved:
            self._save_current_session()
        self._reset_local_session_data()
        if self._worker and self.mode == "LIVE":
            self._worker.request_reset()
            self._worker.request_command(STREAM_ARM_COMMAND)
            self.statusBar().showMessage("Session reset: dashboard cleared and sensor counter reset.")
        else:
            self.statusBar().showMessage("Session reset: dashboard cleared (simulation mode).")

    def _export_csv(self):
        if not self.shots:
            self.statusBar().showMessage("No shots to export.")
            return
        safe_student = self._current_student.strip().lower().replace(" ", "_")
        default_name = f"{safe_student}_tennis_shots.csv" if safe_student else "tennis_shots.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export Shot Data", default_name, "CSV Files (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "idx",
                "time",
                "speed_mph",
                "arm_angle_deg",
                "spin_rpm",
                "landing_x_m",
                "landing_y_m",
                "impact_x_pct",
                "impact_y_pct",
                "impact_redness_pct",
            ])
            for s in self.shots:
                w.writerow([
                    s.idx,
                    s.timestamp,
                    f"{s.speed:.1f}",
                    f"{s.arm_angle:.1f}",
                    s.spin,
                    f"{s.landing_x:.2f}",
                    f"{s.landing_y:.2f}",
                    s.impact_x,
                    s.impact_y,
                    s.impact_redness,
                ])
        self.statusBar().showMessage(f"Exported {len(self.shots)} shots to {path}")

    def _add_simulated_shot(self):
        prof = self._current_competition_profile()
        speed = random.uniform(prof["sim_speed_min"], prof["sim_speed_max"])
        arm = random.uniform(-32.0, 32.0)
        spin = int(random.uniform(prof["sim_spin_min"], prof["sim_spin_max"]))
        land_x = max(-3.8, min(3.8, random.gauss(0.0, prof["sim_land_sigma_x"])))
        land_y = max(1.2, min(10.8, random.gauss(prof["sim_land_center_y"], prof["sim_land_sigma_y"])))
        impact_abs = int(prof["sim_impact_abs"])
        impact_x = int(random.uniform(-impact_abs, impact_abs))
        impact_y = int(random.uniform(-impact_abs, impact_abs))
        redness = int(random.uniform(prof["sim_red_min"], prof["sim_red_max"]))
        self._append_shot(speed, arm, spin, land_x, land_y, impact_x, impact_y, redness)

    def _append_shot(
        self,
        speed: float,
        arm_angle: float,
        spin: int,
        landing_x: float,
        landing_y: float,
        impact_x: int = 0,
        impact_y: int = 0,
        impact_redness: int = 0,
    ):
        shot = Shot(
            idx=(self.shots[-1].idx + 1) if self.shots else 1,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            speed=speed,
            arm_angle=arm_angle,
            spin=spin,
            landing_x=landing_x,
            landing_y=landing_y,
            impact_x=impact_x,
            impact_y=impact_y,
            impact_redness=impact_redness,
        )
        self.shots.append(shot)
        if len(self.shots) > 300:
            self.shots = self.shots[-300:]
        self._active_session_saved = False

    def start_worker(self):
        if self._thread and self._thread.isRunning():
            return
        self.statusBar().showMessage("Connecting to real sensor...")
        self.link_chip.setText("HANDSHAKE\n…")
        self.link_chip.setObjectName("ChipMuted")
        self.link_chip.style().polish(self.link_chip)
        self._thread = QThread()
        self._worker = TennisBleWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.connected.connect(self._on_connected)
        self._worker.ble_handshake.connect(self._on_ble_handshake)
        self._worker.telemetry.connect(self._on_telemetry)
        self._worker.impact.connect(self._on_impact_packet)
        self._worker.command_rx.connect(self._on_command_rx)
        self._worker.status.connect(self._on_status)
        self._thread.start()

    def stop_worker(self):
        if self._worker:
            self._worker.request_command(STREAM_DISARM_COMMAND)
            self._worker.stop()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)
        self._thread = None
        self._worker = None
        self._impact_by_hit_count.clear()
        self._last_impact_reading = (0, 0, 0)
        self.mode = "SIMULATION"
        self.simulation_enabled = True
        self.mode_chip.setText("MODE\nSIMULATION")
        self.sensors_chip.setText("SENSORS\nDISCONNECTED")
        self.sensors_chip.setObjectName("ChipErr")
        self.sensors_chip.style().polish(self.sensors_chip)
        self._reset_link_badge()
        self.statusBar().showMessage(
            "Simulation active until a real TENNIS_KY003 sensor is found (auto-scan on) or you press CONNECT SENSOR."
        )

    def _on_ble_handshake(self, pong_ok: bool):
        if pong_ok:
            self.link_chip.setText("HANDSHAKE\nPONG ✓")
            self.link_chip.setObjectName("ChipLinkOk")
        else:
            self.link_chip.setText("HANDSHAKE\nNO PONG")
            self.link_chip.setObjectName("ChipLinkWarn")
        self.link_chip.style().polish(self.link_chip)

    def _on_connected(self, ok: bool, addr: str):
        if ok:
            self.mode = "LIVE"
            self.simulation_enabled = False
            self.telemetry.ts = time.time()
            self._last_keepalive_sent = 0.0
            self.mode_chip.setText("MODE\nLIVE")
            self.sensors_chip.setText("SENSORS\nCONNECTED")
            self.sensors_chip.setObjectName("ChipOk")
            if self._worker:
                self._worker.request_command(STREAM_ARM_COMMAND)
                self._worker.request_command(CAL_GET_COMMAND)
            self.statusBar().showMessage(f"Connected to sensor: {addr}")
        else:
            self.mode = "SIMULATION"
            self.simulation_enabled = True
            self._impact_by_hit_count.clear()
            self._last_impact_reading = (0, 0, 0)
            self.mode_chip.setText("MODE\nSIMULATION")
            self.sensors_chip.setText("SENSORS\nDISCONNECTED")
            self.sensors_chip.setObjectName("ChipErr")
            self._reset_link_badge()
        self.sensors_chip.style().polish(self.sensors_chip)

    def _on_status(self, msg: str):
        self.statusBar().showMessage(msg)

    def _on_impact_packet(
        self,
        hit_count: int,
        x_mg: int,
        y_mg: int,
        z_mg: int,
        intensity: int,
        contact_x: int,
        contact_y: int,
    ):
        mag_mg = math.sqrt(float(x_mg * x_mg + y_mg * y_mg + z_mg * z_mg))
        self._impact_by_hit_count[hit_count] = (contact_x, contact_y, intensity)
        self._last_impact_reading = (contact_x, contact_y, intensity)
        if self._settings_window is not None:
            self._settings_window.on_impact_event(
                {
                    "hit_count": hit_count,
                    "x_mg": x_mg,
                    "y_mg": y_mg,
                    "z_mg": z_mg,
                    "mag_mg": mag_mg,
                    "intensity": intensity,
                }
            )
        if len(self._impact_by_hit_count) > 128:
            old = sorted(self._impact_by_hit_count.keys())[:-64]
            for key in old:
                self._impact_by_hit_count.pop(key, None)

    def _on_telemetry(self, state: int, count: int, rate_x10: int):
        if state >= 0:
            self.telemetry.state = state
        if rate_x10 >= 0:
            self.telemetry.rate_x10 = rate_x10
        if count >= 0:
            prev = self.telemetry.count
            self.telemetry.count = count
            if self.mode == "LIVE" and count > prev:
                steps = min(count - prev, 3)
                for i in range(steps):
                    event_count = prev + i + 1
                    impact = self._impact_by_hit_count.pop(event_count, None)
                    if impact is None:
                        impact = self._last_impact_reading
                    impact_x, impact_y, redness = impact
                    prof = self._current_competition_profile()
                    rate = self.telemetry.rate_x10 / 10.0
                    speed = max(
                        prof["live_speed_min"],
                        min(
                            prof["live_speed_max"],
                            prof["live_speed_base"]
                            + rate * prof["live_rate_mul"]
                            + (redness * prof["live_red_mul"])
                            + random.uniform(-2.0, 2.0),
                        ),
                    )
                    arm = max(
                        -prof["live_arm_abs"],
                        min(prof["live_arm_abs"], random.uniform(-18.0, 18.0) + impact_x * 0.34),
                    )
                    spin = int(
                        max(
                            prof["live_spin_min"],
                            min(
                                prof["live_spin_max"],
                                prof["live_spin_base"]
                                + rate * prof["live_spin_rate_mul"]
                                + abs(impact_y) * prof["live_spin_impact_mul"]
                                + random.uniform(-95, 110),
                            ),
                        )
                    )
                    lx = max(-3.6, min(3.6, random.gauss(arm / 30.0 + impact_x / 150.0, 1.0)))
                    ly = max(1.2, min(10.9, random.gauss(7.2 + impact_y / 115.0, 1.3)))
                    self._append_shot(speed, arm, spin, lx, ly, impact_x, impact_y, redness)
        self.telemetry.ts = time.time()

    def _live_stream_guard(self):
        if self.mode != "LIVE" or not self._worker:
            return
        now = time.time()
        if (now - self._last_keepalive_sent) >= STREAM_KEEPALIVE_INTERVAL_S:
            self._worker.request_command(STREAM_KEEPALIVE_COMMAND)
            self._last_keepalive_sent = now

        if self.telemetry.ts <= 0:
            return
        stale_for = now - self.telemetry.ts
        if stale_for < LIVE_STREAM_STALE_TIMEOUT_S:
            return
        if (now - self._last_stream_recovery) < LIVE_STREAM_RECOVERY_COOLDOWN_S:
            return

        self._last_stream_recovery = now
        self.statusBar().showMessage("Live stream stale. Re-arming realtime telemetry...")
        self._worker.request_command(STREAM_ARM_COMMAND)

    def _refresh_ui(self, force: bool = False):
        if not self.shots and not force:
            return
        latest = self.shots[-1] if self.shots else None
        if latest:
            self.ms_speed.set_value(latest.speed, "#90df6a")
            self.ms_angle.set_value(latest.arm_angle, "#f7cc32")
            self.ms_spin.set_value(latest.spin, "#4a95ff")
            self.lbl_land_x.setText(f"X (Cross Court)   {latest.landing_x:.2f} m")
            self.lbl_land_y.setText(f"Y (Down Court)    {latest.landing_y:.2f} m")
            self.lbl_impact_xy.setText(f"Impact Offset      {latest.impact_x:+d}, {latest.impact_y:+d}")
            self.lbl_impact_red.setText(f"Impact Redness     {latest.impact_redness:d}%")
            self.impact_widget.set_impact(latest.impact_x, latest.impact_y, latest.impact_redness)
        else:
            self.lbl_impact_xy.setText("Impact Offset      +0, +0")
            self.lbl_impact_red.setText("Impact Redness     0%")
            self.impact_widget.set_impact(0, 0, 0)

        total = len(self.shots)
        avg_speed = sum(s.speed for s in self.shots) / total if total else 0.0
        consistency = 0
        if total >= 2:
            sx = _stddev([s.landing_x for s in self.shots])
            sy = _stddev([s.landing_y for s in self.shots])
            sv = _stddev([s.speed for s in self.shots])
            consistency = int(max(0, min(99, 100.0 - (sx * 10.0 + sy * 5.3 + sv * 0.72))))

        self.stat_total._value_label.setText(str(total))  # type: ignore[attr-defined]
        self.stat_avg._value_label.setText(f"{avg_speed:.1f} mph")  # type: ignore[attr-defined]
        self.stat_cons._value_label.setText(f"{consistency}%")  # type: ignore[attr-defined]

        slow = sum(1 for s in self.shots if s.speed < 40)
        med = sum(1 for s in self.shots if 40 <= s.speed <= 70)
        fast = sum(1 for s in self.shots if s.speed > 70)
        if total > 0:
            self.donut.set_distribution(slow / total, med / total, fast / total)
            self.lbl_dist.setText(f"{(slow/total)*100:.0f}%\n{(med/total)*100:.0f}%\n{(fast/total)*100:.0f}%")
        else:
            self.donut.set_distribution(0.0, 0.0, 0.0)
            self.lbl_dist.setText("0%\n0%\n0%")

        self.court_widget.set_shots(self.shots)
        self.heat_widget.set_shots(self.shots)
        self._refresh_history_table()

    def _refresh_history_table(self):
        rows = self.shots[-18:]
        self.history_table.setRowCount(len(rows))
        for r, s in enumerate(reversed(rows)):
            values = [
                str(s.idx),
                s.timestamp,
                f"{s.speed:.1f}",
                f"{s.arm_angle:.1f}°",
                f"{s.landing_x:.2f}, {s.landing_y:.2f}",
                f"{s.spin:d}",
                f"{s.impact_x:+d},{s.impact_y:+d} {s.impact_redness:d}%",
            ]
            for c, txt in enumerate(values):
                item = QTableWidgetItem(txt)
                if c == 0:
                    item.setForeground(shot_color(s.speed))
                self.history_table.setItem(r, c, item)

    def closeEvent(self, event):  # noqa: N802
        if self.shots and not self._active_session_saved:
            self._save_current_session()
        self.stop_worker()
        super().closeEvent(event)


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Arial", 10))
    w = TennisDashboard()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
