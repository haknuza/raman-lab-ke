# Reusing PhotonicsAI for Raman mapping

The source was reviewed as a foundation for the existing Raman mapping pipeline.
Cleanup removes standalone material unrelated to runtime. It preserves the
calibrated camera stack, printer controls and safeguards, dashboard source and
tests. No physical hardware, firmware, configuration limits or user calibration
files were changed.

## Strong reuse candidates

| Capability | Files | How it helps Raman |
| --- | --- | --- |
| Raw acquisition and source selection | `sample-vision/camera_vision/acquisition.py`, `service.py` | Add a camera source without coupling it to spectral acquisition. |
| Frame identity and image provenance | `sample-vision/camera_vision/storage.py`, `models.py` | Link sample outlines and observations to the exact stored image. |
| Planar calibration and tracking | `sample-vision/camera_vision/calibration.py`, `dynamic_grid.py`, `border.py` | Convert detected image regions into measured plane coordinates, rejecting lost references. |
| Stable target observation | `sample-vision/camera_vision/targets.py`, `dashboard/agents/observation.py` | Reject stale frames, unstable detections and changed calibration before selecting a target. |
| Preview and sample selection UI | `sample-vision/cells.html`, `dashboard/templates/`, `dashboard/static/` | Foundation for a Raman region-selection and progress interface. |
| Bounded printer control | `printer-control/printer_policy.py`, `printer_watchdog.py`, `printer_commands.py` | Reuse complete-plan validation, dispatch-time state checks, stop handling and single-use tokens. |
| SSH transport and printer simulation | `printer-control/printer_client.py` | An alternative to the Raman pipeline's Moonraker adapter, if the installed KE supports the documented authenticated SSH setup. |
| Workflow and evidence | `dashboard/agents/workflow.py`, `inspection.py`, `gallery.py` | Reuse orchestration and evidence patterns after replacing erasing-specific task contracts. |

The retained components are not automatically integrated with `raman_scanner/`. Connecting
the two requires an explicit adapter and compatible coordinates. Preserve the
printer interface's policy and execution contract when doing that work; do not
extract only its raw transport and bypass validation.

## Inherited assumptions that must be replaced

1. **Board extent:** calibration and tracking assume 200 x 200 mm, with 50 mm large
   grid lines. The Raman coverage goal is 220 x 220 mm. Changing a README or one
   constant is insufficient; geometry, tracking, UI and tests must agree.
2. **Coordinate origin:** `calibration.py` translates board coordinates by (+9, +8)
   mm. `dashboard/agents/planning.py` repeats that translation for paper-relative
   moves. These values came from another setup and are unverified here.
3. **Tool geometry:** the erasing planner uses observation pose [209, 208, 100] mm,
   contact Z 14.5 mm and a 10 mm circular wiping radius. These paths cannot be
   reused as Raman focus or scan paths. Preserve the dashboard while replacing
   those task/planning contracts during the Raman UI migration.
4. **Object labels:** red/blue regions are called defective and green regions
   healthy. They are colored markers, not general sample recognition. The Raman
   application should use neutral sample/region labels, with a reviewed mask or
   a detector validated for the actual material.
5. **Imaging geometry:** the homography assumes coplanar targets. Elevated/curved
   samples need height compensation; it supplies no autofocus or LiDAR data.
6. **Camera transport:** the current sources are phone preview and IP Webcam.
   USB camera support is not present. Capture time is host acquisition time, not
   a hardware exposure timestamp.
7. **Operating system:** the existing printer SSH/watchdog implementation imports
   POSIX `fcntl`. The retained lab workers also refer to `.venv/bin/python`.
   Do not claim this upstream stack is Windows-ready just because the standalone
   Raman core supports Windows.
8. **Chemical identification:** visual boundaries and colors do not identify
   sample chemistry. That requires validated Raman spectra and reference data.

## What was removed and why

- `videos/`, `presentation/`, `screenshots/`, `output/` and `docs/report/`: homework
  delivery artifacts and recordings, not dependencies of the application.
- Upstream `shape-scanner/app.py`, `detector.py`, `index.html`, `mcp_server.py` and
  `test_scanner.py`: the superseded uncalibrated triangle/quadrilateral app and its
  dedicated UI, MCP server and tests. The active scanner uses `run_cells.py`,
  `cells_mcp_server.py` and `camera_vision/` instead.
- Upstream `shape-scanner/examples/`: unused example images from that older demo.

20 tracked files were removed, totaling 26,685,890 bytes (25.45 MiB). No remaining
test was deleted to hide a failing behavior. The retained requirements have
runtime/test users and remain pinned as upstream supplied them. The dashboard
and optional phone adapter remain available; default setup/checks now select only
the scanner and printer. No cloud key is needed for that core.

The complete path/size list and exact upstream commit are recorded in
`cleanup-manifest.json`. The original Git history was preserved outside this
fresh repository in `../.upstream-archive/photonicsai.git`. The manifest retains
the original upstream names. To inspect a removed file, run from this project:

```sh
git --git-dir=../.upstream-archive/photonicsai.git show fe9659c:path/to/removed-file
```

The public repository does not include that local archive. Original files are
also available from the upstream repository linked in `../NOTICE.md`. A new
initial commit records the cleaned and renamed project rather than publishing
the old history and removed media again.

## Integration order

1. Reuse the camera acquisition, frame storage and calibration architecture, with
   configuration for measured board size and the camera-to-sample transform.
2. Produce a sample region mask tied to a saved frame and calibration. Generate
   a scan grid inside that mask using the Raman pipeline's scan configuration.
3. Adapt the printer interface behind the Raman motion boundary, preserving its
   preview, complete-plan validation, dispatch checks and uncertain-motion rules.
4. Replace the dashboard's erasing requests with Raman scan requests and expose
   acquisition status, dark references, saturation flags and spectra.
5. Add height mapping/autofocus only after measuring optical focus tolerance and
   validating the appropriate sensor on the actual sample surfaces.

These steps describe future integration, not implemented capabilities of this
cleanup. The existing synthetic Raman pipeline remains the executable starting
point while the actual spectrometer/laser interface is established.
