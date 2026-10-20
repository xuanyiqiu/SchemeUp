import pytest
from hypothesis import given
from hypothesis import strategies as st

from schemeup.domain.camera import MAX_ZOOM, MIN_ZOOM, Camera, CameraSpring, soft_clamp_zoom
from schemeup.domain.geometry import Point, Rect, Size

VIEWPORT = Size(800, 600)

coords = st.floats(min_value=-1e6, max_value=1e6, allow_nan=False)
zooms = st.floats(min_value=MIN_ZOOM, max_value=MAX_ZOOM)
cameras = st.builds(Camera, coords, coords, zooms)
screen_points = st.builds(
    Point,
    st.floats(min_value=0, max_value=VIEWPORT.width),
    st.floats(min_value=0, max_value=VIEWPORT.height),
)


def assert_close(a: Point, b: Point) -> None:
    assert a.x == pytest.approx(b.x, rel=1e-9, abs=1e-6)
    assert a.y == pytest.approx(b.y, rel=1e-9, abs=1e-6)


@given(cameras, screen_points)
def test_screen_world_round_trip(camera: Camera, p: Point) -> None:
    assert_close(camera.to_screen(camera.to_world(p)), p)


@given(cameras, screen_points, st.floats(min_value=0.01, max_value=100))
def test_zoom_keeps_the_point_under_the_cursor(
    camera: Camera, anchor: Point, factor: float
) -> None:
    zoomed = camera.zoomed_at(anchor, factor)
    assert_close(zoomed.to_world(anchor), camera.to_world(anchor))


def test_zoom_is_clamped() -> None:
    assert Camera().zoomed_at(Point(0, 0), 1000).zoom == MAX_ZOOM
    assert Camera().zoomed_at(Point(0, 0), 0.0001).zoom == MIN_ZOOM


def test_pan_moves_content_with_the_pointer() -> None:
    camera = Camera(x=10, y=20, zoom=2)
    world = camera.to_world(Point(100, 100))
    panned = camera.panned_by(30, -10)
    assert_close(panned.to_screen(world), Point(130, 90))


def test_visible_rect_scales_with_zoom() -> None:
    assert Camera(x=5, y=7, zoom=2).visible_rect(VIEWPORT) == Rect(5, 7, 400, 300)


def test_centered_on_puts_the_point_in_the_middle() -> None:
    camera = Camera(zoom=3).centered_on(Point(50, -40), VIEWPORT)
    assert camera.zoom == 3
    assert_close(camera.to_screen(Point(50, -40)), Point(400, 300))


def test_fitted_to_shows_the_whole_rect() -> None:
    rect = Rect(-1000, 0, 4000, 1000)
    camera = Camera().fitted_to(rect, VIEWPORT, padding=50)
    top_left = camera.to_screen(Point(rect.left, rect.top))
    bottom_right = camera.to_screen(Point(rect.right, rect.bottom))
    assert top_left.x == pytest.approx(50)
    assert bottom_right.x == pytest.approx(750)
    assert top_left.y >= 0
    assert bottom_right.y <= VIEWPORT.height


def test_fitted_to_does_not_blow_up_small_content() -> None:
    camera = Camera(zoom=0.5).fitted_to(Rect(0, 0, 10, 10), VIEWPORT, max_zoom=1.0)
    assert camera.zoom == 1.0


def test_fitted_to_handles_a_single_point() -> None:
    camera = Camera().fitted_to(Rect(30, 40, 0, 0), VIEWPORT)
    assert_close(camera.to_screen(Point(30, 40)), Point(400, 300))


@given(cameras, screen_points, st.floats(min_value=0.01, max_value=100))
def test_with_zoom_at_sets_the_exact_zoom(camera: Camera, anchor: Point, zoom: float) -> None:
    zoomed = camera.with_zoom_at(anchor, zoom)
    assert zoomed.zoom == zoom
    assert_close(zoomed.to_world(anchor), camera.to_world(anchor))


def test_with_zoom_at_rejects_non_positive_zoom() -> None:
    with pytest.raises(ValueError):
        Camera().with_zoom_at(Point(0, 0), 0)


def test_soft_clamp_leaves_zoom_inside_the_limits_alone() -> None:
    for zoom in (MIN_ZOOM, 0.5, 1.0, 7.0, MAX_ZOOM):
        assert soft_clamp_zoom(zoom) == pytest.approx(zoom)


def test_soft_clamp_resists_past_the_limits_without_a_hard_stop() -> None:
    above = [soft_clamp_zoom(MAX_ZOOM * f) for f in (1.1, 1.5, 3, 10, 1000)]
    assert above == sorted(above)
    assert MAX_ZOOM < above[0] < MAX_ZOOM * 1.1
    assert above[-1] < MAX_ZOOM * 2
    below = soft_clamp_zoom(MIN_ZOOM / 1000)
    assert MIN_ZOOM / 2 < below < MIN_ZOOM


def run_spring(spring: CameraSpring, seconds: float = 3.0) -> CameraSpring:
    for _ in range(round(seconds * 120)):
        spring = spring.step(1 / 120)
    return spring


@given(cameras, cameras)
def test_camera_spring_starts_at_the_start_and_settles_at_the_target(
    start: Camera, target: Camera
) -> None:
    middle = Point(VIEWPORT.width / 2, VIEWPORT.height / 2)
    spring = CameraSpring.between(start, target, VIEWPORT)
    first = spring.camera(VIEWPORT)
    assert first.zoom == pytest.approx(start.zoom)
    assert_close(first.to_world(middle), start.to_world(middle))

    last = run_spring(spring).settled().camera(VIEWPORT)
    assert last.zoom == pytest.approx(target.zoom)
    assert_close(last.to_world(middle), target.to_world(middle))


def test_camera_spring_comes_to_rest() -> None:
    spring = run_spring(CameraSpring.between(Camera(500, -200, 3), Camera(), VIEWPORT))
    assert spring.at_rest


def test_camera_spring_keeps_a_glide_going_before_turning_back() -> None:
    # The content is gliding right at 2000 px/s while the target is to the right,
    # so the content has to travel left to get there.
    start = Camera(0, 0, 1)
    target = Camera(1000, 0, 1)
    spring = CameraSpring.between(start, target, VIEWPORT, velocity=Point(2000, 0))
    assert spring.screen_velocity().x == pytest.approx(2000)

    origin_on_screen = spring.step(1 / 120).camera(VIEWPORT).to_screen(Point(0, 0))
    assert origin_on_screen.x > 0  # still moving right on the first frame, no brick wall
