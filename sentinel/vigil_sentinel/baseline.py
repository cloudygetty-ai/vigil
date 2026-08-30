"""Snapshot and diff of device state.

This is the heart of the tool. A single scan can only flag things that look
wrong in the abstract; a diff against a known-good snapshot answers the actual
question - "did something land on this phone since Tuesday?"
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field

# Sets of observations we track over time. Each is a dict of id -> attributes.
TRACKED = ["packages", "files", "profiles", "settings", "certificates", "pairings"]

_SNAPSHOT_VERSION = 1


def store_dir() -> str:
    """Where snapshots live. Honours VIGIL_SENTINEL_HOME for testing."""
    root = os.environ.get("VIGIL_SENTINEL_HOME") or os.path.join(
        os.path.expanduser("~"), ".vigil-sentinel"
    )
    path = os.path.join(root, "snapshots")
    os.makedirs(path, exist_ok=True)
    return path


def _slug(platform: str, serial: str) -> str:
    # Serials and UDIDs identify hardware; hash them so the filename on disk
    # isn't itself a piece of PII sitting in the user's home directory.
    digest = hashlib.sha256(serial.encode()).hexdigest()[:16]
    return f"{platform}-{digest}.json"


@dataclass
class Snapshot:
    platform: str
    serial: str
    taken_at: float = field(default_factory=time.time)
    label: str = ""
    data: dict = field(default_factory=lambda: {k: {} for k in TRACKED})

    def record(self, kind: str, key: str, attrs: dict) -> None:
        if kind not in TRACKED:
            raise ValueError(f"untracked kind {kind!r}")
        self.data.setdefault(kind, {})[key] = attrs

    def to_json(self) -> dict:
        return {
            "version": _SNAPSHOT_VERSION,
            "platform": self.platform,
            "serial": self.serial,
            "label": self.label,
            "taken_at": self.taken_at,
            "data": self.data,
        }

    @classmethod
    def from_json(cls, blob: dict) -> "Snapshot":
        snap = cls(
            platform=blob.get("platform", "unknown"),
            serial=blob.get("serial", ""),
            taken_at=blob.get("taken_at", 0.0),
            label=blob.get("label", ""),
        )
        snap.data = {k: blob.get("data", {}).get(k, {}) for k in TRACKED}
        return snap

    def save(self) -> str:
        path = os.path.join(store_dir(), _slug(self.platform, self.serial))
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self.to_json(), fh, indent=2, sort_keys=True)
        os.replace(tmp, path)   # atomic, so an interrupted save can't corrupt the baseline
        return path

    @classmethod
    def load(cls, platform: str, serial: str) -> "Snapshot":
        path = os.path.join(store_dir(), _slug(platform, serial))
        if not os.path.exists(path):
            return None
        try:
            with open(path) as fh:
                return cls.from_json(json.load(fh))
        except (ValueError, OSError):
            return None


@dataclass
class Delta:
    """What changed between two snapshots, per tracked kind."""

    added: dict = field(default_factory=lambda: {k: {} for k in TRACKED})
    removed: dict = field(default_factory=lambda: {k: {} for k in TRACKED})
    changed: dict = field(default_factory=lambda: {k: {} for k in TRACKED})
    baseline_at: float = 0.0

    @property
    def empty(self) -> bool:
        return not any(
            self.added[k] or self.removed[k] or self.changed[k] for k in TRACKED
        )

    def count(self, kind: str) -> int:
        return len(self.added[kind]) + len(self.removed[kind]) + len(self.changed[kind])


def diff(baseline: Snapshot, current: Snapshot) -> Delta:
    """Compare two snapshots.

    Only keys present in *both* snapshots' tracked kinds are compared for
    change; a kind the baseline never collected (because a tool was missing
    that day) yields no phantom additions.
    """
    delta = Delta(baseline_at=baseline.taken_at)
    for kind in TRACKED:
        old = baseline.data.get(kind) or {}
        new = current.data.get(kind) or {}
        if not old and not new:
            continue
        if not old:
            # Baseline never observed this kind - can't call anything "new".
            continue
        for key, attrs in new.items():
            if key not in old:
                delta.added[kind][key] = attrs
            elif old[key] != attrs:
                delta.changed[kind][key] = {"before": old[key], "after": attrs}
        for key, attrs in old.items():
            if key not in new:
                delta.removed[kind][key] = attrs
    return delta
