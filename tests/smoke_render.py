"""Render the hand-written test edit from smoke_capcut.py (preview by default, --full for final quality)."""

import sys
import time
from pathlib import Path

from smoke_capcut import edit

from vedit import render

out = Path(__file__).resolve().parent / "out" / ("final.mp4" if "--full" in sys.argv else "preview.mp4")
t0 = time.time()
print(render.render(edit, out, preview="--full" not in sys.argv))
print(f"took {time.time() - t0:.1f}s")
