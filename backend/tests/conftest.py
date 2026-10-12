"""Global test configuration and environment setup for backend test suite."""

from __future__ import annotations

import os

# Ensure testing defaults are enforced even if a pilot .env exists locally
os.environ["APP_ENV"] = "test"
os.environ["DEV_IDENTITY_ENABLED"] = "true"
os.environ["CLAMAV_ENABLED"] = "false"
os.environ["REQUIRE_MALWARE_SCAN"] = "false"
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

