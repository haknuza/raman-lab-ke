import copy
import csv
import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from raman_scanner.analysis import analyze_run, export_spectra, integrate_band, raman_shifts
from raman_scanner.devices import JsonLineBridge, MoonrakerStage, SimulatedRaman, SimulatedStage
from raman_scanner.importer import import_csv
from raman_scanner.model import ScanError, axis_values, build_plan, load_json, validate_spectrum
from raman_scanner.pipeline import run
from raman_scanner.store import RunStore, run_lock


ROOT = Path(__file__).resolve().parents[1]


def settings():
    return load_json(ROOT / "profiles/machine.simulation.json"), load_json(ROOT / "profiles/scan.demo.json")


class PlanningTests(unittest.TestCase):
    def test_full_bed_includes_all_edges(self):
        machine, _ = settings()
        plan = build_plan(machine, load_json(ROOT / "profiles/scan.full-bed.json"))
        self.assertEqual(len(plan.points), 2025)
        self.assertEqual((plan.points[-1].sample_x, plan.points[-1].sample_y), (220, 220))

    def test_fractional_pitch_and_short_last_interval(self):
        self.assertEqual(axis_values(0, 1, 0.3), [0, 0.3, 0.6, 0.9, 1])
        self.assertEqual(axis_values(0, 0.3, 0.1), [0, 0.1, 0.2, 0.3])

    def test_serpentine_preserves_physical_columns(self):
        machine, scan = settings()
        scan["grid"]["pattern"] = "serpentine"
        points = build_plan(machine, scan).points
        self.assertEqual([p.column for p in points[5:10]], [4, 3, 2, 1, 0])
        self.assertEqual([p.index for p in points], list(range(25)))

    def test_sign_origin_and_focus_plane(self):
        machine, scan = settings()
        machine["sample_origin_mm"] = [50, 60]
        machine["axis_sign"] = [-1, -1]
        scan["focus"]["slope_x"] = 0.1
        point = build_plan(machine, scan).points[-1]
        self.assertEqual((point.machine_x, point.machine_y, point.machine_z), (10, 20, 24))

    def test_rejects_offset_edge_out_of_bounds(self):
        machine, scan = settings()
        machine["sample_origin_mm"] = [210, 0]
        with self.assertRaisesRegex(ScanError, "outside machine bounds"):
            build_plan(machine, scan)

    def test_rejects_invalid_numeric_configs(self):
        for value in [0, -1, float("nan"), float("inf"), True]:
            with self.subTest(value=value):
                machine, scan = settings()
                scan["grid"]["pitch_mm"][0] = value
                with self.assertRaises((ScanError, ValueError)):
                    build_plan(machine, scan)

    def test_rejects_travel_below_focus(self):
        machine, scan = settings()
        machine["motion"]["travel_z_mm"] = 10
        with self.assertRaisesRegex(ScanError, "above every"):
            build_plan(machine, scan)

    def test_rejects_timeout_below_exposure(self):
        machine, scan = settings()
        scan["acquisition"]["averages"] = 10
        with self.assertRaisesRegex(ScanError, "exceed"):
            build_plan(machine, scan)

    def test_unknown_key_does_not_silently_change_behavior(self):
        machine, scan = settings()
        scan["grid"]["pith_mm"] = [1, 1]
        with self.assertRaisesRegex(ScanError, "unknown keys"):
            build_plan(machine, scan)


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name) / "run"
        self.plan = build_plan(*settings())

    def events(self):
        store = RunStore(self.output)
        try:
            return [(row["kind"], json.loads(row["detail"])) for row in store.db.execute("SELECT * FROM events ORDER BY sequence")]
        finally:
            store.close()

    def test_no_motion_during_emission(self):
        run(self.plan, self.output)
        enabled = False
        captured = 0
        for kind, detail in self.events():
            if kind == "laser_off":
                enabled = False
            elif kind == "laser_on":
                enabled = True
            elif kind in ("move_complete", "dark_acquired"):
                self.assertFalse(enabled)
            elif kind == "spectrum_acquired":
                self.assertTrue(enabled)
                captured += 1
            elif kind == "point_saved":
                self.assertFalse(enabled)
        self.assertEqual(captured, 25)

    def test_resume_keeps_original_points_and_dark_provenance(self):
        self.assertEqual(run(self.plan, self.output, stop_after=7)["state"], "paused")
        store = RunStore(self.output)
        first = list(store.rows())
        store.close()
        self.assertEqual(run(self.plan, self.output, resume=True)["state"], "complete")
        store = RunStore(self.output)
        rows = list(store.rows())
        self.assertEqual(len(rows), 25)
        self.assertEqual(rows[:7], first)
        self.assertEqual(len({row["dark_id"] for row in rows}), 2)
        store.close()

    def test_completed_resume_never_connects_devices(self):
        run(self.plan, self.output)
        def forbidden(*args):
            self.fail("Connected a device for a completed run")
        result = run(self.plan, self.output, resume=True, device_factory=forbidden)
        self.assertEqual(result["saved_points"], 25)

    def test_resume_rejects_changed_exposure(self):
        run(self.plan, self.output, stop_after=1)
        machine, scan = settings()
        scan["acquisition"]["integration_ms"] = 1000
        with self.assertRaisesRegex(ScanError, "changed"):
            run(build_plan(machine, scan), self.output, resume=True)

    def test_acquisition_failure_stops_before_next_move(self):
        class FailingRaman(SimulatedRaman):
            def acquire(self, point=None, dark=False):
                if not dark and point.index == 2:
                    raise ScanError("injected readout failure")
                return super().acquire(point, dark)
        def factory(plan, event):
            return SimulatedStage(plan.machine, event), FailingRaman(plan.scan["acquisition"], event)
        with self.assertRaisesRegex(ScanError, "injected"):
            run(self.plan, self.output, device_factory=factory)
        events = self.events()
        self.assertEqual([detail["point"] for kind, detail in events if kind == "move_complete"], [0, 1, 2])
        self.assertIn("motion_stop", [kind for kind, _ in events])
        store = RunStore(self.output)
        self.assertEqual(len(store.completed()), 2)
        self.assertEqual(store.get("state"), "failed")
        store.close()
        self.assertEqual(run(self.plan, self.output, resume=True)["saved_points"], 25)

    def test_saturation_saves_raw_and_stops(self):
        class SaturatedRaman(SimulatedRaman):
            def acquire(self, point=None, dark=False):
                result = super().acquire(point, dark)
                result["saturated"] = not dark
                return result
        def factory(plan, event):
            return SimulatedStage(plan.machine, event), SaturatedRaman(plan.scan["acquisition"], event)
        with self.assertRaisesRegex(ScanError, "Saturation"):
            run(self.plan, self.output, device_factory=factory)
        store = RunStore(self.output)
        rows = list(store.rows())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["flags"], ["saturated"])
        store.close()
        summary = analyze_run(self.output)
        self.assertEqual(summary["valid_points"], 0)

    def test_bad_analysis_band_rejected_before_motion(self):
        machine, scan = settings()
        scan["analysis"]["band_cm1"] = [4000, 5000]
        with self.assertRaisesRegex(ScanError, "outside"):
            run(build_plan(machine, scan), self.output)
        self.assertNotIn("move_complete", [kind for kind, _ in self.events()])

    def test_lock_prevents_concurrent_owners(self):
        with run_lock(self.output):
            with self.assertRaisesRegex(ScanError, "locked"):
                run(self.plan, self.output)

    def test_hardware_requires_explicit_flag_before_any_io(self):
        self.plan.machine["mode"] = "hardware"
        with self.assertRaisesRegex(ScanError, "--hardware"):
            run(self.plan, self.output)
        self.assertFalse(self.output.exists())

    def test_dark_axis_mismatch_rejected(self):
        class Mismatched(SimulatedRaman):
            def acquire(self, point=None, dark=False):
                result = super().acquire(point, dark)
                if not dark:
                    result["wavelength_nm"] = [x+0.01 for x in result["wavelength_nm"]]
                return result
        def factory(plan, event):
            return SimulatedStage(plan.machine, event), Mismatched(plan.scan["acquisition"], event)
        with self.assertRaisesRegex(ScanError, "differs"):
            run(self.plan, self.output, device_factory=factory)

    def test_laser_off_failure_preserves_uncommitted_capture(self):
        class OffFailure(SimulatedRaman):
            def off(self):
                if self.enabled:
                    raise ScanError("injected missing laser-off confirmation")
                super().off()
        def factory(plan, event):
            return SimulatedStage(plan.machine, event), OffFailure(plan.scan["acquisition"], event)
        with self.assertRaisesRegex(ScanError, "Laser-off confirmation failed"):
            run(self.plan, self.output, device_factory=factory)
        captures = list((self.output/"uncommitted-captures").glob("*.json"))
        self.assertEqual(len(captures), 1)
        capture = json.loads(captures[0].read_text())
        self.assertFalse(capture["committed"])
        self.assertEqual(capture["point"]["index"], 0)
        self.assertEqual(len(capture["spectrum"]["counts"]), 601)
        self.assertEqual(len([1 for kind, _ in self.events() if kind == "move_complete"]), 1)
        store = RunStore(self.output)
        self.assertEqual(len(store.completed()), 0)
        self.assertEqual(store.get("state"), "failed")
        store.close()

    def test_nan_firmware_position_is_rejected(self):
        machine, _ = settings()
        machine["hardware"] = {"moonraker_url": "http://localhost:7125"}
        stage = MoonrakerStage(machine, lambda *args: None)
        state = {"webhooks": {"state": "ready"}, "toolhead": {"homed_axes": "xyz", "position": [float('nan'),0,20,0]},
                 "gcode_move": {"speed_factor": 1, "gcode_position": [0,0,20,0]}, "motion_report": {"live_velocity": 0}}
        with self.assertRaisesRegex(ScanError, "finite"):
            stage.check_state(state)


class AnalysisTests(unittest.TestCase):
    def test_invalid_reanalysis_keeps_previous_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/"run"
            run(build_plan(*settings()), root, stop_after=1)
            analyze_run(root)
            files = [root/name for name in ("points.csv", "summary.json", "report.html")]
            before = [file.read_bytes() for file in files]
            with self.assertRaisesRegex(ScanError, "outside"):
                analyze_run(root, band=[4000, 5000])
            self.assertEqual([file.read_bytes() for file in files], before)
            self.assertEqual(list(root.glob(".analysis-*")), [])

    def test_shift_formula(self):
        self.assertAlmostEqual(raman_shifts([785], 785)[0], 0)
        self.assertAlmostEqual(raman_shifts([1/(1/785-1000/1e7)], 785)[0], 1000)

    def test_trapezoid_with_interpolated_boundaries(self):
        self.assertAlmostEqual(integrate_band([0, 1, 2], [0, 2, 0], [0.5, 1.5], "none"), 1.5)

    def test_endpoint_baseline_removes_linear_background(self):
        self.assertAlmostEqual(integrate_band([0, 1, 2], [3, 5, 7], [0.25, 1.75], "linear_endpoints"), 0)
        self.assertAlmostEqual(integrate_band([0, 1, 2], [3, 7, 7], [0, 2], "linear_endpoints"), 2)

    def test_nonmonotonic_axis_is_rejected(self):
        data = SimulatedRaman(settings()[1]["acquisition"], lambda *args: None).acquire(dark=True)
        data["wavelength_nm"][2] = data["wavelength_nm"][1]
        with self.assertRaisesRegex(ScanError, "increasing"):
            validate_spectrum(data)

    def test_export_and_import_preserve_raw(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = build_plan(*settings())
            run(plan, root/"acquired", stop_after=2)
            store = RunStore(root/"acquired")
            original = list(store.rows())
            dark = store.dark(original[0]["dark_id"])
            store.close()
            def write_spectrum(path, spectrum):
                with path.open("w", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(["wavelength_nm", "counts"])
                    writer.writerows(zip(spectrum["wavelength_nm"], spectrum["counts"]))
            write_spectrum(root/"dark.csv", dark)
            for row in original:
                write_spectrum(root/f"point-{row['point_index']}.csv", row["spectrum"])
            (root/"index.csv").write_text("point_index,path\n0,point-0.csv\n1,point-1.csv\n")
            import_csv(plan, root/"index.csv", root/"dark.csv", root/"imported")
            summary = analyze_run(root/"imported")
            self.assertEqual(summary["mode"], "imported")
            self.assertEqual(summary["saved_points"], 2)
            store = RunStore(root/"imported")
            self.assertEqual(next(store.rows())["spectrum"]["counts"], original[0]["spectrum"]["counts"])
            store.close()
            export_spectra(root/"imported", root/"spectra.csv.gz")
            with gzip.open(root/"spectra.csv.gz", "rt") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 1202)
            with self.assertRaisesRegex(ScanError, "Imported data"):
                run(plan, root/"imported", resume=True)
            store = RunStore(root/"imported")
            self.assertEqual(store.get("state"), "partial")
            store.close()


class AdapterTests(unittest.TestCase):
    def test_bridge_correlates_ids(self):
        source = "import sys,json\nfor line in sys.stdin:\n r=json.loads(line);print(json.dumps({'id':r['id'],'result':r['method']}),flush=True)"
        bridge = JsonLineBridge([sys.executable, "-u", "-c", source], 2)
        try:
            self.assertEqual(bridge.call("status"), "status")
            self.assertEqual(bridge.call("laser_off"), "laser_off")
        finally:
            bridge.close()

    def test_late_bridge_reply_cannot_be_reused(self):
        source = "import sys,time,json\nr=json.loads(sys.stdin.readline());time.sleep(2);print(json.dumps({'id':r['id'],'result':{}}),flush=True)"
        bridge = JsonLineBridge([sys.executable, "-u", "-c", source], 0.05)
        try:
            with self.assertRaisesRegex(ScanError, "Bridge failed"):
                bridge.call("acquire")
            with self.assertRaisesRegex(ScanError, "unusable"):
                bridge.call("laser_on")
        finally:
            bridge.close()

    def test_moonraker_uses_completed_motion_and_separate_emergency_endpoint(self):
        machine, scan = settings()
        machine["hardware"] = {"moonraker_url": "http://localhost:7125", "geometry_calibration_id": "fixture"}
        stage = MoonrakerStage(machine, lambda *args: None)
        point = build_plan(*settings()).points[0]
        state = {"webhooks": {"state": "ready"}, "toolhead": {"homed_axes": "xyz", "position": [0,0,20,0], "axis_minimum": [0,0,0], "axis_maximum": [220,220,240]},
                 "gcode_move": {"speed_factor": 1, "gcode_position": [0,0,20,0]}, "motion_report": {"live_velocity": 0},
                 "extruder": {"target": 0}, "heater_bed": {"target": 0}}
        stage.state = lambda: state
        calls = []
        def request(path, body=None, timeout=None):
            calls.append((path, body))
            return "ok"
        stage.request = request
        stage.move(point)
        script = calls[0][1]["script"]
        self.assertTrue(script.endswith("M400"))
        self.assertLess(script.index("G1 Z40"), script.index("G1 X0"))
        self.assertNotIn("G28", script)
        stage.emergency_stop()
        self.assertEqual(calls[-1][0], "/printer/emergency_stop")

    def test_moonraker_rejects_unhomed_machine(self):
        machine, _ = settings()
        machine["hardware"] = {"moonraker_url": "http://localhost:7125"}
        stage = MoonrakerStage(machine, lambda *args: None)
        with self.assertRaisesRegex(ScanError, "homed"):
            stage.check_state({"webhooks": {"state": "ready"}, "toolhead": {"homed_axes": "xy"}})


if __name__ == "__main__":
    unittest.main()
