"""Base exception for the Logic Manager."""

from __future__ import annotations


class LogicManagerError(Exception):
    """Base class: Logic refused to produce a result for this record."""

    code = "logic_error"
