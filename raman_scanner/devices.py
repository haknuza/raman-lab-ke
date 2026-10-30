"""Simulated devices and explicit adapters for commissioned hardware."""
from datetime import datetime, timezone
import json
import math
import os
import queue
import random
import subprocess
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .model import ScanError, number, validate_spectrum


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class SimulatedStage:
    def __init__(self, machine, event):
        self.machine, self.event = machine, event

    def preflight(self):
        self.event("stage_ready", {"simulation": True})

    def move(self, point):
        # The same logical sequence as hardware; no waiting or physical motion.
        self.event("move_complete", {"point": point.index, "commanded_xyz_mm": [point.machine_x, point.machine_y, point.machine_z]})

    def emergency_stop(self):
        self.event("motion_stop", {"simulation": True})

    def close(self):
        pass


class SimulatedRaman:
    def __init__(self, acquisition, event):
        self.settings, self.event, self.enabled = acquisition, event, False

    def off(self):
        self.enabled = False
        self.event("laser_off", {"simulation": True})

    def preflight(self):
        self.off()
        return {"device_id": "SIMULATED-RAMAN-v1", "kind": "simulation"}

    def on(self):
        self.enabled = True
        self.event("laser_on", {"simulation": True})

    def acquire(self, point=None, dark=False):
        if dark == self.enabled:
            raise ScanError("Simulated laser state does not match requested acquisition")
        random_source = random.Random(-1 if dark else point.index)
        laser = self.settings["laser_nm"]
        shifts = [200 + i * 5 for i in range(601)]
        if 1/laser - shifts[-1]/1e7 <= 0:
            raise ScanError("Simulation excitation wavelength cannot cover its synthetic Raman range")
        wave = [1 / (1/laser - s/1e7) for s in shifts]
        if any(w <= 0 for w in wave):
            raise ScanError("Simulation wavelength is incompatible with its generated Stokes range")
        exposure = self.settings["integration_ms"] / 1000
        counts = []
        for shift in shifts:
            value = 100 + 2 * random_source.gauss(0, 1) / math.sqrt(self.settings["averages"])
            if not dark:
                strength = 250 + 400 * (1 + math.sin(point.sample_x / 23) * math.cos(point.sample_y / 29))
                value += exposure * (40 + 0.025 * shift + strength * math.exp(-0.5*((shift-1000)/18)**2)
                                     + 300 * math.exp(-0.5*((shift-1600)/25)**2))
            counts.append(value)
        self.event("dark_acquired" if dark else "spectrum_acquired", {"point": None if dark else point.index})
        return {"wavelength_nm": wave, "counts": counts, "saturated": False,
                "captured_utc": utc_now(), "metadata": {"simulation": True, "signal_units": "synthetic counts", "settings": self.settings}}

    def close(self):
        self.off()


class JsonLineBridge:
    """Persistent RPC process; the vendor driver implements the documented protocol.

    A background reader makes blocking pipe IO work on Windows and Linux. A
    timeout poisons the connection: a late reply can never become a fresh result.
    No command retries are made, particularly after an ambiguous laser command.
    """
    def __init__(self, command, timeout):
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            text=True, encoding="utf-8", bufsize=1)
        except OSError as exc:
            raise ScanError(f"Cannot launch instrument bridge: {exc}") from exc
        self.timeout, self.counter, self.broken = timeout, 0, False
        self.inbox = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.inbox.put(line)
        finally:
            self.inbox.put(None)

    def call(self, method, params=None, timeout=None):
        if self.broken:
            raise ScanError("Instrument bridge connection is unusable; laser state is unknown")
        self.counter += 1
        try:
            self.process.stdin.write(json.dumps({"id": self.counter, "method": method, "params": params or {}}, allow_nan=False) + "\n")
            self.process.stdin.flush()
            line = self.inbox.get(timeout=self.timeout if timeout is None else timeout)
            if line is None:
                raise ScanError("Instrument bridge exited unexpectedly")
            response = json.loads(line)
            if not isinstance(response, dict) or response.get("id") != self.counter:
                raise ScanError("Instrument bridge response ID mismatch")
            if response.get("error") is not None:
                raise ScanError(f"Instrument bridge {method}: {response['error']}")
            if "result" not in response:
                raise ScanError("Instrument bridge response has no result")
            return response["result"]
        except (queue.Empty, ValueError, OSError, ScanError) as exc:
            self.broken = True
            raise ScanError(f"Bridge failed during {method}; do not assume emission is off: {exc}") from exc

    def close(self):
        # Never silently hang forever on a driver after a failed request.
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        self.process.stdin.close()
        self.process.stdout.close()


class BridgeRaman:
    def __init__(self, hardware, acquisition, event):
        self.rpc = JsonLineBridge(hardware["bridge_command"], hardware["bridge_timeout_s"])
        self.settings, self.event = acquisition, event

    def status(self):
        result = self.rpc.call("status")
        if not isinstance(result, dict) or result.get("interlock_closed") is not True:
            raise ScanError("Instrument reports an open or unverified interlock")
        if not isinstance(result.get("laser_enabled"), bool):
            raise ScanError("Instrument must report its emission enable state")
        return result

    def off(self):
        result = self.rpc.call("laser_off")
        if not isinstance(result, dict) or result.get("laser_enabled") is not False:
            raise ScanError("Bridge did not confirm laser emission disabled")
        self.event("laser_off", {"confirmed_by": "instrument_bridge"})

    def preflight(self):
        self.off()
        identity = self.rpc.call("identify")
        if not isinstance(identity, dict) or identity.get("kind") != "hardware" or not identity.get("device_id"):
            raise ScanError("Hardware bridge must identify a real instrument and device_id")
        configured = self.rpc.call("configure", self.settings)
        # Driver must explicitly echo applied acquisition settings. This is not a
        # measurement of optical output power; laser_setting is a recorded label.
        for key in ("integration_ms", "averages", "laser_nm", "laser_setting"):
            if not isinstance(configured, dict) or configured.get(key) != self.settings[key]:
                raise ScanError(f"Bridge did not confirm applied {key}")
        self.off()
        if self.status()["laser_enabled"]:
            raise ScanError("Laser remained enabled after instrument preflight")
        return identity

    def on(self):
        if self.status()["laser_enabled"]:
            raise ScanError("Laser was already enabled before a new point")
        result = self.rpc.call("laser_on")
        if not isinstance(result, dict) or result.get("laser_enabled") is not True:
            raise ScanError("Bridge did not confirm laser enable")
        self.event("laser_on", {"confirmed_by": "instrument_bridge"})

    def acquire(self, point=None, dark=False):
        result = self.rpc.call("acquire", {"dark": dark, "point_index": None if point is None else point.index},
                               timeout=self.settings["timeout_s"])
        validate_spectrum(result)
        self.event("dark_acquired" if dark else "spectrum_acquired", {"point": None if point is None else point.index})
        return result

    def close(self):
        try:
            if not self.rpc.broken:
                self.rpc.call("shutdown")
        finally:
            self.rpc.close()


class MoonrakerStage:
    """Blocking HTTP adapter. Never homes, heats, extrudes, or starts print jobs."""
    def __init__(self, machine, event):
        self.machine, self.event = machine, event
        hw = machine["hardware"]
        self.url = hw["moonraker_url"].rstrip("/")
        self.timeout = machine["motion"]["timeout_s"]
        self.headers = {"Content-Type": "application/json"}
        if hw.get("api_key_env"):
            key = os.environ.get(hw["api_key_env"])
            if not key:
                raise ScanError(f"Set API key environment variable {hw['api_key_env']}")
            self.headers["X-Api-Key"] = key

    def request(self, path, body=None, timeout=None):
        request = Request(self.url + path, headers=self.headers,
                          data=None if body is None else json.dumps(body).encode())
        try:
            with urlopen(request, timeout=self.timeout if timeout is None else timeout) as response:
                value = json.load(response)
            if "error" in value or "result" not in value:
                raise ScanError("Printer API returned an error or malformed response")
            return value["result"]
        except (URLError, HTTPError, OSError, ValueError) as exc:
            raise ScanError(f"Printer API failed at {path}: {exc}") from exc

    def state(self):
        objects = {"webhooks": None, "toolhead": None, "gcode_move": None,
                   "idle_timeout": None, "print_stats": None, "heater_bed": None,
                   "extruder": None, "bed_mesh": None, "motion_report": None}
        return self.request("/printer/objects/query", {"objects": objects})["status"]

    def check_state(self, state):
        if state.get("webhooks", {}).get("state") != "ready":
            raise ScanError("Klipper is not ready")
        tool = state.get("toolhead", {})
        if not set("xyz").issubset(tool.get("homed_axes", "")):
            raise ScanError("XYZ must already be homed using the verified mounting procedure")
        if state.get("print_stats", {}).get("state") in ("printing", "paused"):
            raise ScanError("An active or paused print job owns the printer")
        velocity = state.get("motion_report", {}).get("live_velocity")
        if velocity is None or abs(number(velocity, "live_velocity")) > 0.001:
            raise ScanError("Printer must report zero live velocity before a scan move")
        for heater in ("extruder", "heater_bed"):
            if state.get(heater, {}).get("target", 0) != 0:
                raise ScanError(f"{heater} heater target must already be zero")
        if state.get("bed_mesh", {}).get("profile_name") or state.get("bed_mesh", {}).get("mesh_matrix"):
            raise ScanError("Active bed mesh changes the Z path; clear it during commissioning")
        move = state.get("gcode_move", {})
        if move.get("speed_factor") != 1:
            raise ScanError("Printer speed override must be 100%")
        xyz = move.get("gcode_position", [])[:3]
        if len(xyz) != 3:
            raise ScanError("Printer did not report G-code XYZ position")
        for v, lo, hi in zip(xyz, self.machine["bounds_mm"]["min"], self.machine["bounds_mm"]["max"]):
            number(v, "printer position")
            if not lo <= v <= hi:
                raise ScanError("Current G-code position is outside the calibrated workspace")
        # G-code limits may be offset from native kinematic limits. Require a
        # zero translation for this first adapter so bounds are unambiguous.
        native = tool.get("position", [])[:3]
        for value in native:
            number(value, "native position")
        if len(native) != 3 or any(abs(a-b) > 0.02 for a, b in zip(xyz, native)):
            raise ScanError("Nonzero G-code offsets are unsupported by this motion adapter")
        if not tool.get("axis_minimum") or not tool.get("axis_maximum"):
            raise ScanError("Printer must report native axis limits")
        for lo, hi, native_lo, native_hi in zip(self.machine["bounds_mm"]["min"], self.machine["bounds_mm"]["max"], tool["axis_minimum"], tool["axis_maximum"]):
            number(native_lo, "native axis minimum")
            number(native_hi, "native axis maximum")
            if lo < native_lo or hi > native_hi:
                raise ScanError("Configured workspace exceeds printer native limits")

    def preflight(self):
        self.check_state(self.state())
        self.event("stage_ready", {"adapter": "moonraker", "calibration_id": self.machine["hardware"]["geometry_calibration_id"]})

    def move(self, point):
        self.check_state(self.state())
        m = self.machine["motion"]
        # Lift vertically first, travel XY above the commissioned sample/fixture
        # envelope, then descend. M400 makes the request wait for all motion.
        script = "\n".join(["G90", f"G1 Z{m['travel_z_mm']:.6f} F{m['z_speed_mm_s']*60:.3f}",
                            f"G1 X{point.machine_x:.6f} Y{point.machine_y:.6f} F{m['xy_speed_mm_s']*60:.3f}",
                            f"G1 Z{point.machine_z:.6f} F{m['z_speed_mm_s']*60:.3f}", "M400"])
        if self.request("/printer/gcode/script", {"script": script}) != "ok":
            raise ScanError("Printer did not confirm motion script completion")
        state = self.state()
        # After M400, some firmware keeps idle_timeout='Printing' briefly. The
        # final position and homing state are the relevant completion checks.
        if not set("xyz").issubset(state.get("toolhead", {}).get("homed_axes", "")):
            raise ScanError("Printer lost homing state during motion")
        actual = state.get("gcode_move", {}).get("gcode_position", [])[:3]
        for value in actual:
            number(value, "final commanded position")
        target = [point.machine_x, point.machine_y, point.machine_z]
        if len(actual) != 3 or any(abs(a-b) > 0.02 for a, b in zip(actual, target)):
            raise ScanError("Reported commanded position does not match scan target")
        self.event("move_complete", {"point": point.index, "commanded_xyz_mm": target, "position_source": "firmware; not independent metrology"})

    def emergency_stop(self):
        self.request("/printer/emergency_stop", {}, timeout=5)
        self.event("motion_stop", {"adapter": "moonraker"})

    def close(self):
        pass


def make_devices(plan, event):
    if plan.machine["mode"] == "simulation":
        return SimulatedStage(plan.machine, event), SimulatedRaman(plan.scan["acquisition"], event)
    stage = MoonrakerStage(plan.machine, event)
    instrument = BridgeRaman(plan.machine["hardware"], plan.scan["acquisition"], event)
    return stage, instrument
