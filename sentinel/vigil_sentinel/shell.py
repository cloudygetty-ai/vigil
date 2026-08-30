"""Subprocess plumbing and external-tool discovery.

Every probe funnels through run() so that a missing tool, a hung device or a
non-zero exit is a value we can reason about rather than an exception that
aborts the scan.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field


DEFAULT_TIMEOUT = 25


@dataclass
class Result:
    """Outcome of one external command."""

    argv: list = field(default_factory=list)
    code: int = -1
    out: str = ""
    err: str = ""
    timed_out: bool = False
    missing: bool = False

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.timed_out and not self.missing

    @property
    def lines(self) -> list:
        return [ln.rstrip() for ln in self.out.splitlines() if ln.strip()]

    def __bool__(self) -> bool:
        return self.ok


def have(tool: str) -> bool:
    """True when `tool` is on PATH."""
    return shutil.which(tool) is not None


def run(argv, timeout: int = DEFAULT_TIMEOUT, stdin: str = None) -> Result:
    """Run argv, capturing output. Never raises for ordinary failures."""
    argv = [str(a) for a in argv]
    if not have(argv[0]):
        return Result(argv=argv, missing=True, err=f"{argv[0]} not found on PATH")
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            input=stdin,
        )
    except subprocess.TimeoutExpired:
        return Result(argv=argv, timed_out=True, err=f"timed out after {timeout}s")
    except OSError as exc:
        return Result(argv=argv, err=str(exc))
    return Result(argv=argv, code=proc.returncode, out=proc.stdout or "", err=proc.stderr or "")


class Adb:
    """Thin adb wrapper bound to one device serial."""

    def __init__(self, serial: str = None):
        self.serial = serial

    def _base(self) -> list:
        return ["adb"] + (["-s", self.serial] if self.serial else [])

    def raw(self, *args, timeout: int = DEFAULT_TIMEOUT) -> Result:
        return run(self._base() + list(args), timeout=timeout)

    def shell(self, command: str, timeout: int = DEFAULT_TIMEOUT) -> Result:
        return run(self._base() + ["shell", command], timeout=timeout)

    def getprop(self, key: str) -> str:
        res = self.shell(f"getprop {key}")
        return res.out.strip() if res.ok else ""

    def setting(self, namespace: str, key: str) -> str:
        """Read a Settings.{Global,Secure,System} value. '' when unset."""
        res = self.shell(f"settings get {namespace} {key}")
        if not res.ok:
            return ""
        val = res.out.strip()
        return "" if val in ("null", "") else val
