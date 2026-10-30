# Ender 3 V3 KE Raman scanner plan

## Purpose and current status

Use the existing Raman instrument and the Creality Ender 3 V3 KE motion system to collect spectra at known sample positions and build a spatial Raman map. The user wants the full nominal 220 x 220 mm bed area available for scanning. This is a proposed design, not a validated machine conversion. No printer settings, firmware, wiring, or instrument controls have been changed.

The user subsequently requested the complete pipeline first, with samples allowed to change and the host operating system undecided. The initial software implementation is described in `README.md`: configurable planning, simulated acquisition, resumable raw storage, CSV import/export, processing and an offline report. Hardware integration remains unverified.

Assumption for the first hardware implementation: a secured, approximately flat sample that can move with the bed. Sample-specific area, focus plane and acquisition settings are per-run configuration. The user has not yet identified the exact Raman model.

## What the supplied documents establish

| Source | Relevant information | Design consequence |
| --- | --- | --- |
| `documentation/instruments/SOP_Raman spectrometer_785nm.docx`, sections 1 and 4, figures 1, 3 and 5 | Identifies an Avantes AvaRaman D Bundle at 785 nm. Photos show a blue integrated probe, separate laser controller, and AvaSpec-HSC-TEC spectrometer. Lists lenses with 4.5 mm and 9 mm working distances. | This is the strongest evidence for the likely installed setup, but does not prove which hardware or lens the user currently has. |
| `documentation/instruments/021023-785nm Integrated Raman Probe - Operation Manual.pdf`, printed pages 8-11 | Documents remote interlock, external power control, 9 mm working distance from shaft or 0.5 mm from distance regulator, and a nominal probe body of 101.6 x 50.8 x 22.9 mm. Shaft diameter is listed as 6.35 mm. | Confirm the actual probe and installed optics before CAD. Support the body and relieve cable loads; shaft diameter alone is insufficient for a mount. |
| Same probe manual, product summary and laser safety | Class 3B, invisible 785 nm radiation, hundreds of milliwatts. | Beam containment and the manufacturer's hardware interlock are integral to the design. |
| `documentation/instruments/020437-AvaRAMAN manual-2-00.pdf`, section 1.2.2 | Lists several separate fiber probes with different diameters and focal lengths. | Do not mix dimensions or connector specifications across product generations. |
| `documentation/instruments/How to perform Raman measurements.pdf`, pages 3-4 | Discusses integration time, saturation, averaging, and taking a dark with the laser off. | Establish measurement settings on a stationary reference before scanning. |
| `documentation/instruments/020379-AvaSoft 8 Manual.pdf`, sections 4.11.2 and 4.11.3.2 | Requires a new dark after changing integration time and describes laser wavelength calibration using a PTFE reference. | Dark subtraction and spectral calibration are separate operations. |

The JSON conversions were used to locate topics, then relevant PDF text and the integrated probe specification and dimension drawings were checked. The SOP's embedded equipment photos were also inspected. Its instruction to keep the shutter open is not a basis for relying on software alone to prevent emission. The generic manual and SOP specify different stabilization contexts; use the confirmed system procedure rather than treating one warm-up duration as universal.

The SOP mentions a CODE folder for Python data saving. No such folder was present in the inspected workspace.

## Mechanical arrangement

- Secure the sample and its fixture to the bed. Bed motion supplies the relative Y scan.
- Attach the probe vertically to a rigid bracket on the X carriage. Carriage motion supplies X; the gantry supplies Z for initial focus or a measured surface-height map.
- Keep the spectrometer and laser controller beside the printer on a stationary support.
- Support the probe body without blocking controls or needed heat dissipation. Measure probe mass and bracket deflection before setting acceleration. Do not assume it is a lightweight passive fiber probe.
- Route fiber and electrical cables with strain relief and sufficient slack for the complete motion envelope. Obtain the actual cable's minimum bend radius; do not infer it from fiber diameter.
- Keep heaters off during initial scanning. Check clearance of the nozzle, touch probe, bracket, sample fixtures, and cables throughout all travel.

### Full bed coverage

220 x 220 mm is the nominal print footprint, not a verified Raman measurement envelope. A probe attached beside the nozzle introduces an XY offset and can prevent access to one or more edges. Aim to put the probe optical axis near the original nozzle XY position, subject to mechanical feasibility. A replacement toolhead mount may be needed for full coverage; that requires a planned response to heater/thermistor and homing dependencies before removing printer components.

Define the transform between sample coordinates and printer coordinates, including probe offsets and the bed-motion sign. Verify it using marked sample positions. Check all four corners at safe height with the laser disabled and measure the true usable rectangle. Do not exceed configured mechanical travel to recover an unreachable edge.

Do not run normal printing start sequences, automatic nozzle-based Z offset routines, or bed probing with the Raman probe in a possible collision path. Establish a safe homing procedure for the final hardware first. The printer's nozzle reference and bed mesh do not establish Raman focus. An active bed mesh can also introduce Z motion that must be understood before scanning.

## Focus and spatial resolution

Confirm the installed lens and the physical reference from which its working distance is measured. The SOP's 4.5 mm and 9 mm lenses and the generic manual's 0.5 mm distance-regulator gap are not interchangeable values.

First focus at one stationary reference point, then test focus at the bed corners. Measure sample tilt and flatness. If peak intensity varies strongly with height, level the sample or implement a verified surface-height map before full-area acquisition. Z-axis control alone is not autofocus. Do not slide a contact spacer across an unknown surface.

Choose scan pitch after measuring optical spot size, axial focus tolerance, and positioning repeatability. Printer microstep size and printing accuracy do not establish Raman spatial resolution. Full 3D surface following is a later scope decision requiring geometry or height sensing.

## Control and data acquisition

Use one host application to coordinate two independent interfaces:

1. Printer motion through an interface confirmed to be available on this printer and firmware.
2. Spectrometer acquisition through the compatible Avantes SDK/library, with laser control handled separately if the confirmed controller supports it.

Creality publishes a Klipper fork for the KE. Do not assume the installed printer exposes a standard USB serial port or an available Moonraker API. Inspect firmware version, network access, and available services before choosing a motion adapter. Firmware replacement or rooting is not a prerequisite assumed by this plan.

The proposed point sequence is:

1. Verify scan bounds, homing state, clearance, settings, and instrument readiness.
2. Inhibit laser emission for travel through a manufacturer-supported method verified on the actual controller.
3. Move to the next XYZ point.
4. Wait for actual motion completion, then allow a measured vibration-settling interval.
5. Enable measurement emission within the enclosed system, start a fresh acquisition, and wait for acquisition completion. Coordinate any required laser settling with the actual controller's behavior.
6. Save the spectrum and metadata, inhibit emission, and only then advance.
7. On completion or fault, inhibit emission and stop advancing. Do not automatically home or retract along an unverified path.

Klipper documents `M400` to wait for pending movement. A motion adapter must await the appropriate completion response; an upload/queue acknowledgement is insufficient. A fixed dwell cannot substitute for confirmation that a spectrum completed.

Start with software-coordinated stop-and-measure acquisition. Hardware triggering can be evaluated later if timing requires it. Printer fan/heater wiring is not an established laser-control interface. The integrated probe manual describes a 0-1 V external control input; this must not be treated as compatible with arbitrary printer PWM or logic outputs.

For initial optical validation, use the existing AvaSoft workflow. For automation, confirm spectrometer model, host OS, driver, SDK availability, and supported acquisition calls first. Do not assume simultaneous AvaSoft and SDK access to the same device.

For each point save sample X/Y/Z, commanded machine X/Y/Z, point and row identifiers, timestamps, integration time, averaging count, laser setting, lens, dark reference identifier, calibration information, and saturation/error flags. Label machine coordinates as commanded unless independent metrology verifies position. Preserve raw detector data and wavelength calibration alongside derived Raman shifts and processed results.

Use a raster grid initially. Compare scans that approach points from the same direction before choosing a faster serpentine path, because reversal effects may displace alternate rows.

## Laser containment

Enclose the full illuminated sample and motion envelope in a beam-containment enclosure suitable for the confirmed wavelength and power, with its access interlock connected through the manufacturer's supported hardware interlock interface. Contain plausible direct and reflected beam paths across the complete scan, including from reflective substrates. Have the arrangement and appropriate 785 nm eyewear reviewed by the responsible laser safety person. A printer enclosure or ordinary tinted panel is not evidence of laser attenuation.

Keep the manufacturer's safety controls intact. An emergency stop must inhibit laser emission as well as stop motion; the printer's stop command alone cannot establish that the independent laser is off. Software disconnects and stalled scans also need a defined response. Begin motion validation with the laser disabled and use suitable reference samples for optical validation.

## Scan duration

For a grid including both edges, when pitch divides 220 mm exactly:

`points = (220 / pitch_mm + 1)^2`

`total_time ~= points * (integration_seconds * averages + move + settle + transfer)`

Illustrative exposure-only times for one 3-second acquisition per point:

| Pitch | Grid | Spectra | Exposure time only |
| --- | --- | --- | --- |
| 5 mm | 45 x 45 | 2,025 | 1.69 hours |
| 2 mm | 111 x 111 | 12,321 | 10.27 hours |
| 1 mm | 221 x 221 | 48,841 | 40.70 hours |

These are calculations, not demonstrated performance or recommended exposure settings. Motion, settling, reference measurements, readout, file saving, and averaging increase duration. Scanning the full bed at fine pitch can take days.

## Build sequence and unresolved inputs

1. Identify the actual probe, spectrometer, controller, installed lens, and host computer. Compare the hardware with the SOP's figures 1, 3 and 5.
2. Specify sample type, mass, thickness, surface flatness, and desired feature size. Preserve full 220 x 220 mm as the coverage goal while verifying reach experimentally.
3. Measure probe body, mass, available mounting features, cable routing, and carriage geometry. Design a bracket around those measurements.
4. Establish laser containment, safe homing, software limits, and collision clearance. Perform a full-envelope dry run with emission disabled.
5. Establish a repeatable reference spectrum, dark subtraction, spectral calibration, and focus across the bed.
6. Verify a small grid, such as 5 x 5 points, with explicit coordinate-to-spectrum association and return-to-reference checks. Tune motion and settling from measured results.
7. Expand coverage gradually, then run the full grid and generate a map of a selected Raman peak or spectral feature.

## Official external references checked

- [Creality KE support and nominal dimensions](https://www.creality.cn/support/creality-ender-3-v3-ke)
- [Creality official KE Klipper source](https://github.com/CrealityOfficial/Ender-3_V3_KE_Klipper)
- [Klipper G-code reference including M400](https://www.klipper3d.org/G-Codes.html)
- [Avantes description of its SDK and Linux interfaces](https://www.avantes.com/content/uploads/2022/04/Spectroscopy-in-Process-Monitoring.pdf)

External references support general capabilities. They do not establish the firmware, accessible APIs, SDK compatibility, or verified performance of the user's equipment.
