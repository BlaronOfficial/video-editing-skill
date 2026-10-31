"""DaVinci Resolve hand-offs.

  free   the import package (exports/package.py, target "resolve"): FCPXML 1.10 + ProRes 4444 graphics + LUT +
         SRT + stems + README. Works with every edition; the owner imports it (File > Import > Timeline), or
         screen.py does it on the owner's screen with their OK.
  studio live.py drives Resolve Studio through its scripting API (Studio-only since 21.1): new project or
         timeline from the package, LUT on the clips, read-back check. Add-only: never deletes or overwrites.
  learn  exports/diff.py reads a timeline the owner exported from Resolve (FCPXML/OTIO/EDL) and learns from it.
"""
