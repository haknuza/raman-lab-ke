# Instrument bridge protocol

The pipeline can launch a separate driver process using a JSON argument array in `hardware.bridge_command`. This lets the driver use the vendor's supported Python environment on Windows or Linux. Commands run directly without a shell. Driver messages are newline-delimited JSON on stdin/stdout; send diagnostics to stderr only.

**An Avantes driver is not included.** Implement this protocol around the actual supported SDK and laser controller. The PDF set identifies multiple hardware generations, and the laser USB/control API has not been established. Do not infer laser commands from spectrometer acquisition calls, connector names, printer PWM, or a front-panel button.

## Requests and responses

```json
{"id":1,"method":"laser_off","params":{}}
```

Success:

```json
{"id":1,"result":{"laser_enabled":false}}
```

Failure:

```json
{"id":1,"error":{"message":"Controller did not confirm laser off"}}
```

Return exactly one response with the request's integer ID. The caller has only one outstanding request. It does not retry a failed or timed-out command, and it invalidates the connection after any RPC failure. A late readout must never be attributed to a later point.

| Method | Required behavior and result |
| --- | --- |
| `identify` | Return `{"kind":"hardware","device_id":"stable spectrometer and controller identifier",...}`. Keep this identity stable across sessions; use serial numbers where possible. Include relevant model/SDK/firmware identifiers. |
| `configure` | Apply the requested integration time, averaging and excitation settings with emission disabled. Confirm and echo `integration_ms`, `averages`, `laser_nm`, `laser_setting`. Record wavelength calibration and applied settings in spectrum metadata. Do not report requested settings as applied when the SDK rejects or clamps them. Laser setting units are specific to the real controller. |
| `laser_off` | Inhibit emission using the supported instrument interface, verify the result, then return `{"laser_enabled":false}`. Returning a desired software state is insufficient. This method must remain usable during driver cleanup. |
| `status` | Return boolean `interlock_closed` and `laser_enabled` from the actual instrument state. An unverified state is an error. Do not bypass an open interlock. |
| `laser_on` | Check hardware readiness and interlocks, enable emission through the supported interface, verify the result, return `{"laser_enabled":true}`. |
| `acquire` | Start a fresh acquisition after receiving this request, wait for completion and read raw detector counts. The parameters include `dark` and `point_index` (`null` for a dark). Check emission state matches the requested measurement. Do not return a cached or partially completed scan. Return the spectrum object below. |
| `shutdown` | Disable emission, stop acquisition, release the SDK/device handles, respond successfully, then exit. Also clean up on stdin EOF and supported termination signals. |

The main application confirms off, identifies/configures the instrument, checks status, acquires a dark, and then performs one fresh exposure per completed move. Each exposure has its own on/off sequence. If the actual laser requires a stabilization strategy incompatible with that sequence, resolve it with a supported shutter/gating implementation and verify optical stability before live scanning; do not silently reinterpret the protocol.

## Spectrum object

```json
{
  "wavelength_nm": [800.0, 800.5, 801.0],
  "counts": [120.0, 135.0, 128.0],
  "saturated": false,
  "captured_utc": "2026-10-30T13:00:00+00:00",
  "metadata": {
    "device_timestamp": "vendor timestamp if available",
    "acquisition_id": "unique fresh acquisition identifier",
    "calibration_id": "installed wavelength calibration identifier",
    "settings": {"integration_ms": 3000, "averages": 1}
  }
}
```

Arrays must have equal lengths of at least three, finite values, positive strictly increasing wavelengths, and match the dark's wavelength axis. Timestamp must include a timezone. Counts must be raw detector counts with software dark/baseline/smoothing corrections disabled, or fully documented detector-native behavior in metadata. `saturated` must reflect vendor saturation detection; configure `adc_max` only when its meaning for the detector is known. Do not invent a universal 16-bit full-scale threshold.

The official [Avantes Python example](https://avantesusa.com/wp-content/uploads/2022/10/Python-Updates_October-2022.pdf) shows the general acquisition sequence: initialize, enumerate, activate, retrieve pixel/wavelength configuration, prepare measurement, start, poll readiness, read scope data, deactivate and close. Use the actual SDK's compatible wrapper. The example itself illustrates different nested/flattened configuration field spellings, so copying an ABI layout from another device/library version is not a supported integration.

## Failure handling

The bridge and instrument need an independent fail-off response to host disconnects, lost communication and crashes. A blocked `acquire` request, a frozen host, or a killed process can prevent the main application from executing `laser_off`. Process termination does not prove optical emission stopped. A manufacturer-supported interlock/watchdog must handle that case.

The application also requests the printer's dedicated emergency-stop endpoint after a scan fault; it never assumes that endpoint stops the independent Raman laser. Do not use the laser's safety interlock as a high-frequency modulation input unless the manufacturer explicitly supports that use.

Driver integration must be tested on the stationary instrument first: confirm settings and dark behavior, fresh acquisition semantics, timeout behavior, saturation reporting, emission gating/stabilization, interlock behavior, and verified shutdown. Only then integrate motion.
