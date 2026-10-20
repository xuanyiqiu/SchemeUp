import pytest

from schemeup.domain.geometry import Size
from schemeup.domain.style import FontFamily


class FakeMeasurer:
    """Every character is 10 units wide and every line 20 units tall."""

    def measure(self, text: str, family: FontFamily, size: float, max_width: float | None) -> Size:
        lines: list[int] = []
        for paragraph in text.split("\n"):
            if max_width is None:
                lines.append(len(paragraph))
                continue
            per_line = max(int(max_width // 10), 1)
            chunks = max((len(paragraph) + per_line - 1) // per_line, 1)
            lines += [min(len(paragraph), per_line)] * chunks
        width = max(lines, default=0) * 10.0
        return Size(width if max_width is None else max_width, len(lines) * 20.0)


@pytest.fixture
def measurer() -> FakeMeasurer:
    return FakeMeasurer()
