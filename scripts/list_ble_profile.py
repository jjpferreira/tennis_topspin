#!/usr/bin/env python3
"""List the BLE GATT profile (services, characteristics, descriptors) exposed
by the tennis sensor.

This is intentionally minimal: it does NOT subscribe to anything, write
anything, or run the full app. It just connects, prints what the device
advertises, and disconnects. Use it whenever you suspect the macOS GATT cache
is hiding characteristics from the dashboard.

Usage:
    python3 scripts/list_ble_profile.py
    python3 scripts/list_ble_profile.py --address 9256D226-C4F7-D3DB-5024-...
    python3 scripts/list_ble_profile.py --timeout 8

Expected output for a healthy connection (latest firmware):
    9 characteristics, including UUIDs ending in
        a1 (state)  a2 (count)  a3 (rate)
        a4 (command)  a5 (impact)  a6 (gate-speed)
        a7 (rpm)  a8 (health)  a9 (fw-version)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Iterable

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

NAME_PREFIXES = ("TENNIS_KY003",)
TENNIS_SERVICE_UUIDS = (
    "7f4af201-1fb5-459e-8fcc-c5c9c331914d",  # current
    "7f4af201-1fb5-459e-8fcc-c5c9c331914c",  # legacy (pre-cache-bust)
)
KNOWN_CHARACTERISTIC_TAGS = {
    "7be5483e-36e1-4688-b7f5-ea07361b26a1": "state",
    "7be5483e-36e1-4688-b7f5-ea07361b26a2": "count",
    "7be5483e-36e1-4688-b7f5-ea07361b26a3": "rate",
    "7be5483e-36e1-4688-b7f5-ea07361b26a4": "command",
    "7be5483e-36e1-4688-b7f5-ea07361b26a5": "impact",
    "7be5483e-36e1-4688-b7f5-ea07361b26a6": "gate-speed",
    "7be5483e-36e1-4688-b7f5-ea07361b26a7": "rpm",
    "7be5483e-36e1-4688-b7f5-ea07361b26a8": "health",
    "7be5483e-36e1-4688-b7f5-ea07361b26a9": "fw-version",
}


def _device_local_name(d: BLEDevice, adv: AdvertisementData | None) -> str:
    return (adv.local_name if adv else None) or d.name or ""


async def _find_device(timeout: float, explicit_addr: str | None) -> BLEDevice | None:
    print(f"Scanning for tennis sensor for {timeout:.1f}s...")
    devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
    matches: list[tuple[BLEDevice, AdvertisementData]] = []
    for _addr, (dev, adv) in devices.items():
        name = _device_local_name(dev, adv)
        if explicit_addr and dev.address.lower() == explicit_addr.lower():
            return dev
        if any(name.startswith(p) for p in NAME_PREFIXES):
            matches.append((dev, adv))
    if not matches:
        return None
    matches.sort(key=lambda x: x[1].rssi if x[1] else -999, reverse=True)
    best, adv = matches[0]
    print(
        f"Found {_device_local_name(best, adv)!r} "
        f"address={best.address} rssi={adv.rssi if adv else 'n/a'}"
    )
    return best


def _format_props(props: Iterable[str]) -> str:
    return ",".join(sorted(props)) or "(none)"


async def list_profile(address: str | None, timeout: float) -> int:
    device = await _find_device(timeout=timeout, explicit_addr=address)
    if device is None:
        print(
            "ERROR: no tennis sensor found. "
            "Power-cycle the ESP32 and try again, or pass --address explicitly.",
            file=sys.stderr,
        )
        return 2

    print(f"\nConnecting to {device.address}...")
    async with BleakClient(device) as client:
        services = client.services
        if not services:
            print("ERROR: GATT discovery returned no services.", file=sys.stderr)
            return 3

        total_chars = 0
        for service in services:
            print(f"\nservice {service.uuid}")
            tag = "(tennis)" if service.uuid.lower() in TENNIS_SERVICE_UUIDS else ""
            if tag:
                print(f"    {tag}")
            for ch in service.characteristics:
                total_chars += 1
                ch_tag = KNOWN_CHARACTERISTIC_TAGS.get(ch.uuid.lower(), "")
                tag_label = f" ({ch_tag})" if ch_tag else ""
                props = _format_props(str(p) for p in (ch.properties or []))
                print(f"  char {ch.uuid}{tag_label} props={props}")
                for desc in ch.descriptors or []:
                    print(f"      descriptor {desc.uuid} handle={desc.handle}")

        print(
            f"\nTotal characteristics on this peripheral: {total_chars}"
        )
        seen = {ch.uuid.lower() for s in services for ch in s.characteristics}
        missing = [
            f"{uuid} ({tag})"
            for uuid, tag in KNOWN_CHARACTERISTIC_TAGS.items()
            if uuid not in seen
        ]
        if missing:
            print("\nMISSING from GATT (firmware exposes these but they aren't visible):")
            for line in missing:
                print(f"  - {line}")
            print(
                "\nIf you ARE on the latest firmware, this is a stale macOS GATT "
                "cache. Forget the device, run scripts/reset_ble_cache_mac.sh, "
                "and reconnect."
            )
            return 1
        print("\nAll 9 expected tennis characteristics are visible.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--address",
        help="Explicit BLE address (CoreBluetooth UUID on macOS). Skips scanning.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=6.0,
        help="Scan timeout in seconds (default: 6).",
    )
    args = parser.parse_args()
    return asyncio.run(list_profile(address=args.address, timeout=args.timeout))


if __name__ == "__main__":
    raise SystemExit(main())
