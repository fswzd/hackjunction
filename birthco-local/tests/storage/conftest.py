"""Lease tests use an explicit logical clock, independent of the date they run."""
import pytest


@pytest.fixture(autouse=True)
def fixed_storage_clock(monkeypatch):
    from backend.storage import repository,queue
    # Matches explicit datetime(2026, 11, 7, UTC) claims used by this suite.
    # Production UTC time is untouched outside these tests.
    now=lambda:"2026-11-07T00:00:00.000Z"
    monkeypatch.setattr(repository,"utc_now",now)
    monkeypatch.setattr(queue,"utc_now",now)
