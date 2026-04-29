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
import signal
import struct
import sys
import time
import warnings
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
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
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
RPM_X10_UUID = "7be5483e-36e1-4688-b7f5-ea07361b26a7"
COMMAND_UUID = "7be5483e-36e1-4688-b7f5-ea07361b26a4"
IMPACT_UUID = "7be5483e-36e1-4688-b7f5-ea07361b26a5"
GATE_SPEED_UUID = "7be5483e-36e1-4688-b7f5-ea07361b26a6"
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
    rpm_x10: int = 0
    gate_speed_mph: float = 0.0
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
    spin_type: str = "Flat"
    shot_type: str = "Forehand"
    face_tilt_deg: float = 0.0
    brush_angle_deg: float = 0.0
    net_clearance_m: float = 0.0
    bounce_kick_m: float = 0.0
    coaching_cue: str = ""
    benchmark_score: int = 0
    target_zone_hit: bool = False


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
        self.target_overlay_mode = "Off"
        self.setMinimumHeight(438)

    def set_shots(self, shots: list[Shot]):
        self.shots = shots[-45:]  # keep cleaner like target
        self.update()

    def set_target_overlay(self, mode: str):
        self.target_overlay_mode = mode
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

        self._draw_target_overlay(p, court)

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

    def _draw_target_overlay(self, p: QPainter, court: QRectF):
        if self.target_overlay_mode == "Off":
            return

        zone_specs: list[tuple[float, float, float, float, QColor, str]] = []
        if self.target_overlay_mode == "20 Topspin Cross-Court":
            zone_specs.append((-3.2, -0.6, 6.5, 10.2, QColor(45, 212, 109, 74), "TOPSPIN CC"))
            zone_specs.append((0.6, 3.2, 6.5, 10.2, QColor(45, 212, 109, 40), "ALT"))
        elif self.target_overlay_mode == "15 Serve T":
            zone_specs.append((-0.7, 0.7, 7.1, 9.8, QColor(255, 215, 138, 78), "SERVE T"))
        elif self.target_overlay_mode == "15 Backhand Topspin":
            zone_specs.append((0.6, 3.2, 6.4, 10.2, QColor(143, 208, 255, 78), "BH TOPSPIN"))
        elif self.target_overlay_mode == "20 Heavy Ball":
            zone_specs.append((-2.8, 2.8, 7.3, 10.5, QColor(190, 132, 255, 76), "HEAVY BALL"))

        for x1, x2, y1, y2, fill_color, label in zone_specs:
            poly = QPolygonF(
                [
                    self._landing_to_point(court, x1, y1),
                    self._landing_to_point(court, x2, y1),
                    self._landing_to_point(court, x2, y2),
                    self._landing_to_point(court, x1, y2),
                ]
            )
            p.setBrush(fill_color)
            p.setPen(QPen(QColor(fill_color.red(), fill_color.green(), fill_color.blue(), 185), 1.4, Qt.PenStyle.DashLine))
            p.drawPolygon(poly)
            center = poly.boundingRect().center()
            p.setPen(QColor("#d9e8f8"))
            p.setFont(QFont("Arial", 8, QFont.Weight.Bold))
            p.drawText(QPointF(center.x() - 25, center.y()), label)

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


class ConsistencyComparisonWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(210)
        self._labels = ["0-5m", "5-10m", "10-15m", "15-20m", "20-25m", "25-30m", "30-35m", "35-40m"]
        self._a: list[float] = []
        self._b: list[float] = []
        self._name_a = "A"
        self._name_b = "B"

    def set_data(self, a_vals: list[float], b_vals: list[float], name_a: str, name_b: str):
        self._a = a_vals[: len(self._labels)]
        self._b = b_vals[: len(self._labels)]
        self._name_a = name_a
        self._name_b = name_b
        self.update()

    def paintEvent(self, event):  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        area = QRectF(42, 28, max(120, self.width() - 58), max(110, self.height() - 56))

        p.setPen(QPen(QColor("#dde4ee"), 1))
        for i in range(6):
            y = area.top() + area.height() * i / 5.0
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            pct = int(100 - i * 10)
            p.setPen(QColor("#7d8793"))
            p.setFont(QFont("Arial", 7))
            p.drawText(10, int(y + 3), f"{pct}%")
            p.setPen(QPen(QColor("#dde4ee"), 1))

        self._draw_area_fill(p, area, self._a, QColor(75, 147, 210, 55))
        self._draw_line(p, area, self._a, QColor("#4b93d2"), solid=True)
        self._draw_line(p, area, self._b, QColor("#3da187"), solid=False)

        p.setPen(QColor("#4b93d2"))
        p.drawText(14, 30, f"■ {self._name_a}")
        p.setPen(QColor("#3da187"))
        p.drawText(74, 30, f"■ {self._name_b}")

        p.setPen(QColor("#8b95a1"))
        p.setFont(QFont("Arial", 7))
        for i, lbl in enumerate(self._labels):
            x = area.left() + area.width() * i / (len(self._labels) - 1)
            p.drawText(int(x - 12), int(area.bottom() + 14), lbl)

    @staticmethod
    def _draw_area_fill(p: QPainter, area: QRectF, vals: list[float], color: QColor):
        if len(vals) < 2:
            return
        poly = QPolygonF()
        for i, v in enumerate(vals):
            n = max(0.0, min(v / 100.0, 1.0))
            x = area.left() + area.width() * i / (len(vals) - 1)
            y = area.bottom() - area.height() * n
            poly.append(QPointF(x, y))
        poly.append(QPointF(area.right(), area.bottom()))
        poly.append(QPointF(area.left(), area.bottom()))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawPolygon(poly)

    @staticmethod
    def _draw_line(p: QPainter, area: QRectF, vals: list[float], color: QColor, solid: bool):
        if len(vals) < 2:
            return
        pen = QPen(color, 2.0)
        if not solid:
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        path = QPainterPath()
        for i, v in enumerate(vals):
            n = max(0.0, min(v / 100.0, 1.0))
            x = area.left() + area.width() * i / (len(vals) - 1)
            y = area.bottom() - area.height() * n
            pt = QPointF(x, y)
            if i == 0:
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        p.drawPath(path)
        p.setPen(QPen(color, 1.0))
        p.setBrush(color)
        for i, v in enumerate(vals):
            n = max(0.0, min(v / 100.0, 1.0))
            x = area.left() + area.width() * i / (len(vals) - 1)
            y = area.bottom() - area.height() * n
            p.drawEllipse(QPointF(x, y), 2.8, 2.8)


class StrokeSpeedComparisonWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(180)
        self._labels = ["Forehand", "Backhand", "Serve", "Volley", "Slice"]
        self._a: list[float] = [0.0] * 5
        self._b: list[float] = [0.0] * 5

    def set_data(self, a_vals: list[float], b_vals: list[float]):
        self._a = a_vals[:5]
        self._b = b_vals[:5]
        self.update()

    def paintEvent(self, event):  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        area = QRectF(34, 28, max(120, self.width() - 46), max(95, self.height() - 52))
        p.setPen(QPen(QColor("#dde4ee"), 1))
        for i in range(6):
            y = area.bottom() - area.height() * i / 5.0
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            p.setPen(QColor("#9ca3af"))
            p.setFont(QFont("Arial", 7))
            p.drawText(6, int(y + 3), f"{i * 40}km/h")
            p.setPen(QPen(QColor("#dde4ee"), 1))
        w = area.width() / max(1, len(self._labels))
        for i, lbl in enumerate(self._labels):
            x = area.left() + i * w
            h1 = area.height() * max(0.0, min(self._a[i] / 200.0, 1.0))
            h2 = area.height() * max(0.0, min(self._b[i] / 200.0, 1.0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#4b93d2"))
            p.drawRoundedRect(QRectF(x + w * 0.18, area.bottom() - h1, w * 0.24, h1), 3, 3)
            p.setBrush(QColor("#3da187"))
            p.drawRoundedRect(QRectF(x + w * 0.48, area.bottom() - h2, w * 0.24, h2), 3, 3)
            p.setPen(QColor("#8b95a1"))
            p.setFont(QFont("Arial", 7))
            p.drawText(int(x + 1), int(area.bottom() + 13), lbl[:8])


class ShotDistributionComparisonWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(180)
        self._labels = ["Forehand", "Backhand", "Serve", "Volley", "Slice"]
        self._a: list[float] = [0.0] * 5
        self._b: list[float] = [0.0] * 5

    def set_data(self, a_vals: list[float], b_vals: list[float]):
        self._a = a_vals[:5]
        self._b = b_vals[:5]
        self.update()

    def paintEvent(self, event):  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        row_h = max(24.0, (self.height() - 36) / 5.0)
        for i, lbl in enumerate(self._labels):
            y = 26 + i * row_h
            p.setPen(QColor("#4b5563"))
            p.setFont(QFont("Arial", 8))
            p.drawText(12, int(y + 11), lbl)
            left = 96.0
            width = max(80.0, self.width() - 180.0)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#e5e7eb"))
            p.drawRoundedRect(QRectF(left, y + 2, width, 8), 4, 4)
            p.setBrush(QColor("#4b93d2"))
            p.drawRoundedRect(QRectF(left, y + 2, width * max(0.0, min(self._a[i] / 60.0, 1.0)), 8), 4, 4)
            p.setBrush(QColor("#3da187"))
            p.drawRoundedRect(QRectF(left, y + 12, width * max(0.0, min(self._b[i] / 60.0, 1.0)), 8), 4, 4)
            p.setPen(QColor("#6b7280"))
            p.drawText(int(left + width + 8), int(y + 15), f"{self._a[i]:.0f}% / {self._b[i]:.0f}%")


class RadarComparisonWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(300)
        self._labels = ["Consistency", "Net play", "Serve power", "Precision", "Stamina"]
        self._a: list[float] = [0.0] * 5
        self._b: list[float] = [0.0] * 5
        self._name_a = "A"
        self._name_b = "B"

    def set_data(self, a_vals: list[float], b_vals: list[float], name_a: str, name_b: str):
        self._a = a_vals[:5]
        self._b = b_vals[:5]
        self._name_a = name_a
        self._name_b = name_b
        self.update()

    def paintEvent(self, event):  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        c = QPointF(self.width() * 0.5, self.height() * 0.57)
        radius = max(70.0, min(self.width() * 0.18, self.height() * 0.36))
        n = len(self._labels)

        for i in range(n):
            tip = self._radar_point(c, radius, i, n)
            p.setPen(QPen(QColor("#e3e8f0"), 1))
            p.drawLine(c, tip)

        for ring in range(1, 6):
            frac = ring / 5.0
            poly = QPolygonF([self._radar_point(c, radius * frac, i, n) for i in range(n)])
            p.setPen(QPen(QColor("#dbe3ee"), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolygon(poly)
        for i, lbl in enumerate(self._labels):
            pt = self._radar_point(c, radius * 1.18, i, n)
            p.setPen(QColor("#7d8793"))
            p.setFont(QFont("Arial", 8))
            x = pt.x() - 30
            y = pt.y() + 4
            if i == 0:
                x = pt.x() - 28
                y = pt.y() - 3
            elif i == 1:
                x = pt.x() + 4
            elif i == 2:
                x = pt.x() + 2
                y = pt.y() + 10
            elif i == 3:
                x = pt.x() - 50
                y = pt.y() + 10
            elif i == 4:
                x = pt.x() - 56
            p.drawText(int(x), int(y), lbl)
        self._draw_radar_poly(p, c, radius, self._a, QColor(75, 147, 210, 90), QColor("#4b93d2"))
        self._draw_radar_poly(p, c, radius, self._b, QColor(61, 161, 135, 90), QColor("#3da187"))
        p.setPen(QColor("#4b93d2"))
        p.drawText(14, 30, f"■ {self._name_a}")
        p.setPen(QColor("#3da187"))
        p.drawText(76, 30, f"■ {self._name_b}")

    @staticmethod
    def _radar_point(center: QPointF, radius: float, idx: int, total: int) -> QPointF:
        ang = (math.pi * 2.0 * idx / total) - (math.pi / 2.0)
        return QPointF(center.x() + math.cos(ang) * radius, center.y() + math.sin(ang) * radius)

    def _draw_radar_poly(self, p: QPainter, center: QPointF, radius: float, vals: list[float], fill: QColor, edge: QColor):
        n = len(self._labels)
        poly = QPolygonF(
            [
                self._radar_point(center, radius * max(0.0, min(vals[i] / 100.0, 1.0)), i, n)
                for i in range(n)
            ]
        )
        p.setPen(QPen(edge, 1.4))
        p.setBrush(fill)
        p.drawPolygon(poly)


class StatsBIWindow(QWidget):
    def __init__(self, dashboard: "TennisDashboard"):
        super().__init__()
        self.dashboard = dashboard
        self.setWindowTitle("Tennis Stats BI")
        self.resize(1080, 760)
        self._profile_switching = False
        self._session_switching = False
        self._session_maps: dict[str, dict] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroll, 1)
        body = QWidget()
        scroll.setWidget(body)
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(10)

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
        row.addWidget(self.btn_compare, 0)
        content.addLayout(row)

        self.lbl_profile_meta = QLabel("Session comparison")
        self.lbl_profile_meta.setStyleSheet("color:#e5e7eb; font-size:18px; font-weight:700;")
        content.addWidget(self.lbl_profile_meta)

        self.lbl_snapshot = QLabel("Topspin training data")
        self.lbl_snapshot.setStyleSheet("color:#9ca3af; font-size:11px;")
        content.addWidget(self.lbl_snapshot)

        sel_row = QHBoxLayout()
        sel_row.setSpacing(8)
        dot_a = QLabel("●")
        dot_a.setStyleSheet("color:#4b93d2; font-size:12px;")
        dot_b = QLabel("●")
        dot_b.setStyleSheet("color:#3da187; font-size:12px;")
        self.session_a_combo = QComboBox()
        self.session_b_combo = QComboBox()
        self.session_a_combo.setMinimumWidth(280)
        self.session_b_combo.setMinimumWidth(280)
        sel_row.addWidget(dot_a)
        sel_row.addWidget(QLabel("Session A"))
        sel_row.addWidget(self.session_a_combo, 1)
        sel_row.addWidget(dot_b)
        sel_row.addWidget(QLabel("Session B"))
        sel_row.addWidget(self.session_b_combo, 1)
        content.addLayout(sel_row)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(8)
        self.card_shots = self._make_stat_card("Shots hit")
        self.card_consistency = self._make_stat_card("Consistency")
        self.card_top_speed = self._make_stat_card("Top speed")
        self.card_avg_rally = self._make_stat_card("Avg rally")
        self.card_errors = self._make_stat_card("Errors")
        for card in (
            self.card_shots,
            self.card_consistency,
            self.card_top_speed,
            self.card_avg_rally,
            self.card_errors,
        ):
            cards_row.addWidget(card, 1)
        content.addLayout(cards_row)

        trend_panel = self._make_light_panel("Consistency over time (shots in, %)")
        trend_layout = trend_panel.layout()  # type: ignore[assignment]
        self.consistency_chart = ConsistencyComparisonWidget()
        trend_layout.addWidget(self.consistency_chart)  # type: ignore[attr-defined]
        content.addWidget(trend_panel)

        mid_row = QHBoxLayout()
        mid_row.setSpacing(8)
        speed_panel = self._make_light_panel("Average ball speed by stroke (km/h)")
        speed_layout = speed_panel.layout()  # type: ignore[assignment]
        self.stroke_speed_chart = StrokeSpeedComparisonWidget()
        speed_layout.addWidget(self.stroke_speed_chart)  # type: ignore[attr-defined]
        mid_row.addWidget(speed_panel, 1)
        dist_panel = self._make_light_panel("Shot distribution")
        dist_layout = dist_panel.layout()  # type: ignore[assignment]
        self.shot_dist_chart = ShotDistributionComparisonWidget()
        dist_layout.addWidget(self.shot_dist_chart)  # type: ignore[attr-defined]
        mid_row.addWidget(dist_panel, 1)
        content.addLayout(mid_row)

        radar_panel = self._make_light_panel("Performance radar")
        radar_layout = radar_panel.layout()  # type: ignore[assignment]
        self.radar_chart = RadarComparisonWidget()
        radar_layout.addWidget(self.radar_chart)  # type: ignore[attr-defined]
        content.addWidget(radar_panel)
        content.addStretch(1)

        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        self.level_combo.currentTextChanged.connect(self._on_level_changed)
        self.session_a_combo.currentTextChanged.connect(self._on_session_changed)
        self.session_b_combo.currentTextChanged.connect(self._on_session_changed)
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

    def _on_session_changed(self, _text: str):
        if self._session_switching:
            return
        self._refresh_comparison_dashboard()

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

        sessions = list(self.dashboard._profiles.get(self.dashboard._current_student, []))
        self._session_maps.clear()
        self._session_switching = True
        self.session_a_combo.clear()
        self.session_b_combo.clear()
        rows = list(reversed(sessions))
        for i, s in enumerate(rows, start=1):
            label = self._session_label(s, i)
            self._session_maps[label] = s
            self.session_a_combo.addItem(label)
            self.session_b_combo.addItem(label)
        if self.session_a_combo.count() > 0:
            self.session_a_combo.setCurrentIndex(0)
            self.session_b_combo.setCurrentIndex(1 if self.session_b_combo.count() > 1 else 0)
        self._session_switching = False
        self._refresh_comparison_dashboard()

    @staticmethod
    def _make_light_panel(title: str) -> QFrame:
        panel = QFrame()
        panel.setStyleSheet("background: #ffffff; border-radius: 10px; border: 1px solid #dfe4eb;")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        lbl = QLabel(title)
        lbl.setStyleSheet("color:#1f2937; font-size:11px; font-weight:700;")
        lay.addWidget(lbl)
        return panel

    @staticmethod
    def _make_stat_card(title: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet("background: #ffffff; border-radius: 10px; border: 1px solid #dfe4eb;")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet("color:#374151; font-size:10px;")
        v = QLabel("0")
        v.setStyleSheet("color:#111827; font-size:34px; font-weight:800;")
        d = QLabel("0 vs B")
        d.setStyleSheet("color:#6b7280; font-size:9px;")
        lay.addWidget(t)
        lay.addWidget(v)
        lay.addWidget(d)
        card._val = v  # type: ignore[attr-defined]
        card._delta = d  # type: ignore[attr-defined]
        return card

    @staticmethod
    def _session_label(session: dict, idx: int) -> str:
        raw = str(session.get("started_at", "")).strip()
        if len(raw) >= 10:
            try:
                dt = datetime.fromisoformat(raw)
                return f"{dt.strftime('%b %d')} - Session {idx}"
            except ValueError:
                pass
        return f"Session {idx}"

    def _selected_sessions(self) -> tuple[dict | None, dict | None]:
        sa = self._session_maps.get(self.session_a_combo.currentText())
        sb = self._session_maps.get(self.session_b_combo.currentText())
        return sa, sb

    @staticmethod
    def _delta_text(a: float, b: float, unit: str = "") -> tuple[str, str]:
        d = a - b
        sign = "+" if d >= 0 else ""
        color = "#16a34a" if d >= 0 else "#b45309"
        return f"{sign}{d:.1f}{unit} vs B", color

    @staticmethod
    def _derived_consistency_curve(summary: dict) -> list[float]:
        base = float(summary.get("consistency", 0.0))
        seed = max(1, sum(ord(c) for c in str(summary.get("started_at", ""))))
        r = random.Random(seed)
        vals = []
        for i in range(8):
            drift = (i * 2.2) - 7.0
            vals.append(max(35.0, min(95.0, base + drift + r.uniform(-2.5, 2.5))))
        return vals

    @staticmethod
    def _derived_stroke_speeds(summary: dict) -> list[float]:
        speed = float(summary.get("avg_speed", 0.0)) * 1.60934
        return [
            speed * 1.06,  # forehand
            speed * 0.92,  # backhand
            speed * 1.38,  # serve
            speed * 0.76,  # volley
            speed * 0.86,  # slice
        ]

    @staticmethod
    def _derived_shot_distribution(summary: dict) -> list[float]:
        fast = float(summary.get("fast_pct", 0.0))
        impact = float(summary.get("avg_impact_redness", 0.0))
        f = max(20.0, min(44.0, 28.0 + (fast - 22.0) * 0.34))
        b = max(16.0, min(34.0, 26.0 + (impact - 45.0) * 0.14))
        s = max(8.0, min(28.0, 14.0 + fast * 0.20))
        v = max(4.0, min(20.0, 10.0 - fast * 0.06 + impact * 0.03))
        sl = max(6.0, min(24.0, 100.0 - (f + b + s + v)))
        total = f + b + s + v + sl
        scale = 100.0 / max(1.0, total)
        return [f * scale, b * scale, s * scale, v * scale, sl * scale]

    @staticmethod
    def _derived_radar(summary: dict) -> list[float]:
        consistency = float(summary.get("consistency", 0.0))
        speed = float(summary.get("avg_speed", 0.0))
        spin = float(summary.get("avg_spin", 0.0))
        fast = float(summary.get("fast_pct", 0.0))
        impact = float(summary.get("avg_impact_redness", 0.0))
        return [
            max(30.0, min(100.0, consistency)),
            max(25.0, min(100.0, consistency * 0.55 + impact * 0.42)),
            max(30.0, min(100.0, speed * 1.0 + fast * 0.42)),
            max(24.0, min(100.0, spin / 33.0)),
            max(20.0, min(100.0, consistency * 0.6 + fast * 0.4)),
        ]

    def _set_card(self, card: QFrame, value: str, delta: str, delta_color: str):
        card._val.setText(value)  # type: ignore[attr-defined]
        card._delta.setText(delta)  # type: ignore[attr-defined]
        card._delta.setStyleSheet(f"color:{delta_color}; font-size:9px;")  # type: ignore[attr-defined]

    def _refresh_comparison_dashboard(self):
        sessions = self.dashboard._profiles.get(self.dashboard._current_student, [])
        self.lbl_profile_meta.setText(f"Session comparison")
        self.lbl_snapshot.setText(
            f"Topspin training data | Student: {self.dashboard._current_student} | Sessions: {len(sessions)}"
        )
        sa, sb = self._selected_sessions()
        if sa is None:
            self._set_card(self.card_shots, "0", "0 vs B", "#6b7280")
            self._set_card(self.card_consistency, "0%", "0 vs B", "#6b7280")
            self._set_card(self.card_top_speed, "0", "0 vs B", "#6b7280")
            self._set_card(self.card_avg_rally, "0.0", "0 vs B", "#6b7280")
            self._set_card(self.card_errors, "0", "0 vs B", "#6b7280")
            return
        if sb is None:
            sb = sa

        a_shots = float(sa.get("shot_count", 0))
        b_shots = float(sb.get("shot_count", 0))
        a_cons = float(sa.get("consistency", 0.0))
        b_cons = float(sb.get("consistency", 0.0))
        a_speed = float(sa.get("avg_speed", 0.0)) * 1.60934
        b_speed = float(sb.get("avg_speed", 0.0)) * 1.60934
        a_rally = max(1.0, min(14.0, 2.2 + a_cons * 0.085))
        b_rally = max(1.0, min(14.0, 2.2 + b_cons * 0.085))
        a_errors = max(0.0, 30.0 - a_cons * 0.19)
        b_errors = max(0.0, 30.0 - b_cons * 0.19)

        d, c = self._delta_text(a_shots, b_shots)
        self._set_card(self.card_shots, f"{int(round(a_shots))}", d, c)
        d, c = self._delta_text(a_cons, b_cons, "%")
        self._set_card(self.card_consistency, f"{a_cons:.0f}%", d, c)
        d, c = self._delta_text(a_speed, b_speed, "km/h")
        self._set_card(self.card_top_speed, f"{a_speed:.0f}", d, c)
        d, c = self._delta_text(a_rally, b_rally)
        self._set_card(self.card_avg_rally, f"{a_rally:.1f}", d, c)
        d, c = self._delta_text(-a_errors, -b_errors)  # lower is better
        self._set_card(self.card_errors, f"{a_errors:.0f}", d.replace("vs B", "errors vs B"), c)

        name_a = self.session_a_combo.currentText() or "A"
        name_b = self.session_b_combo.currentText() or "B"
        self.consistency_chart.set_data(
            self._derived_consistency_curve(sa),
            self._derived_consistency_curve(sb),
            name_a,
            name_b,
        )
        self.stroke_speed_chart.set_data(
            self._derived_stroke_speeds(sa),
            self._derived_stroke_speeds(sb),
        )
        self.shot_dist_chart.set_data(
            self._derived_shot_distribution(sa),
            self._derived_shot_distribution(sb),
        )
        self.radar_chart.set_data(
            self._derived_radar(sa),
            self._derived_radar(sb),
            name_a,
            name_b,
        )

class SettingsWindow(QWidget):
    def __init__(self, dashboard: "TennisDashboard", scope: str = "all"):
        super().__init__()
        self.dashboard = dashboard
        self.scope = scope
        self.has_hardware_settings = scope in ("all", "hardware")
        self.has_app_settings = scope in ("all", "app")
        self.setWindowTitle("Tennis App & Hardware Settings")
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
        self.settings_groups = QTabWidget()
        self.settings_groups.setObjectName("SettingsGroups")
        root.addWidget(self.settings_groups, 1)

        hardware_page = QWidget()
        hardware_page_lay = QVBoxLayout(hardware_page)
        hardware_page_lay.setContentsMargins(0, 0, 0, 0)
        hardware_page_lay.setSpacing(8)
        self.hardware_tabs = QTabWidget()
        self.hardware_tabs.setObjectName("SettingsTabs")
        hardware_page_lay.addWidget(self.hardware_tabs, 1)
        self.settings_groups.addTab(hardware_page, "Hardware Settings")

        app_page = QWidget()
        app_page_lay = QVBoxLayout(app_page)
        app_page_lay.setContentsMargins(0, 0, 0, 0)
        app_page_lay.setSpacing(8)
        self.app_tabs = QTabWidget()
        self.app_tabs.setObjectName("SettingsTabs")
        app_page_lay.addWidget(self.app_tabs, 1)
        self.settings_groups.addTab(app_page, "App Settings")
        if self.scope == "hardware":
            self.settings_groups.setCurrentIndex(0)
            self.settings_groups.tabBar().setVisible(False)
            self.setWindowTitle("Hardware Settings")
        elif self.scope == "app":
            self.settings_groups.setCurrentIndex(1)
            self.settings_groups.tabBar().setVisible(False)
            self.setWindowTitle("App Settings")

        cal_tab = QWidget()
        cal_tab_lay = QVBoxLayout(cal_tab)
        cal_tab_lay.setContentsMargins(0, 0, 0, 0)
        cal_tab_lay.setSpacing(8)
        self.hardware_tabs.addTab(cal_tab, "Calibration")

        wiz_tab = QWidget()
        wiz_tab_lay = QVBoxLayout(wiz_tab)
        wiz_tab_lay.setContentsMargins(0, 0, 0, 0)
        wiz_tab_lay.setSpacing(8)
        self.hardware_tabs.addTab(wiz_tab, "Wizard")

        comp_tab = QWidget()
        comp_tab_lay = QVBoxLayout(comp_tab)
        comp_tab_lay.setContentsMargins(0, 0, 0, 0)
        comp_tab_lay.setSpacing(8)
        self.app_tabs.addTab(comp_tab, "Competition Profiles")

        train_tab = QWidget()
        train_tab_lay = QVBoxLayout(train_tab)
        train_tab_lay.setContentsMargins(0, 0, 0, 0)
        train_tab_lay.setSpacing(8)
        self.app_tabs.addTab(train_tab, "Training")

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
        self.cal_min_valid_input = QLineEdit("250")
        cal_grid.addWidget(QLabel("Counts per G"), 0, 0)
        cal_grid.addWidget(self.cal_counts_input, 0, 1)
        cal_grid.addWidget(QLabel("mg @ 100%"), 1, 0)
        cal_grid.addWidget(self.cal_impact_input, 1, 1)
        cal_grid.addWidget(QLabel("contact full-scale mg"), 2, 0)
        cal_grid.addWidget(self.cal_contact_input, 2, 1)
        cal_grid.addWidget(QLabel("min valid impact mg"), 3, 0)
        cal_grid.addWidget(self.cal_min_valid_input, 3, 1)
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

        train_box = QFrame()
        train_box.setObjectName("Panel")
        train_lay = QVBoxLayout(train_box)
        train_lay.setContentsMargins(10, 8, 10, 8)
        train_lay.setSpacing(8)
        train_lay.addWidget(QLabel("TRAINING CONTROLS"))

        top_cards = QHBoxLayout()
        top_cards.setSpacing(8)

        surface_card = QFrame()
        surface_card.setObjectName("Panel")
        surface_lay = QVBoxLayout(surface_card)
        surface_lay.setContentsMargins(8, 6, 8, 6)
        surface_lay.setSpacing(4)
        surface_title = QLabel("COURT SURFACE")
        surface_title.setObjectName("PanelTitle")
        self.lbl_surface_help = QLabel("Affects bounce kick estimate")
        self.lbl_surface_help.setObjectName("SmallMuted")
        self.train_surface_combo = QComboBox()
        self.train_surface_combo.addItems(["Hard", "Clay", "Grass"])
        surface_lay.addWidget(surface_title)
        surface_lay.addWidget(self.lbl_surface_help)
        surface_lay.addWidget(self.train_surface_combo)
        top_cards.addWidget(surface_card, 1)

        intent_card = QFrame()
        intent_card.setObjectName("Panel")
        intent_lay = QVBoxLayout(intent_card)
        intent_lay.setContentsMargins(8, 6, 8, 6)
        intent_lay.setSpacing(4)
        intent_title = QLabel("SHOT INTENT")
        intent_title.setObjectName("PanelTitle")
        self.lbl_intent_help = QLabel("Auto infer or force a stroke type")
        self.lbl_intent_help.setObjectName("SmallMuted")
        self.train_intent_combo = QComboBox()
        self.train_intent_combo.addItems(["Auto", "Forehand", "Backhand", "Serve"])
        intent_lay.addWidget(intent_title)
        intent_lay.addWidget(self.lbl_intent_help)
        intent_lay.addWidget(self.train_intent_combo)
        top_cards.addWidget(intent_card, 1)

        train_lay.addLayout(top_cards)

        drill_card = QFrame()
        drill_card.setObjectName("Panel")
        drill_lay = QVBoxLayout(drill_card)
        drill_lay.setContentsMargins(8, 6, 8, 6)
        drill_lay.setSpacing(4)
        drill_title = QLabel("TARGET / DRILL TEMPLATE")
        drill_title.setObjectName("PanelTitle")
        self.lbl_drill_help = QLabel("Select a target zone objective for current session")
        self.lbl_drill_help.setObjectName("SmallMuted")
        self.train_drill_combo = QComboBox()
        self.train_drill_combo.addItems(
            ["Off", "20 Topspin Cross-Court", "15 Serve T", "15 Backhand Topspin", "20 Heavy Ball"]
        )
        drill_lay.addWidget(drill_title)
        drill_lay.addWidget(self.lbl_drill_help)
        drill_lay.addWidget(self.train_drill_combo)
        train_lay.addWidget(drill_card)

        self.lbl_training_status = QLabel("Drill Progress: Off")
        self.lbl_training_status.setObjectName("SmallMuted")
        self.lbl_training_tip = QLabel("Tip: use TARGET chip on main screen for fast tablet selection.")
        self.lbl_training_tip.setObjectName("SmallMuted")
        train_lay.addWidget(self.lbl_training_status)
        train_lay.addWidget(self.lbl_training_tip)
        train_tab_lay.addWidget(train_box)
        train_tab_lay.addStretch(1)

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
        self.train_surface_combo.currentTextChanged.connect(self._on_training_surface_changed)
        self.train_intent_combo.currentTextChanged.connect(self._on_training_intent_changed)
        self.train_drill_combo.currentTextChanged.connect(self._on_training_drill_changed)
        self._refresh_competition_editor(self.comp_profile_combo.currentText())

    def _apply_calibration_from_inputs(self):
        self.dashboard._apply_firmware_calibration_from_ui(
            self.cal_counts_input.text(),
            self.cal_impact_input.text(),
            self.cal_contact_input.text(),
            self.cal_min_valid_input.text(),
        )

    def set_calibration_values(
        self,
        counts_per_g: float,
        impact_mg_100: int,
        contact_full_scale_mg: int,
        min_valid_impact_mg: int,
    ):
        self.cal_counts_input.setText(f"{counts_per_g:.2f}")
        self.cal_impact_input.setText(str(int(impact_mg_100)))
        self.cal_contact_input.setText(str(int(contact_full_scale_mg)))
        self.cal_min_valid_input.setText(str(int(min_valid_impact_mg)))

    def set_calibration_status(self, text: str):
        self.lbl_cal_status.setText(text)

    def show_hardware_settings(self):
        self.setWindowTitle("Hardware Settings")
        self.settings_groups.setCurrentIndex(0)
        self.settings_groups.tabBar().setVisible(False)

    def show_app_settings(self):
        self.setWindowTitle("App Settings")
        self.settings_groups.setCurrentIndex(1)
        self.settings_groups.tabBar().setVisible(False)

    def show_all_settings(self):
        self.setWindowTitle("Tennis App & Hardware Settings")
        self.settings_groups.tabBar().setVisible(True)

    def refresh(self):
        current = self.comp_profile_combo.currentText() or self.dashboard._competition_level
        self.comp_profile_combo.blockSignals(True)
        self.comp_profile_combo.clear()
        self.comp_profile_combo.addItems(list(self.dashboard._competition_profiles.keys()))
        self.comp_profile_combo.setCurrentText(current)
        self.comp_profile_combo.blockSignals(False)
        self._refresh_competition_editor(self.comp_profile_combo.currentText())
        self.train_surface_combo.blockSignals(True)
        self.train_surface_combo.setCurrentText(self.dashboard._court_surface)
        self.train_surface_combo.blockSignals(False)
        self.train_intent_combo.blockSignals(True)
        self.train_intent_combo.setCurrentText(self.dashboard._shot_intent_override)
        self.train_intent_combo.blockSignals(False)
        self.train_drill_combo.blockSignals(True)
        self.train_drill_combo.setCurrentText(self.dashboard._drill_mode)
        self.train_drill_combo.blockSignals(False)
        self.lbl_training_status.setText(self.dashboard._drill_status_text)
        self._refresh_training_help()

    def _on_training_surface_changed(self, value: str):
        self.dashboard.set_court_surface(value)
        self._refresh_training_help()

    def _on_training_intent_changed(self, value: str):
        self.dashboard.set_shot_intent_override(value)
        self._refresh_training_help()

    def _on_training_drill_changed(self, value: str):
        self.dashboard.set_drill_mode(value)
        self._refresh_training_help()

    def _refresh_training_help(self):
        surface_help = {
            "Hard": "Balanced bounce profile",
            "Clay": "Higher kick after bounce",
            "Grass": "Lower and skiddier bounce",
        }.get(self.dashboard._court_surface, "Affects bounce kick estimate")
        self.lbl_surface_help.setText(surface_help)

        intent_help = {
            "Auto": "Uses sensor/shot model inference",
            "Forehand": "Force forehand tagging",
            "Backhand": "Force backhand tagging",
            "Serve": "Force serve tagging",
        }.get(self.dashboard._shot_intent_override, "Auto infer or force a stroke type")
        self.lbl_intent_help.setText(intent_help)

        heavy_cfg = self.dashboard._heavy_ball_thresholds()
        drill_help = {
            "Off": "No target gating, free training mode",
            "20 Topspin Cross-Court": "Goal: 20 topspin cross-court hits",
            "15 Serve T": "Goal: 15 serve-T hits with clean clearance",
            "15 Backhand Topspin": "Goal: 15 topspin backhand hits",
            "20 Heavy Ball": (
                f"Goal: 20 heavy-ball shots (>= {heavy_cfg['min_speed']:.0f} mph, "
                f">= {heavy_cfg['min_spin']:.0f} spin, deep + clean impact)"
            ),
        }.get(self.dashboard._drill_mode, "Select a target zone objective for current session")
        self.lbl_drill_help.setText(drill_help)

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
    telemetry = pyqtSignal(int, int, int, int)
    impact = pyqtSignal(int, int, int, int, int, int, int, int, int)
    gate_speed = pyqtSignal(int, int, int)
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
        self._command_char_uuid: str | None = None
        self._command_notify_uuid: str | None = None
        self._available_char_uuids: set[str] = set()
        self._warned_no_command_channel = False
        self._diag_counts: dict[str, int] = {}

    @staticmethod
    def _has_prop(props: list[str], needle: str) -> bool:
        n = needle.lower()
        return any(n in p.lower() for p in props)

    def _has_char(self, uuid: str) -> bool:
        return uuid.lower() in self._available_char_uuids

    async def _resolve_command_characteristics(self):
        self._command_char_uuid = None
        self._command_notify_uuid = None
        self._available_char_uuids.clear()
        if not self._client:
            return
        try:
            services = self._client.services
        except Exception as exc:
            self.status.emit(f"BLE service discovery failed: {exc}")
            return
        if not services:
            # Some Bleak backends require explicit service discovery once.
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", FutureWarning)
                    await self._client.get_services()
                services = self._client.services
            except Exception as exc:
                self.status.emit(f"BLE service discovery returned no services ({exc}).")
                return
            if not services:
                self.status.emit("BLE service discovery returned no services.")
                return

        command_exact = None
        writable_fallback = None
        tennis_service_seen = False
        tennis_writable_uuids: list[str] = []
        for service in services:
            if service.uuid.lower() == TENNIS_SERVICE_UUID.lower():
                tennis_service_seen = True
            for ch in service.characteristics:
                self._available_char_uuids.add(ch.uuid.lower())
                props = [str(p) for p in (ch.properties or [])]
                is_writable = self._has_prop(props, "write")
                is_notify = self._has_prop(props, "notify")
                if ch.uuid.lower() == COMMAND_UUID.lower():
                    command_exact = ch
                if service.uuid.lower() == TENNIS_SERVICE_UUID.lower() and is_writable and writable_fallback is None:
                    writable_fallback = ch
                if service.uuid.lower() == TENNIS_SERVICE_UUID.lower() and is_writable:
                    tennis_writable_uuids.append(ch.uuid)

                if command_exact is not None:
                    break
            if command_exact is not None:
                break

        selected = command_exact or writable_fallback
        if selected is None:
            if not tennis_service_seen:
                self.status.emit("Connected device does not expose Tennis service UUID.")
            elif tennis_writable_uuids:
                listed = ", ".join(tennis_writable_uuids[:4])
                self.status.emit(
                    f"Command UUID mismatch. Expected {COMMAND_UUID}; writable found: {listed}"
                )
            else:
                self.status.emit("Command characteristic unavailable on this firmware.")
            return

        props = [str(p) for p in (selected.properties or [])]
        self._command_char_uuid = selected.uuid
        if self._has_prop(props, "notify"):
            self._command_notify_uuid = selected.uuid
        if selected.uuid.lower() != COMMAND_UUID.lower():
            self.status.emit(f"Using fallback command characteristic: {selected.uuid}")

    def stop(self):
        self._running = False
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._disconnect(), self._loop)

    def request_reset(self):
        self.request_command("RESET")

    def request_command(self, text: str):
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._write_command(text), self._loop)

    def can_send_commands(self) -> bool:
        return bool(self._command_char_uuid)

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
            # CoreBluetooth can still deliver disconnect callbacks briefly after
            # we stop. Keeping the loop open avoids "Event loop is closed"
            # crashes raised from bleak delegate callbacks on macOS.
            try:
                self._loop.run_until_complete(asyncio.sleep(0.15))
            except Exception:
                pass
            asyncio.set_event_loop(None)
            self._loop = None

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
                await self._resolve_command_characteristics()
                self._warned_no_command_channel = False
                await self._client.start_notify(SENSOR_STATE_UUID, self._on_state)
                await self._client.start_notify(HIT_COUNT_UUID, self._on_count)
                await self._client.start_notify(RATE_X10_UUID, self._on_rate)
                try:
                    await self._client.start_notify(RPM_X10_UUID, self._on_rpm)
                except Exception:
                    self.status.emit("RPM characteristic unavailable on this firmware.")
                try:
                    await self._client.start_notify(IMPACT_UUID, self._on_impact)
                except Exception:
                    self.status.emit("Impact characteristic unavailable on this firmware.")
                try:
                    await self._client.start_notify(GATE_SPEED_UUID, self._on_gate_speed)
                except Exception:
                    self.status.emit("Gate speed characteristic unavailable on this firmware.")
                command_notify_ok = bool(self._command_notify_uuid)
                if command_notify_ok:
                    try:
                        await self._client.start_notify(self._command_notify_uuid, self._on_command_notify)
                    except Exception:
                        command_notify_ok = False
                        self.status.emit("Command notify unavailable; skipping PONG health check.")
                else:
                    self.status.emit("Command notify unavailable; skipping PONG health check.")
                ping_ok = False
                if command_notify_ok and self._command_char_uuid:
                    ping_ok = await self._await_command_ack(
                        STREAM_KEEPALIVE_COMMAND, PING_ACK_SUBSTRING, PING_HEALTH_TIMEOUT_S
                    )
                    self.ble_handshake.emit(ping_ok)
                self.connected.emit(True, device.address)
                if ping_ok:
                    self.status.emit("Connected — health check OK (PONG). Live streaming.")
                else:
                    if command_notify_ok and self._command_char_uuid:
                        self.status.emit(
                            "Connected — no PONG before timeout (flash newer firmware?). Live streaming."
                        )
                    else:
                        self.status.emit(
                            "Connected — command channel unavailable. Firmware may keep stream disabled until STREAM:ON/PING."
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
        if not self._client or not self._client.is_connected or not self._command_char_uuid:
            return False
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._pending_cmd_ack = fut
        try:
            await self._client.write_gatt_char(self._command_char_uuid, cmd.encode("utf-8"), response=False)
            payload = await asyncio.wait_for(fut, timeout=timeout_s)
            return ack_needle.upper() in payload.upper()
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return False
        finally:
            self._pending_cmd_ack = None

    async def _write_command(self, text: str):
        if not self._client or not self._client.is_connected:
            return
        if not self._command_char_uuid:
            if not self._warned_no_command_channel:
                self._warned_no_command_channel = True
                self.status.emit("Command failed: command characteristic not available on connected firmware.")
            return
        try:
            await self._client.write_gatt_char(self._command_char_uuid, text.encode("utf-8"), response=False)
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

    def _diag(self, key: str, value):
        # Diagnostic logger: prints first packet of each kind, then every 50th.
        n = self._diag_counts.get(key, 0) + 1
        self._diag_counts[key] = n
        if n == 1 or n % 50 == 0:
            print(f"[BLE-DIAG] {key} #{n} = {value}", flush=True)

    def _on_state(self, _sender, data: bytearray):
        if len(data) >= 1:
            v = int(data[0])
            self._diag("state", v)
            self.telemetry.emit(v, -1, -1, -1)

    def _on_count(self, _sender, data: bytearray):
        if len(data) >= 4:
            v = int(struct.unpack("<I", bytes(data[:4]))[0])
            self._diag("count", v)
            self.telemetry.emit(-1, v, -1, -1)

    def _on_rate(self, _sender, data: bytearray):
        if len(data) >= 2:
            v = int(struct.unpack("<H", bytes(data[:2]))[0])
            self._diag("rate_x10", v)
            self.telemetry.emit(-1, -1, v, -1)

    def _on_rpm(self, _sender, data: bytearray):
        if len(data) >= 2:
            v = int(struct.unpack("<H", bytes(data[:2]))[0])
            self._diag("rpm_x10", v)
            self.telemetry.emit(-1, -1, -1, v)

    def _on_impact(self, _sender, data: bytearray):
        if len(data) >= 16:
            hit_count, x_mg, y_mg, z_mg, mag_mg, intensity, contact_x, contact_y, flags = struct.unpack(
                "<IhhhHBbbB", bytes(data[:16])
            )
            valid = 1 if (flags & 0x01) else 0
            self.impact.emit(hit_count, x_mg, y_mg, z_mg, mag_mg, intensity, contact_x, contact_y, valid)
        elif len(data) >= 13:
            hit_count, x_mg, y_mg, z_mg, intensity, contact_x, contact_y = struct.unpack("<IhhhBbb", bytes(data[:13]))
            mag_mg = int(math.sqrt(float(x_mg * x_mg + y_mg * y_mg + z_mg * z_mg)))
            valid = 1 if intensity > 0 else 0
            self.impact.emit(hit_count, x_mg, y_mg, z_mg, mag_mg, intensity, contact_x, contact_y, valid)

    def _on_gate_speed(self, _sender, data: bytearray):
        if len(data) >= 10:
            sample_id, speed_kmh_x10, transit_us = struct.unpack("<IHI", bytes(data[:10]))
            self.gate_speed.emit(sample_id, speed_kmh_x10, int(transit_us / 1000))
        elif len(data) >= 8:
            sample_id, speed_kmh_x10, transit_ms = struct.unpack("<IHH", bytes(data[:8]))
            self.gate_speed.emit(sample_id, speed_kmh_x10, transit_ms)


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
        self._last_gate_speed_mph = 0.0
        self._last_gate_speed_ts = 0.0
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
        self._hardware_settings_window: SettingsWindow | None = None
        self._app_settings_window: SettingsWindow | None = None
        self._connect_popup: QDialog | None = None
        self._connect_popup_stage: QLabel | None = None
        self._connect_popup_detail: QLabel | None = None
        self._connect_popup_sensor: QLabel | None = None
        self._connect_popup_btn: QPushButton | None = None
        self._connect_popup_steps: list[QLabel] = []
        self._connect_step_states = ["pending", "pending", "pending", "pending"]
        self._last_handshake_ok = False
        self._fw_calibration = {
            "counts_per_g": 410.0,
            "impact_mg_100": 4200,
            "contact_full_scale_mg": 1500,
            "min_valid_impact_mg": 250,
        }
        self._fw_gate_distance_cm = 3.0
        self._fw_rpm_pulses_per_rev = 1
        self._court_surface = "Hard"
        self._drill_mode = "Off"
        self._drill_goal = 20
        self._drill_hits = 0
        self._drill_attempts = 0
        self._drill_goal_announced = False
        self._last_count_sample_val = 0
        self._last_count_sample_ts = 0.0
        self._drill_status_text = "Drill Progress: Off"
        self._shot_intent_override = "Auto"
        self._ui_simple_mode = True

        self._build_ui()
        self._update_drill_status()
        self._refresh_target_chip()
        self._apply_detail_mode()
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

        self._level_chip_buttons: dict[str, QPushButton] = {}
        self.level_chip_popup = QFrame(self, Qt.WindowType.Popup)
        self.level_chip_popup.setObjectName("LevelPopup")
        level_lay = QVBoxLayout(self.level_chip_popup)
        level_lay.setContentsMargins(8, 8, 8, 8)
        level_lay.setSpacing(6)
        for level in self._competition_profiles.keys():
            short = {"Newbie": "NEWBIE", "Competitive": "COMPETITIVE", "Professional": "PRO"}.get(
                level, level.upper()
            )
            btn = QPushButton(short)
            btn.setObjectName("LevelOptionChip")
            btn.clicked.connect(lambda _checked=False, lvl=level: self._on_level_chip_selected(lvl))
            level_lay.addWidget(btn)
            self._level_chip_buttons[level] = btn
        self.target_chip_popup = QFrame(self, Qt.WindowType.Popup)
        self.target_chip_popup.setObjectName("LevelPopup")
        target_lay = QVBoxLayout(self.target_chip_popup)
        target_lay.setContentsMargins(8, 8, 8, 8)
        target_lay.setSpacing(6)
        self._target_chip_buttons: dict[str, QPushButton] = {}
        for mode, label in (
            ("Off", "OFF"),
            ("20 Topspin Cross-Court", "TOPSPIN CC"),
            ("15 Serve T", "SERVE T"),
            ("15 Backhand Topspin", "BACKHAND TOPSPIN"),
            ("20 Heavy Ball", "HEAVY BALL"),
        ):
            btn = QPushButton(label)
            btn.setObjectName("LevelOptionChip")
            btn.clicked.connect(lambda _checked=False, m=mode: self._on_target_chip_selected(m))
            target_lay.addWidget(btn)
            self._target_chip_buttons[mode] = btn
        self.detail_chip = QPushButton("DETAIL\nSIMPLE")
        self.detail_chip.setObjectName("ChipLevel")
        self.detail_chip.setMinimumWidth(104)
        self.detail_chip.clicked.connect(self._toggle_detail_mode)
        self.detail_chip.setToolTip("Toggle Simple/Advanced details")
        hh.addWidget(self.detail_chip)

        self.mode_chip = QLabel("MODE\nSIMULATION")
        self.mode_chip.setObjectName("ChipOk")
        self.mode_chip.setMinimumWidth(95)
        self.sensors_chip = QLabel("SENSORS\nDISCONNECTED")
        self.sensors_chip.setObjectName("ChipErr")
        self.sensors_chip.setMinimumWidth(95)
        self.link_chip = QLabel("HANDSHAKE\n—")
        self.link_chip.setObjectName("ChipMuted")
        self.link_chip.setMinimumWidth(102)
        self.btn_stats_menu = QPushButton("📊")
        self.btn_stats_menu.setObjectName("IconBtn")
        self.btn_stats_menu.setFixedSize(30, 22)
        self.btn_stats_menu.setToolTip("Open Students & Stats")
        self.btn_stats_menu.clicked.connect(self._open_stats_screen)
        self.btn_settings_menu = QPushButton("⚙")
        self.btn_settings_menu.setObjectName("IconBtn")
        self.btn_settings_menu.setFixedSize(30, 22)
        self.btn_settings_menu.setToolTip("Settings")
        self.btn_settings_menu.clicked.connect(self._toggle_settings_popup)
        self.clock_lbl = QLabel("--:--:--\n--- --, ----")
        self.clock_lbl.setObjectName("ClockLabel")
        self.clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.clock_lbl.setMinimumWidth(120)
        hh.addWidget(self.mode_chip)
        hh.addWidget(self.sensors_chip)
        hh.addWidget(self.link_chip)
        hh.addWidget(self.btn_stats_menu)
        hh.addWidget(self.btn_settings_menu)
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
        self.lbl_live_rpm = QLabel("Live RPM           0")
        self.lbl_gate_speed = QLabel("Gate Speed         --.- mph")
        self.lbl_impact_xy.setObjectName("SmallMuted")
        self.lbl_impact_red.setObjectName("SmallMuted")
        self.lbl_live_rpm.setObjectName("SmallMuted")
        self.lbl_gate_speed.setObjectName("SmallMuted")
        self.left_current.layout().addWidget(self.lbl_impact_xy)
        self.left_current.layout().addWidget(self.lbl_impact_red)
        self.left_current.layout().addWidget(self.lbl_live_rpm)
        self.left_current.layout().addWidget(self.lbl_gate_speed)
        self.lbl_spin_type = QLabel("Spin Type          Flat")
        self.lbl_shot_type = QLabel("Shot Type          Forehand")
        self.lbl_coaching = QLabel("Coaching Cue       Build brush-up path")
        self.lbl_benchmark = QLabel("Benchmark Score    0 / 100")
        self.lbl_spin_type.setObjectName("SmallMuted")
        self.lbl_shot_type.setObjectName("SmallMuted")
        self.lbl_coaching.setObjectName("SmallMuted")
        self.lbl_benchmark.setObjectName("SmallMuted")
        self.left_current.layout().addWidget(self.lbl_spin_type)
        self.left_current.layout().addWidget(self.lbl_shot_type)
        self.left_current.layout().addWidget(self.lbl_coaching)
        self.left_current.layout().addWidget(self.lbl_benchmark)
        left_col.addWidget(self.left_current)

        self.left_pred = self._panel("PREDICTED LANDING")
        self.lbl_land_x = QLabel("X (Cross Court)   0.00 m")
        self.lbl_land_y = QLabel("Y (Down Court)    0.00 m")
        self.left_pred.layout().addWidget(self.lbl_land_x)
        self.left_pred.layout().addWidget(self.lbl_land_y)
        self.lbl_face_tilt = QLabel("Face Tilt @ Impact  0.0°")
        self.lbl_brush = QLabel("Brush Angle         0.0°")
        self.lbl_net_clearance = QLabel("Net Clearance       0.00 m")
        self.lbl_bounce = QLabel("Post-bounce Kick    0.00 m")
        self.lbl_target_zone = QLabel("Target Zone         MISS")
        self.lbl_face_tilt.setObjectName("SmallMuted")
        self.lbl_brush.setObjectName("SmallMuted")
        self.lbl_net_clearance.setObjectName("SmallMuted")
        self.lbl_bounce.setObjectName("SmallMuted")
        self.lbl_target_zone.setObjectName("SmallMuted")
        self.left_pred.layout().addWidget(self.lbl_face_tilt)
        self.left_pred.layout().addWidget(self.lbl_brush)
        self.left_pred.layout().addWidget(self.lbl_net_clearance)
        self.left_pred.layout().addWidget(self.lbl_bounce)
        self.left_pred.layout().addWidget(self.lbl_target_zone)
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
        header_chip_height = 28
        self.level_chip = QPushButton("LEVEL: COMPETITIVE ▾")
        self.level_chip.setObjectName("TargetHeaderBtn")
        self.level_chip.setMinimumWidth(185)
        self.level_chip.setFixedHeight(header_chip_height)
        self.level_chip.setToolTip("Choose competition level")
        self.level_chip.clicked.connect(self._toggle_level_chip_popup)
        icons.addWidget(self.level_chip)
        icons.addStretch(1)
        self.target_chip = QPushButton("TARGET: OFF ▾")
        self.target_chip.setObjectName("TargetHeaderBtn")
        self.target_chip.setMinimumWidth(170)
        self.target_chip.setFixedHeight(header_chip_height)
        self.target_chip.setToolTip("Choose target zone / drill")
        self.target_chip.clicked.connect(self._toggle_target_chip_popup)
        icons.addWidget(self.target_chip)
        self.court_panel.layout().addLayout(icons)
        self.settings_popup = QFrame(self, Qt.WindowType.Popup)
        self.settings_popup.setObjectName("SettingsPopup")
        settings_lay = QVBoxLayout(self.settings_popup)
        settings_lay.setContentsMargins(8, 8, 8, 8)
        settings_lay.setSpacing(6)
        self.btn_settings_hardware = QPushButton("Hardware Settings")
        self.btn_settings_hardware.setObjectName("SettingsMenuOption")
        self.btn_settings_hardware.clicked.connect(self._open_hardware_settings_from_menu)
        settings_lay.addWidget(self.btn_settings_hardware)
        self.btn_settings_app = QPushButton("App Settings")
        self.btn_settings_app.setObjectName("SettingsMenuOption")
        self.btn_settings_app.clicked.connect(self._open_app_settings_from_menu)
        settings_lay.addWidget(self.btn_settings_app)
        self.court_widget = CourtWidget()
        self.court_widget.set_target_overlay(self._drill_mode)
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
        self.history_table = QTableWidget(0, 10)
        self.history_table.setHorizontalHeaderLabels(
            ["#", "TIME", "SPEED", "SPIN", "SPIN TYPE", "SHOT", "LANDING", "NET CLR", "TARGET", "COACHING"]
        )
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.history_table.setColumnWidth(0, 54)
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_panel.layout().addWidget(self.history_table)
        lower.addWidget(self.history_panel, 2)

        wizard_row = QFrame()
        wizard_row.setObjectName("Panel")
        wizard_lay = QVBoxLayout(wizard_row)
        wizard_lay.setContentsMargins(10, 8, 10, 8)
        wizard_lay.setSpacing(2)
        self.lbl_connect_stage = QLabel("LIVE WIZARD · Ready")
        self.lbl_connect_stage.setObjectName("PanelTitle")
        self.lbl_connect_detail = QLabel(
            "Step 1/4 Discover sensor · Step 2/4 Link BLE · Step 3/4 Handshake · Step 4/4 Live stream"
        )
        self.lbl_connect_detail.setObjectName("SmallMuted")
        wizard_lay.addWidget(self.lbl_connect_stage)
        wizard_lay.addWidget(self.lbl_connect_detail)
        outer.addWidget(wizard_row)

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

    def _set_connection_wizard_state(self, stage: str, detail: str):
        if hasattr(self, "lbl_connect_stage"):
            self.lbl_connect_stage.setText(f"LIVE WIZARD · {stage}")
        if hasattr(self, "lbl_connect_detail"):
            self.lbl_connect_detail.setText(detail)
        if self._connect_popup_stage is not None:
            self._connect_popup_stage.setText(stage)
        if self._connect_popup_detail is not None:
            self._connect_popup_detail.setText(detail)

    def _set_connection_wizard_sensor(self, text: str):
        if self._connect_popup_sensor is not None:
            self._connect_popup_sensor.setText(text)

    def _set_connect_step_state(self, step_idx: int, state: str):
        if not (0 <= step_idx < len(self._connect_step_states)):
            return
        self._connect_step_states[step_idx] = state
        self._refresh_connect_step_labels()

    def _reset_connect_step_states(self):
        self._connect_step_states = ["pending", "pending", "pending", "pending"]
        self._refresh_connect_step_labels()

    def _refresh_connect_step_labels(self):
        if not self._connect_popup_steps:
            return
        labels = [
            "Discover sensor",
            "Link BLE",
            "Handshake",
            "Live stream",
        ]
        style_map = {
            "pending": ("○", "#9bb0c7"),
            "in_progress": ("◔", "#8fd0ff"),
            "done": ("✓", "#31e46a"),
            "warn": ("⚠", "#ffd78a"),
        }
        for i, lbl in enumerate(self._connect_popup_steps):
            st = self._connect_step_states[i] if i < len(self._connect_step_states) else "pending"
            icon, color = style_map.get(st, style_map["pending"])
            lbl.setText(f"<span style='color:{color}; font-weight:700'>{icon}</span>  {i + 1}. {labels[i]}")

    def _ensure_connect_popup(self):
        if self._connect_popup is not None:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Live Connection Wizard")
        dlg.setModal(False)
        dlg.resize(460, 190)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)
        ttl = QLabel("Connect to ESP32 sensor")
        ttl.setObjectName("PanelTitle")
        lay.addWidget(ttl)
        self._connect_popup_stage = QLabel("Ready")
        self._connect_popup_stage.setObjectName("MainTitle")
        lay.addWidget(self._connect_popup_stage)
        self._connect_popup_detail = QLabel("Press CONNECT SENSOR to begin guided connection.")
        self._connect_popup_detail.setObjectName("SmallMuted")
        self._connect_popup_detail.setWordWrap(True)
        lay.addWidget(self._connect_popup_detail)
        self._connect_popup_sensor = QLabel("Sensor found: waiting...")
        self._connect_popup_sensor.setObjectName("SmallMuted")
        self._connect_popup_sensor.setWordWrap(True)
        lay.addWidget(self._connect_popup_sensor)
        steps_box = QFrame()
        steps_box.setObjectName("Panel")
        steps_lay = QVBoxLayout(steps_box)
        steps_lay.setContentsMargins(8, 6, 8, 6)
        steps_lay.setSpacing(3)
        self._connect_popup_steps = []
        for _ in range(4):
            s = QLabel("")
            s.setObjectName("SmallMuted")
            self._connect_popup_steps.append(s)
            steps_lay.addWidget(s)
        lay.addWidget(steps_box)
        row = QHBoxLayout()
        row.addStretch(1)
        self._connect_popup_btn = QPushButton("Close")
        self._connect_popup_btn.setObjectName("SecondaryBtn")
        self._connect_popup_btn.clicked.connect(self._on_connect_popup_button)
        row.addWidget(self._connect_popup_btn)
        lay.addLayout(row)
        self._connect_popup = dlg
        self._reset_connect_step_states()

    def _show_connect_popup(self):
        self._ensure_connect_popup()
        if self._connect_popup_btn is not None:
            self._connect_popup_btn.setText("Close")
        if self._connect_popup is not None:
            self._connect_popup.show()
            self._connect_popup.raise_()
            self._connect_popup.activateWindow()

    def _on_connect_popup_button(self):
        if self._connect_popup is not None:
            self._connect_popup.hide()

    def _auto_start_discovery(self):
        if self._thread and self._thread.isRunning():
            return
        self.statusBar().showMessage("Auto-discovery enabled: scanning for tennis BLE sensor...")
        self._set_connection_wizard_state(
            "Step 1/4 Discovering Sensor",
            "Scanning for TENNIS_KY003 advertising the tennis BLE service...",
        )
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

    def _toggle_level_chip_popup(self):
        if self.target_chip_popup.isVisible():
            self.target_chip_popup.hide()
        if hasattr(self, "settings_popup") and self.settings_popup.isVisible():
            self.settings_popup.hide()
        if self.level_chip_popup.isVisible():
            self.level_chip_popup.hide()
            return
        chip_width = self.level_chip.width()
        chip_height = self.level_chip.height()
        popup_width = max(180, chip_width + 18)
        self.level_chip_popup.setFixedWidth(popup_width)
        for btn in self._level_chip_buttons.values():
            btn.setMinimumWidth(popup_width - 16)
            btn.setFixedHeight(chip_height)
        pos = self.level_chip.mapToGlobal(self.level_chip.rect().bottomLeft())
        self.level_chip_popup.move(pos.x(), pos.y() + 6)
        self.level_chip_popup.adjustSize()
        self.level_chip_popup.show()

    def _on_level_chip_selected(self, level: str):
        self.level_chip_popup.hide()
        if level == self._competition_level:
            self._refresh_competition_toggle()
            return
        self._set_competition_level(level)

    def _toggle_detail_mode(self):
        self._ui_simple_mode = not self._ui_simple_mode
        self._apply_detail_mode()

    def _apply_detail_mode(self):
        self.detail_chip.setText("DETAIL\nSIMPLE" if self._ui_simple_mode else "DETAIL\nADVANCED")

        advanced_widgets = [
            self.lbl_live_rpm,
            self.lbl_gate_speed,
            self.lbl_spin_type,
            self.lbl_shot_type,
            self.lbl_coaching,
            self.lbl_benchmark,
            self.lbl_face_tilt,
            self.lbl_brush,
            self.lbl_net_clearance,
            self.lbl_bounce,
            self.lbl_target_zone,
        ]
        for widget in advanced_widgets:
            widget.setVisible(not self._ui_simple_mode)

        # Keep history focused in simple mode.
        self.history_table.setColumnHidden(4, self._ui_simple_mode)  # spin type
        self.history_table.setColumnHidden(5, self._ui_simple_mode)  # shot type
        self.history_table.setColumnHidden(7, self._ui_simple_mode)  # net clearance
        self.history_table.setColumnHidden(8, self._ui_simple_mode)  # target
        self.history_table.setColumnHidden(9, self._ui_simple_mode)  # coaching

    def set_court_surface(self, surface: str):
        if surface not in {"Hard", "Clay", "Grass"}:
            return
        self._court_surface = surface
        self.statusBar().showMessage(f"Court surface set to {self._court_surface}.")
        for w in self._app_settings_windows():
            w.lbl_training_status.setText(self._drill_status_text)

    def _toggle_target_chip_popup(self):
        if self.level_chip_popup.isVisible():
            self.level_chip_popup.hide()
        if hasattr(self, "settings_popup") and self.settings_popup.isVisible():
            self.settings_popup.hide()
        if self.target_chip_popup.isVisible():
            self.target_chip_popup.hide()
            return
        chip_width = self.target_chip.width()
        chip_height = self.target_chip.height()
        popup_width = max(180, chip_width + 18)
        self.target_chip_popup.setFixedWidth(popup_width)
        for btn in self._target_chip_buttons.values():
            btn.setMinimumWidth(popup_width - 16)
            btn.setFixedHeight(chip_height)
        pos = self.target_chip.mapToGlobal(self.target_chip.rect().bottomLeft())
        self.target_chip_popup.move(pos.x(), pos.y() + 6)
        self.target_chip_popup.adjustSize()
        self.target_chip_popup.show()

    def _toggle_settings_popup(self):
        if self.level_chip_popup.isVisible():
            self.level_chip_popup.hide()
        if self.target_chip_popup.isVisible():
            self.target_chip_popup.hide()
        if self.settings_popup.isVisible():
            self.settings_popup.hide()
            return
        sender = self.sender()
        if isinstance(sender, QPushButton):
            self.settings_popup.adjustSize()
            pos = sender.mapToGlobal(sender.rect().bottomRight())
            self.settings_popup.move(pos.x() - self.settings_popup.width(), pos.y() + 6)
        self.settings_popup.show()

    def _open_hardware_settings_from_menu(self):
        self.settings_popup.hide()
        self._open_hardware_settings_screen()

    def _open_app_settings_from_menu(self):
        self.settings_popup.hide()
        self._open_app_settings_screen()

    def _on_target_chip_selected(self, mode: str):
        self.target_chip_popup.hide()
        self._apply_drill_mode(mode, sync_settings=True)

    def set_shot_intent_override(self, intent: str):
        if intent not in {"Auto", "Forehand", "Backhand", "Serve"}:
            return
        self._shot_intent_override = intent
        self.statusBar().showMessage(f"Shot intent set to {self._shot_intent_override}.")

    def set_drill_mode(self, mode: str):
        if mode not in {"Off", "20 Topspin Cross-Court", "15 Serve T", "15 Backhand Topspin", "20 Heavy Ball"}:
            return
        self._apply_drill_mode(mode, sync_settings=False)

    def _apply_drill_mode(self, mode: str, sync_settings: bool):
        self._drill_mode = mode
        if self._drill_mode in {"15 Serve T", "15 Backhand Topspin"}:
            self._drill_goal = 15
        elif self._drill_mode in {"20 Topspin Cross-Court", "20 Heavy Ball"}:
            self._drill_goal = 20
        else:
            self._drill_goal = 20
        self._drill_hits = 0
        self._drill_attempts = 0
        self._drill_goal_announced = False
        self.court_widget.set_target_overlay(self._drill_mode)
        self._update_drill_status()
        self._refresh_target_chip()
        if sync_settings:
            for w in self._app_settings_windows():
                w.refresh()

    def _update_drill_status(self):
        if self._drill_mode == "Off":
            self._drill_status_text = "Drill Progress: Off"
            for w in self._app_settings_windows():
                w.lbl_training_status.setText(self._drill_status_text)
            return
        self._drill_status_text = f"Drill Progress: {self._drill_hits}/{self._drill_goal} ({self._drill_attempts} shots)"
        for w in self._app_settings_windows():
            w.lbl_training_status.setText(self._drill_status_text)

    def _refresh_target_chip(self):
        label = {
            "Off": "OFF",
            "20 Topspin Cross-Court": "TOPSPIN CC",
            "15 Serve T": "SERVE T",
            "15 Backhand Topspin": "BACKHAND",
            "20 Heavy Ball": "HEAVY BALL",
        }.get(self._drill_mode, self._drill_mode.upper())
        self.target_chip.setText(f"TARGET: {label} ▾")

        active_palette = {
            "Off": {"border": "#3a4d66", "bg": "#102033", "hover": "#15304b", "fg": "#a8bfd8"},
            "20 Topspin Cross-Court": {"border": "#2a6c54", "bg": "#05291f", "hover": "#083629", "fg": "#8ff0af"},
            "15 Serve T": {"border": "#8a6a2a", "bg": "#2a2210", "hover": "#3a2c12", "fg": "#ffd78a"},
            "15 Backhand Topspin": {"border": "#2b5f8f", "bg": "#0a2943", "hover": "#10375a", "fg": "#8fd0ff"},
            "20 Heavy Ball": {"border": "#654299", "bg": "#1e1534", "hover": "#2a1e49", "fg": "#d7c0ff"},
        }.get(
            self._drill_mode,
            {"border": "#3a4d66", "bg": "#102033", "hover": "#15304b", "fg": "#a8bfd8"},
        )
        self.target_chip.setStyleSheet(
            f"""
            QPushButton {{
                border: 1px solid {active_palette['border']};
                border-radius: 7px;
                padding: 4px 10px;
                font-size: 10px;
                font-weight: 800;
                color: {active_palette['fg']};
                background: {active_palette['bg']};
            }}
            QPushButton:hover {{
                background: {active_palette['hover']};
            }}
            """
        )

        self.target_chip_popup.setStyleSheet(
            """
            QFrame#LevelPopup {
                background: #071528;
                border: 1px solid #1d4369;
                border-radius: 8px;
            }
            """
        )
        per_mode = {
            "Off": {"border": "#3a4d66", "bg": "#102033", "hover": "#15304b", "fg": "#a8bfd8"},
            "20 Topspin Cross-Court": {"border": "#2a6c54", "bg": "#05291f", "hover": "#083629", "fg": "#8ff0af"},
            "15 Serve T": {"border": "#8a6a2a", "bg": "#2a2210", "hover": "#3a2c12", "fg": "#ffd78a"},
            "15 Backhand Topspin": {"border": "#2b5f8f", "bg": "#0a2943", "hover": "#10375a", "fg": "#8fd0ff"},
            "20 Heavy Ball": {"border": "#654299", "bg": "#1e1534", "hover": "#2a1e49", "fg": "#d7c0ff"},
        }
        for mode, btn in self._target_chip_buttons.items():
            pal = per_mode.get(mode, per_mode["Off"])
            width = "2px" if mode == self._drill_mode else "1px"
            weight = "900" if mode == self._drill_mode else "800"
            btn.setStyleSheet(
                f"""
                QPushButton {{
                    border: {width} solid {pal['border']};
                    border-radius: 7px;
                    padding: 6px 10px;
                    font-size: 10px;
                    font-weight: {weight};
                    color: {pal['fg']};
                    background: {pal['bg']};
                    text-align: center;
                }}
                QPushButton:hover {{
                    background: {pal['hover']};
                }}
                """
            )

    def _drill_hit_for_shot(self, shot: Shot) -> bool:
        if self._drill_mode == "20 Topspin Cross-Court":
            return shot.spin_type == "Topspin" and shot.target_zone_hit
        if self._drill_mode == "15 Serve T":
            return shot.shot_type == "Serve" and shot.target_zone_hit and shot.net_clearance_m >= 0.22
        if self._drill_mode == "15 Backhand Topspin":
            return shot.shot_type == "Backhand" and shot.spin_type == "Topspin" and shot.target_zone_hit
        if self._drill_mode == "20 Heavy Ball":
            # Heavy ball proxy from available hardware/derived signals.
            # Thresholds are level-aware so Newbie/Competitive/Professional
            # coaching targets can progress naturally.
            cfg = self._heavy_ball_thresholds()
            return (
                shot.speed >= cfg["min_speed"]
                and shot.spin >= cfg["min_spin"]
                and shot.landing_y >= cfg["min_depth_y"]
                and abs(shot.landing_x) <= cfg["max_abs_x"]
                and shot.impact_redness >= cfg["min_impact_redness"]
            )
        return False

    def _heavy_ball_thresholds(self) -> dict[str, float]:
        profile = self._competition_profiles.get(
            self._competition_level, self._competition_profiles[DEFAULT_COMPETITION_LEVEL]
        )
        depth_by_level = {"Newbie": 6.9, "Competitive": 7.2, "Professional": 7.5}
        width_by_level = {"Newbie": 3.0, "Competitive": 2.8, "Professional": 2.5}
        return {
            "min_speed": max(42.0, float(profile["target_speed"]) * 0.95),
            "min_spin": max(1100.0, float(profile["target_spin"]) * 0.90),
            "min_impact_redness": max(28.0, float(profile["target_impact"]) * 0.85),
            "min_depth_y": depth_by_level.get(self._competition_level, 7.2),
            "max_abs_x": width_by_level.get(self._competition_level, 2.8),
        }

    @staticmethod
    def _classify_spin_type(spin: int, impact_y: int) -> str:
        if spin >= 1700 and impact_y > -20:
            return "Topspin"
        if spin <= 900 or impact_y < -35:
            return "Slice"
        return "Flat"

    @staticmethod
    def _infer_shot_type(speed: float, arm_angle: float) -> str:
        if speed >= 85.0 and abs(arm_angle) <= 22.0:
            return "Serve"
        return "Forehand" if arm_angle >= 0.0 else "Backhand"

    @staticmethod
    def _estimate_face_tilt(arm_angle: float, impact_y: int) -> float:
        return max(-25.0, min(25.0, arm_angle * 0.12 - impact_y * 0.20))

    @staticmethod
    def _estimate_brush_angle(spin: int, impact_y: int) -> float:
        return max(4.0, min(36.0, abs(impact_y) * 0.22 + max(0, spin - 900) / 130.0))

    def _estimate_net_clearance(self, speed: float, spin: int, arm_angle: float) -> float:
        clearance = 0.35 + (spin / 3000.0) * 0.55 - (speed / 120.0) * 0.18 + (arm_angle / 90.0) * 0.22
        return max(0.05, min(1.50, clearance))

    def _estimate_bounce_kick(self, speed: float, spin: int) -> float:
        surface_mul = {"Hard": 1.0, "Clay": 1.18, "Grass": 0.82}.get(self._court_surface, 1.0)
        kick = (0.10 + (spin / 3000.0) * 1.20 + max(0.0, speed - 40.0) * 0.003) * surface_mul
        return max(0.05, min(2.50, kick))

    def _is_target_zone_hit(self, shot_type: str, arm_angle: float, landing_x: float, landing_y: float, spin_type: str) -> bool:
        if shot_type == "Serve":
            return -1.4 <= landing_x <= 1.4 and 7.1 <= landing_y <= 9.8
        if shot_type == "Backhand":
            cross_ok = landing_x >= 0.4
        elif shot_type == "Forehand":
            cross_ok = landing_x <= -0.4
        else:
            cross_ok = (arm_angle >= 0.0 and landing_x <= -0.4) or (arm_angle < 0.0 and landing_x >= 0.4)
        return cross_ok and 6.5 <= landing_y <= 10.2 and spin_type == "Topspin"

    @staticmethod
    def _coaching_cue(spin_type: str, face_tilt_deg: float, brush_angle_deg: float) -> str:
        if spin_type != "Topspin":
            return "Too flat: brush up more through contact."
        if face_tilt_deg < 8.0:
            return "Face too open: close racket face slightly."
        if brush_angle_deg < 16.0:
            return "Good intent, add more low-to-high swing path."
        if face_tilt_deg > 17.0:
            return "Face too closed: recover a few degrees."
        return "Great topspin mechanics: keep same tempo."

    @staticmethod
    def _benchmark_score(speed: float, spin: int, face_tilt_deg: float, brush_angle_deg: float) -> int:
        speed_score = max(0.0, 100.0 - abs(speed - 66.0) * 2.4)
        spin_score = max(0.0, 100.0 - abs(spin - 2200) / 22.0)
        face_score = max(0.0, 100.0 - abs(face_tilt_deg - 12.0) * 7.0)
        brush_score = max(0.0, 100.0 - abs(brush_angle_deg - 22.0) * 4.0)
        return int(max(0.0, min(100.0, speed_score * 0.28 + spin_score * 0.36 + face_score * 0.18 + brush_score * 0.18)))

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
        if not hasattr(self, "_level_chip_buttons") or not self._level_chip_buttons:
            return
        short = {
            "Newbie": "NEWBIE",
            "Competitive": "COMPETITIVE",
            "Professional": "PRO",
        }.get(self._competition_level, self._competition_level.upper())
        glass_border = "rgba(178, 216, 248, 0.34)"
        glass_bg = "rgba(235, 246, 255, 0.08)"
        glass_hover = "rgba(235, 246, 255, 0.16)"
        glass_fg = "rgba(220, 237, 252, 0.86)"
        level_palettes = {
            "Newbie": {
                "border": "rgba(116, 173, 224, 0.40)",
                "bg": "rgba(44, 120, 180, 0.14)",
                "hover": "rgba(44, 120, 180, 0.22)",
                "active_bg": "rgba(44, 120, 180, 0.30)",
                "fg": "rgba(196, 230, 255, 0.88)",
            },
            "Competitive": {
                "border": "rgba(223, 186, 106, 0.42)",
                "bg": "rgba(186, 138, 48, 0.14)",
                "hover": "rgba(186, 138, 48, 0.22)",
                "active_bg": "rgba(186, 138, 48, 0.30)",
                "fg": "rgba(255, 229, 176, 0.90)",
            },
            "Professional": {
                "border": "rgba(124, 214, 180, 0.42)",
                "bg": "rgba(45, 170, 118, 0.14)",
                "hover": "rgba(45, 170, 118, 0.22)",
                "active_bg": "rgba(45, 170, 118, 0.30)",
                "fg": "rgba(195, 244, 218, 0.90)",
            },
        }
        palette = level_palettes.get(
            self._competition_level,
            {
                "border": "rgba(124, 214, 180, 0.42)",
                "bg": "rgba(45, 170, 118, 0.14)",
                "hover": "rgba(45, 170, 118, 0.22)",
                "active_bg": "rgba(45, 170, 118, 0.30)",
                "fg": "rgba(195, 244, 218, 0.90)",
            },
        )
        if hasattr(self, "level_chip"):
            self.level_chip.setText(f"LEVEL: {short} ▾")
            self.level_chip.setStyleSheet(
                f"""
                QPushButton {{
                    border: 1px solid {palette['border']};
                    border-radius: 7px;
                    padding: 4px 10px;
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
        if hasattr(self, "level_chip_popup"):
            self.level_chip_popup.setStyleSheet(
                """
                QFrame#LevelPopup {
                    background: #071528;
                    border: 1px solid #1d4369;
                    border-radius: 8px;
                }
                """
            )
        for level, btn in self._level_chip_buttons.items():
            option_palette = level_palettes.get(level, palette)
            border = option_palette["border"]
            bg = option_palette["bg"]
            fg = option_palette["fg"]
            hover = option_palette["hover"]
            active_bg = option_palette["active_bg"]
            is_active = level == self._competition_level
            btn.setChecked(is_active)
            if level == self._competition_level:
                btn.setStyleSheet(
                    f"""
                    QPushButton {{
                        border: 2px solid {border};
                        border-radius: 10px;
                        padding: 7px 10px;
                        font-size: 10px;
                        font-weight: 900;
                        color: {fg};
                        background: {active_bg};
                        text-align: center;
                    }}
                    QPushButton:hover {{
                        background: {hover};
                    }}
                    """
                )
            else:
                btn.setStyleSheet(
                    f"""
                    QPushButton {{
                        border: 1px solid {glass_border};
                        border-radius: 10px;
                        padding: 7px 10px;
                        font-size: 10px;
                        font-weight: 800;
                        color: {glass_fg};
                        background: {glass_bg};
                        text-align: center;
                    }}
                    QPushButton:hover {{
                        background: {glass_hover};
                    }}
                    """
                )

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

    def _all_settings_windows(self) -> list[SettingsWindow]:
        windows = []
        for w in (self._settings_window, self._hardware_settings_window, self._app_settings_window):
            if w is not None and w not in windows:
                windows.append(w)
        return windows

    def _hardware_settings_windows(self) -> list[SettingsWindow]:
        return [w for w in self._all_settings_windows() if w.has_hardware_settings]

    def _app_settings_windows(self) -> list[SettingsWindow]:
        return [w for w in self._all_settings_windows() if w.has_app_settings]

    def _set_calibration_status(self, text: str):
        for w in self._hardware_settings_windows():
            w.set_calibration_status(text)

    def _refresh_calibration_ui(self):
        for w in self._hardware_settings_windows():
            w.set_calibration_values(
                self._fw_calibration["counts_per_g"],
                int(self._fw_calibration["impact_mg_100"]),
                int(self._fw_calibration["contact_full_scale_mg"]),
                int(self._fw_calibration["min_valid_impact_mg"]),
            )

    def _send_worker_command(self, text: str, quiet_when_unavailable: bool = False) -> bool:
        if not self._worker:
            self.statusBar().showMessage("Sensor not connected.")
            return False
        if not self._worker.can_send_commands():
            if not quiet_when_unavailable:
                self.statusBar().showMessage(
                    "Connected in telemetry-only mode: firmware command characteristic unavailable."
                )
            return False
        self._worker.request_command(text)
        return True

    def _request_firmware_calibration(self):
        if self._send_worker_command(CAL_GET_COMMAND):
            self._set_calibration_status("Requested calibration from firmware...")

    def _apply_firmware_calibration_from_ui(
        self,
        counts_txt: str,
        impact_txt: str,
        contact_txt: str,
        min_valid_txt: str,
    ):
        try:
            counts_per_g = float(counts_txt)
            impact_mg_100 = int(float(impact_txt))
            contact_full_scale_mg = int(float(contact_txt))
            min_valid_impact_mg = int(float(min_valid_txt))
        except ValueError:
            self._set_calibration_status("Calibration values invalid.")
            return

        if (
            counts_per_g < 50.0
            or impact_mg_100 < 100
            or contact_full_scale_mg < 100
            or min_valid_impact_mg < 50
        ):
            self._set_calibration_status("Calibration values out of range.")
            return

        cmd = f"CAL:SET:{counts_per_g:.2f},{impact_mg_100},{contact_full_scale_mg},{min_valid_impact_mg}"
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
            if len(parts) in (3, 4):
                try:
                    self._fw_calibration["counts_per_g"] = float(parts[0])
                    self._fw_calibration["impact_mg_100"] = int(parts[1])
                    self._fw_calibration["contact_full_scale_mg"] = int(parts[2])
                    self._fw_calibration["min_valid_impact_mg"] = int(parts[3]) if len(parts) >= 4 else 250
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
            return
        if text.startswith("GATE:CFG:"):
            raw = text[len("GATE:CFG:"):]
            try:
                self._fw_gate_distance_cm = float(raw)
                self.statusBar().showMessage(f"Gate distance loaded: {self._fw_gate_distance_cm:.3f} cm")
            except ValueError:
                pass
            return
        if text.startswith("RPM:CFG:"):
            raw = text[len("RPM:CFG:"):]
            try:
                self._fw_rpm_pulses_per_rev = int(raw)
                self.statusBar().showMessage(f"RPM pulses/rev loaded: {self._fw_rpm_pulses_per_rev}")
            except ValueError:
                pass
            return

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
            self._settings_window = SettingsWindow(self, scope="all")
            self._settings_window.setStyleSheet(self.styleSheet())
        self._settings_window.show_all_settings()
        self._refresh_calibration_ui()
        self._settings_window.refresh()
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()
        if self.mode == "LIVE" and self._worker:
            self._request_firmware_calibration()

    def _open_hardware_settings_screen(self):
        if self._hardware_settings_window is None:
            self._hardware_settings_window = SettingsWindow(self, scope="hardware")
            self._hardware_settings_window.setStyleSheet(self.styleSheet())
        self._hardware_settings_window.show_hardware_settings()
        self._refresh_calibration_ui()
        self._hardware_settings_window.refresh()
        self._hardware_settings_window.show()
        self._hardware_settings_window.raise_()
        self._hardware_settings_window.activateWindow()
        if self.mode == "LIVE" and self._worker:
            self._request_firmware_calibration()

    def _open_app_settings_screen(self):
        if self._app_settings_window is None:
            self._app_settings_window = SettingsWindow(self, scope="app")
            self._app_settings_window.setStyleSheet(self.styleSheet())
        self._app_settings_window.show_app_settings()
        self._app_settings_window.refresh()
        self._app_settings_window.show()
        self._app_settings_window.raise_()
        self._app_settings_window.activateWindow()

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
            "drill_mode": self._drill_mode,
            "drill_hits": int(self._drill_hits),
            "drill_attempts": int(self._drill_attempts),
            "drill_hit_rate": round((self._drill_hits * 100.0 / self._drill_attempts), 2) if self._drill_attempts else 0.0,
            "court_surface": self._court_surface,
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
            QPushButton#TargetHeaderBtn {
                border: 1px solid #3a4d66;
                border-radius: 7px;
                padding: 4px 10px;
                font-size: 10px;
                font-weight: 800;
                color: #a8bfd8;
                background: #102033;
            }
            QPushButton#TargetHeaderBtn:hover {
                background: #15304b;
            }
            QPushButton#PrimaryBtn {
                background: #2f7d2b; border: 1px solid #4da24a; color: #f1fff0;
            }
            QPushButton#PrimaryBtn:hover { background: #3e9a39; }
            QPushButton#IconBtn {
                background: #0d2d50; border: 1px solid #2d5886; border-radius: 5px;
                padding: 0px; font-size: 12px;
            }
            QFrame#SettingsPopup {
                background: #071528;
                border: 1px solid #1d4369;
                border-radius: 8px;
            }
            QPushButton#SettingsMenuOption {
                background: #0d2d50;
                border: 1px solid #2a5278;
                border-radius: 7px;
                padding: 6px 10px;
                font-size: 10px;
                font-weight: 800;
                color: #cfe6ff;
                text-align: left;
                min-width: 154px;
            }
            QPushButton#SettingsMenuOption:hover {
                background: #17406c;
                border-color: #3a6b97;
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
        self.telemetry.rpm_x10 = 0
        self.telemetry.state = 0
        self.play_queue = 0
        self._last_count_sample_val = 0
        self._last_count_sample_ts = 0.0
        self._impact_by_hit_count.clear()
        self._last_impact_reading = (0, 0, 0)
        self._drill_hits = 0
        self._drill_attempts = 0
        self._drill_goal_announced = False
        self._update_drill_status()
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
                "spin_type",
                "shot_type",
                "face_tilt_deg",
                "brush_angle_deg",
                "net_clearance_m",
                "bounce_kick_m",
                "coaching_cue",
                "benchmark_score",
                "target_zone_hit",
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
                    s.spin_type,
                    s.shot_type,
                    f"{s.face_tilt_deg:.2f}",
                    f"{s.brush_angle_deg:.2f}",
                    f"{s.net_clearance_m:.2f}",
                    f"{s.bounce_kick_m:.2f}",
                    s.coaching_cue,
                    s.benchmark_score,
                    int(s.target_zone_hit),
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
        spin_type = self._classify_spin_type(spin, impact_y)
        shot_type = self._infer_shot_type(speed, arm_angle)
        if self._shot_intent_override in {"Forehand", "Backhand", "Serve"}:
            shot_type = self._shot_intent_override
        face_tilt_deg = self._estimate_face_tilt(arm_angle, impact_y)
        brush_angle_deg = self._estimate_brush_angle(spin, impact_y)
        net_clearance_m = self._estimate_net_clearance(speed, spin, arm_angle)
        bounce_kick_m = self._estimate_bounce_kick(speed, spin)
        target_zone_hit = self._is_target_zone_hit(shot_type, arm_angle, landing_x, landing_y, spin_type)
        coaching_cue = self._coaching_cue(spin_type, face_tilt_deg, brush_angle_deg)
        benchmark_score = self._benchmark_score(speed, spin, face_tilt_deg, brush_angle_deg)

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
            spin_type=spin_type,
            shot_type=shot_type,
            face_tilt_deg=face_tilt_deg,
            brush_angle_deg=brush_angle_deg,
            net_clearance_m=net_clearance_m,
            bounce_kick_m=bounce_kick_m,
            coaching_cue=coaching_cue,
            benchmark_score=benchmark_score,
            target_zone_hit=target_zone_hit,
        )
        self.shots.append(shot)
        if self._drill_mode != "Off":
            self._drill_attempts += 1
            if self._drill_hit_for_shot(shot):
                self._drill_hits += 1
            self._update_drill_status()
            if self._drill_hits >= self._drill_goal and not self._drill_goal_announced:
                self._drill_goal_announced = True
                self.statusBar().showMessage(f"Drill complete: {self._drill_mode} targets achieved.")
        if len(self.shots) > 300:
            self.shots = self.shots[-300:]
        self._active_session_saved = False

    def start_worker(self):
        if self._thread and self._thread.isRunning():
            return
        self._show_connect_popup()
        self._set_connection_wizard_sensor("Sensor found: scanning...")
        self._reset_connect_step_states()
        self._set_connect_step_state(0, "in_progress")
        self.btn_connect.setEnabled(False)
        self.btn_connect.setText("CONNECTING...")
        self.statusBar().showMessage("Connecting to real sensor...")
        self._set_connection_wizard_state(
            "Step 2/4 Linking BLE",
            "Opening BLE link and subscribing to telemetry channels...",
        )
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
        self._worker.gate_speed.connect(self._on_gate_speed_packet)
        self._worker.command_rx.connect(self._on_command_rx)
        self._worker.status.connect(self._on_status)
        self._thread.start()

    def stop_worker(self):
        if self._worker:
            self._send_worker_command(STREAM_DISARM_COMMAND, quiet_when_unavailable=True)
            self._worker.stop()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            if not self._thread.wait(3000):
                # Last-resort guard: avoid Qt aborting with
                # "QThread: Destroyed while thread is still running".
                self._thread.terminate()
                self._thread.wait(1000)
        self._thread = None
        self._worker = None
        self._impact_by_hit_count.clear()
        self._last_impact_reading = (0, 0, 0)
        self._last_gate_speed_mph = 0.0
        self._last_gate_speed_ts = 0.0
        self.telemetry.gate_speed_mph = 0.0
        self.telemetry.rpm_x10 = 0
        self.mode = "SIMULATION"
        self.simulation_enabled = True
        self.btn_connect.setEnabled(True)
        self.btn_connect.setText("CONNECT SENSOR")
        self.mode_chip.setText("MODE\nSIMULATION")
        self.sensors_chip.setText("SENSORS\nDISCONNECTED")
        self.sensors_chip.setObjectName("ChipErr")
        self.sensors_chip.style().polish(self.sensors_chip)
        self._reset_link_badge()
        self._set_connection_wizard_state(
            "Ready",
            "Press CONNECT SENSOR to start the guided live connection.",
        )
        self._set_connection_wizard_sensor("Sensor found: waiting...")
        self._reset_connect_step_states()
        if self._connect_popup_btn is not None:
            self._connect_popup_btn.setText("Close")
        self.statusBar().showMessage(
            "Simulation active until a real TENNIS_KY003 sensor is found (auto-scan on) or you press CONNECT SENSOR."
        )

    def _on_ble_handshake(self, pong_ok: bool):
        self._last_handshake_ok = pong_ok
        if pong_ok:
            self.link_chip.setText("HANDSHAKE\nPONG ✓")
            self.link_chip.setObjectName("ChipLinkOk")
            self._set_connect_step_state(2, "done")
            self._set_connect_step_state(3, "done")
            self._set_connection_wizard_state(
                "Step 4/4 Live Stream Ready",
                "Handshake succeeded. Firmware is responding to PING/PONG and live data is active.",
            )
        else:
            self.link_chip.setText("HANDSHAKE\nNO PONG")
            self.link_chip.setObjectName("ChipLinkWarn")
            self._set_connect_step_state(2, "warn")
            self._set_connect_step_state(3, "done")
            self._set_connection_wizard_state(
                "Step 3/4 Handshake Warning",
                "Connected but no PONG yet. Live stream may still run on older firmware builds.",
            )
        self.link_chip.style().polish(self.link_chip)

    def _on_connected(self, ok: bool, addr: str):
        if ok:
            self._reset_local_session_data()
            self.mode = "LIVE"
            self.simulation_enabled = False
            self.telemetry.ts = time.time()
            self._last_keepalive_sent = 0.0
            self.btn_connect.setEnabled(False)
            self.btn_connect.setText("LIVE CONNECTED")
            self.mode_chip.setText("MODE\nLIVE")
            self.sensors_chip.setText("SENSORS\nCONNECTED")
            self.sensors_chip.setObjectName("ChipOk")
            self._set_connect_step_state(1, "done")
            self._set_connect_step_state(2, "in_progress")
            self._set_connection_wizard_sensor(f"Sensor found: {addr}")
            if self._worker:
                self._send_worker_command(STREAM_ARM_COMMAND, quiet_when_unavailable=True)
                self._send_worker_command(CAL_GET_COMMAND, quiet_when_unavailable=True)
                self._send_worker_command("GATE:GET", quiet_when_unavailable=True)
                self._send_worker_command("RPM:GET", quiet_when_unavailable=True)
                if not self._worker.can_send_commands():
                    self.link_chip.setText("HANDSHAKE\nN/A")
                    self.link_chip.setObjectName("ChipMuted")
                    self.link_chip.style().polish(self.link_chip)
                    self._set_connect_step_state(2, "warn")
                    self._set_connect_step_state(3, "done")
                    self.statusBar().showMessage(
                        "Connected in telemetry-only mode. Flash latest firmware to enable command channel."
                    )
            if self._connect_popup_btn is not None:
                self._connect_popup_btn.setText("Close")
            self.statusBar().showMessage(f"Connected to sensor: {addr}")
        else:
            self.mode = "SIMULATION"
            self.simulation_enabled = True
            self._last_handshake_ok = False
            self._last_count_sample_val = 0
            self._last_count_sample_ts = 0.0
            self.btn_connect.setEnabled(True)
            self.btn_connect.setText("CONNECT SENSOR")
            self._impact_by_hit_count.clear()
            self._last_impact_reading = (0, 0, 0)
            self._last_gate_speed_mph = 0.0
            self._last_gate_speed_ts = 0.0
            self.telemetry.gate_speed_mph = 0.0
            self.telemetry.rpm_x10 = 0
            self.mode_chip.setText("MODE\nSIMULATION")
            self.sensors_chip.setText("SENSORS\nDISCONNECTED")
            self.sensors_chip.setObjectName("ChipErr")
            self._reset_link_badge()
            if self._thread and self._thread.isRunning():
                self._set_connection_wizard_sensor("Sensor found: scanning...")
                self._set_connect_step_state(0, "in_progress")
                self._set_connection_wizard_state(
                    "Step 1/4 Discovering Sensor",
                    "Sensor not yet found. Keep device powered and close to your computer.",
                )
            else:
                self._set_connection_wizard_sensor("Sensor found: waiting...")
                self._reset_connect_step_states()
                self._set_connection_wizard_state(
                    "Ready",
                    "Press CONNECT SENSOR to start the guided live connection.",
                )
            if self._connect_popup_btn is not None:
                self._connect_popup_btn.setText("Close")
        self.sensors_chip.style().polish(self.sensors_chip)

    def _on_status(self, msg: str):
        self.statusBar().showMessage(msg)
        m = msg.lower()
        if "scanning" in m or "no tennis ble sensor found" in m:
            self._set_connection_wizard_sensor("Sensor found: scanning...")
            self._set_connect_step_state(0, "in_progress")
            self._set_connection_wizard_state(
                "Step 1/4 Discovering Sensor",
                "Looking for TENNIS_KY003 advertising the tennis service UUID...",
            )
        elif "connecting to" in m:
            self._set_connection_wizard_sensor(msg.replace("Connecting to ", "Sensor found: "))
            self._set_connect_step_state(0, "done")
            self._set_connect_step_state(1, "in_progress")
            self._set_connection_wizard_state(
                "Step 2/4 Linking BLE",
                "Found sensor. Establishing BLE link and subscribing to notifications...",
            )
        elif "no pong" in m:
            self._set_connect_step_state(2, "warn")
            self._set_connect_step_state(3, "done")
            self._set_connection_wizard_state(
                "Step 3/4 Handshake Warning",
                "Connected but no PONG health response yet. Firmware may be older.",
            )
        elif "health check ok" in m or "pong ✓" in m:
            self._set_connect_step_state(2, "done")
            self._set_connect_step_state(3, "done")
            self._set_connection_wizard_state(
                "Step 4/4 Live Stream Ready",
                "Handshake confirmed. Live telemetry stream is healthy.",
            )
        elif "telemetry-only mode" in m:
            if not self._last_handshake_ok:
                self._set_connect_step_state(2, "warn")
                self._set_connect_step_state(3, "done")
        elif "command failed" in m:
            if not self._last_handshake_ok:
                self._set_connect_step_state(2, "warn")
                self._set_connection_wizard_state(
                    "Step 3/4 Command Channel Issue",
                    msg,
                )

    def _on_gate_speed_packet(self, sample_id: int, speed_kmh_x10: int, transit_ms: int):
        _ = sample_id
        kmh = speed_kmh_x10 / 10.0
        mph = kmh * 0.621371
        self._last_gate_speed_mph = mph
        self._last_gate_speed_ts = time.time()
        self.telemetry.gate_speed_mph = mph
        self.lbl_gate_speed.setText(f"Gate Speed         {mph:>4.1f} mph ({transit_ms} ms)")

    def _on_impact_packet(
        self,
        hit_count: int,
        x_mg: int,
        y_mg: int,
        z_mg: int,
        magnitude_mg: int,
        intensity: int,
        contact_x: int,
        contact_y: int,
        valid: int,
    ):
        mag_mg = float(magnitude_mg)
        if not valid:
            return
        self._impact_by_hit_count[hit_count] = (contact_x, contact_y, intensity)
        self._last_impact_reading = (contact_x, contact_y, intensity)
        event = {
            "hit_count": hit_count,
            "x_mg": x_mg,
            "y_mg": y_mg,
            "z_mg": z_mg,
            "mag_mg": mag_mg,
            "intensity": intensity,
            "valid": bool(valid),
        }
        for w in self._hardware_settings_windows():
            w.on_impact_event(event)
        if len(self._impact_by_hit_count) > 128:
            old = sorted(self._impact_by_hit_count.keys())[:-64]
            for key in old:
                self._impact_by_hit_count.pop(key, None)

    def _on_telemetry(self, state: int, count: int, rate_x10: int, rpm_x10: int):
        now_ts = time.time()
        if state >= 0:
            self.telemetry.state = state
        if rate_x10 >= 0:
            self.telemetry.rate_x10 = rate_x10
        if rpm_x10 >= 0:
            self.telemetry.rpm_x10 = rpm_x10
        elif rate_x10 >= 0:
            ppr = max(1, int(self._fw_rpm_pulses_per_rev))
            self.telemetry.rpm_x10 = int((rate_x10 * 60) / ppr)
        if count >= 0:
            prev = self.telemetry.count
            self.telemetry.count = count
            if (
                self.mode == "LIVE"
                and rate_x10 < 0
                and self._last_count_sample_ts > 0.0
                and count > self._last_count_sample_val
            ):
                dt = now_ts - self._last_count_sample_ts
                if dt > 0.05:
                    inferred_rate = (count - self._last_count_sample_val) / dt
                    self.telemetry.rate_x10 = int(max(0.0, min(6553.5, inferred_rate * 10.0)))
                    if rpm_x10 < 0:
                        ppr = max(1, int(self._fw_rpm_pulses_per_rev))
                        self.telemetry.rpm_x10 = int((self.telemetry.rate_x10 * 60) / ppr)
            self._last_count_sample_val = count
            self._last_count_sample_ts = now_ts
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
                    model_speed = max(
                        prof["live_speed_min"],
                        min(
                            prof["live_speed_max"],
                            prof["live_speed_base"]
                            + rate * prof["live_rate_mul"]
                            + (redness * prof["live_red_mul"])
                            + random.uniform(-2.0, 2.0),
                        ),
                    )
                    speed = model_speed
                    now = time.time()
                    if (now - self._last_gate_speed_ts) <= 0.35 and self._last_gate_speed_mph > 0.1:
                        speed = max(
                            prof["live_speed_min"],
                            min(
                                prof["live_speed_max"],
                                self._last_gate_speed_mph * 0.72 + model_speed * 0.28,
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
                    measured_rpm = self.telemetry.rpm_x10 / 10.0
                    if measured_rpm > 1.0:
                        spin = int(
                            max(
                                prof["live_spin_min"],
                                min(
                                    prof["live_spin_max"],
                                    measured_rpm * 0.82 + spin * 0.18,
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
            self._send_worker_command(STREAM_KEEPALIVE_COMMAND, quiet_when_unavailable=True)
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
        self._send_worker_command(STREAM_ARM_COMMAND, quiet_when_unavailable=True)

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
            self.lbl_live_rpm.setText(f"Live RPM           {self.telemetry.rpm_x10 / 10.0:.1f}")
            self.lbl_spin_type.setText(f"Spin Type          {latest.spin_type}")
            self.lbl_shot_type.setText(f"Shot Type          {latest.shot_type}")
            self.lbl_coaching.setText(f"Coaching Cue       {latest.coaching_cue}")
            self.lbl_benchmark.setText(f"Benchmark Score    {latest.benchmark_score:d} / 100")
            self.lbl_face_tilt.setText(f"Face Tilt @ Impact  {latest.face_tilt_deg:.1f}°")
            self.lbl_brush.setText(f"Brush Angle         {latest.brush_angle_deg:.1f}°")
            self.lbl_net_clearance.setText(f"Net Clearance       {latest.net_clearance_m:.2f} m")
            self.lbl_bounce.setText(f"Post-bounce Kick    {latest.bounce_kick_m:.2f} m ({self._court_surface})")
            self.lbl_target_zone.setText(f"Target Zone         {'HIT' if latest.target_zone_hit else 'MISS'}")
            gate_speed_text = "--.- mph"
            if self.telemetry.gate_speed_mph > 0.0:
                gate_speed_text = f"{self.telemetry.gate_speed_mph:.1f} mph"
            self.lbl_gate_speed.setText(f"Gate Speed         {gate_speed_text}")
            self.impact_widget.set_impact(latest.impact_x, latest.impact_y, latest.impact_redness)
        else:
            self.lbl_impact_xy.setText("Impact Offset      +0, +0")
            self.lbl_impact_red.setText("Impact Redness     0%")
            self.lbl_live_rpm.setText(f"Live RPM           {self.telemetry.rpm_x10 / 10.0:.1f}")
            self.lbl_spin_type.setText("Spin Type          Flat")
            self.lbl_shot_type.setText("Shot Type          Forehand")
            self.lbl_coaching.setText("Coaching Cue       Build brush-up path")
            self.lbl_benchmark.setText("Benchmark Score    0 / 100")
            self.lbl_face_tilt.setText("Face Tilt @ Impact  0.0°")
            self.lbl_brush.setText("Brush Angle         0.0°")
            self.lbl_net_clearance.setText("Net Clearance       0.00 m")
            self.lbl_bounce.setText(f"Post-bounce Kick    0.00 m ({self._court_surface})")
            self.lbl_target_zone.setText("Target Zone         MISS")
            self.lbl_gate_speed.setText("Gate Speed         --.- mph")
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
                f"{s.spin:d}",
                s.spin_type,
                s.shot_type,
                f"{s.landing_x:.2f}, {s.landing_y:.2f}",
                f"{s.net_clearance_m:.2f} m",
                "HIT" if s.target_zone_hit else "MISS",
                s.coaching_cue,
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
    app.aboutToQuit.connect(w.stop_worker)

    # Make Ctrl+C in terminal trigger a clean Qt shutdown.
    signal.signal(signal.SIGINT, lambda *_args: app.quit())

    w.show()
    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        w.stop_worker()
        app.quit()
        raise SystemExit(0)


if __name__ == "__main__":
    main()
