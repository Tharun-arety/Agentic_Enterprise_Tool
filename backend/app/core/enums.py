"""Enum helpers shared across domains."""

from __future__ import annotations

import enum


def enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    """Persist the enum *value* (e.g. "LaFeSi") rather than its member name.

    Passed to SQLAlchemy's `Enum(..., values_callable=...)`. Without it the
    column stores the Python member name, which is an implementation detail
    that leaks into the database and into every ad-hoc SQL query written
    against it.
    """
    return [member.value for member in enum_cls]
