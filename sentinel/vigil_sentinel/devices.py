"""Discovery of attached phones."""

from __future__ import annotations

from dataclasses import dataclass

from .shell import run, have, Adb


@dataclass
class Device:
    platform: str        # "android" | "ios"
    serial: str
    label: str = ""
    state: str = "ok"    # "ok" | "unauthorized" | "offline" | "locked"
    note: str = ""

    @property
    def usable(self) -> bool:
        return self.state == "ok"


def _android_devices() -> list:
    if not have("adb"):
        return []
    res = run(["adb", "devices", "-l"], timeout=20)
    if not res.ok:
        return []
    found = []
    for line in res.lines[1:]:            # first line is the "List of devices" banner
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        model = ""
        for token in parts[2:]:
            if token.startswith("model:"):
                model = token.split(":", 1)[1].replace("_", " ")
        if state == "device":
            dev = Device("android", serial, model or serial, "ok")
        elif state == "unauthorized":
            dev = Device("android", serial, model or serial, "unauthorized",
                         "Unlock the phone and tap 'Allow USB debugging'.")
        else:
            dev = Device("android", serial, model or serial, "offline", f"adb state: {state}")
        found.append(dev)
    return found


def _ios_devices() -> list:
    if not have("idevice_id"):
        return []
    res = run(["idevice_id", "-l"], timeout=20)
    if not res.ok:
        return []
    found = []
    for udid in res.lines:
        udid = udid.strip()
        if not udid:
            continue
        name = run(["idevicename", "-u", udid], timeout=15)
        label = name.out.strip() if name.ok else udid[:12]
        # ideviceinfo failing while the device is listed almost always means the
        # pairing/trust prompt has not been accepted yet.
        probe = run(["ideviceinfo", "-u", udid, "-k", "ProductVersion"], timeout=15)
        if probe.ok:
            found.append(Device("ios", udid, label, "ok"))
        else:
            found.append(Device("ios", udid, label, "unauthorized",
                                "Unlock the iPhone and tap 'Trust This Computer'."))
    return found


def discover() -> list:
    """All attached phones, Android first."""
    return _android_devices() + _ios_devices()


def missing_tooling() -> list:
    """Which backends are unavailable, so the CLI can tell the user how to fix it."""
    gaps = []
    if not have("adb"):
        gaps.append(("android", "adb",
                     "Install Android platform-tools: "
                     "brew install android-platform-tools  |  "
                     "apt install android-tools-adb"))
    if not have("idevice_id"):
        gaps.append(("ios", "libimobiledevice",
                     "Install libimobiledevice: "
                     "brew install libimobiledevice ideviceinstaller  |  "
                     "apt install libimobiledevice-utils ideviceinstaller"))
    return gaps
