"""Rendering: ANSI terminal output and a standalone HTML report."""

from __future__ import annotations

import html
import os
import sys
import time

from .findings import SEVERITIES, CATEGORIES
from .baseline import TRACKED


_ANSI = {
    "CRITICAL": "\033[97;41m",
    "HIGH": "\033[38;5;208m",
    "MEDIUM": "\033[38;5;220m",
    "LOW": "\033[38;5;110m",
    "INFO": "\033[38;5;245m",
    "OK": "\033[38;5;77m",
}
_RESET = "\033[0m"
_DIM = "\033[38;5;240m"
_BOLD = "\033[1m"

_VERDICT_ANSI = {
    "COMPROMISED": "\033[97;41m",
    "SUSPICIOUS": "\033[30;48;5;208m",
    "HARDEN": "\033[30;48;5;220m",
    "CLEAN": "\033[30;48;5;77m",
}

CATEGORY_TITLES = {
    "delivery": "DELIVERY - how something got onto the device",
    "persistence": "PERSISTENCE - what stayed behind",
    "surveillance": "SURVEILLANCE - what can watch you",
    "network": "NETWORK - interception and rogue infrastructure",
    "integrity": "INTEGRITY - is the OS itself trustworthy",
    "exposure": "EXPOSURE - what leaves you open to the next attempt",
}


def _color_enabled(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return hasattr(stream, "isatty") and stream.isatty()


class Terminal:
    def __init__(self, stream=None):
        self.stream = stream or sys.stdout
        self.color = _color_enabled(self.stream)

    def _c(self, text: str, code: str) -> str:
        return f"{code}{text}{_RESET}" if self.color else text

    def write(self, text: str = "") -> None:
        self.stream.write(text + "\n")

    def rule(self, char: str = "-") -> None:
        self.write(self._c(char * 74, _DIM))

    def header(self, report, device_label: str) -> None:
        self.write()
        self.write(self._c("  VIGIL SENTINEL", _BOLD))
        self.write(self._c(f"  {device_label}", _DIM))
        self.write(self._c(f"  {time.strftime('%Y-%m-%d %H:%M:%S')}", _DIM))
        self.write()

    def verdict(self, report) -> None:
        score = report.score()
        verdict = report.verdict()
        badge = self._c(f"  {verdict}  ", _VERDICT_ANSI.get(verdict, ""))
        self.rule("=")
        self.write(f"  {badge}   threat score {score}/100")
        counts = report.counts()
        summary = "   ".join(
            self._c(f"{sev} {counts[sev]}", _ANSI[sev])
            for sev in SEVERITIES if counts[sev]
        )
        if summary:
            self.write(f"  {summary}")
        self.rule("=")

    def findings(self, report, show_all: bool = False) -> None:
        items = report.sorted() if show_all else report.actionable()
        if not items:
            self.write()
            self.write(self._c("  Nothing actionable found.", _ANSI["OK"]))
            return

        for category in CATEGORIES:
            group = [f for f in items if f.category == category]
            if not group:
                continue
            self.write()
            self.write(self._c(f"  {CATEGORY_TITLES[category]}", _BOLD))
            self.rule()
            for finding in group:
                tag = self._c(f" {finding.severity:^8} ", _ANSI[finding.severity])
                self.write(f"  {tag}  {finding.title}")
                if finding.detail:
                    for line in _wrap(finding.detail, 66):
                        self.write(self._c(f"            {line}", _DIM))
                for line in finding.evidence[:12]:
                    for sub in str(line).splitlines():
                        self.write(self._c(f"            > {sub}", _DIM))
                if len(finding.evidence) > 12:
                    self.write(self._c(f"            > ... {len(finding.evidence) - 12} more", _DIM))
                if finding.remediation:
                    for line in finding.remediation.splitlines():
                        self.write(self._c(f"            FIX  {line}", _ANSI["OK"]))
                self.write()

    def delta(self, delta) -> None:
        if delta is None:
            self.write()
            self.write(self._c("  No baseline yet. Re-run with --baseline to record one,", _DIM))
            self.write(self._c("  then this section will list everything that appeared since.", _DIM))
            return
        self.write()
        self.write(self._c("  CHANGES SINCE BASELINE", _BOLD))
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(delta.baseline_at))
        self.write(self._c(f"  baseline taken {when}", _DIM))
        self.rule()
        if delta.empty:
            self.write(self._c("  Nothing changed. No new apps, files, profiles or settings.", _ANSI["OK"]))
            return
        for kind in TRACKED:
            for label, bucket, code in (
                ("NEW", delta.added[kind], _ANSI["HIGH"]),
                ("GONE", delta.removed[kind], _ANSI["INFO"]),
                ("CHANGED", delta.changed[kind], _ANSI["MEDIUM"]),
            ):
                for key in sorted(bucket)[:25]:
                    self.write(f"  {self._c(f'{label:>7}', code)}  {kind[:-1]:<12} {key}")
                if len(bucket) > 25:
                    self.write(self._c(f"          ... {len(bucket) - 25} more {kind}", _DIM))

    def gaps(self, report) -> None:
        if not report.skipped:
            return
        self.write()
        self.write(self._c("  NOT CHECKED", _BOLD))
        self.rule()
        for probe, reason in report.skipped:
            self.write(self._c(f"  {probe}: {reason}", _DIM))


def _wrap(text: str, width: int) -> list:
    words = text.split()
    lines, current = [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

_HTML_HEAD = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VIGIL SENTINEL - {label}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
:root{{--s0:#04070a;--s1:#090d12;--s2:#0f1520;--s3:#16202e;--s4:#1e2d3d;
--tx0:#dde6f0;--tx1:#7a8fa6;--tx2:#2e4057;--cyan:#00d4ff;
--crit:#ef4444;--high:#f97316;--med:#f59e0b;--low:#60a5fa;--info:#64748b;--ok:#22d66c}}
body{{background:var(--s0);color:var(--tx0);font:14px/1.6 ui-monospace,"DM Mono",Menlo,monospace;padding:32px 20px;max-width:1000px;margin:0 auto}}
h1{{font-size:26px;letter-spacing:.16em;font-weight:600}}
h2{{font-size:12px;letter-spacing:.2em;color:var(--tx1);text-transform:uppercase;margin:34px 0 12px;padding-bottom:8px;border-bottom:1px solid var(--s4)}}
.sub{{color:var(--tx1);font-size:12px;margin-top:4px}}
.verdict{{display:flex;align-items:center;gap:18px;background:var(--s2);border:1px solid var(--s4);border-radius:12px;padding:20px 22px;margin:22px 0}}
.badge{{font-size:20px;letter-spacing:.14em;padding:10px 18px;border-radius:8px;font-weight:700;color:#04070a}}
.score{{font-size:34px;font-weight:700}}
.counts{{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;margin-left:auto}}
.f{{background:var(--s1);border:1px solid var(--s4);border-left-width:3px;border-radius:9px;padding:15px 17px;margin-bottom:11px}}
.f h3{{font-size:14px;font-weight:600;display:flex;gap:11px;align-items:baseline}}
.sev{{font-size:10px;letter-spacing:.13em;padding:3px 8px;border-radius:4px;color:#04070a;font-weight:700;flex-shrink:0}}
.detail{{color:var(--tx1);font-size:13px;margin-top:9px}}
.ev{{background:#05080c;border:1px solid var(--s3);border-radius:6px;padding:9px 12px;margin-top:10px;font-size:12px;color:var(--tx1);white-space:pre-wrap;word-break:break-all;overflow-x:auto}}
.fix{{margin-top:10px;font-size:12.5px;color:var(--ok);white-space:pre-wrap;border-left:2px solid var(--ok);padding-left:11px}}
.delta td{{padding:5px 12px 5px 0;font-size:12.5px;border-bottom:1px solid var(--s2)}}
.delta{{width:100%;border-collapse:collapse}}
.tag{{font-size:10px;letter-spacing:.1em;padding:2px 7px;border-radius:3px;color:#04070a;font-weight:700}}
footer{{margin-top:44px;color:var(--tx2);font-size:11px;border-top:1px solid var(--s3);padding-top:16px}}
@media(prefers-color-scheme:light){{body{{background:#f6f8fa;color:#0f1520}}
.f,.verdict{{background:#fff;border-color:#d6dee8}}.ev{{background:#f0f3f7;border-color:#dde3ea;color:#41556b}}
h1{{color:#0f1520}}.sub,.detail{{color:#5a6b7d}}}}
</style></head><body>
"""

_SEV_HEX = {
    "CRITICAL": "#ef4444", "HIGH": "#f97316", "MEDIUM": "#f59e0b",
    "LOW": "#60a5fa", "INFO": "#64748b", "OK": "#22d66c",
}
_VERDICT_HEX = {
    "COMPROMISED": "#ef4444", "SUSPICIOUS": "#f97316",
    "HARDEN": "#f59e0b", "CLEAN": "#22d66c",
}


def render_html(report, delta, device_label: str) -> str:
    esc = html.escape
    out = [_HTML_HEAD.format(label=esc(device_label))]
    out.append(f"<h1>VIGIL SENTINEL</h1>")
    out.append(f'<div class="sub">{esc(device_label)} &middot; '
               f'{time.strftime("%Y-%m-%d %H:%M:%S")}</div>')

    verdict = report.verdict()
    counts = report.counts()
    out.append('<div class="verdict">')
    out.append(f'<span class="badge" style="background:{_VERDICT_HEX[verdict]}">{verdict}</span>')
    out.append(f'<span class="score">{report.score()}<span style="font-size:15px;color:var(--tx1)">/100</span></span>')
    out.append('<span class="counts">')
    for sev in SEVERITIES:
        if counts[sev]:
            out.append(f'<span style="color:{_SEV_HEX[sev]}">{sev} {counts[sev]}</span>')
    out.append("</span></div>")

    # Changes since baseline come first: it is the question the user actually asked.
    out.append("<h2>Changes since baseline</h2>")
    if delta is None:
        out.append('<div class="detail">No baseline recorded yet. Run with '
                   '<code>--baseline</code> to store one; every later scan will list '
                   'exactly what appeared in between.</div>')
    elif delta.empty:
        out.append('<div class="detail" style="color:var(--ok)">Nothing changed since the '
                   'baseline. No new apps, files, profiles or settings.</div>')
    else:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(delta.baseline_at))
        out.append(f'<div class="sub">baseline taken {when}</div><table class="delta">')
        for kind in TRACKED:
            for label, bucket, hexc in (("NEW", delta.added[kind], "#f97316"),
                                        ("GONE", delta.removed[kind], "#64748b"),
                                        ("CHANGED", delta.changed[kind], "#f59e0b")):
                for key in sorted(bucket)[:60]:
                    out.append(f'<tr><td><span class="tag" style="background:{hexc}">{label}</span></td>'
                               f'<td style="color:var(--tx1)">{esc(kind[:-1])}</td>'
                               f'<td>{esc(str(key))}</td></tr>')
        out.append("</table>")

    for category in CATEGORIES:
        group = [f for f in report.sorted() if f.category == category]
        if not group:
            continue
        out.append(f"<h2>{esc(CATEGORY_TITLES[category])}</h2>")
        for finding in group:
            hexc = _SEV_HEX[finding.severity]
            out.append(f'<div class="f" style="border-left-color:{hexc}">')
            out.append(f'<h3><span class="sev" style="background:{hexc}">{finding.severity}</span>'
                       f'<span>{esc(finding.title)}</span></h3>')
            if finding.detail:
                out.append(f'<div class="detail">{esc(finding.detail)}</div>')
            if finding.evidence:
                body = "\n".join(esc(str(e)) for e in finding.evidence[:60])
                out.append(f'<div class="ev">{body}</div>')
            if finding.remediation:
                out.append(f'<div class="fix">{esc(finding.remediation)}</div>')
            out.append("</div>")

    if report.skipped:
        out.append("<h2>Not checked</h2>")
        for probe, reason in report.skipped:
            out.append(f'<div class="detail">{esc(probe)}: {esc(reason)}</div>')

    out.append('<footer>VIGIL SENTINEL reads live device and network state over USB. '
               'Every verdict above is shown with the raw evidence it was drawn from. '
               'iOS does not permit arbitrary file enumeration, so an AirDropped file '
               'saved inside an app container is not visible to any tool - on-device or '
               'otherwise.</footer></body></html>')
    return "\n".join(out)
