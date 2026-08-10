"""The measured quantities, and their units.

One definition, imported by the ORM, the spec-limit validation, and the metric
summaries. The names keep the engineering spec's casing
(`temperature_span_delta_K`, `cooling_capacity_W`) rather than being lower-cased
to satisfy PEP 8: the unit suffix is part of the metric's identity, and using
one spelling from the column through the JSON to the React chart removes a
translation layer that would otherwise be maintained by hand.
"""

from __future__ import annotations

METRIC_UNITS: dict[str, str] = {
    "temperature_span_delta_K": "K",
    "pressure_drop_mbar": "mbar",
    "magnetization_cycles_hz": "Hz",
    "cooling_capacity_W": "W",
}

METRIC_NAMES: tuple[str, ...] = tuple(METRIC_UNITS)
