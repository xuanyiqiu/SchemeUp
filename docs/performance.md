# Canvas performance

I check the canvas with `benchmarks/canvas_bench.py`. It fills a note with 5,000
elements (a mix of rough rectangles, ellipses, diamonds, arrows, text and freehand
strokes), zooms so about 640 of them are on screen in a 1920x1080 view, and times
real repaints while panning, zooming and dragging 50 selected elements. The
numbers come from the Qt offscreen platform on my laptop, so they only compare
runs with each other.

```
uv run python benchmarks/canvas_bench.py 5000
```

| Case | Before | After |
| --- | --- | --- |
| Pan, median frame | 50 ms | 16 ms |
| Zoom, median frame | 52 ms | 23 ms |
| Drag 50 selected, median frame | 52 ms | 16 ms |

Two things were costing frames, and neither was the drawing of the elements.

`Document.content_bounds()` took the union of every element's bounds on each
paint, 5,000 of them, to know where the pages of a paged note end. A document
never changes after it is created, so it is now computed once per version, and
a note without pages no longer asks for it at all. That was about 14 ms a frame.

The sheet lines were the other cost. Drawing 350 translucent one-pixel lines with
`drawLines` takes about 21 ms on a full-HD target, because Qt blends each pixel
of every line. I now blend each line color with the known background once and
paint it as an opaque one-pixel rect in source composition mode, which takes
about 1 ms and looks the same.

Zoom is still above the 16.7 ms target. Elements get larger while zooming in, so
the rasterizing of rough fills and strokes dominates there. If it matters in
practice, the next step is a cached pixmap of the static layer that is scaled
during the gesture and redrawn when it settles, as the architecture document
describes.
