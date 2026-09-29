"""Shared fixtures: make `src` importable and build one small network per session."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.network_builder import build_synthetic_network  # noqa: E402


@pytest.fixture(scope="session")
def small_graph():
    """15 x 15 synthetic grid (3.75 km box), seed 7."""
    return build_synthetic_network(n=15, spacing_m=250.0, seed=7)
