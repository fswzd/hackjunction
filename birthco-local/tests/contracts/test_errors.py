from contextlib import contextmanager

import pytest

from backend.domain.errors import DomainError


def test_domain_error_can_cross_generator_context_manager_without_being_masked():
    error=DomainError("VERSION_CONFLICT","Lease expired","Stop the worker")
    @contextmanager
    def transaction():
        yield
    with pytest.raises(DomainError) as captured:
        with transaction():
            raise error
    assert captured.value is error and captured.value.code=="VERSION_CONFLICT"
    assert captured.value.__traceback__ is not None
