import pytest

from schemeup.infrastructure.platform.motion import (
    system_prefers_reduced_motion,
    wants_reduced_motion,
)


def test_system_preference_can_be_read() -> None:
    # The value depends on the machine; reading it must simply work everywhere.
    assert isinstance(system_prefers_reduced_motion(), bool)


@pytest.mark.parametrize(
    ("override", "expected"),
    [("full", False), ("reduced", True), (" Reduced ", True), ("FULL", False)],
)
def test_override_wins_over_the_system(override: str, expected: bool) -> None:
    assert wants_reduced_motion(override) is expected


@pytest.mark.parametrize("override", [None, "", "sometimes"])
def test_without_a_valid_override_the_system_decides(override: str | None) -> None:
    assert wants_reduced_motion(override) is system_prefers_reduced_motion()
