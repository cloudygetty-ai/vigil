"""iOS probes over USB lockdown, via libimobiledevice. No jailbreak required.

Be clear about the ceiling: iOS does not let anything - on-device or over USB -
enumerate arbitrary files. AFC reaches /var/mobile/Media only (camera roll,
Downloads, Books, Recordings). An AirDropped file that the user saved into an
app's container is not readable without a full backup.

So the iOS strategy is different from Android's. Instead of hunting files, it
targets what a payload must leave behind to be useful: a configuration profile,
an out-of-store app signature, or a live sharingd transfer in the syslog.
"""

from __future__ import annotations

import os
import plistlib
import re
import tempfile
import time

from ..findings import Finding
from ..shell import run, have


# Signer identities Apple issues for App Store distribution. Anything else means
# the app was side-loaded with a developer or enterprise certificate.
APPSTORE_SIGNERS = ("Apple iPhone OS Application Signing", "Apple Mac OS Application Signing")

# Processes whose crashes are worth a second look. sharingd handles AirDrop;
# repeated crashes there can mean a malformed payload was thrown at it.
NOTABLE_CRASH_PROCS = [
    "sharingd", "identityservicesd", "imagent", "WebKit", "MessagesBlastDoorService",
    "bluetoothd", "wifid", "mDNSResponder", "AirDrop", "profiled", "mobile_installation",
]

AIRDROP_SYSLOG_PATTERNS = [
    r"sharingd",
    r"AirDrop",
    r"OTATransfer",
    r"TransferSession",
    r"BrowseSession",
]


def _info(udid: str, key: str = None, domain: str = None) -> str:
    argv = ["ideviceinfo", "-u", udid]
    if domain:
        argv += ["-q", domain]
    if key:
        argv += ["-k", key]
    res = run(argv, timeout=25)
    return res.out.strip() if res.ok else ""


def _info_all(udid: str) -> dict:
    """Full lockdown dump as a dict, via the xml output mode."""
    res = run(["ideviceinfo", "-u", udid, "-x"], timeout=30)
    if not res.ok:
        return {}
    try:
        return plistlib.loads(res.out.encode())
    except Exception:
        return {}


# --------------------------------------------------------------------------
# Device posture
# --------------------------------------------------------------------------

def probe_device_posture(udid: str, snap) -> list:
    """Passcode, supervision and activation state."""
    info = _info_all(udid)
    if not info:
        return []

    findings = []
    version = str(info.get("ProductVersion", "?"))
    model = str(info.get("ProductType", "?"))
    name = str(info.get("DeviceName", "?"))
    snap.record("settings", "ios_version", {"value": version})

    findings.append(Finding(
        id="ios.posture.device",
        title=f"{name} - {model} on iOS {version}",
        severity="INFO",
        category="exposure",
        evidence=[f"{k} = {info[k]}" for k in
                  ("DeviceName", "ProductType", "ProductVersion", "BuildVersion")
                  if k in info],
        probe="posture",
    ))

    if info.get("PasswordProtected") is False:
        findings.append(Finding(
            id="ios.posture.nopasscode",
            title="This iPhone has no passcode",
            severity="CRITICAL",
            category="exposure",
            detail=(
                "Without a passcode, anyone who picks up the phone has everything: "
                "they can accept an AirDrop, install a configuration profile, and "
                "pair it to their computer in under a minute. Data protection "
                "encryption keys are also not derived, so the storage is far easier "
                "to read offline."
            ),
            evidence=["lockdown PasswordProtected = false"],
            remediation="Settings > Face ID & Passcode > Turn Passcode On. Use six digits or more.",
            probe="posture",
        ))

    # Supervision means an organisation controls this device via MDM.
    supervised = info.get("IsSupervised")
    if supervised:
        findings.append(Finding(
            id="ios.posture.supervised",
            title="This iPhone is SUPERVISED",
            severity="HIGH",
            category="persistence",
            detail=(
                "A supervised device is enrolled in Mobile Device Management. Whoever "
                "controls the MDM server can install apps silently, read the device "
                "inventory, apply restrictions and wipe it remotely. Expected on a "
                "company phone. On a personal phone it means someone else set it up."
            ),
            evidence=[f"lockdown IsSupervised = {supervised}"],
            remediation=(
                "Settings > General > VPN & Device Management. If an MDM profile is "
                "listed and you did not enrol, removing it may require the "
                "organisation's permission - a factory reset is the reliable exit."
            ),
            probe="posture",
        ))
    return findings


# --------------------------------------------------------------------------
# Configuration profiles - the classic AirDrop payload
# --------------------------------------------------------------------------

def probe_profiles(udid: str, snap) -> list:
    """Provisioning and configuration profiles.

    A .mobileconfig accepted from an AirDrop can install a root CA, a VPN, a
    proxy and a web-clip in one tap. It is the single highest-value thing an
    attacker can get onto a non-jailbroken iPhone.
    """
    findings = []

    # Provisioning profiles: present whenever a non-App-Store app is installed.
    if have("ideviceprovision"):
        res = run(["ideviceprovision", "-u", udid, "list"], timeout=30)
        if res.ok:
            entries = [l for l in res.lines if l and not l.lower().startswith("device")]
            for line in entries:
                snap.record("profiles", line.strip(), {"kind": "provisioning"})
            if entries:
                findings.append(Finding(
                    id="ios.profiles.provisioning",
                    title=f"{len(entries)} provisioning profile(s) installed",
                    severity="HIGH",
                    category="persistence",
                    detail=(
                        "Provisioning profiles exist to let apps run that did not come "
                        "from the App Store - developer builds and enterprise-signed "
                        "apps. If you are not a developer and this is not a work phone, "
                        "something was side-loaded onto this device."
                    ),
                    evidence=entries[:30],
                    remediation=(
                        "Settings > General > VPN & Device Management, then remove the "
                        "profile and delete the app it belongs to.\n"
                        "Or over USB: ideviceprovision remove <UUID>"
                    ),
                    probe="profiles",
                ))
            else:
                findings.append(Finding(
                    id="ios.profiles.clean",
                    title="No provisioning profiles installed",
                    severity="OK",
                    category="persistence",
                    probe="profiles",
                ))
    else:
        findings.append(Finding(
            id="ios.profiles.manual",
            title="Check configuration profiles by hand (ideviceprovision not installed)",
            severity="INFO",
            category="persistence",
            detail=(
                "iOS exposes no public API for listing configuration profiles over USB, "
                "so this must be checked on the device itself. It is worth doing - a "
                "malicious .mobileconfig is the most powerful thing an attacker can "
                "AirDrop to you."
            ),
            remediation=(
                "On the iPhone: Settings > General > VPN & Device Management.\n"
                "If that row does not appear at all, no profiles are installed - good.\n"
                "If it does, every entry there should be one you deliberately added."
            ),
            probe="profiles",
        ))
    return findings


# --------------------------------------------------------------------------
# Installed apps and their signatures
# --------------------------------------------------------------------------

def probe_apps(udid: str, snap) -> list:
    """Apps whose signer is not Apple's App Store identity."""
    if not have("ideviceinstaller"):
        return [Finding(
            id="ios.apps.unavailable",
            title="Skipped app inventory - ideviceinstaller not installed",
            severity="INFO",
            category="persistence",
            remediation="brew install ideviceinstaller  |  apt install ideviceinstaller",
            probe="apps",
        )]

    res = run(["ideviceinstaller", "-u", udid, "list", "-o", "xml"], timeout=90)
    if not res.ok:
        # Older releases used a different flag spelling.
        res = run(["ideviceinstaller", "-u", udid, "-l", "-o", "xml"], timeout=90)
    if not res.ok:
        return []

    try:
        start = res.out.index("<?xml")
        apps = plistlib.loads(res.out[start:].encode())
    except Exception:
        return []
    if not isinstance(apps, list):
        return []

    sideloaded = []
    for app in apps:
        if not isinstance(app, dict):
            continue
        bundle = str(app.get("CFBundleIdentifier", "?"))
        signer = str(app.get("SignerIdentity", ""))
        name = str(app.get("CFBundleDisplayName", bundle))
        snap.record("packages", bundle, {"name": name, "signer": signer})
        if signer and not any(signer.startswith(s) for s in APPSTORE_SIGNERS):
            sideloaded.append(f"{name}  ({bundle})\n    signed by: {signer}")

    if sideloaded:
        return [Finding(
            id="ios.apps.sideloaded",
            title=f"{len(sideloaded)} app(s) not signed by the App Store",
            severity="HIGH",
            category="persistence",
            detail=(
                "These apps were installed with a developer or enterprise certificate "
                "rather than through the App Store, which means they bypassed Apple's "
                "review. That is how a malicious app reaches a non-jailbroken iPhone."
            ),
            evidence=sideloaded[:30],
            remediation=(
                "Delete the app, then remove its profile in "
                "Settings > General > VPN & Device Management."
            ),
            probe="apps",
        )]
    return [Finding(
        id="ios.apps.clean",
        title=f"All {len(apps)} installed apps carry App Store signatures",
        severity="OK",
        category="persistence",
        probe="apps",
    )]


# --------------------------------------------------------------------------
# Live AirDrop activity
# --------------------------------------------------------------------------

def probe_airdrop_syslog(udid: str, snap, seconds: int = 10) -> list:
    """Watch the device log for sharingd - the daemon behind AirDrop.

    This is the one place iOS genuinely tells you an AirDrop happened. Run it
    with --watch while you leave the phone sitting on a table: if transfers
    appear that you did not accept, someone nearby is pushing at it.
    """
    if not have("idevicesyslog"):
        return [Finding(
            id="ios.airdrop.unavailable",
            title="Skipped AirDrop log watch - idevicesyslog not installed",
            severity="INFO",
            category="delivery",
            probe="airdrop",
        )]

    res = run(["idevicesyslog", "-u", udid], timeout=seconds + 5)
    # idevicesyslog streams until killed, so a timeout here is the expected exit
    # path; we keep whatever it printed before we cut it off.
    text = res.out or ""
    if not text.strip():
        return [Finding(
            id="ios.airdrop.quiet",
            title=f"No AirDrop activity in {seconds}s of device log",
            severity="OK",
            category="delivery",
            probe="airdrop",
        )]

    pattern = re.compile("|".join(AIRDROP_SYSLOG_PATTERNS), re.IGNORECASE)
    hits = [ln.strip() for ln in text.splitlines() if pattern.search(ln)]
    for line in hits:
        snap.record("settings", f"airdrop_log::{hash(line) & 0xffffff}", {"line": line[:200]})

    if not hits:
        return [Finding(
            id="ios.airdrop.quiet",
            title=f"No AirDrop activity in {seconds}s of device log",
            severity="OK",
            category="delivery",
            probe="airdrop",
        )]

    transfers = [h for h in hits if re.search(r"transfer|receiv|accept|ask", h, re.I)]
    return [Finding(
        id="ios.airdrop.activity",
        title=f"sharingd (AirDrop) was active - {len(hits)} log line(s), {len(transfers)} transfer-related",
        severity="HIGH" if transfers else "MEDIUM",
        category="delivery",
        detail=(
            "sharingd is the iOS daemon that advertises your device to AirDrop and "
            "handles incoming transfers. Activity here while you were not sending "
            "anything means your phone was at least discoverable, and possibly "
            "receiving offers."
        ),
        evidence=hits[:40],
        remediation=(
            "Settings > General > AirDrop > Receiving Off (or Contacts Only).\n"
            "Control Centre > long-press the network tile > AirDrop for a quick toggle."
        ),
        probe="airdrop",
    )]


# --------------------------------------------------------------------------
# Media directory - what AFC can actually reach
# --------------------------------------------------------------------------

def probe_media_files(udid: str, snap) -> list:
    """Inventory /var/mobile/Media via AFC.

    AFC exposes no modification times through `ls`, and calling `info` per file
    is far too slow over USB, so this deliberately makes no judgement about
    recency. Its value is the baseline: on the next scan, the diff names every
    file that appeared here since - which is exactly how an AirDropped photo
    shows up, since those land in DCIM.
    """
    if not have("afcclient"):
        return []

    seen = 0
    for directory in ("/DCIM", "/Downloads", "/Books", "/Recordings"):
        res = run(["afcclient", "-u", udid, "ls", directory], timeout=40)
        if not res.ok:
            continue
        for entry in res.lines:
            entry = entry.strip()
            if not entry or entry in (".", ".."):
                continue
            snap.record("files", f"{directory}/{entry}", {"dir": directory})
            seen += 1

    if not seen:
        return []
    return [Finding(
        id="ios.files.inventory",
        title=f"Recorded {seen} entries in the device media directory",
        severity="INFO",
        category="delivery",
        detail=(
            "Baselined for comparison. iOS only exposes the media directory over "
            "USB, so files saved into an app's own container are not visible here."
        ),
        probe="media_files",
    )]


# --------------------------------------------------------------------------
# Crash reports
# --------------------------------------------------------------------------

def probe_crashes(udid: str, snap) -> list:
    """Crashes in transfer-handling daemons can mark a failed exploit attempt."""
    if not have("idevicecrashreport"):
        return []
    tmp = tempfile.mkdtemp(prefix="vigil-crash-")
    res = run(["idevicecrashreport", "-u", udid, "-k", tmp], timeout=120)
    if not res.ok and not os.listdir(tmp):
        return []

    notable = []
    for root, _dirs, files in os.walk(tmp):
        for fname in files:
            for proc in NOTABLE_CRASH_PROCS:
                if fname.lower().startswith(proc.lower()):
                    full = os.path.join(root, fname)
                    try:
                        mtime = os.path.getmtime(full)
                        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
                    except OSError:
                        stamp = "?"
                    notable.append(f"{stamp}  {fname}")
                    snap.record("files", f"crash::{fname}", {"proc": proc})
                    break

    if not notable:
        return [Finding(
            id="ios.crashes.clean",
            title="No crashes in transfer or messaging daemons",
            severity="OK",
            category="integrity",
            probe="crashes",
        )]
    return [Finding(
        id="ios.crashes.notable",
        title=f"{len(notable)} crash report(s) in sensitive daemons",
        severity="MEDIUM",
        category="integrity",
        detail=(
            "Crashes in sharingd, BlastDoor, WebKit or imagent are how a failed "
            "exploit against an AirDropped or messaged payload usually shows up. "
            "One crash is probably a bug; a cluster around one timestamp is not."
        ),
        evidence=sorted(notable, reverse=True)[:30],
        remediation=(
            f"Full reports were copied to {tmp}. Settings > Privacy & Security > "
            "Analytics & Improvements > Analytics Data holds the same files on device."
        ),
        probe="crashes",
    )]


# --------------------------------------------------------------------------
# Pairing hygiene
# --------------------------------------------------------------------------

def probe_pairing(udid: str, snap) -> list:
    """iOS keeps a pairing record for every computer the phone has trusted.

    Those records cannot be enumerated over lockdown - Apple exposes no API for
    it - but they are real, they persist until explicitly cleared, and a
    pairing record grants that computer backup-level access whenever the phone
    is plugged in. So this is reported as an action rather than a detection.
    """
    return [Finding(
        id="ios.pairing.hygiene",
        title="Trusted-computer pairings cannot be listed - clear them if unsure",
        severity="INFO",
        category="delivery",
        detail=(
            "Every time you tapped 'Trust This Computer', iOS stored a pairing record "
            "that survives reboots and lets that machine read a full backup of this "
            "phone over USB or - once paired - over WiFi sync. There is no way to see "
            "the list. If a computer you don't control has ever been plugged into this "
            "phone, assume the pairing is still there."
        ),
        remediation=(
            "Settings > General > Transfer or Reset iPhone > Reset > Reset Location "
            "& Privacy. This revokes every trusted-computer pairing at once. You will "
            "re-approve your own computers the next time you connect them."
        ),
        probe="pairing",
    )]


def run(udid: str, snap, watch_seconds: int = 0) -> list:
    findings = []
    probes = [
        lambda: probe_device_posture(udid, snap),
        lambda: probe_profiles(udid, snap),
        lambda: probe_apps(udid, snap),
        lambda: probe_media_files(udid, snap),
        lambda: probe_crashes(udid, snap),
        lambda: probe_pairing(udid, snap),
    ]
    if watch_seconds > 0:
        probes.insert(1, lambda: probe_airdrop_syslog(udid, snap, watch_seconds))

    for probe in probes:
        try:
            findings.extend(probe())
        except Exception as exc:
            findings.append(Finding(
                id="ios.probe.error",
                title=f"A probe failed: {exc}",
                severity="INFO",
                category="exposure",
                probe="internal",
            ))
    return findings
