"""Stop, settle, acquire, persist; no movement can overlap an exposure."""
import time

from .devices import make_devices, utc_now
from .model import ScanError, validate_spectrum
from .store import RunStore, run_lock


def check_pair(spectrum, dark):
    validate_spectrum(spectrum)
    validate_spectrum(dark)
    a, b = spectrum["wavelength_nm"], dark["wavelength_nm"]
    if len(a) != len(b) or any(abs(x-y) > 1e-7 for x, y in zip(a, b)):
        raise ScanError("Spectrum wavelength calibration differs from its dark reference")


def run(plan, directory, resume=False, allow_hardware=False, stop_after=None, device_factory=make_devices, progress=None):
    if plan.machine["mode"] == "hardware" and not allow_hardware:
        raise ScanError("Hardware configuration requires --hardware; default operation never connects to devices")
    if stop_after is not None and (isinstance(stop_after, bool) or stop_after < 1):
        raise ScanError("stop_after must be positive")
    with run_lock(directory):
        store = RunStore(directory, plan, resume)
        if store.get("data_source", plan.machine["mode"]) != plan.machine["mode"]:
            store.close()
            raise ScanError("Imported data cannot be resumed as an acquired hardware or simulation run")
        stage = instrument = None
        fault = None
        try:
            done = store.completed()
            if len(done) == len(plan.points):
                return {"state": store.get("state"), "saved_points": len(done), "note": "No device connection; all points already recorded"}
            store.set("state", "initializing")
            store.event("session_started", {"resume": resume, "mode": plan.machine["mode"]})
            stage, instrument = device_factory(plan, store.event)
            # The laser must be off before even preparing the motion adapter.
            identity = instrument.preflight()
            previous = store.get("instrument_identity")
            if previous is not None and previous != identity:
                raise ScanError("Instrument identity changed since the previous session")
            store.set("instrument_identity", identity)
            stage.preflight()
            dark = validate_spectrum(instrument.acquire(dark=True))
            acquisition = plan.scan["acquisition"]
            if dark["saturated"] or ("adc_max" in acquisition and max(dark["counts"]) >= acquisition["adc_max"]):
                raise ScanError("Dark reference is saturated")
            from .analysis import integrate_band, raman_shifts
            # Validate processing coverage before the first move or laser enable.
            integrate_band(raman_shifts(dark["wavelength_nm"], acquisition["laser_nm"]),
                           [0] * len(dark["counts"]), plan.scan["analysis"]["band_cm1"], plan.scan["analysis"]["baseline"])
            dark_id = store.add_dark(dark)
            store.event("dark_saved", {"dark_id": dark_id})
            hardware = plan.machine["mode"] == "hardware"
            acquired = 0
            store.set("state", "running")
            store.set("last_error", None)
            for point in plan.points:
                if point.index in done:
                    continue
                instrument.off()
                stage.move(point)  # Must return only after physical move completion.
                if hardware:
                    time.sleep(acquisition["settle_s"])
                instrument.on()
                spectrum = None
                try:
                    if hardware:
                        time.sleep(acquisition["laser_settle_s"])
                    spectrum = validate_spectrum(instrument.acquire(point=point))
                finally:
                    # No later movement, even if capture or saving raises.
                    try:
                        instrument.off()
                    except BaseException as off_error:
                        if spectrum is not None:
                            store.save_uncommitted_capture(point, spectrum, dark_id, off_error)
                        raise
                check_pair(spectrum, dark)
                saturated = spectrum["saturated"] or ("adc_max" in acquisition and max(spectrum["counts"]) >= acquisition["adc_max"])
                flags = ["saturated"] if saturated else []
                store.save_point(point, spectrum, dark_id, flags)
                store.event("point_saved", {"point": point.index, "dark_id": dark_id, "flags": flags})
                acquired += 1
                done.add(point.index)
                if progress:
                    progress(len(done), len(plan.points))
                if saturated and acquisition["stop_on_saturation"]:
                    raise ScanError(f"Saturation at point {point.index}; raw spectrum saved, scan stopped")
                if stop_after is not None and acquired >= stop_after:
                    break
            state = "complete" if len(done) == len(plan.points) else "paused"
            store.set("state", state)
            store.set("updated_utc", utc_now())
            store.event("session_finished", {"state": state, "saved_points": len(done)})
            return {"state": state, "saved_points": len(done), "total_points": len(plan.points)}
        except BaseException as exc:
            fault = exc
            store.set("state", "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed")
            store.set("last_error", str(exc) or type(exc).__name__)
            store.event("session_failed", {"error": str(exc) or type(exc).__name__})
            raise
        finally:
            cleanup_errors = []
            if instrument is not None:
                try:
                    instrument.off()
                except BaseException as exc:
                    cleanup_errors.append(f"Laser-off confirmation failed: {exc}")
            if stage is not None and (fault is not None or cleanup_errors):
                try:
                    stage.emergency_stop()
                except BaseException as exc:
                    cleanup_errors.append(f"Motion stop failed: {exc}")
            for device in (instrument, stage):
                if device is not None:
                    try:
                        device.close()
                    except BaseException as exc:
                        cleanup_errors.append(f"Device close failed: {exc}")
            if cleanup_errors:
                store.set("state", "failed")
                store.set("last_error", "; ".join(cleanup_errors))
                store.event("cleanup_failed", {"errors": cleanup_errors})
            store.close()
            if cleanup_errors:
                raise ScanError("; ".join(cleanup_errors)) from fault
