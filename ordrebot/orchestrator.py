from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from polaris_automat import run_polaris
from kellox_login import run_kellox
from ktm_login import run_ktm


def route_orders(order_lines: List[Dict[str, object]]) -> Dict[str, List[Dict[str, object]]]:
    grouped: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for line in order_lines:
        vendor = str(line.get("leverandor", "unknown")).lower()
        grouped[vendor].append(line)
    return dict(grouped)


def run_all(order_lines: List[Dict[str, object]]) -> None:
    groups = route_orders(order_lines)

    polaris_orders = groups.get("polaris", [])
    kellox_orders = groups.get("kellox", [])
    ktm_orders = groups.get("ktm", [])

    if polaris_orders:
        run_polaris(polaris_orders, interactive=False)
    if kellox_orders:
        run_kellox(kellox_orders, interactive=False)
    if ktm_orders:
        run_ktm(ktm_orders, interactive=False)

