"""Book layout: page geometry, section policies, pagination convergence, CSS."""

from printforge.layout.plan import (
    Converged,
    LayoutConvergenceError,
    LayoutPlan,
    PageGeometry,
    PageSide,
    inside_margin,
    paginate_until_stable,
    plan_layout,
)
from printforge.layout.styles import describe, stylesheet

__all__ = [
    "Converged",
    "LayoutConvergenceError",
    "LayoutPlan",
    "PageGeometry",
    "PageSide",
    "describe",
    "inside_margin",
    "paginate_until_stable",
    "plan_layout",
    "stylesheet",
]
