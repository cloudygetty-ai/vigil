"""Finding model, severity ordering and threat scoring."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict


# Ordered worst-first. Index doubles as sort key.
SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO", "OK"]

# Contribution to the 0-100 threat score.
_WEIGHT = {"CRITICAL": 40, "HIGH": 20, "MEDIUM": 8, "LOW": 3, "INFO": 0, "OK": 0}

# Probe families, used to group the report.
CATEGORIES = [
    "delivery",    # how something arrived: AirDrop, Quick Share, Bluetooth, USB
    "persistence", # what stayed behind: apps, profiles, admins
    "surveillance",# what can watch you: accessibility, notification listeners
    "network",     # MITM, ARP spoofing, rogue DNS, ADB over WiFi
    "integrity",   # bootloader, root, verified boot
    "exposure",    # settings that leave you open to the next attempt
]


@dataclass
class Finding:
    """One observation about the device.

    `evidence` holds the raw strings the verdict was drawn from, so nothing in
    the report is unfalsifiable - the user can always see what was read.
    """

    id: str
    title: str
    severity: str
    category: str
    detail: str = ""
    evidence: list = field(default_factory=list)
    remediation: str = ""
    probe: str = ""

    def __post_init__(self):
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity {self.severity!r}")
        if self.category not in CATEGORIES:
            raise ValueError(f"unknown category {self.category!r}")

    @property
    def rank(self) -> int:
        return SEVERITIES.index(self.severity)

    def to_dict(self) -> dict:
        return asdict(self)


class Report:
    """Collects findings from every probe and scores the device."""

    def __init__(self, target: str = "unknown"):
        self.target = target
        self.findings: list = []
        self.skipped: list = []   # (probe, reason) for probes that could not run

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def skip(self, probe: str, reason: str) -> None:
        self.skipped.append((probe, reason))

    def extend(self, findings) -> None:
        for f in findings:
            self.add(f)

    def sorted(self) -> list:
        return sorted(self.findings, key=lambda f: (f.rank, f.category, f.id))

    def actionable(self) -> list:
        """Findings worth a human's attention - everything above INFO."""
        return [f for f in self.sorted() if f.severity not in ("INFO", "OK")]

    def counts(self) -> dict:
        out = {s: 0 for s in SEVERITIES}
        for f in self.findings:
            out[f.severity] += 1
        return out

    def score(self) -> int:
        """0 (clean) to 100 (thoroughly compromised).

        Saturating rather than linear: three CRITICALs is already as bad as the
        scale goes, and piling on more shouldn't imply precision we don't have.
        """
        raw = sum(_WEIGHT[f.severity] for f in self.findings)
        return min(100, raw)

    def verdict(self) -> str:
        score = self.score()
        # Any single CRITICAL is unambiguous on its own - an unlocked bootloader,
        # an interception proxy, wireless debugging left on. None of those are
        # judgement calls, so one is enough regardless of what the score adds to.
        if score >= 60 or self.counts()["CRITICAL"]:
            return "COMPROMISED"
        if score >= 30:
            return "SUSPICIOUS"
        # CLEAN must mean "nothing to act on". A lone MEDIUM scores below the
        # HARDEN threshold, and reporting that as clean would bury a real finding.
        if score >= 10 or self.actionable():
            return "HARDEN"
        return "CLEAN"
