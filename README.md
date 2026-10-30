# Raman Lab KE

This project coordinates a configurable spatial scan, records one raw Raman spectrum per position, and generates a spectral-feature map. Sample dimensions and measurement settings can change between runs. The printer geometry is a separate profile.

The repository combines the Raman pipeline with reusable camera, printer and
chat components. See [the project layout](docs/PROJECT_LAYOUT.md) for folder names
and [source attribution](NOTICE.md) for upstream credits. Local manuals, device
configuration, credentials and experiment outputs are excluded from Git.

**Current status:** the complete software workflow runs with simulated devices and accepts explicitly indexed CSV spectra. It includes a Moonraker motion adapter and a protocol for an external instrument driver. The Avantes/laser driver, installed printer API, mounting geometry, focus, and hardware behavior have not been connected or validated. The driver protocol is an integration boundary, not an implemented Avantes driver. No printer or laser was operated during development.

## Quick start

Use Python 3.10 or newer on Linux or Windows. The core has no third-party dependencies. Run commands from this directory.

```bash
python -m raman_scanner plan --machine profiles/machine.simulation.json --scan profiles/scan.demo.json
python -m raman_scanner run --machine profiles/machine.simulation.json --scan profiles/scan.demo.json --output runs/my-demo
```

Open `runs/my-demo/report.html` in a browser. The self-contained report works offline. Click a map position to see its spectrum and switch between raw and dark-corrected counts. Reports embed at most 256 representative spectra; all spectra remain in the run database. A gray map cell is missing or flagged.

The local `runs/demo/report.html` is a completed 25-point synthetic example. Run
outputs are ignored by Git; a fresh clone can generate its own report with the
commands above. Simulations do not wait for the configured exposure time;
duration estimates still use the configured integration and averaging settings.

## What happens in a run

```mermaid
flowchart LR
    A[Machine and scan profiles] --> B[Validate coordinates and bounds]
    B --> C[Initialize devices with laser off]
    C --> D[Record dark reference]
    D --> E[Move and wait for completion]
    E --> F[Settle and acquire spectrum]
    F --> G[Disable emission]
    G --> H[Save raw data and coordinates]
    H -->|next position| E
    H --> I[Dark subtraction and band integration]
    I --> J[Offline report and CSV export]
```

The hardware motion path raises to the configured travel Z, traverses XY, then descends to focus. Travel Z must clear the complete sample, mount and fixture envelope, including the initial vertical path. Configuration validation checks numerical bounds, not physical collision geometry. The pipeline never automatically homes, starts a print, heats, or extrudes.

## Change the sample without changing the pipeline

Copy `profiles/scan.demo.json` and edit the copy for each experiment:

| Setting | Purpose |
| --- | --- |
| `sample_id`, `notes` | Record the sample and experimental context. |
| `grid.x_mm`, `grid.y_mm` | Sample coordinates for the region of interest. |
| `grid.pitch_mm` | X and Y sampling intervals. Both requested edges are included; the final interval can be shorter than the pitch. |
| `grid.pattern` | `raster` or `serpentine`; verify effects of direction reversals before using serpentine on hardware. |
| `focus.machine_z_mm` | Commanded printer Z at the reference sample coordinate. This is not the probe's optical working distance. |
| `focus.slope_x`, `focus.slope_y` | Optional measured plane slopes in mm/mm. Defaults are zero; this is not autofocus or a general height map. |
| `focus.reference_sample_mm` | Sample coordinate at which `machine_z_mm` applies. |
| `focus.calibration_id`, `focus.lens_id` | Identify the focus setup and installed optics. |
| `acquisition.integration_ms`, `averages` | Exposure time per integration and number of averaged integrations. |
| `acquisition.laser_nm` | Calibrated excitation wavelength used for the Raman shift conversion. |
| `acquisition.laser_setting` | Recorded instrument setting with units; it is not a measured sample-plane power. The hardware driver must confirm it. |
| `acquisition.settle_s`, `laser_settle_s` | Delays after movement and laser enable, respectively. Establish these experimentally. |
| `acquisition.adc_max` | Optional detector saturation threshold, if established for the actual instrument. |
| `analysis.band_cm1`, `baseline` | Feature-integration band and optional straight baseline between its endpoints. |

`profiles/scan.full-bed.json` targets 220 x 220 mm at 5 mm pitch: 2,025 positions. At one 3-second integration, exposure alone takes 1.69 hours. Finer grids cost considerably more time. The nominal print area does not establish the reachable Raman area.

The machine profile defines calibrated bounds, the sample origin in printer coordinates, and the sign of each XY axis:

```text
commanded_X = sample_origin_X + axis_sign_X * sample_X
commanded_Y = sample_origin_Y + axis_sign_Y * sample_Y
commanded_Z = focus_Z + slope_X * (sample_X - reference_X)
                      + slope_Y * (sample_Y - reference_Y)
```

Calibrate this transform with actual marked sample positions; printer bed motion alone does not establish the sign convention. Tilt compensation assumes a measured plane. Curved surfaces require a later height-map or autofocus implementation.

## Pause and resume

```bash
python -m raman_scanner run --machine profiles/machine.simulation.json --scan profiles/scan.demo.json --output runs/resume-demo --stop-after 7
python -m raman_scanner status runs/resume-demo
python -m raman_scanner run --machine profiles/machine.simulation.json --scan profiles/scan.demo.json --output runs/resume-demo --resume
```

Completed spectra are inserted transactionally and are never overwritten. A resumed session takes a fresh dark and links newly acquired points to it. Machine, sample, optics, and acquisition profiles must match the saved configuration exactly. If the sample moved or focus changed, create a new run. Resume also checks the instrument identity, but cannot detect physical sample movement.

An error stops acquisition and attempts to disable emission and stop motion. It does not automatically home or retract. An off-confirmation failure preserves any valid readout in `uncommitted-captures/`, without marking that point complete. Independent hardware interlocks/watchdogs remain necessary: a host application cannot guarantee laser shutdown after a computer, network, or driver failure.

An exclusive `.run-lock` prevents two owners of the same run directory. If a process crashes, the lock may remain. Remove it only after verifying that the old process and devices have stopped. It does not prevent a different application or run directory from controlling the same hardware; hardware scanning requires exclusive ownership of the printer and instrument.

## Reprocess and export

```bash
python -m raman_scanner analyze runs/my-demo --band 1540 1660
python -m raman_scanner export runs/my-demo --output runs/my-demo/spectra.csv.gz
python -m raman_scanner spectrum runs/my-demo 0 --output runs/my-demo/point-0.csv
```

Analysis regenerates `points.csv`, `summary.json`, and `report.html` without editing raw spectra or the original configuration. It uses:

```text
Raman shift (cm^-1) = 10^7 * (1 / excitation_nm - 1 / wavelength_nm)
dark-corrected counts = raw counts - associated dark counts
band area = trapezoidal integral over the selected Raman interval
```

Band endpoints are interpolated. With `linear_endpoints`, a line between the band endpoints is subtracted only for band integration. No automatic smoothing, fluorescence fitting, cosmic-ray removal, concentration prediction, or chemical identification is performed. Areas are not normalized for exposure, averaging implementation, or optical power. Saturated points retain raw data but are excluded from the displayed quantitative map.

`run.sqlite` contains configuration and hashes, instrument identity, raw wavelength/count arrays, dark references, coordinates, timestamps, quality flags and an event log. Machine coordinates are commanded values, not independently measured positions. `spectra.csv.gz` streams the complete spectral dataset in long format, with raw, dark, corrected counts and Raman shifts. Back up the entire run directory.

## Use existing Raman exports

Normalize raw exported spectra to UTF-8 comma-separated CSV with these headers:

```csv
wavelength_nm,counts
800.0,123
800.5,145
801.0,138
```

Alternatively use `raman_shift_cm1,counts` with the correct excitation wavelength in the scan profile. All axes must be increasing and match the dark spectrum. Do not label an already dark-corrected or baseline-subtracted export as raw counts.

Create an index file linking each spectrum to a scan-plan point. Paths are relative to the index file:

```csv
point_index,path
0,point-0.csv
1,point-1.csv
```

Export the planned coordinate list to make the association explicit:

```bash
python -m raman_scanner plan --machine profiles/machine.simulation.json --scan profiles/scan.demo.json --csv planned-points.csv
python -m raman_scanner import-csv --machine profiles/machine.simulation.json --scan profiles/scan.demo.json --index spectra-index.csv --dark dark.csv --output runs/imported
```

Import never connects to hardware. It preserves source-file hashes and labels the data as imported, even when a simulation geometry profile supplied coordinates. Coordinate association, exposure settings and calibration are user supplied. File modification time is recorded as an unverified timestamp; saturation is unknown unless `adc_max` is configured. Partial imports can be analyzed. A failed import retains already stored data for inspection; use a new directory for a corrected import. Imported data cannot be resumed as a simulated or hardware acquisition.

## Connect hardware later

The core is ready for device integration without deciding the host OS now. The unresolved work is specific to the installed equipment:

1. Confirm the printer exposes a usable Moonraker API; stock Creality firmware is not assumed to do so. The adapter implements its documented HTTP endpoints and waits for `M400` plus a reported target position.
2. Obtain the compatible Avantes SDK and official Python wrapper for the selected OS and exact spectrometer. Implement the instrument bridge described in [the driver protocol](docs/INSTRUMENT_BRIDGE.md), including the actual supported laser-control interface. This repository does not guess that interface or vendor structure layouts.
3. Calibrate reach, coordinate signs, focus, clearance, speed, acceleration and settling with the final mount. The motion adapter uses configured feed rates and the printer's existing acceleration limits; set suitable acceleration during commissioning.
4. Copy `profiles/machine.hardware.template.json` and replace every null/placeholder with measured values. Its missing geometry deliberately prevents execution. Set real sample/optics settings in a separate scan profile. The template's optional API-key environment variable must exist if retained.
5. Establish suitable containment, functioning interlocks and an independent fail-off response. Validate a stationary spectrum and a small grid before expanding coverage.

Only the explicit hardware command connects to physical devices:

```bash
python -m raman_scanner run --machine profiles/machine.actual.json --scan profiles/scan.actual.json --output runs/actual-001 --hardware
```

The first motion adapter requires homed XYZ, no active/paused print, heaters targeted off, zero live velocity, no active bed mesh, 100% speed override, and matching G-code/native coordinates. It does not alter these prerequisites or automatically home the modified toolhead. It does not implement autofocus, automatic collision detection, printer rooting, or firmware installation.

## Validation and source material

```bash
python -m unittest discover -s tests -v
```

Tests cover full-bed planning, transforms, invalid bounds/settings, acquisition ordering, interruption and resume, saturation, reference compatibility, imports/exports, bridge timeouts and motion completion. Device adapter tests use fixtures, not physical hardware.

The optional report interaction check uses Node.js without a browser or external dependencies:

```bash
node tests/check_report.cjs runs/demo/report.html
```

This exercises map selection, signal switching, chart drawing calls and CSV download generation with a mocked document/canvas. It does not verify the rendered visual layout.

The locally supplied PDFs, JSON conversions and SOP informed the design in [the hardware plan](docs/RAMAN_SCANNER_PLAN.md). They are kept under `documentation/instruments/` and excluded from the public repository. Official interface references:

- [Moonraker printer API](https://moonraker.readthedocs.io/en/latest/external_api/printer/)
- [Klipper G-code reference](https://www.klipper3d.org/G-Codes.html)
- [Avantes official Python SDK example](https://avantesusa.com/wp-content/uploads/2022/10/Python-Updates_October-2022.pdf)

The Avantes example is evidence of the SDK acquisition flow, not proof of compatibility with the unverified installed instrument. Dark subtraction and wavelength calibration remain distinct operations.

## Camera, printer and dashboard components

`sample-vision/`, `printer-control/`, `dashboard/` and `camera-adapter/` contain the
retained PhotonicsAI foundations. Their runtime paths and setup options use the
new folder names. The dashboard remains available as requested; its existing
actions still implement erasing and are not yet Raman scan controls.

```sh
python3 scripts/setup.py --list
python3 scripts/setup.py --with-dashboard
python3 scripts/check.py --with-dashboard
```

Use macOS/Linux and Python 3.11+ for the upstream component setup. By default,
setup installs only `sample-vision` and `printer-control`; the dashboard and
phone adapter are optional. See [the reuse review](docs/RAMAN_REUSE.md) for
inherited geometry and remaining integration work.
