"""`setup audio-device [--dry-run]` — create the multi-output device the recorder switches to.

A macOS "Multi-Output Device" is a *stacked* aggregate device: audio is sent
to every subdevice at once. Speakers are the master clock; BlackHole gets
drift compensation because a virtual device and the built-in output run on
different clocks and would desynchronise a long transcript otherwise.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys

from ghostbrain.doctor.checks_recorder import BLACKHOLE_DEVICE

AGGREGATE_UID = "tech.codeship.ghostbrain.multioutput"


class DeviceNotFound(RuntimeError):
    pass


def _platform() -> str:
    return sys.platform


def _configured_name() -> str:
    from ghostbrain.recorder.daemon import DaemonConfig

    return DaemonConfig.load().audio_device


def _existing_output_names() -> list[str]:
    from ghostbrain.recorder import audio_switcher

    try:
        return audio_switcher.list_outputs()
    except audio_switcher.AudioSwitcherError:
        return []


def build_description(name: str, *, speakers_uid: str, blackhole_uid: str) -> dict:
    return {
        "name": name,
        "uid": AGGREGATE_UID,
        "stacked": 1,
        "private": 0,
        "master": speakers_uid,
        "subdevices": [
            {"uid": speakers_uid},
            {"uid": blackhole_uid, "drift": 1},
        ],
    }


def _prop(obj_id: int, selector: int, scope: int) -> bytes:
    """Read a CoreAudio property's raw bytes via AudioObjectGetPropertyData.

    The PyObjC binding does not know the property's real C type (it's a
    generic ``void*``), so it hands back raw bytes and we decode per
    property below. Two gotchas found by testing against the installed
    pyobjc-framework-CoreAudio binding (11.x):

    - the zero-length "qualifier data" input arg must be ``b""``, not
      ``None`` — ``None`` makes the bridge try to iterate it and raise
      ``TypeError: converting to a C array``.
    - the output arg must be passed as ``None`` (let the bridge allocate
      and hand back ``bytes``); a pre-sized ``bytearray``/``NSMutableData``
      hits the same "converting to a C array" error.
    """
    import CoreAudio as CA

    addr = CA.AudioObjectPropertyAddress(selector, scope, CA.kAudioObjectPropertyElementMain)
    err, size = CA.AudioObjectGetPropertyDataSize(obj_id, addr, 0, b"", None)
    if err != 0:
        raise DeviceNotFound(f"CoreAudio property {selector} size query failed: OSStatus {err}")
    if size == 0:
        return b""
    err, _actual_size, data = CA.AudioObjectGetPropertyData(obj_id, addr, 0, b"", size, None)
    if err != 0:
        raise DeviceNotFound(f"CoreAudio property {selector} failed: OSStatus {err}")
    return data


def _cfstring_prop(obj_id: int, selector: int, scope: int) -> str | None:
    """Decode a CFStringRef property (e.g. device name/UID).

    ``_prop`` returns the raw pointer bytes (a CFStringRef is a pointer, not
    inline data), so we unpack the 8-byte pointer and hand it to
    ``objc.objc_object(c_void_p=...)`` to bridge it back into a real
    (bridged) Python string.
    """
    import objc

    data = _prop(obj_id, selector, scope)
    if not data:
        return None
    ptr = struct.unpack("<Q", data)[0]
    return str(objc.objc_object(c_void_p=ptr))


def _uint32_prop(obj_id: int, selector: int, scope: int) -> int | None:
    data = _prop(obj_id, selector, scope)
    if len(data) < 4:
        return None
    return struct.unpack("<I", data[:4])[0]


def _find_uids() -> tuple[str, str]:
    """Return (built-in speakers UID, BlackHole UID) via CoreAudio; raise DeviceNotFound."""
    import CoreAudio as CA

    scope_global = CA.kAudioObjectPropertyScopeGlobal
    scope_output = CA.kAudioObjectPropertyScopeOutput

    try:
        raw_ids = _prop(CA.kAudioObjectSystemObject, CA.kAudioHardwarePropertyDevices, scope_global)
        device_ids = struct.unpack(f"<{len(raw_ids) // 4}I", raw_ids) if raw_ids else ()

        speakers = blackhole = None
        for dev in device_ids:
            name = _cfstring_prop(dev, CA.kAudioObjectPropertyName, scope_global)
            uid = _cfstring_prop(dev, CA.kAudioDevicePropertyDeviceUID, scope_global)
            if name == BLACKHOLE_DEVICE:
                blackhole = uid
            elif speakers is None:
                # HDMI/DisplayPort outputs have their own (non-builtin) transport
                # types, so this check naturally excludes them too.
                transport = _uint32_prop(dev, CA.kAudioDevicePropertyTransportType, scope_global)
                if transport == CA.kAudioDeviceTransportTypeBuiltIn:
                    # built-in output (not the built-in mic): must have output streams
                    streams = _prop(dev, CA.kAudioDevicePropertyStreams, scope_output)
                    if streams:
                        speakers = uid
    except DeviceNotFound:
        raise
    except Exception as e:
        # A shape/type mismatch in the CoreAudio binding (e.g. a decode helper
        # getting back something other than what we expect) must not escape as
        # a raw traceback — main() turns any RuntimeError into a one-line failure.
        raise RuntimeError(f"CoreAudio enumeration failed: {e!r}") from e

    if blackhole is None:
        raise DeviceNotFound(BLACKHOLE_DEVICE)
    if speakers is None:
        raise DeviceNotFound("built-in output")
    return speakers, blackhole


def _create(description: dict) -> int:
    """Create the aggregate device; return the OSStatus (0 = success)."""
    import CoreAudio as CA

    try:
        err, _device_id = CA.AudioHardwareCreateAggregateDevice(description, None)
    except Exception as e:
        # Guard against the binding returning an unexpected shape (e.g. not a
        # 2-tuple) — surface it as a one-line failure instead of a traceback.
        raise RuntimeError(f"AudioHardwareCreateAggregateDevice returned an unexpected result: {e!r}") from e
    return int(err)


_MANUAL_RECIPE = (
    "Create it by hand: open Audio MIDI Setup → '+' → Create Multi-Output Device, tick your speakers "
    "and 'BlackHole 2ch', enable Drift Correction on BlackHole, and rename the device to match."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ghostbrain-api setup audio-device")
    parser.add_argument("--dry-run", action="store_true", help="print the device description, create nothing")
    args = parser.parse_args([] if argv is None else argv)
    if _platform() != "darwin":
        print("setup audio-device is macOS only", file=sys.stderr)
        return 1
    name = _configured_name()
    if name in _existing_output_names():
        print(f"output device '{name}' already exists")
        return 0
    try:
        speakers_uid, blackhole_uid = _find_uids()
    except DeviceNotFound as e:
        if str(e) == BLACKHOLE_DEVICE:
            print(f"{BLACKHOLE_DEVICE} is not installed; run: setup deps --only blackhole (in Terminal)", file=sys.stderr)
        else:
            print(f"could not find {e}; {_MANUAL_RECIPE}", file=sys.stderr)
        return 1
    except ImportError:
        print(f"CoreAudio bindings unavailable in this build; {_MANUAL_RECIPE}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 — covers OSError/RuntimeError from CoreAudio and
        # any unexpected shape (e.g. TypeError unpacking a binding result that didn't match
        # what we expected) — never let a raw traceback reach the user here.
        print(f"audio-device failed: {e}", file=sys.stderr)
        return 1
    desc = build_description(name, speakers_uid=speakers_uid, blackhole_uid=blackhole_uid)
    if args.dry_run:
        print(json.dumps(desc, indent=2))
        return 0
    try:
        status = _create(desc)
    except Exception as e:  # noqa: BLE001 — see above
        print(f"audio-device failed: {e}", file=sys.stderr)
        return 1
    if status != 0:
        print(f"AudioHardwareCreateAggregateDevice failed: OSStatus {status}. {_MANUAL_RECIPE}", file=sys.stderr)
        return 1
    print(f"created multi-output device '{name}' (speakers + {BLACKHOLE_DEVICE}, drift-corrected)")
    return 0
