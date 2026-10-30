# Calibrated camera scanner

Camera acquisition, frame identity, append-only image storage, planar calibration,
board tracking, region geometry, preview UI and MCP tools are retained. The
current detector segments red/blue/green marker regions; it is not a general
sample detector or a chemical classifier.

The older uncalibrated triangle/quadrilateral app was removed. Current entry
points are `run_cells.py`, `scan_image.py` and `cells_mcp_server.py`.

## Run without hardware

From the repository root:

```sh
python3 scripts/setup.py --component sample-vision
```

Then:

```sh
cd sample-vision
.venv/bin/python run_cells.py --demo
```

Open `http://127.0.0.1:8767`. For a one-shot synthetic scan:

```sh
.venv/bin/python scan_image.py --scene mixed
```

Explicit scans preserve raw frames, annotations and result JSON under
`results/images/`. Live preview stays in memory. Demo mode contacts no camera or
printer hardware.

## Camera and calibration

The inherited sources are the optional Blackmagic iPhone preview adapter in
`../camera-adapter/` and an IP Webcam snapshot endpoint. Both are retained while
the Raman camera is undecided. There is no USB webcam or LiDAR driver yet.

Calibration assumes a 200 x 200 mm reference board, 50 mm large grid lines and
(+9, +8) mm printer translation. These inherited values must be made configurable
and calibrated before using coordinates for Raman motion. A camera homography
applies to the calibrated plane, not arbitrary sample heights.

See [the integration contract](CAMERA_VISION.md) for endpoints, frame identity,
storage and calibration behavior, and [the reuse review](../docs/RAMAN_REUSE.md)
for adaptation priorities. Historical environment/test claims in the integration
contract describe upstream work, not this checkout.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests use synthetic images, temporary storage, mock camera responses and local
test servers. They do not validate physical targeting accuracy.
