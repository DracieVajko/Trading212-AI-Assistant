"""Pie-aware portfolio exposure and execution modelling.

Public API for aggregation and actionability views.
Re-exports for convenience.
"""
from investment_engine.portfolio.exposure import (
    CanonicalExposure,
    ExecutionCapabilities,
    PieExposure,
    StandaloneExposure,
    build_canonical_exposures,
    evaluate_opportunistic_standalone_add,
    generate_actionability_view,
    generate_exposure_view,
)
from investment_engine.portfolio.pie_metadata import (
    PieMetadata,
    PieUniverse,
    load_pie_universe,
)
from investment_engine.portfolio.sidecar import (
    PieSidecarConfig,
    PieSidecarRegistry,
    load_sidecar_registry,
)

__all__ = [
    "CanonicalExposure",
    "ExecutionCapabilities",
    "PieExposure",
    "PieMetadata",
    "PieSidecarConfig",
    "PieSidecarRegistry",
    "PieUniverse",
    "StandaloneExposure",
    "build_canonical_exposures",
    "evaluate_opportunistic_standalone_add",
    "generate_actionability_view",
    "generate_exposure_view",
    "load_pie_universe",
    "load_sidecar_registry",
]
