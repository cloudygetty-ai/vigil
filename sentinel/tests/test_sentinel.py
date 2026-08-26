"""Tests for VIGIL SENTINEL.

The device probes are exercised against canned adb output, so the parsing and
verdict logic is covered without a phone attached.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("VIGIL_SENTINEL_HOME", tempfile.mkdtemp(prefix="vigil-test-"))

from vigil_sentinel.baseline import Snapshot, diff
from vigil_sentinel.findings import Finding, Report
from vigil_sentinel.report import render_html, Terminal
from vigil_sentinel.shell import Result
from vigil_sentinel.probes import android


class FakeAdb:
    """Stands in for shell.Adb, replaying canned command output."""

    def __init__(self, shell_map=None, props=None, settings=None):
        self.shell_map = shell_map or {}
        self.props = props or {}
        self.settings_map = settings or {}
        self.calls = []

    def shell(self, command, timeout=25):
        self.calls.append(command)
        for needle, output in self.shell_map.items():
            if needle in command:
                return Result(argv=["adb", "shell", command], code=0, out=output)
        return Result(argv=["adb", "shell", command], code=1, err="not stubbed")

    def getprop(self, key):
        return self.props.get(key, "")

    def setting(self, namespace, key):
        return self.settings_map.get(key, "")


class TestFindings(unittest.TestCase):
    def test_score_saturates(self):
        report = Report()
        for i in range(10):
            report.add(Finding(id=f"c{i}", title="x", severity="CRITICAL", category="network"))
        self.assertEqual(report.score(), 100)
        self.assertEqual(report.verdict(), "COMPROMISED")

    def test_clean_device(self):
        report = Report()
        report.add(Finding(id="a", title="fine", severity="OK", category="network"))
        report.add(Finding(id="b", title="fyi", severity="INFO", category="network"))
        self.assertEqual(report.score(), 0)
        self.assertEqual(report.verdict(), "CLEAN")
        self.assertEqual(report.actionable(), [])

    def test_lone_medium_is_not_clean(self):
        """A finding worth acting on must never report CLEAN."""
        report = Report()
        report.add(Finding(id="m", title="x", severity="MEDIUM", category="delivery"))
        self.assertEqual(report.verdict(), "HARDEN")

    def test_single_critical_is_compromised(self):
        report = Report()
        report.add(Finding(id="c", title="x", severity="CRITICAL", category="network"))
        self.assertEqual(report.verdict(), "COMPROMISED")

    def test_severity_ordering(self):
        report = Report()
        report.add(Finding(id="low", title="x", severity="LOW", category="network"))
        report.add(Finding(id="crit", title="x", severity="CRITICAL", category="network"))
        report.add(Finding(id="med", title="x", severity="MEDIUM", category="network"))
        self.assertEqual([f.id for f in report.sorted()], ["crit", "med", "low"])

    def test_rejects_bad_severity(self):
        with self.assertRaises(ValueError):
            Finding(id="x", title="y", severity="SPICY", category="network")


class TestBaseline(unittest.TestCase):
    def test_added_removed_changed(self):
        base = Snapshot("android", "S1")
        base.record("packages", "com.keep", {"v": 1})
        base.record("packages", "com.gone", {"v": 1})
        base.record("packages", "com.mutate", {"v": 1})

        now = Snapshot("android", "S1")
        now.record("packages", "com.keep", {"v": 1})
        now.record("packages", "com.mutate", {"v": 2})
        now.record("packages", "com.new", {"v": 1})

        delta = diff(base, now)
        self.assertEqual(set(delta.added["packages"]), {"com.new"})
        self.assertEqual(set(delta.removed["packages"]), {"com.gone"})
        self.assertEqual(set(delta.changed["packages"]), {"com.mutate"})
        self.assertFalse(delta.empty)

    def test_unobserved_kind_yields_no_phantom_additions(self):
        """A kind the baseline never collected must not read as all-new."""
        base = Snapshot("ios", "U1")          # no files recorded at all
        now = Snapshot("ios", "U1")
        now.record("files", "/DCIM/IMG_1.HEIC", {"dir": "/DCIM"})
        delta = diff(base, now)
        self.assertEqual(delta.added["files"], {})
        self.assertTrue(delta.empty)

    def test_save_load_roundtrip(self):
        snap = Snapshot("android", "ROUNDTRIP")
        snap.record("settings", "adb_wifi_enabled", {"value": "1"})
        snap.save()
        loaded = Snapshot.load("android", "ROUNDTRIP")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.data["settings"]["adb_wifi_enabled"], {"value": "1"})

    def test_load_missing_returns_none(self):
        self.assertIsNone(Snapshot.load("android", "NEVER-EXISTED-XYZ"))


class TestAndroidPackages(unittest.TestCase):
    LISTING = (
        "package:com.whatsapp  installer=com.android.vending\n"
        "package:com.evil.tracker  installer=com.android.packageinstaller\n"
        "package:com.pushed.payload  installer=null\n"
    )
    DUMPSYS = (
        "    firstInstallTime=2026-08-20 14:02:11\n"
        "    lastUpdateTime=2026-08-20 14:02:11\n"
        "    versionName=1.0\n"
        "    android.permission.RECORD_AUDIO: granted=true\n"
        "    android.permission.READ_SMS: granted=true\n"
        "    android.permission.CAMERA: granted=false\n"
    )

    def test_flags_only_non_store_installers(self):
        adb = FakeAdb(shell_map={
            "pm list packages": self.LISTING,
            "dumpsys package": self.DUMPSYS,
        })
        snap = Snapshot("android", "S")
        findings = android.probe_packages(adb, snap)
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.id, "android.packages.sideloaded")
        # Play Store app must not be flagged; the other two must be.
        blob = "\n".join(finding.evidence)
        self.assertNotIn("com.whatsapp", blob)
        self.assertIn("com.evil.tracker", blob)
        self.assertIn("com.pushed.payload", blob)
        # Sensitive granted permissions escalate the severity.
        self.assertEqual(finding.severity, "HIGH")
        self.assertIn("RECORD_AUDIO", blob)
        # granted=false must not be reported as held.
        self.assertNotIn("CAMERA", blob)
        # All three, including the trusted one, land in the snapshot.
        self.assertEqual(len(snap.data["packages"]), 3)

    def test_all_store_installed_is_ok(self):
        adb = FakeAdb(shell_map={
            "pm list packages": "package:com.whatsapp  installer=com.android.vending\n"
        })
        snap = Snapshot("android", "S")
        findings = android.probe_packages(adb, snap)
        self.assertEqual(findings[0].severity, "OK")


class TestAndroidSurfaces(unittest.TestCase):
    def test_adb_over_wifi_is_critical(self):
        adb = FakeAdb(settings={"adb_wifi_enabled": "1"})
        snap = Snapshot("android", "S")
        findings = android.probe_adb_wifi(adb, snap)
        self.assertEqual(findings[0].severity, "CRITICAL")
        self.assertEqual(findings[0].category, "delivery")

    def test_usb_debugging_alone_is_low(self):
        adb = FakeAdb(settings={"adb_enabled": "1"})
        snap = Snapshot("android", "S")
        findings = android.probe_adb_wifi(adb, snap)
        self.assertEqual(findings[0].severity, "LOW")

    def test_tcp_port_also_trips_wifi_debugging(self):
        adb = FakeAdb(settings={}, props={"service.adb.tcp.port": "5555"})
        snap = Snapshot("android", "S")
        findings = android.probe_adb_wifi(adb, snap)
        self.assertEqual(findings[0].severity, "CRITICAL")

    def test_disabled_tcp_port_does_not_trip(self):
        adb = FakeAdb(settings={}, props={"service.adb.tcp.port": "-1"})
        snap = Snapshot("android", "S")
        self.assertEqual(android.probe_adb_wifi(adb, snap), [])

    def test_accessibility_requires_master_switch(self):
        snap = Snapshot("android", "S")
        # Services listed but the master toggle is off - not actually running.
        adb = FakeAdb(settings={
            "enabled_accessibility_services": "com.evil/.Svc",
            "accessibility_enabled": "0",
        })
        self.assertEqual(android.probe_accessibility(adb, snap)[0].severity, "OK")

        adb = FakeAdb(settings={
            "enabled_accessibility_services": "com.evil/.Svc:com.other/.Svc",
            "accessibility_enabled": "1",
        })
        finding = android.probe_accessibility(adb, Snapshot("android", "S"))[0]
        self.assertEqual(finding.severity, "HIGH")
        self.assertEqual(len(finding.evidence), 2)

    def test_device_admin_parsing(self):
        adb = FakeAdb(shell_map={
            "dumpsys device_policy":
                "  admin=ComponentInfo{com.spy.app/com.spy.app.AdminReceiver}\n",
            "dpm list-owners": "No device owner\n",
        })
        finding = android.probe_device_admins(adb, Snapshot("android", "S"))[0]
        self.assertEqual(finding.severity, "HIGH")
        self.assertIn("com.spy.app/com.spy.app.AdminReceiver", finding.evidence)

    def test_global_proxy_is_critical(self):
        adb = FakeAdb(settings={"http_proxy": "10.0.0.5:8080"})
        findings = android.probe_network(adb, Snapshot("android", "S"))
        proxy = [f for f in findings if f.id == "android.net.proxy"]
        self.assertEqual(proxy[0].severity, "CRITICAL")

    def test_unset_proxy_sentinel_is_ignored(self):
        """Android stores 'no proxy' as the literal string ':0'."""
        adb = FakeAdb(settings={"http_proxy": ":0"})
        findings = android.probe_network(adb, Snapshot("android", "S"))
        self.assertEqual([f for f in findings if f.id == "android.net.proxy"], [])

    def test_unlocked_bootloader_is_critical(self):
        adb = FakeAdb(props={"ro.boot.verifiedbootstate": "orange"})
        findings = android.probe_integrity(adb, Snapshot("android", "S"))
        self.assertEqual(findings[0].severity, "CRITICAL")

    def test_green_verified_boot_is_quiet(self):
        adb = FakeAdb(props={"ro.boot.verifiedbootstate": "green", "ro.boot.flash.locked": "1"})
        self.assertEqual(android.probe_integrity(adb, Snapshot("android", "S")), [])


class TestAndroidFiles(unittest.TestCase):
    STAT = (
        "1756000000|4823000|/sdcard/Download/invoice.apk\n"
        "1600000000|120|/sdcard/Download/old-note.txt\n"
    )

    def test_apk_in_downloads_is_flagged_regardless_of_age(self):
        adb = FakeAdb(shell_map={"find /sdcard/Download": self.STAT})
        snap = Snapshot("android", "S")
        findings = android.probe_received_files(adb, snap, window_hours=72)
        exe = [f for f in findings if f.id == "android.files.executable"]
        self.assertEqual(len(exe), 1)
        self.assertEqual(exe[0].severity, "HIGH")
        self.assertIn("invoice.apk", "\n".join(exe[0].evidence))
        # The old .txt is neither executable nor recent, so it raises nothing.
        self.assertNotIn("old-note.txt", "\n".join(exe[0].evidence))
        self.assertIn("/sdcard/Download/invoice.apk", snap.data["files"])

    def test_probe_survives_missing_directories(self):
        adb = FakeAdb(shell_map={})       # every find fails
        findings = android.probe_received_files(adb, Snapshot("android", "S"))
        self.assertEqual(findings, [])


class TestAndroidRunner(unittest.TestCase):
    def test_run_isolates_probe_failures(self):
        class Exploding(FakeAdb):
            def setting(self, namespace, key):
                raise RuntimeError("adb died")

        # Package listing still works, so probes not touching settings must survive.
        adb = Exploding(shell_map={
            "pm list packages": "package:com.whatsapp  installer=com.android.vending\n"
        })
        findings = android.run(adb, Snapshot("android", "S"))
        errors = [f for f in findings if f.id == "android.probe.error"]
        self.assertTrue(errors, "a failing probe should be reported, not raised")
        # Probes that do not depend on the broken call still produced findings.
        self.assertTrue(len(findings) > len(errors))


class TestReportRendering(unittest.TestCase):
    def _report(self):
        report = Report()
        report.add(Finding(
            id="x", title="Something <script>alert(1)</script> bad", severity="CRITICAL",
            category="delivery", detail="d", evidence=["ev & <tag>"], remediation="fix it",
        ))
        return report

    def test_html_escapes_untrusted_text(self):
        html = render_html(self._report(), None, "Pixel & <b>")
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("Pixel &amp; &lt;b&gt;", html)

    def test_html_is_self_contained(self):
        html = render_html(self._report(), None, "dev")
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertNotIn("http://", html.replace("http://www.w3.org", ""))

    def test_terminal_render_without_color(self):
        import io
        buf = io.StringIO()
        term = Terminal(buf)
        term.color = False
        report = self._report()
        term.verdict(report)
        term.findings(report)
        text = buf.getvalue()
        self.assertIn("COMPROMISED", text)   # one CRITICAL is enough on its own
        self.assertIn("fix it", text)
        self.assertNotIn("\033[", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
