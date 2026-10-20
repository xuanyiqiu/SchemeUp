# SchemeUp

SchemeUp is a desktop whiteboard for my own notes. I use Excalidraw a lot for software design sketches and for working through LeetCode problems, but I wanted it offline, with real paper backgrounds and proper snapping. I also wanted all the small meeting notes I write to live in one place instead of in hundreds of text files spread around my disk. So every note here is an infinite canvas, and the app keeps them in its own library with folders, tags, a Kanban board and a calendar.

It's written in Python with PySide6 (Qt) and runs completely offline. There are no accounts and nothing goes to the cloud.

## Status

This is the very beginning (Phase 0). Right now there's a window with an infinite canvas over a 5 mm grid. You can zoom around the cursor, pan with inertia, and jump back to the origin with a button. The plan for the rest, and the reasons behind the main decisions, are in [docs/architecture.md](docs/architecture.md).

## Running it

You need [uv](https://docs.astral.sh/uv/). It takes care of the Python version and installs the dependencies into a local virtual environment.

```
uv sync
uv run schemeup
```

The controls so far: Ctrl + wheel (or a touchpad pinch) zooms around the cursor, the wheel pans (hold Shift to pan sideways), and dragging with the middle button or with Space held down pans with inertia. Ctrl + = and Ctrl + - zoom in and out, and Ctrl + 0 goes back to 100%.

The canvas follows the Windows "Animation effects" setting. With it turned off, camera moves are instant and there's no inertia. Until there's a settings screen, you can override that with the `SCHEMEUP_MOTION` environment variable, set to `full` or `reduced`.

## Development

```
uv run pytest
uv run ruff check .
uv run ruff format .
uv run mypy
uv run lint-imports
```

`lint-imports` checks the layering rules. The domain and application code can't import Qt, and the UI and infrastructure layers can't import each other. To run the ruff checks on every commit, run `uv run pre-commit install` once.

The code lives in `src/schemeup`:

- `domain` is the pure Python model.
- `application` holds the use cases.
- `rendering` is the QPainter drawing code that the canvas and the exporters share.
- `infrastructure` deals with storage, the OS and export.
- `ui` has the widgets.

Tests mirror that layout under `tests/`.

## License

MIT. Qt and PySide6 are used under the LGPL v3; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
