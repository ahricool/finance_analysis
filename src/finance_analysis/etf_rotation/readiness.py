"""Pure coverage validation shared by production and tests."""

from __future__ import annotations


class ETFRotationReadinessError(RuntimeError):
    pass


def coverage_ratio(available: int, expected: int) -> float:
    return available / expected if expected > 0 else 0.0


def require_minimum_coverage(
    *,
    label: str,
    available: int,
    expected: int,
    minimum: float,
) -> tuple[float, str | None]:
    ratio = coverage_ratio(available, expected)
    if ratio < minimum:
        raise ETFRotationReadinessError(
            f"ETF Rotation {label} coverage {available}/{expected} ({ratio:.2%}) "
            f"is below the {minimum:.2%} minimum"
        )
    warning = None
    if available < expected:
        warning = f"{label} coverage is partial: {available}/{expected} ({ratio:.2%})"
    return ratio, warning


__all__ = ["ETFRotationReadinessError", "coverage_ratio", "require_minimum_coverage"]
