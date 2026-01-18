"""Graph building and export module."""

from .models import (
    Entity,
    EntityType,
    Relation,
    RelationType,
    CausalEffect,
    TemporalOrder,
    CausalGraph,
    CausalGraphValidationError,
    CAUSAL_RELATION_TYPES,
)

# NOTE: Do NOT import builder/exporter/validator at module import time.
# These modules depend on extraction, which imports `src.graph.models`, and eager
# imports here can create circular-import issues (observed in ckg-augment tests).
# We keep the public API via lazy attribute loading below.

__all__ = [
    "Entity",
    "EntityType",
    "Relation",
    "RelationType",
    "CausalEffect",
    "TemporalOrder",
    "CausalGraph",
    "CausalGraphValidationError",
    "CAUSAL_RELATION_TYPES",
    "GraphBuilder",
    "GraphExporter",
    "CKGValidator",
    "ValidationReport",
    "validate_ckg",
]


def __getattr__(name: str):
    if name == "GraphBuilder":
        from .builder import GraphBuilder as _GraphBuilder

        return _GraphBuilder
    if name == "GraphExporter":
        from .exporter import GraphExporter as _GraphExporter

        return _GraphExporter
    if name in {"CKGValidator", "ValidationReport", "validate_ckg"}:
        from .validator import CKGValidator as _CKGValidator
        from .validator import ValidationReport as _ValidationReport
        from .validator import validate_ckg as _validate_ckg

        return {
            "CKGValidator": _CKGValidator,
            "ValidationReport": _ValidationReport,
            "validate_ckg": _validate_ckg,
        }[name]
    raise AttributeError(name)
