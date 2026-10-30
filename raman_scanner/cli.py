import argparse
import csv
import json
from pathlib import Path
import sqlite3
import sys

from .analysis import analyze_run, export_spectra, processed
from .importer import import_csv
from .model import ScanError, plan_from_files, point_dict
from .pipeline import run
from .store import RunStore


def emit(value):
    print(json.dumps(value, indent=2, allow_nan=False))


def configuration_arguments(parser):
    parser.add_argument("--machine", required=True, help="Machine geometry and device connection profile JSON")
    parser.add_argument("--scan", required=True, help="Sample and acquisition profile JSON")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Configurable Raman mapping: plan, acquire, resume, process, and export.")
    commands = parser.add_subparsers(dest="command", required=True)
    plan_command = commands.add_parser("plan", help="Validate a scan and estimate duration; no hardware IO")
    configuration_arguments(plan_command)
    plan_command.add_argument("--csv", help="Write all sample and commanded coordinates as CSV")
    acquire = commands.add_parser("run", help="Execute a simulated or explicitly enabled hardware scan")
    configuration_arguments(acquire)
    acquire.add_argument("--output", required=True, help="New run directory, or existing directory with --resume")
    acquire.add_argument("--resume", action="store_true")
    acquire.add_argument("--hardware", action="store_true", help="Allow connections for a hardware machine profile")
    acquire.add_argument("--stop-after", type=int, help="Pause after this many newly acquired points")
    analyze = commands.add_parser("analyze", help="Reprocess a saved run without changing raw data")
    analyze.add_argument("run_directory")
    analyze.add_argument("--band", type=float, nargs=2, metavar=("LOW_CM1", "HIGH_CM1"))
    analyze.add_argument("--baseline", choices=["linear_endpoints", "none"])
    export = commands.add_parser("export", help="Export every spectrum as a streaming gzip CSV")
    export.add_argument("run_directory")
    export.add_argument("--output", required=True, help="Path ending in .csv.gz")
    status = commands.add_parser("status", help="Read scan state and progress without hardware IO")
    status.add_argument("run_directory")
    spectrum = commands.add_parser("spectrum", help="Export one recorded point's spectrum to CSV")
    spectrum.add_argument("run_directory")
    spectrum.add_argument("point_index", type=int)
    spectrum.add_argument("--output", required=True)
    imported = commands.add_parser("import-csv", help="Import raw spectra using an explicit point-to-file index; no hardware IO")
    configuration_arguments(imported)
    imported.add_argument("--index", required=True)
    imported.add_argument("--dark", required=True)
    imported.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in ("plan", "run", "import-csv"):
            plan = plan_from_files(args.machine, args.scan)
        if args.command == "plan":
            if args.csv:
                with Path(args.csv).open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=["point_index", "row", "column", "sample_x", "sample_y", "machine_x", "machine_y", "machine_z"])
                    writer.writeheader()
                    for point in plan.points:
                        values = point_dict(point)
                        values["point_index"] = values.pop("index")
                        writer.writerow(values)
            emit(plan.summary())
        elif args.command == "run":
            def progress(done, total):
                if done == total or done % max(1, total//20) == 0:
                    print(f"Recorded {done}/{total} positions", file=sys.stderr)
            result = run(plan, args.output, args.resume, args.hardware, args.stop_after, progress=progress)
            emit({**result, "report": str((Path(args.output)/"report.html").resolve()), "analysis": analyze_run(args.output)})
        elif args.command == "analyze":
            emit(analyze_run(args.run_directory, args.band, args.baseline))
        elif args.command == "export":
            if not args.output.endswith(".csv.gz"):
                raise ScanError("Full spectral export must end in .csv.gz")
            emit(export_spectra(args.run_directory, args.output))
        elif args.command == "status":
            store = RunStore(args.run_directory)
            try:
                configuration = store.get("configuration")
                emit({"state": store.get("state"), "saved_points": len(store.completed()),
                      "sample_id": configuration["scan"]["sample_id"], "mode": store.get("data_source", configuration["machine"]["mode"]),
                      "last_error": store.get("last_error"), "config_sha256": store.get("config_sha256")})
            finally:
                store.close()
        elif args.command == "import-csv":
            result = import_csv(plan, args.index, args.dark, args.output)
            emit({**result, "analysis": analyze_run(args.output)})
        elif args.command == "spectrum":
            store = RunStore(args.run_directory)
            try:
                row = next((r for r in store.rows() if r["point_index"] == args.point_index), None)
                if row is None:
                    raise ScanError("Requested point has no saved spectrum")
                dark = store.dark(row["dark_id"])
                shifts, corrected = processed(row, dark, store.get("configuration")["scan"]["acquisition"]["laser_nm"])
                with Path(args.output).open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(["wavelength_nm", "raman_shift_cm1", "raw_counts", "dark_counts", "dark_corrected_counts"])
                    writer.writerows(zip(row["spectrum"]["wavelength_nm"], shifts, row["spectrum"]["counts"], dark["counts"], corrected))
                emit({"point_index": args.point_index, "output": str(Path(args.output).resolve())})
            finally:
                store.close()
        return 0
    except KeyboardInterrupt:
        print("Interrupted. Check device state before resuming; completed spectra remain saved.", file=sys.stderr)
        return 130
    except (ScanError, OSError, ValueError, sqlite3.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
