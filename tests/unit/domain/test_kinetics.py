import pytest
from hypothesis import given
from hypothesis import strategies as st

from schemeup.domain.geometry import Point
from schemeup.domain.kinetics import (
    Inertia,
    Spring,
    VelocityTracker,
    rubber_band,
)


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


def test_default_glide_matches_ios_scroll_projection() -> None:
    # Apple projects a flick of v px/s to travel (v / 1000) * 0.998 / 0.002 px.
    apple_distance = 1000 / 1000 * 0.998 / 0.002
    inertia = Inertia(Point(1000, 0))
    assert inertia.velocity.x * inertia.time_constant == pytest.approx(apple_distance, rel=2e-3)


def run(spring: Spring, seconds: float, dt: float = 1 / 120) -> list[Spring]:
    states = [spring]
    for _ in range(round(seconds / dt)):
        states.append(states[-1].step(dt))
    return states


def test_critically_damped_spring_settles_without_overshoot() -> None:
    states = run(Spring(value=0, target=100, response=0.4), seconds=2)
    assert max(s.value for s in states) <= 100 + 1e-9
    assert states[-1].at_rest
    assert states[-1].value == pytest.approx(100, abs=1e-3)


def test_bouncy_spring_overshoots_then_settles() -> None:
    states = run(Spring(value=0, target=100, response=0.4, damping_ratio=0.6), seconds=3)
    assert max(s.value for s in states) > 100
    assert states[-1].value == pytest.approx(100, abs=1e-3)


@given(
    st.floats(min_value=0.001, max_value=0.1),
    st.floats(min_value=-500, max_value=500),
    st.sampled_from([1.0, 0.8, 0.5]),
)
def test_spring_does_not_depend_on_frame_rate(dt: float, velocity: float, damping: float) -> None:
    spring = Spring(value=-40, target=60, velocity=velocity, damping_ratio=damping)
    once = spring.step(2 * dt)
    twice = spring.step(dt).step(dt)
    assert twice.value == pytest.approx(once.value, abs=1e-9)
    assert twice.velocity == pytest.approx(once.velocity, abs=1e-6)


def test_retargeting_keeps_position_and_velocity() -> None:
    moving = run(Spring(value=0, target=100), seconds=0.1)[-1]
    redirected = moving.retargeted(-50)
    assert redirected.value == moving.value
    assert redirected.velocity == moving.velocity
    # It keeps going forward for a moment before turning around, no brick wall.
    assert redirected.step(1 / 120).value > moving.value


def test_spring_starts_with_the_handed_over_velocity() -> None:
    spring = Spring(value=0, target=0, velocity=300)
    assert spring.step(0.001).value == pytest.approx(0.3, rel=0.05)


def test_invalid_springs_are_rejected() -> None:
    with pytest.raises(ValueError):
        Spring(0, 1, response=0)
    with pytest.raises(ValueError):
        Spring(0, 1, damping_ratio=1.5)


def test_rubber_band_follows_at_first_then_resists() -> None:
    assert rubber_band(1, dimension=1000) == pytest.approx(0.55, rel=1e-3)
    assert rubber_band(-1, dimension=1000) == pytest.approx(-0.55, rel=1e-3)
    pulls = [rubber_band(o, dimension=100) for o in range(0, 10000, 100)]
    assert pulls == sorted(pulls)
    assert pulls[-1] < 100
