"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .baseline import Snapshot, diff
from .devices import discover, missing_tooling, Device
from .findings import Report, Finding
from .report import Terminal, render_html
from .shell import Adb
from .probes import android as android_probes
from .probes import ios as ios_probes
from .probes import network as network_probes


# Exit codes double as a scripting signal.
EXIT = {"CLEAN": 0, "HARDEN": 1, "SUSPICIOUS": 2, "COMPROMISED": 3}


def _scan_device(device: Device, args, report: Report) -> Snapshot:
    snap = Snapshot(platform=device.platform, serial=device.serial, label=device.label)
    if device.platform == "android":
        adb = Adb(device.serial)
        report.extend(android_probes.run(adb, snap, window_hours=args.window))
    elif device.platform == "ios":
        report.extend(ios_probes.run(device.serial, snap, watch_seconds=args.watch))
    return snap


def _print_tooling_gaps(term: Terminal) -> None:
    gaps = missing_tooling()
    if not gaps:
        return
    term.write()
    term.write("  Backends unavailable on this machine:")
    for platform, tool, howto in gaps:
        term.write(f"    {platform:<8} needs {tool}")
        term.write(f"             {howto}")


def cmd_devices(args) -> int:
    term = Terminal()
    devices = discover()
    term.write()
    if not devices:
        term.write("  No phones detected over USB.")
        term.write()
        term.write("  Android: enable Settings > About phone > tap Build number 7x,")
        term.write("           then Developer options > USB debugging, and accept the prompt.")
        term.write("  iPhone:  unlock it and tap 'Trust This Computer' when asked.")
        _print_tooling_gaps(term)
        return 1
    for device in devices:
        state = "ready" if device.usable else device.state.upper()
        term.write(f"  {device.platform:<8} {device.label:<26} {device.serial:<26} {state}")
        if device.note:
            term.write(f"           {device.note}")
    _print_tooling_gaps(term)
    return 0


def cmd_scan(args) -> int:
    term = Terminal()
    report = Report()
    delta = None
    device_label = "network only"
    snapshot = None

    devices = [] if args.network_only else discover()
    if args.device:
        devices = [d for d in devices if d.serial == args.device]
        if not devices:
            term.write(f"  No attached device with serial {args.device}.")
            return 1

    usable = [d for d in devices if d.usable]
    for device in devices:
        if not device.usable:
            report.skip(f"{device.platform}:{device.label}",
                        f"{device.state} - {device.note or 'device not ready'}")

    if not args.network_only and not usable:
        term.header(report, "no device attached")
        term.write("  No usable phone attached - scanning the network only.")
        term.write("  Run `sentinel devices` to see what is connected.")
        _print_tooling_gaps(term)

    target = usable[0] if usable else None
    if target:
        device_label = f"{target.label} ({target.platform})"
        snapshot = _scan_device(target, args, report)

    if not args.no_network:
        net_snap = snapshot or Snapshot(platform="host", serial="localhost")
        report.extend(network_probes.run(net_snap))
        if snapshot is None:
            snapshot = net_snap

    # Diff against the stored baseline before overwriting it.
    if snapshot and not args.no_baseline_diff:
        previous = Snapshot.load(snapshot.platform, snapshot.serial)
        if previous:
            delta = diff(previous, snapshot)
            _findings_from_delta(delta, report)

    term.header(report, device_label)
    term.verdict(report)
    term.delta(delta)
    term.findings(report, show_all=args.all)
    term.gaps(report)
    term.write()

    if args.baseline and snapshot:
        term.write(f"  Baseline saved: {snapshot.save()}")
    if args.html:
        with open(args.html, "w") as fh:
            fh.write(render_html(report, delta, device_label))
        term.write(f"  HTML report written to {args.html}")
    if args.json:
        payload = {
            "version": __version__,
            "device": device_label,
            "score": report.score(),
            "verdict": report.verdict(),
            "findings": [f.to_dict() for f in report.sorted()],
            "skipped": report.skipped,
        }
        with open(args.json, "w") as fh:
            json.dump(payload, fh, indent=2)
        term.write(f"  JSON report written to {args.json}")
    term.write()

    return EXIT[report.verdict()]


def _findings_from_delta(delta, report: Report) -> None:
    """Turn the baseline diff into findings.

    A new app or file since a known-good baseline is far stronger evidence than
    any heuristic, so these outrank most single-scan checks.
    """
    new_packages = delta.added["packages"]
    if new_packages:
        report.add(Finding(
            id="delta.packages.new",
            title=f"{len(new_packages)} app(s) appeared since the baseline",
            severity="HIGH",
            category="persistence",
            detail="These were not on the device when you recorded the baseline.",
            evidence=[f"{k}  {v}" for k, v in sorted(new_packages.items())][:30],
            remediation="Uninstall anything you did not install yourself.",
            probe="baseline",
        ))

    new_files = delta.added["files"]
    if new_files:
        report.add(Finding(
            id="delta.files.new",
            title=f"{len(new_files)} file(s) appeared since the baseline",
            severity="MEDIUM",
            category="delivery",
            detail=(
                "New files in transfer and media folders. This is the clearest "
                "answer to 'did someone send something to this phone' - if you did "
                "not download these, they arrived another way."
            ),
            evidence=sorted(new_files)[:40],
            remediation="Delete what you did not ask for.",
            probe="baseline",
        ))

    new_profiles = delta.added["profiles"]
    if new_profiles:
        report.add(Finding(
            id="delta.profiles.new",
            title=f"{len(new_profiles)} configuration profile(s) appeared since the baseline",
            severity="CRITICAL",
            category="persistence",
            detail=(
                "A profile installed since your baseline can add a root certificate, "
                "a VPN and a proxy in one step. This is the highest-value payload "
                "anyone can get onto an iPhone."
            ),
            evidence=sorted(new_profiles)[:20],
            remediation="Settings > General > VPN & Device Management. Remove it.",
            probe="baseline",
        ))

    changed_certs = delta.changed["certificates"]
    if changed_certs:
        report.add(Finding(
            id="delta.certificates.changed",
            title=f"The HTTPS issuer changed for {len(changed_certs)} host(s) since the baseline",
            severity="CRITICAL",
            category="network",
            detail=(
                "The certificate authority signing a well-known site is different than "
                "it was at baseline. Public sites do not change issuer between two of "
                "your scans; something on this network is now re-signing your HTTPS "
                "traffic, which means it can read it."
            ),
            evidence=[
                f"{host}: {v['before'].get('issuer', '?')} -> {v['after'].get('issuer', '?')}"
                for host, v in sorted(changed_certs.items())
            ],
            remediation=(
                "Leave this network. Then look for a root certificate you did not "
                "install in your system and browser trust stores."
            ),
            probe="baseline",
        ))

    changed_settings = delta.changed["settings"]
    security_keys = ("adb_wifi", "http_proxy", "accessibility", "notification_listeners",
                     "gateway", "install_non_market", "verifiedboot", "device_admin")
    notable = {
        k: v for k, v in changed_settings.items()
        if any(s in k for s in security_keys)
    }
    if notable:
        report.add(Finding(
            id="delta.settings.changed",
            title=f"{len(notable)} security-relevant setting(s) changed since the baseline",
            severity="HIGH",
            category="exposure",
            evidence=[f"{k}: {v['before']} -> {v['after']}" for k, v in sorted(notable.items())][:20],
            detail="Someone with access to the phone altered how it can be reached.",
            probe="baseline",
        ))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sentinel",
        description="VIGIL SENTINEL - detect what was put on your phone via AirDrop, "
                    "Quick Share, Bluetooth or WiFi.",
    )
    parser.add_argument("--version", action="version", version=f"vigil-sentinel {__version__}")
    sub = parser.add_subparsers(dest="command")

    scan = sub.add_parser("scan", help="scan the attached phone and the local network")
    scan.add_argument("--device", metavar="SERIAL", help="target one device by serial/UDID")
    scan.add_argument("--baseline", action="store_true",
                      help="record this scan as the known-good baseline")
    scan.add_argument("--no-baseline-diff", action="store_true",
                      help="skip comparison against the stored baseline")
    scan.add_argument("--window", type=int, default=72, metavar="HOURS",
                      help="how far back a file counts as 'recent' (default 72)")
    scan.add_argument("--watch", type=int, default=0, metavar="SECONDS",
                      help="iOS: watch the device log for AirDrop activity for N seconds")
    scan.add_argument("--network-only", action="store_true", help="skip the phone entirely")
    scan.add_argument("--no-network", action="store_true", help="skip the network probes")
    scan.add_argument("--all", action="store_true", help="show passing checks too")
    scan.add_argument("--html", metavar="PATH", help="write a standalone HTML report")
    scan.add_argument("--json", metavar="PATH", help="write machine-readable findings")
    scan.set_defaults(func=cmd_scan)

    devices = sub.add_parser("devices", help="list attached phones")
    devices.set_defaults(func=cmd_devices)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        # Bare `sentinel` runs a scan, which is what people mean.
        args = parser.parse_args(["scan"] + list(argv or sys.argv[1:]))
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n  Interrupted.", file=sys.stderr)
        return 130
    except BrokenPipeError:
        # Piping into head/less closes stdout early. Detach it so the interpreter
        # does not print a second BrokenPipeError while flushing on exit.
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except OSError:
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
