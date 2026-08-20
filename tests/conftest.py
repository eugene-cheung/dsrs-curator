"""Test env: never contact a live model."""

from __future__ import annotations

import os

os.environ["LLM_MODE"] = "mock"
