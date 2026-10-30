"""Import explicitly indexed raw spectra without connecting to any hardware."""
import csv
from datetime import datetime, timezone
import hashlib
from pathlib import Path

from .model import ScanError, fingerprint, validate_spectrum
from .pipeline import check_pair
from .store import RunStore, run_lock


def read_spectrum_csv(path, laser_nm):
    path = Path(path)
    try:
        content = path.read_bytes()
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(text.splitlines())
        fields = reader.fieldnames or []
        axis = "wavelength_nm" if "wavelength_nm" in fields else "raman_shift_cm1"
        if axis not in fields or "counts" not in fields:
            raise ScanError(f"{path.name}: expected wavelength_nm,counts or raman_shift_cm1,counts headers")
        wavelengths, counts = [], []
        for row in reader:
            x, y = float(row[axis]), float(row["counts"])
            if axis == "raman_shift_cm1":
                denominator = 1/laser_nm - x/1e7
                if denominator <= 0:
                    raise ScanError("Raman shift cannot be converted to a positive wavelength")
                x = 1 / denominator
            wavelengths.append(x)
            counts.append(y)
        spectrum = {"wavelength_nm": wavelengths, "counts": counts, "saturated": False,
                    "captured_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                    "metadata": {"source": "csv_import", "source_name": path.name,
                                 "source_sha256": hashlib.sha256(content).hexdigest(),
                                 "timestamp_source": "file modification time; acquisition time unverified",
                                 "saturation_source": "unknown unless adc_max is configured"}}
        return validate_spectrum(spectrum)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise ScanError(f"Cannot read spectrum CSV {path}: {exc}") from exc


def import_csv(plan, index_path, dark_path, directory):
    index_path = Path(index_path)
    laser = plan.scan["acquisition"]["laser_nm"]
    dark = read_spectrum_csv(dark_path, laser)
    adc_max = plan.scan["acquisition"].get("adc_max")
    if adc_max is not None and max(dark["counts"]) >= adc_max:
        raise ScanError("Imported dark reference is saturated")
    try:
        reader = csv.DictReader(index_path.read_text(encoding="utf-8-sig").splitlines())
        if not {"point_index", "path"}.issubset(reader.fieldnames or []):
            raise ScanError("Index CSV needs point_index,path headers; indices refer to the exported scan plan")
        entries, seen = [], set()
        for row in reader:
            index = int(row["point_index"])
            if index < 0 or index >= len(plan.points) or index in seen:
                raise ScanError(f"Duplicate or out-of-range imported point index {index}")
            if not row["path"].strip():
                raise ScanError("Imported spectrum path must not be empty")
            seen.add(index)
            entries.append((index, index_path.parent / row["path"]))
        if not entries:
            raise ScanError("Index CSV contains no spectra")
    except (OSError, ValueError, KeyError) as exc:
        raise ScanError(f"Cannot read index CSV: {exc}") from exc
    with run_lock(directory):
        store = RunStore(directory, plan)
        try:
            store.set("data_source", "imported")
            store.set("state", "importing")
            store.set("import_note", "Coordinates and acquisition settings supplied by the operator; motion and exposure were not verified by this pipeline")
            store.set("import_index_sha256", fingerprint(index_path.read_text(encoding="utf-8-sig")))
            dark_id = store.add_dark(dark)
            for index, path in entries:
                spectrum = read_spectrum_csv(path, laser)
                check_pair(spectrum, dark)
                flags = []
                if adc_max is not None and max(spectrum["counts"]) >= adc_max:
                    flags.append("saturated")
                store.save_point(plan.points[index], spectrum, dark_id, flags)
            state = "complete" if len(entries) == len(plan.points) else "partial"
            store.set("state", state)
            store.event("csv_imported", {"points": len(entries), "coordinate_source": "user index and scan plan"})
            return {"state": state, "imported_points": len(entries)}
        except BaseException as exc:
            store.set("state", "failed")
            store.set("last_error", str(exc))
            raise
        finally:
            store.close()
