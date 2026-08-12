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


def enum_text(value: object) -> str:
    """The readable form of a value that may or may not be an enum member.

    Schemas here hand back enum members on some paths and plain strings on
    others, so callers cannot assume. `str()` on a member yields
    `ChangePriority.URGENT`, which reads badly in an answer and — worse —
    silently fails any comparison against `"urgent"`. That bug appeared three
    times in three modules before this became one function.
    """
    return str(getattr(value, "value", value))
