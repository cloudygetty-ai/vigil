"""Android probes, driven over adb. No root required.

Every check here reads state Android exposes to the `shell` user. Where a read
needs root (user CA store, /data inspection) the probe degrades to a reported
gap rather than guessing.
"""

from __future__ import annotations

import posixpath
import time

from ..findings import Finding
from ..shell import Adb


# Installers we treat as legitimate app sources.
TRUSTED_INSTALLERS = {
    "com.android.vending",                  # Google Play
    "com.sec.android.app.samsungapps",      # Galaxy Store
    "com.amazon.venezia",                   # Amazon Appstore
    "com.huawei.appmarket",
    "com.xiaomi.market",
    "com.oppo.market",
    "com.heytap.market",
    "org.fdroid.fdroid",                    # F-Droid: user-chosen, not covert
}

# An app installed by *these* got there because someone tapped an APK file or
# ran `adb install` - exactly the paths an attacker with 60 seconds of physical
# or WiFi-debugging access would use.
SIDELOAD_INSTALLERS = {
    "com.android.packageinstaller",
    "com.google.android.packageinstaller",
    "com.android.shell",                    # adb install
    "null",
    "",
}

# Directories where transferred files land. "delivery" dirs are high-signal:
# nothing writes there except a transfer or a deliberate download.
DELIVERY_DIRS = [
    "/sdcard/Download",
    "/sdcard/Bluetooth",
    "/sdcard/bluetooth",
]

# Scanned for the baseline diff, but too noisy to flag on their own.
MEDIA_DIRS = [
    "/sdcard/Pictures",
    "/sdcard/Documents",
    "/sdcard/Movies",
    "/sdcard/DCIM",
]

# Extensions that can execute or reconfigure the device.
EXECUTABLE_EXT = {
    ".apk", ".apkm", ".xapk", ".apks",       # installable packages
    ".dex", ".jar", ".so", ".elf", ".bin",   # code
    ".sh", ".bash",                          # scripts
    ".mobileconfig",                         # iOS profile, but AirDropped cross-platform
}

# Runtime permissions that matter for surveillance.
SENSITIVE_PERMS = [
    "android.permission.RECORD_AUDIO",
    "android.permission.CAMERA",
    "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_BACKGROUND_LOCATION",
    "android.permission.READ_SMS",
    "android.permission.RECEIVE_SMS",
    "android.permission.READ_CONTACTS",
    "android.permission.READ_CALL_LOG",
    "android.permission.SYSTEM_ALERT_WINDOW",
    "android.permission.PACKAGE_USAGE_STATS",
    "android.permission.QUERY_ALL_PACKAGES",
]

MAX_DEEP_INSPECT = 25   # cap per-package dumpsys calls; each costs ~0.3s


def _short(pkg: str) -> str:
    return pkg.rsplit(".", 1)[-1]


# --------------------------------------------------------------------------
# Package inventory
# --------------------------------------------------------------------------

def _list_packages(adb: Adb) -> dict:
    """Third-party packages mapped to their installer."""
    res = adb.shell("pm list packages -3 -i", timeout=40)
    if not res.ok:
        return {}
    packages = {}
    for line in res.lines:
        if not line.startswith("package:"):
            continue
        body = line[len("package:"):]
        installer = ""
        if "installer=" in body:
            body, installer = body.split("installer=", 1)
            installer = installer.strip()
        packages[body.strip()] = installer.strip()
    return packages


def _package_detail(adb: Adb, pkg: str) -> dict:
    """firstInstallTime / lastUpdateTime / granted sensitive permissions."""
    res = adb.shell(f"dumpsys package {pkg}", timeout=20)
    detail = {"firstInstall": "", "lastUpdate": "", "perms": [], "versionName": ""}
    if not res.ok:
        return detail
    for line in res.out.splitlines():
        stripped = line.strip()
        if stripped.startswith("firstInstallTime=") and not detail["firstInstall"]:
            detail["firstInstall"] = stripped.split("=", 1)[1].strip()
        elif stripped.startswith("lastUpdateTime=") and not detail["lastUpdate"]:
            detail["lastUpdate"] = stripped.split("=", 1)[1].strip()
        elif stripped.startswith("versionName=") and not detail["versionName"]:
            detail["versionName"] = stripped.split("=", 1)[1].strip()
        else:
            for perm in SENSITIVE_PERMS:
                # Runtime perms print as "perm: granted=true"; install-time perms
                # appear bare under "requested permissions". Only count granted.
                if stripped.startswith(perm) and "granted=false" not in stripped:
                    if perm not in detail["perms"]:
                        detail["perms"].append(perm)
    return detail


def probe_packages(adb: Adb, snap) -> list:
    """Apps that did not come from an app store."""
    packages = _list_packages(adb)
    if not packages:
        return []

    suspicious = []
    for pkg, installer in sorted(packages.items()):
        snap.record("packages", pkg, {"installer": installer or "null"})
        if installer in TRUSTED_INSTALLERS:
            continue
        suspicious.append((pkg, installer))

    if not suspicious:
        return [Finding(
            id="android.packages.clean",
            title=f"All {len(packages)} user-installed apps came from a known app store",
            severity="OK",
            category="persistence",
            probe="packages",
        )]

    # Enrich the flagged ones only - dumpsys per package is expensive.
    evidence = []
    high_risk = []
    for pkg, installer in suspicious[:MAX_DEEP_INSPECT]:
        detail = _package_detail(adb, pkg)
        snap.data["packages"][pkg].update({
            "firstInstall": detail["firstInstall"],
            "version": detail["versionName"],
            "perms": sorted(detail["perms"]),
        })
        src = installer if installer else "null (adb or system)"
        line = f"{pkg}  installer={src}"
        if detail["firstInstall"]:
            line += f"  installed={detail['firstInstall']}"
        if detail["perms"]:
            line += "\n    granted: " + ", ".join(_short(p) for p in detail["perms"])
            high_risk.append(pkg)
        evidence.append(line)

    if len(suspicious) > MAX_DEEP_INSPECT:
        evidence.append(f"... and {len(suspicious) - MAX_DEEP_INSPECT} more")

    severity = "HIGH" if high_risk else "MEDIUM"
    detail_text = (
        f"{len(suspicious)} app(s) were not installed from an app store. That means "
        "someone tapped an APK file on this device or pushed one over adb. Apps "
        "arriving by Quick Share, Bluetooth or a USB cable land exactly this way."
    )
    if high_risk:
        detail_text += (
            f" {len(high_risk)} of them hold permissions usable for surveillance."
        )

    return [Finding(
        id="android.packages.sideloaded",
        title=f"{len(suspicious)} app(s) installed outside any app store",
        severity=severity,
        category="persistence",
        detail=detail_text,
        evidence=evidence,
        remediation=(
            "Review each package. Uninstall anything you did not install yourself:\n"
            "  adb uninstall <package>\n"
            "On the phone: Settings > Apps > (app) > Uninstall."
        ),
        probe="packages",
    )]


# --------------------------------------------------------------------------
# Surveillance surfaces
# --------------------------------------------------------------------------

def _split_services(raw: str) -> list:
    """Settings store these as ':'-separated component names."""
    return [s.strip() for s in raw.replace("\n", "").split(":") if s.strip()]


def probe_accessibility(adb: Adb, snap) -> list:
    """Accessibility services can read every screen and synthesise taps.

    This is the single most abused Android surveillance surface - it is how
    essentially all commodity stalkerware reads your messages.
    """
    enabled = adb.setting("secure", "enabled_accessibility_services")
    master = adb.setting("secure", "accessibility_enabled")
    snap.record("settings", "enabled_accessibility_services", {"value": enabled})

    services = _split_services(enabled)
    if not services or master != "1":
        return [Finding(
            id="android.accessibility.clean",
            title="No accessibility services are running",
            severity="OK",
            category="surveillance",
            probe="accessibility",
        )]

    return [Finding(
        id="android.accessibility.enabled",
        title=f"{len(services)} accessibility service(s) can read your screen",
        severity="HIGH",
        category="surveillance",
        detail=(
            "An accessibility service sees the content of every screen you open - "
            "messages, passwords as you type them, banking apps - and can tap and "
            "type on your behalf. Legitimate uses exist (screen readers, password "
            "managers, Tasker). Anything here you don't recognise is spyware."
        ),
        evidence=services,
        remediation=(
            "Settings > Accessibility > Downloaded apps. Turn off anything you did "
            "not deliberately enable, then uninstall it."
        ),
        probe="accessibility",
    )]


def probe_notification_listeners(adb: Adb, snap) -> list:
    """Notification listeners receive the text of every notification."""
    enabled = adb.setting("secure", "enabled_notification_listeners")
    snap.record("settings", "enabled_notification_listeners", {"value": enabled})
    services = _split_services(enabled)
    if not services:
        return [Finding(
            id="android.notiflisten.clean",
            title="No notification listeners registered",
            severity="OK",
            category="surveillance",
            probe="notification_listeners",
        )]
    return [Finding(
        id="android.notiflisten.enabled",
        title=f"{len(services)} app(s) can read all your notifications",
        severity="MEDIUM",
        category="surveillance",
        detail=(
            "Notification access exposes message previews, 2FA codes and delivery "
            "alerts to the listening app, even for messages you never open. "
            "Smartwatch and car apps need it; little else does."
        ),
        evidence=services,
        remediation="Settings > Notifications > Device & app notifications. Revoke anything unfamiliar.",
        probe="notification_listeners",
    )]


def probe_device_admins(adb: Adb, snap) -> list:
    """Device admin / device owner apps resist uninstall and can wipe or lock."""
    res = adb.shell("dumpsys device_policy", timeout=25)
    if not res.ok:
        return []
    admins = []
    for line in res.out.splitlines():
        stripped = line.strip()
        # Entries print as "admin=ComponentInfo{com.pkg/com.pkg.Receiver}"
        if stripped.startswith("admin=ComponentInfo{") and stripped.endswith("}"):
            admins.append(stripped[len("admin=ComponentInfo{"):-1])
    owners = adb.shell("dpm list-owners", timeout=15)
    owner_lines = [l for l in owners.lines if "no owner" not in l.lower()] if owners.ok else []

    for a in admins:
        snap.record("settings", f"device_admin::{a}", {"active": True})

    if not admins and not owner_lines:
        return [Finding(
            id="android.deviceadmin.clean",
            title="No device administrator apps active",
            severity="OK",
            category="persistence",
            probe="device_admins",
        )]

    evidence = list(admins) + [f"owner: {l}" for l in owner_lines]
    return [Finding(
        id="android.deviceadmin.active",
        title=f"{len(admins) + len(owner_lines)} device administrator(s) registered",
        severity="HIGH",
        category="persistence",
        detail=(
            "Device admins can lock, wipe, enforce policy and - most importantly - "
            "block their own uninstall. Stalkerware registers as a device admin "
            "precisely so you cannot remove it the normal way. Corporate MDM also "
            "shows up here and is expected on a work phone."
        ),
        evidence=evidence,
        remediation=(
            "Settings > Security > Device admin apps. Deactivate the unfamiliar "
            "entry first, then uninstall the app."
        ),
        probe="device_admins",
    )]


# --------------------------------------------------------------------------
# Delivery channels
# --------------------------------------------------------------------------

def probe_adb_wifi(adb: Adb, snap) -> list:
    """ADB over WiFi lets anyone on your network install apps with no prompt.

    This is the most direct answer to "did someone use WiFi to put something on
    my phone" - if this is on, they could have.
    """
    wifi_flag = adb.setting("global", "adb_wifi_enabled")
    tcp_port = adb.getprop("service.adb.tcp.port")
    adb_enabled = adb.setting("global", "adb_enabled")

    snap.record("settings", "adb_wifi_enabled", {"value": wifi_flag})
    snap.record("settings", "service.adb.tcp.port", {"value": tcp_port})

    findings = []
    if wifi_flag == "1" or (tcp_port and tcp_port not in ("-1", "0")):
        findings.append(Finding(
            id="android.adb.wifi",
            title="Wireless debugging is ENABLED - the phone accepts commands over WiFi",
            severity="CRITICAL",
            category="delivery",
            detail=(
                "With wireless debugging on, any already-paired computer on the same "
                "network can install apps, read storage and run shell commands on "
                "this phone silently. It is the cleanest way to push something onto "
                "a phone over WiFi, and it survives reboots on some builds."
            ),
            evidence=[
                f"settings global adb_wifi_enabled = {wifi_flag or 'unset'}",
                f"service.adb.tcp.port = {tcp_port or 'unset'}",
            ],
            remediation=(
                "Settings > Developer options > Wireless debugging: OFF.\n"
                "Then tap 'Revoke authorisations for USB debugging' to drop every "
                "paired computer, and turn Developer options off entirely."
            ),
            probe="adb_wifi",
        ))
    elif adb_enabled == "1":
        findings.append(Finding(
            id="android.adb.usb",
            title="USB debugging is enabled",
            severity="LOW",
            category="exposure",
            detail=(
                "Expected - this scan needs it. But leaving it on means any computer "
                "you have ever trusted can access this phone whenever it is plugged in."
            ),
            evidence=[f"settings global adb_enabled = {adb_enabled}"],
            remediation="Turn Developer options off when this scan is finished.",
            probe="adb_wifi",
        ))
    return findings


def probe_unknown_sources(adb: Adb, snap) -> list:
    """Which apps are allowed to install other apps."""
    legacy = adb.setting("global", "install_non_market_apps")
    snap.record("settings", "install_non_market_apps", {"value": legacy})
    if legacy == "1":
        return [Finding(
            id="android.unknownsources.on",
            title="Installation from unknown sources is allowed globally",
            severity="MEDIUM",
            category="exposure",
            detail=(
                "The device will install APKs from outside any app store. On older "
                "Android this is a single global switch; anything that reaches your "
                "storage can be installed with one tap."
            ),
            evidence=[f"settings global install_non_market_apps = {legacy}"],
            remediation="Settings > Security > Install unknown apps: revoke for every app.",
            probe="unknown_sources",
        )]
    return []


def _stat_dir(adb: Adb, directory: str) -> list:
    """(mtime, size, path) for every file under `directory`.

    Uses toybox stat via find -exec, which is present on Android 6+. Falls back
    to a name-only listing when stat is unavailable so we still populate the
    baseline.
    """
    cmd = f"find {directory} -type f -exec stat -c '%Y|%s|%n' {{}} + 2>/dev/null"
    res = adb.shell(cmd, timeout=60)
    entries = []
    if res.ok and res.out.strip():
        for line in res.lines:
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            try:
                entries.append((int(parts[0]), int(parts[1]), parts[2]))
            except ValueError:
                continue
        if entries:
            return entries
    # Fallback: names only.
    res = adb.shell(f"find {directory} -type f 2>/dev/null", timeout=60)
    if res.ok:
        entries = [(0, 0, p) for p in res.lines]
    return entries


def probe_received_files(adb: Adb, snap, window_hours: int = 72) -> list:
    """Files sitting in transfer directories, with an emphasis on recent ones."""
    findings = []
    now = time.time()
    cutoff = now - window_hours * 3600

    recent = []
    executables = []
    total = 0

    for directory in DELIVERY_DIRS + MEDIA_DIRS:
        is_delivery = directory in DELIVERY_DIRS
        for mtime, size, path in _stat_dir(adb, directory):
            total += 1
            snap.record("files", path, {"mtime": mtime, "size": size})
            ext = posixpath.splitext(path)[1].lower()
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)) if mtime else "unknown"
            row = f"{stamp}  {size:>10,}B  {path}"
            if ext in EXECUTABLE_EXT:
                executables.append(row)
            elif is_delivery and mtime and mtime >= cutoff:
                recent.append(row)

    if executables:
        findings.append(Finding(
            id="android.files.executable",
            title=f"{len(executables)} installable/executable file(s) in your storage",
            severity="HIGH",
            category="delivery",
            detail=(
                "APKs and scripts sitting in Downloads or Bluetooth are what a "
                "transferred payload looks like before it is installed. If you did "
                "not download these yourself, someone sent them to this phone."
            ),
            evidence=sorted(executables)[:40],
            remediation=(
                "Delete anything you don't recognise, and check whether it was "
                "already installed (see the sideloaded-apps finding above)."
            ),
            probe="received_files",
        ))

    if recent:
        findings.append(Finding(
            id="android.files.recent",
            title=f"{len(recent)} file(s) landed in transfer folders in the last {window_hours}h",
            severity="MEDIUM" if len(recent) > 0 else "INFO",
            category="delivery",
            detail=(
                "Downloads and Bluetooth are where Quick Share, Nearby Share and "
                "Bluetooth transfers deposit files. Recent arrivals you did not "
                "initiate are the clearest sign someone sent you something."
            ),
            evidence=sorted(recent, reverse=True)[:40],
            remediation="Delete what you did not ask for. Then run the exposure check below.",
            probe="received_files",
        ))

    if not findings and total:
        findings.append(Finding(
            id="android.files.clean",
            title=f"No executables or recent arrivals across {total} scanned files",
            severity="OK",
            category="delivery",
            probe="received_files",
        ))
    return findings


# --------------------------------------------------------------------------
# Network and integrity
# --------------------------------------------------------------------------

def probe_network(adb: Adb, snap) -> list:
    """Proxy, VPN and the WiFi network the phone is on."""
    findings = []

    proxy = adb.setting("global", "http_proxy")
    snap.record("settings", "http_proxy", {"value": proxy})
    if proxy and proxy != ":0":
        findings.append(Finding(
            id="android.net.proxy",
            title=f"A global HTTP proxy is configured: {proxy}",
            severity="CRITICAL",
            category="network",
            detail=(
                "Every unencrypted request from this phone is being routed through "
                "that host, and combined with an installed CA certificate it can "
                "read HTTPS too. A global proxy set without your knowledge means "
                "your traffic is being intercepted."
            ),
            evidence=[f"settings global http_proxy = {proxy}"],
            remediation=(
                "Settings > WiFi > (network) > Advanced > Proxy: None.\n"
                "Clear the global setting: adb shell settings put global http_proxy :0"
            ),
            probe="network",
        ))

    links = adb.shell("ip -o addr show 2>/dev/null", timeout=20)
    if links.ok:
        tun = [l for l in links.lines if " tun" in l or " ppp" in l]
        if tun:
            findings.append(Finding(
                id="android.net.vpn",
                title="A VPN tunnel interface is active",
                severity="MEDIUM",
                category="network",
                detail=(
                    "All traffic is passing through a VPN. Fine if you set it up - "
                    "but a VPN profile installed by someone else routes everything "
                    "you do through their server."
                ),
                evidence=tun,
                remediation="Settings > Network > VPN. Remove any profile you did not create.",
                probe="network",
            ))

    wifi = adb.shell("dumpsys wifi | grep -m1 -i 'mWifiInfo SSID'", timeout=25)
    if wifi.ok and wifi.out.strip():
        snap.record("settings", "wifi_current", {"value": wifi.out.strip()})
        findings.append(Finding(
            id="android.net.wifi",
            title="Current WiFi association",
            severity="INFO",
            category="network",
            evidence=[wifi.out.strip()],
            probe="network",
        ))
    return findings


def probe_integrity(adb: Adb, snap) -> list:
    """Bootloader lock state and root - the foundation everything else rests on."""
    findings = []
    verified = adb.getprop("ro.boot.verifiedbootstate")
    locked = adb.getprop("ro.boot.flash.locked")
    snap.record("settings", "verifiedbootstate", {"value": verified})

    if verified and verified.lower() != "green" or locked == "0":
        findings.append(Finding(
            id="android.integrity.bootloader",
            title="Bootloader is unlocked or verified boot is not green",
            severity="CRITICAL",
            category="integrity",
            detail=(
                "An unlocked bootloader means the system partition can be replaced "
                "with a modified one. Nothing else this scan reports can be fully "
                "trusted on an unlocked device, because the OS doing the reporting "
                "may itself be modified."
            ),
            evidence=[
                f"ro.boot.verifiedbootstate = {verified or 'unset'}",
                f"ro.boot.flash.locked = {locked or 'unset'}",
            ],
            remediation=(
                "If you did not unlock this yourself, treat the phone as untrusted: "
                "back up your data, factory reset, and relock the bootloader."
            ),
            probe="integrity",
        ))

    su = adb.shell("which su 2>/dev/null || ls /system/xbin/su /system/bin/su 2>/dev/null", timeout=15)
    if su.ok and su.out.strip():
        findings.append(Finding(
            id="android.integrity.root",
            title="Root binary present",
            severity="HIGH",
            category="integrity",
            detail="A `su` binary is installed, so apps can escalate to full system access.",
            evidence=su.lines,
            remediation="If you did not root this phone deliberately, factory reset it.",
            probe="integrity",
        ))
    return findings


def run(adb: Adb, snap, window_hours: int = 72) -> list:
    """Run every Android probe. Order matches report priority."""
    findings = []
    for probe in (
        lambda: probe_adb_wifi(adb, snap),
        lambda: probe_packages(adb, snap),
        lambda: probe_accessibility(adb, snap),
        lambda: probe_device_admins(adb, snap),
        lambda: probe_notification_listeners(adb, snap),
        lambda: probe_received_files(adb, snap, window_hours),
        lambda: probe_network(adb, snap),
        lambda: probe_integrity(adb, snap),
        lambda: probe_unknown_sources(adb, snap),
    ):
        try:
            findings.extend(probe())
        except Exception as exc:                      # one bad probe must not kill the scan
            findings.append(Finding(
                id="android.probe.error",
                title=f"A probe failed: {exc}",
                severity="INFO",
                category="exposure",
                probe="internal",
            ))
    return findings
