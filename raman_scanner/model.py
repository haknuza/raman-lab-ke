"""Configuration, coordinate transforms, and bounded scan planning."""
from dataclasses import asdict, dataclass
from decimal import Decimal
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path


class ScanError(Exception):
    """An actionable configuration, acquisition, or data error."""


def number(value, name, minimum=None, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ScanError(f"{name} must be a finite number")
    if (minimum is not None and value < minimum) or (positive and value <= 0):
        raise ScanError(f"{name} is outside its allowed range")
    return float(value)


def integer(value, name, minimum=1):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ScanError(f"{name} must be an integer >= {minimum}")
    return value


def vector(value, name, size=3):
    if not isinstance(value, list) or len(value) != size:
        raise ScanError(f"{name} must contain {size} numbers")
    return [number(v, name) for v in value]


def strict_keys(obj, required, optional=(), name="configuration"):
    if not isinstance(obj, dict):
        raise ScanError(f"{name} must be an object")
    missing, extra = set(required) - obj.keys(), obj.keys() - set(required) - set(optional)
    if missing or extra:
        raise ScanError(f"{name}: missing keys {sorted(missing)}, unknown keys {sorted(extra)}")


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ScanError(f"Cannot read JSON {path}: {exc}") from exc


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class Point:
    index: int
    row: int
    column: int
    sample_x: float
    sample_y: float
    machine_x: float
    machine_y: float
    machine_z: float


@dataclass
class Plan:
    machine: dict
    scan: dict
    points: list[Point]

    @property
    def snapshot(self):
        return {"schema_version": 1, "machine": self.machine, "scan": self.scan}

    @property
    def digest(self):
        return fingerprint(self.snapshot)

    def summary(self):
        a = self.scan["acquisition"]
        exposure = a["integration_ms"] * a["averages"] / 1000
        return {
            "mode": self.machine["mode"], "sample_id": self.scan["sample_id"],
            "points": len(self.points),
            "columns": len({p.column for p in self.points}),
            "rows": len({p.row for p in self.points}),
            "exposure_hours": len(self.points) * exposure / 3600,
            "exposure_plus_settle_hours": len(self.points) * (exposure + a["settle_s"]) / 3600,
            "timing_note": "Lower bounds; excludes motion, readout, laser settling and references. Simulation does not wait for exposures.",
            "machine_min": [min(getattr(p, f"machine_{axis}") for p in self.points) for axis in "xyz"],
            "machine_max": [max(getattr(p, f"machine_{axis}") for p in self.points) for axis in "xyz"],
            "config_sha256": self.digest,
        }


def axis_values(start, stop, pitch):
    """Always include the requested end; the final interval may be shorter."""
    start, stop, pitch = map(lambda v: Decimal(str(v)), (start, stop, pitch))
    count = int((stop - start) // pitch)
    if count > 1_000_000:
        raise ScanError("Axis has too many positions; increase pitch")
    values = [start + i * pitch for i in range(count + 1)]
    if values[-1] != stop:
        values.append(stop)
    return [float(v) for v in values]


def build_plan(machine, scan):
    # Copy via JSON so callers cannot silently mutate a persisted plan.
    machine, scan = json.loads(canonical(machine)), json.loads(canonical(scan))
    strict_keys(machine, ["schema_version", "mode", "machine_id", "bounds_mm", "sample_origin_mm", "axis_sign", "motion"], ["hardware"])
    strict_keys(scan, ["schema_version", "sample_id", "grid", "focus", "acquisition", "analysis"], ["notes"])
    if type(machine["schema_version"]) is not int or type(scan["schema_version"]) is not int or machine["schema_version"] != 1 or scan["schema_version"] != 1:
        raise ScanError("Only configuration schema_version 1 is supported")
    if machine["mode"] not in ("simulation", "hardware"):
        raise ScanError("machine.mode must be simulation or hardware")
    for obj, key in [(machine, "machine_id"), (scan, "sample_id")]:
        if not isinstance(obj[key], str) or not obj[key].strip():
            raise ScanError(f"{key} must be a nonempty string")
    bounds = machine["bounds_mm"]
    strict_keys(bounds, ["min", "max"], name="bounds_mm")
    lower, upper = vector(bounds["min"], "bounds min"), vector(bounds["max"], "bounds max")
    if any(lo >= hi for lo, hi in zip(lower, upper)):
        raise ScanError("Each machine minimum must be below its maximum")
    origin = vector(machine["sample_origin_mm"], "sample_origin_mm", 2)
    signs = vector(machine["axis_sign"], "axis_sign", 2)
    if any(s not in (-1, 1) for s in signs):
        raise ScanError("axis_sign entries must be -1 or 1")
    motion = machine["motion"]
    strict_keys(motion, ["xy_speed_mm_s", "z_speed_mm_s", "travel_z_mm", "timeout_s"])
    for key in ("xy_speed_mm_s", "z_speed_mm_s", "timeout_s"):
        number(motion[key], key, positive=True)
    travel_z = number(motion["travel_z_mm"], "travel_z_mm")
    if not lower[2] <= travel_z <= upper[2]:
        raise ScanError("travel_z_mm is outside machine bounds")
    grid = scan["grid"]
    strict_keys(grid, ["x_mm", "y_mm", "pitch_mm", "pattern"])
    spans = []
    for key in ("x_mm", "y_mm"):
        span = vector(grid[key], key, 2)
        if span[0] > span[1]:
            raise ScanError(f"{key} start must be <= end")
        spans.append(span)
    pitch = vector(grid["pitch_mm"], "pitch_mm", 2)
    if any(v <= 0 for v in pitch):
        raise ScanError("Both scan pitches must be positive")
    if grid["pattern"] not in ("raster", "serpentine"):
        raise ScanError("pattern must be raster or serpentine")
    focus = scan["focus"]
    strict_keys(focus, ["machine_z_mm", "slope_x", "slope_y", "reference_sample_mm", "calibration_id", "lens_id"])
    z0 = number(focus["machine_z_mm"], "focus machine_z_mm")
    slopes = [number(focus[k], k) for k in ("slope_x", "slope_y")]
    reference = vector(focus["reference_sample_mm"], "reference_sample_mm", 2)
    for key in ("calibration_id", "lens_id"):
        if not isinstance(focus[key], str) or not focus[key].strip():
            raise ScanError(f"focus.{key} must identify the calibration or optics")
    a = scan["acquisition"]
    strict_keys(a, ["integration_ms", "averages", "laser_nm", "settle_s", "laser_settle_s", "timeout_s", "laser_setting", "stop_on_saturation"], ["adc_max"])
    for key in ("integration_ms", "laser_nm", "timeout_s"):
        number(a[key], key, positive=True)
    for key in ("settle_s", "laser_settle_s"):
        number(a[key], key, minimum=0)
    integer(a["averages"], "averages")
    if not isinstance(a["stop_on_saturation"], bool):
        raise ScanError("stop_on_saturation must be boolean")
    if not isinstance(a["laser_setting"], str) or not a["laser_setting"].strip():
        raise ScanError("laser_setting must record the instrument setting and units")
    if a["timeout_s"] <= a["integration_ms"] * a["averages"] / 1000:
        raise ScanError("acquisition.timeout_s must exceed the total exposure time")
    if "adc_max" in a:
        number(a["adc_max"], "adc_max", positive=True)
    analysis = scan["analysis"]
    strict_keys(analysis, ["band_cm1", "baseline"])
    band = vector(analysis["band_cm1"], "band_cm1", 2)
    if band[0] >= band[1]:
        raise ScanError("Analysis band must have increasing endpoints")
    if analysis["baseline"] not in ("linear_endpoints", "none"):
        raise ScanError("baseline must be linear_endpoints or none")
    if machine["mode"] == "hardware":
        hw = machine.get("hardware", {})
        strict_keys(hw, ["moonraker_url", "bridge_command", "bridge_timeout_s", "geometry_calibration_id"], ["api_key_env"])
        if not isinstance(hw["moonraker_url"], str) or not hw["moonraker_url"].startswith(("http://", "https://")):
            raise ScanError("Set hardware.moonraker_url to the confirmed printer API")
        if not isinstance(hw["bridge_command"], list) or not hw["bridge_command"] or not all(isinstance(v, str) and v for v in hw["bridge_command"]):
            raise ScanError("bridge_command must be a nonempty argument array")
        if not isinstance(hw["geometry_calibration_id"], str) or not hw["geometry_calibration_id"].strip():
            raise ScanError("Record the verified geometry_calibration_id before hardware use")
        number(hw["bridge_timeout_s"], "bridge_timeout_s", positive=True)
    xs, ys = axis_values(*spans[0], pitch[0]), axis_values(*spans[1], pitch[1])
    if len(xs) * len(ys) > 1_000_000:
        raise ScanError("More than one million points; increase pitch or split the scan")
    points = []
    for row, y in enumerate(ys):
        columns = list(enumerate(xs))
        if grid["pattern"] == "serpentine" and row % 2:
            columns.reverse()
        for column, x in columns:
            xyz = [origin[0] + signs[0] * x, origin[1] + signs[1] * y,
                   z0 + slopes[0] * (x-reference[0]) + slopes[1] * (y-reference[1])]
            if any(not lo <= v <= hi for v, lo, hi in zip(xyz, lower, upper)):
                raise ScanError(f"Sample point ({x}, {y}) maps outside machine bounds: {xyz}")
            if xyz[2] > travel_z:
                raise ScanError("travel_z_mm must be at or above every configured focus height")
            points.append(Point(len(points), row, column, x, y, *xyz))
    return Plan(machine, scan, points)


def plan_from_files(machine_path, scan_path):
    return build_plan(load_json(machine_path), load_json(scan_path))


def validate_spectrum(value):
    if not isinstance(value, dict):
        raise ScanError("Spectrum response must be an object")
    required = ("wavelength_nm", "counts", "saturated", "captured_utc", "metadata")
    if any(k not in value for k in required):
        raise ScanError(f"Spectrum must include {required}")
    wave, counts = value["wavelength_nm"], value["counts"]
    if not isinstance(wave, list) or not isinstance(counts, list) or len(wave) != len(counts) or len(wave) < 3:
        raise ScanError("Spectrum needs >= 3 equally sized wavelength and counts entries")
    for w, c in zip(wave, counts):
        number(w, "wavelength_nm", positive=True)
        number(c, "counts")
    if any(wave[i] >= wave[i+1] for i in range(len(wave)-1)):
        raise ScanError("Spectrum wavelengths must be strictly increasing")
    if not isinstance(value["saturated"], bool) or not isinstance(value["metadata"], dict):
        raise ScanError("Spectrum saturated must be boolean and metadata an object")
    if not isinstance(value["captured_utc"], str) or not value["captured_utc"]:
        raise ScanError("Spectrum needs its capture timestamp")
    try:
        stamp = datetime.fromisoformat(value["captured_utc"].replace("Z", "+00:00"))
        if stamp.utcoffset() is None:
            raise ValueError("timezone missing")
    except ValueError as exc:
        raise ScanError("Spectrum captured_utc must be an ISO timestamp with a timezone") from exc
    return value


def point_dict(point):
    return asdict(point)
