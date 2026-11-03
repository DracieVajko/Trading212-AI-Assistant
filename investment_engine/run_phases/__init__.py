"""Phase helpers extracted from ``run_engine``.

Each phase owns one stage of the pipeline and returns a small typed result, so
``run_engine`` reads as a linear list of stages instead of one 1,900-line body.
"""

from __future__ import annotations
