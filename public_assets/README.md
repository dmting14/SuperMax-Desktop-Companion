# Public character animation

`generate_walk.py` draws this project's generic stick figure directly with
PySide6 `QPainter`. It reads no private character image or reference frame.

Run `python public_assets/generate_walk.py` to regenerate the 24 transparent
480 × 760 PNG frames at 24 FPS. The manifest under `animations/` uses the
existing animation loader. The artwork and generator are covered by the
repository's MIT license.

The optional private theme requires a separate asset root with an
`animations/manifest.json` and is never part of this repository.
