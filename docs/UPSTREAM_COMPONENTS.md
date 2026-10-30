# PhotonicsAI components for the Raman scanner

This is a reduced working copy of PhotonicsAI Lab Cell Erasing, retained as a
camera, dashboard and printer-control foundation for the Raman project. The
active Raman acquisition pipeline remains in `raman_scanner/`; these components
are not connected to its live acquisition yet.

## Components retained

| Directory | What we can reuse |
| --- | --- |
| `sample-vision/` | Camera capture, frame identity, planar calibration, board tracking, region geometry, image storage, preview UI and scanner MCP |
| `printer-control/` | Bounded motion, telemetry checks, authenticated SSH transport, watchdog, preview/dispatch validation, mock printer and tests |
| `dashboard/` | Chat dashboard, bilingual UI, observation/evidence workers, spatial queries, structured proposals and workflow tests |
| `camera-adapter/` | Optional Blackmagic iPhone adapter, preview and camera controls |
| `scripts/` | Selective environment setup and hardware-free checks |
| `docs/` | Raman reuse review, cleanup record and validation notes |

The chat dashboard is preserved as a foundation. Its existing actions implement
colored-mark erasing, not Raman measurement. Do not use it as a Raman control UI
until its task contracts, routes, tool geometry and acquisition state have been
adapted. The phone adapter stays optional while camera hardware is undecided.
Core setup does not require a Groq account or install the dashboard.

Removed: homework report/presentation sources and PDFs, demonstration recordings,
UI screenshots, the superseded triangle/quadrilateral app and its unused example
images. Requirements remain unchanged: retained packages have direct runtime or
test uses. Original Git history, upstream credits and the printer MIT license
remain intact. Removed tracked files are listed in `docs/cleanup-manifest.json`.

## Install selected components

Use Python 3.11 or newer for the pinned upstream dependencies:

```sh
python3 scripts/setup.py
```

The default installs the camera scanner and printer interface into separate
virtual environments. It does not start services or connect to hardware.
Optional component selection:

```sh
python3 scripts/setup.py --with-dashboard
python3 scripts/setup.py --with-iphone
python3 scripts/setup.py --component sample-vision
```

For live language requests, copy `dashboard/.env.example` to `dashboard/.env`
and set the key locally. Do not commit `.env`. The retained dashboard also has a
scripted hardware-free demo; see its own README.

## Hardware-free camera demo

```sh
cd sample-vision
.venv/bin/python run_cells.py --demo
```

Open `http://127.0.0.1:8767`. See [the scanner guide](../sample-vision/README.md).

## Validation

```sh
python3 scripts/check.py
python3 scripts/check.py --component dashboard
```

Default checks cover the scanner and printer. Select the optional dashboard
explicitly or use `--with-dashboard`. `--python /absolute/path/to/python` can
select an existing compatible interpreter without modifying that environment.
Dependency checks run before tests. Browser tests are development-only; see
`dashboard/tests/`.

Tests use mock/synthetic inputs and local transports. Follow the printer
component's `AGENTS.md` and README before separate hardware work. Cleanup does not
change motion safeguards or authorize physical testing.

## Adaptation priorities

Read [the Raman reuse review](RAMAN_REUSE.md). The inherited camera geometry
assumes a 200 x 200 mm board and (+9, +8) mm printer offset. The erasing workflow
assumes a fixed observation pose and contact-tool paths. These are not validated
Raman positions or focus settings.

Upstream credit: PhotonicsAI Lab project by Aren Ananyan, David Sargsyan,
Andranik Arakelyan and Yerem Bareghamyan. The printer interface retains its MIT
license credited to WhoEvenAm.
