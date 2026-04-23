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
import math
import random
import struct
import sys
import time
from dataclasses import dataclass
from datetime import datetime

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF, QRadialGradient
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
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


class TennisBleWorker(QObject):
    connected = pyqtSignal(bool, str)
    telemetry = pyqtSignal(int, int, int)
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

        self._build_ui()
        self._apply_style()

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
        for glyph in ("⌖", "◉", "⛶"):
            b = QPushButton(glyph)
            b.setObjectName("IconBtn")
            b.setFixedSize(26, 22)
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

        self.history_panel = self._panel("SHOT HISTORY")
        self.history_table = QTableWidget(0, 6)
        self.history_table.setHorizontalHeaderLabels(["#", "TIME", "SPEED (mph)", "ARM ANGLE", "LANDING (X,Y)", "SPIN"])
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
            QPushButton#PrimaryBtn {
                background: #2f7d2b; border: 1px solid #4da24a; color: #f1fff0;
            }
            QPushButton#PrimaryBtn:hover { background: #3e9a39; }
            QPushButton#IconBtn {
                background: #0d2d50; border: 1px solid #2d5886; border-radius: 5px;
                padding: 0px; font-size: 12px;
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
        self._reset_local_session_data()
        self.statusBar().showMessage("Shot history cleared.")

    def _reset_local_session_data(self):
        self.shots.clear()
        self.telemetry.count = 0
        self.telemetry.rate_x10 = 0
        self.telemetry.state = 0
        self.play_queue = 0
        self._refresh_ui(force=True)

    def _reset_session(self):
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
        path, _ = QFileDialog.getSaveFileName(self, "Export Shot Data", "tennis_shots.csv", "CSV Files (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["idx", "time", "speed_mph", "arm_angle_deg", "spin_rpm", "landing_x_m", "landing_y_m"])
            for s in self.shots:
                w.writerow([s.idx, s.timestamp, f"{s.speed:.1f}", f"{s.arm_angle:.1f}", s.spin, f"{s.landing_x:.2f}", f"{s.landing_y:.2f}"])
        self.statusBar().showMessage(f"Exported {len(self.shots)} shots to {path}")

    def _add_simulated_shot(self):
        speed = random.uniform(30.0, 79.0)
        arm = random.uniform(-32.0, 32.0)
        spin = int(random.uniform(500, 1850))
        land_x = max(-3.8, min(3.8, random.gauss(0.0, 1.55)))
        land_y = max(1.2, min(10.8, random.gauss(7.0, 1.8)))
        self._append_shot(speed, arm, spin, land_x, land_y)

    def _append_shot(self, speed: float, arm_angle: float, spin: int, landing_x: float, landing_y: float):
        shot = Shot(
            idx=(self.shots[-1].idx + 1) if self.shots else 1,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            speed=speed,
            arm_angle=arm_angle,
            spin=spin,
            landing_x=landing_x,
            landing_y=landing_y,
        )
        self.shots.append(shot)
        if len(self.shots) > 300:
            self.shots = self.shots[-300:]

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
            self.statusBar().showMessage(f"Connected to sensor: {addr}")
        else:
            self.mode = "SIMULATION"
            self.simulation_enabled = True
            self.mode_chip.setText("MODE\nSIMULATION")
            self.sensors_chip.setText("SENSORS\nDISCONNECTED")
            self.sensors_chip.setObjectName("ChipErr")
            self._reset_link_badge()
        self.sensors_chip.style().polish(self.sensors_chip)

    def _on_status(self, msg: str):
        self.statusBar().showMessage(msg)

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
                for _ in range(steps):
                    rate = self.telemetry.rate_x10 / 10.0
                    speed = max(28.0, min(83.0, 27.0 + rate * 4.0 + random.uniform(-2.8, 2.8)))
                    arm = random.uniform(-30.0, 30.0)
                    spin = int(max(450, min(2100, 650 + rate * 115 + random.uniform(-100, 130))))
                    lx = max(-3.8, min(3.8, random.gauss(arm / 25.0, 1.15)))
                    ly = max(1.1, min(10.8, random.gauss(7.2, 1.5)))
                    self._append_shot(speed, arm, spin, lx, ly)
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
            ]
            for c, txt in enumerate(values):
                item = QTableWidgetItem(txt)
                if c == 0:
                    item.setForeground(shot_color(s.speed))
                self.history_table.setItem(r, c, item)

    def closeEvent(self, event):  # noqa: N802
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
