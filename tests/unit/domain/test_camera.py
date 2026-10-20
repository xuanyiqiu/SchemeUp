import pytest
from hypothesis import given
from hypothesis import strategies as st

from schemeup.domain.camera import MAX_ZOOM, MIN_ZOOM, Camera
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


@given(cameras, cameras)
def test_interpolate_starts_and_ends_at_the_endpoints(start: Camera, end: Camera) -> None:
    middle = Point(VIEWPORT.width / 2, VIEWPORT.height / 2)
    first = start.interpolate(end, 0.0, VIEWPORT)
    last = start.interpolate(end, 1.0, VIEWPORT)
    assert first.zoom == pytest.approx(start.zoom)
    assert last.zoom == pytest.approx(end.zoom)
    assert_close(first.to_world(middle), start.to_world(middle))
    assert_close(last.to_world(middle), end.to_world(middle))
