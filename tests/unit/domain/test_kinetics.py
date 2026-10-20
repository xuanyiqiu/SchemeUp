import pytest
from hypothesis import given
from hypothesis import strategies as st

from schemeup.domain.geometry import Point
from schemeup.domain.kinetics import Inertia, VelocityTracker


def test_velocity_of_a_steady_drag() -> None:
    tracker = VelocityTracker()
    for i in range(10):
        tracker.add(i * 0.01, Point(5.0 * i, -2.0 * i))
    velocity = tracker.velocity(now=0.09)
    assert velocity.x == pytest.approx(500)
    assert velocity.y == pytest.approx(-200)


def test_pausing_before_release_gives_no_velocity() -> None:
    tracker = VelocityTracker(window=0.08)
    tracker.add(0.00, Point(0, 0))
    tracker.add(0.01, Point(50, 0))
    assert tracker.velocity(now=0.3) == Point(0, 0)


def test_one_sample_gives_no_velocity() -> None:
    tracker = VelocityTracker()
    tracker.add(1.0, Point(3, 4))
    assert tracker.velocity(now=1.0) == Point(0, 0)


def test_launch_caps_the_speed() -> None:
    inertia = Inertia.launch(Point(30000, 40000), max_speed=5000)
    assert inertia.velocity.length() == pytest.approx(5000)


def test_inertia_comes_to_rest_after_its_natural_distance() -> None:
    inertia = Inertia(Point(1000, 0), time_constant=0.3)
    travelled = 0.0
    while inertia.active:
        delta, inertia = inertia.step(1 / 60)
        travelled += delta.x
    # The full integral is v * tau = 300 px; stopping at stop_speed loses v_stop * tau.
    assert 300 - inertia.stop_speed * 0.3 - 1 <= travelled <= 300


@given(st.floats(min_value=0.001, max_value=0.2))
def test_inertia_does_not_depend_on_frame_rate(dt: float) -> None:
    inertia = Inertia(Point(800, -300))
    one_step, after_one = inertia.step(2 * dt)
    first, half = inertia.step(dt)
    second, after_two = half.step(dt)
    assert (first + second).x == pytest.approx(one_step.x)
    assert (first + second).y == pytest.approx(one_step.y)
    assert after_two.velocity.x == pytest.approx(after_one.velocity.x)
