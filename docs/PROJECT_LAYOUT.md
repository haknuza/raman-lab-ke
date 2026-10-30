# Raman Lab KE repository layout

This is one project repository with its own Git history. Components share the
repository root; there is no nested PhotonicsAI repository or Git submodule.

| Project path | Purpose | Previous name |
| --- | --- | --- |
| `raman_scanner/` | Acquisition coordination, data storage, analysis, reports and CLI | Kept as the Python package name |
| `sample-vision/` | Camera acquisition, calibration, region detection, images and MCP | `shape-scanner/` |
| `printer-control/` | Bounded printer commands, SSH transport, watchdog and mocks | `photonics-printer-mcp-main/` |
| `dashboard/` | Retained chat UI, orchestration and evidence tools | `lab-agents/` |
| `camera-adapter/` | Optional Blackmagic phone camera adapter | `camera-control/` |
| `documentation/instruments/` | Local vendor manuals, JSON conversions and SOP; ignored by Git | `DocumentsRegardingRammanSpectrography/` |
| `docs/` | Design, integration, provenance and validation notes | Combined documentation directories |
| `profiles/` | Example machine and scan configuration | Unchanged |
| `scripts/` | Component environment setup and offline checks | Lifted to the repository root |
| `tests/` | Standalone Raman pipeline tests | Unchanged |
| `runs/` | Local experiment/simulation outputs; ignored by Git | Unchanged |

The local project directory is `raman-lab-ke`. The previous wrapper directory
`PhotonicsAI-Lab-Cell-Erasing` has been removed after its contents were integrated.

Original Git metadata is preserved beside this project at
`../.upstream-archive/photonicsai.git`, outside the new repository. The original
cleanup manifest keeps upstream path names so it can locate deleted objects in
that history. The public project records upstream attribution in `NOTICE.md`.

The standalone Raman core remains compatible with Python 3.10+ on Linux/Windows.
The inherited printer/phone/dashboard stack has platform-specific assumptions;
folder renaming does not change those requirements or complete its Raman
integration. See `RAMAN_REUSE.md` for the remaining work.
