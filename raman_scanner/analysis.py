"""Non-destructive dark subtraction, Raman shifts, band integration, and export."""
import bisect
import csv
import gzip
import json
import math
from pathlib import Path
import uuid

from .model import ScanError, number
from .pipeline import check_pair
from .store import RunStore


def raman_shifts(wavelength_nm, laser_nm):
    number(laser_nm, "laser_nm", positive=True)
    return [1e7 * (1 / laser_nm - 1 / wavelength) for wavelength in wavelength_nm]


def interpolate(xs, ys, x):
    right = bisect.bisect_left(xs, x)
    if right < len(xs) and xs[right] == x:
        return ys[right]
    if right == 0 or right == len(xs):
        raise ScanError("Analysis band extends outside measured spectrum")
    left = right - 1
    ratio = (x-xs[left]) / (xs[right]-xs[left])
    return ys[left] + ratio * (ys[right]-ys[left])


def integrate_band(shifts, counts, band, baseline):
    lo, hi = band
    if lo < shifts[0] or hi > shifts[-1]:
        raise ScanError("Analysis band extends outside measured Raman range")
    xs = [lo] + [x for x in shifts if lo < x < hi] + [hi]
    ys = [interpolate(shifts, counts, x) for x in xs]
    if baseline == "linear_endpoints":
        start, end = ys[0], ys[-1]
        ys = [y - (start + (end-start)*(x-lo)/(hi-lo)) for x, y in zip(xs, ys)]
    elif baseline != "none":
        raise ScanError("Unknown baseline method")
    return sum((b-a)*(u+v)/2 for a, b, u, v in zip(xs, xs[1:], ys, ys[1:]))


def processed(row, dark, laser_nm):
    spectrum = row["spectrum"]
    check_pair(spectrum, dark)
    corrected = [value-reference for value, reference in zip(spectrum["counts"], dark["counts"])]
    return raman_shifts(spectrum["wavelength_nm"], laser_nm), corrected


POINT_FIELDS = ["point_index", "row", "column", "sample_x_mm", "sample_y_mm", "commanded_machine_x_mm",
                "commanded_machine_y_mm", "commanded_machine_z_mm", "captured_utc", "dark_id", "band_area", "flags"]


def analyze_run(directory, band=None, baseline=None):
    directory = Path(directory)
    store = RunStore(directory)
    names = ("points.csv", "summary.json", "report.html")
    token = uuid.uuid4().hex
    staged = {name: directory/f".analysis-{token}-{name}" for name in names}
    try:
        configuration = store.get("configuration")
        scan = configuration["scan"]
        band = scan["analysis"]["band_cm1"] if band is None else band
        baseline = scan["analysis"]["baseline"] if baseline is None else baseline
        if len(band) != 2 or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in band) or band[0] >= band[1]:
            raise ScanError("Analysis band needs two increasing finite values")
        count = len(store.completed())
        preview_stride = max(1, math.ceil(count / 256))
        points, previews, darks = [], {}, {}
        with staged["points.csv"].open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=POINT_FIELDS)
            writer.writeheader()
            for ordinal, row in enumerate(store.rows()):
                dark_id = row["dark_id"]
                if dark_id not in darks:
                    darks[dark_id] = store.dark(dark_id)
                shifts, corrected = processed(row, darks[dark_id], scan["acquisition"]["laser_nm"])
                area = integrate_band(shifts, corrected, band, baseline)
                p = row["point"]
                values = [row["point_index"], p["row"], p["column"], p["sample_x"], p["sample_y"],
                          p["machine_x"], p["machine_y"], p["machine_z"], row["spectrum"]["captured_utc"],
                          dark_id, None if row["flags"] else area, ";".join(row["flags"])]
                writer.writerow(dict(zip(POINT_FIELDS, values)))
                points.append({"index": p["index"], "x": p["sample_x"], "y": p["sample_y"],
                               "area": None if row["flags"] else area, "flags": row["flags"]})
                if ordinal % preview_stride == 0:
                    previews[str(p["index"])] = {"shift": shifts, "raw": row["spectrum"]["counts"], "corrected": corrected}
        summary = {"schema_version": 1, "mode": store.get("data_source", configuration["machine"]["mode"]), "state": store.get("state"),
                   "sample_id": scan["sample_id"], "saved_points": count,
                   "valid_points": sum(not p["flags"] for p in points),
                   "analysis": {"band_cm1": band, "baseline": baseline, "units": "counts * cm^-1", "normalized": False},
                   "preview_spectra": len(previews), "config_sha256": store.get("config_sha256"),
                   "provenance_note": store.get("import_note")}
        staged["summary.json"].write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        from .report import write_report
        write_report(staged["report.html"], {"summary": summary, "grid": scan["grid"], "points": points, "spectra": previews})
        for name in names:
            staged[name].replace(directory/name)
        return summary
    finally:
        store.close()
        for path in staged.values():
            if path.exists():
                path.unlink()


def export_spectra(directory, output):
    """Stream all detector pixels into a gzip CSV; bounded memory for large maps."""
    store = RunStore(directory)
    try:
        acquisition = store.get("configuration")["scan"]["acquisition"]
        darks = {}
        with gzip.open(output, "wt", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["point_index", "sample_x_mm", "sample_y_mm", "wavelength_nm", "raman_shift_cm1", "raw_counts", "dark_counts", "dark_corrected_counts", "dark_id", "flags"])
            for row in store.rows():
                if row["dark_id"] not in darks:
                    darks[row["dark_id"]] = store.dark(row["dark_id"])
                dark = darks[row["dark_id"]]
                shifts, corrected = processed(row, dark, acquisition["laser_nm"])
                for wavelength, shift, raw, reference, value in zip(row["spectrum"]["wavelength_nm"], shifts, row["spectrum"]["counts"], dark["counts"], corrected):
                    writer.writerow([row["point_index"], row["point"]["sample_x"], row["point"]["sample_y"], wavelength, shift, raw, reference, value, row["dark_id"], ";".join(row["flags"])])
        return {"output": str(Path(output).resolve()), "points": len(store.completed())}
    finally:
        store.close()
