# Cleanup validation on 30 October 2026

This record describes the Raman-focused cleanup of the cloned checkout. The
upstream homework validation record remains in the separately archived upstream
Git history at commit `fe9659c`; it is not part of this new repository's history.
Its historical results are not evidence of validation against this Raman setup.

## Checks performed

| Check | Result | Scope |
| --- | --- | --- |
| Camera/vision suite excluding stdio MCP | 60 passed | Synthetic detection, frame storage, calibration, board tracking, target stability, HTTP routes and camera source handling |
| Full printer suite | 143 passed | Mock printer, local Unix sockets and stdio MCP; rerun outside sandbox after local socket binding was blocked |
| Printer environment dependency consistency | Passed | Existing compatible environment; no packages installed or changed |
| Python syntax | Passed | All remaining Python source, including the modified setup/check scripts |
| Setup/check component selection | Passed | Core defaults, optional dashboard/phone selection and explicit component selection, without installation or hardware calls |
| Deletion manifest | Passed | All 20 deleted tracked paths exactly match the recorded manifest |
| Git whitespace checks | Passed | No patch whitespace errors |

The first camera attempt used the host environment and reached one missing Flask
import. Rerunning with the existing local Flask package directory made all 60
selected camera checks pass. This used OpenCV 4.14.0.94, NumPy 2.2.6, Pydantic
2.13.5 and Flask 3.1.3; it was not a fresh install of the scanner's pinned upstream
requirements. The remaining stdio camera MCP integration test was not run.

The printer checks used an existing compatible Python 3.10 environment with
FastMCP 4.1.0, MCP 2.3.0 and Pydantic 2.14.1. Initial sandbox runs were interrupted
or reported local Unix-socket `PermissionError`; a separate permitted rerun covers
those transport tests and passed all 143 checks. No printer safety policy or tests were weakened to avoid
those environment restrictions.

The complete dashboard regression/browser suites, optional phone adapter suite,
and a fresh Python 3.11+ requirements installation were not run as part of this
cleanup. Dashboard source and assets were preserved as requested. No dependencies
were installed, downgraded or removed, and no real `.env` was created.

## Physical scope

No real camera capture, printer SSH connection, movement, homing, heating, mesh
change, firmware change, live model request or Raman laser operation was performed.
Passing software tests does not validate physical clearance, board calibration,
optical focus or sample recognition on this installation.

## Repository reorganization

After consolidation into `raman-lab-ke`, the 31 Raman core tests and the 60
selected camera checks passed again. Component path references, setup/check
selection, report interaction logic and Python syntax were checked under the
new names. Local manuals, experiment outputs and environment files are ignored
by Git. A source audit found no credential-pattern or absolute personal-path
matches in the public source set. The upstream printer license and credits were
preserved.
