"""Host-side network probes.

These run on the computer, not the phone, and answer a different question:
is the network you are both sitting on being tampered with? ARP spoofing, a
rogue DNS resolver and a TLS-intercepting proxy are the three ways a WiFi
attacker reads or rewrites traffic without ever touching the device.
"""

from __future__ import annotations

import re
import socket
import ssl

from ..findings import Finding
from ..shell import run, have


# Issuer organisations that legitimately appear in public certificate chains.
# A chain terminating anywhere else on a major site means something local is
# re-signing traffic.
PUBLIC_CA_HINTS = (
    "DigiCert", "Let's Encrypt", "GlobalSign", "Sectigo", "Comodo", "Amazon",
    "Google Trust Services", "GTS", "ISRG", "Baltimore", "Entrust", "GeoTrust",
    "Thawte", "VeriSign", "Cloudflare", "Microsoft", "Apple",
)

# Names that give away a corporate or attacker interception appliance.
INTERCEPTOR_HINTS = (
    "mitmproxy", "Charles", "Fiddler", "Burp", "Zscaler", "Netskope", "Blue Coat",
    "Bluecoat", "Forcepoint", "Palo Alto", "FortiGate", "Fortinet", "Squid",
    "Kaspersky", "Bitdefender", "ESET", "Avast", "AVG", "Sophos",
)

CANARY_HOST = "www.cloudflare.com"
CANARY_DNS_NAME = "one.one.one.one"
CANARY_DNS_EXPECTED = {"1.1.1.1", "1.0.0.1"}


def _arp_table() -> list:
    """[(ip, mac)] from whichever tool this OS ships."""
    for argv in (["ip", "neigh", "show"], ["arp", "-an"]):
        if not have(argv[0]):
            continue
        res = run(argv, timeout=15)
        if not res.ok:
            continue
        pairs = []
        for line in res.lines:
            ip_match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", line)
            mac_match = re.search(r"([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})", line)
            if ip_match and mac_match:
                pairs.append((ip_match.group(1), mac_match.group(1).lower()))
        if pairs:
            return pairs
    return []


def _default_gateway() -> str:
    for argv in (["ip", "route", "show", "default"], ["route", "-n", "get", "default"]):
        if not have(argv[0]):
            continue
        res = run(argv, timeout=15)
        if not res.ok:
            continue
        match = re.search(r"(?:via|gateway:)\s+(\d{1,3}(?:\.\d{1,3}){3})", res.out)
        if match:
            return match.group(1)
    return ""


def probe_arp(snap) -> list:
    """Two IPs sharing one MAC is the signature of an ARP spoof."""
    table = _arp_table()
    if not table:
        return []

    gateway = _default_gateway()
    by_mac = {}
    for ip, mac in table:
        by_mac.setdefault(mac, []).append(ip)
        snap.record("settings", f"arp::{ip}", {"mac": mac})

    findings = []
    # Ignore broadcast/unset placeholders that legitimately repeat.
    collisions = {
        mac: sorted(set(ips)) for mac, ips in by_mac.items()
        if len(set(ips)) > 1 and mac not in ("ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00")
    }
    if collisions:
        evidence = [f"{mac}  claims  {', '.join(ips)}" for mac, ips in collisions.items()]
        gateway_involved = any(gateway in ips for ips in collisions.values())
        findings.append(Finding(
            id="net.arp.collision",
            title=f"{len(collisions)} MAC address(es) claim more than one IP",
            severity="CRITICAL" if gateway_involved else "HIGH",
            category="network",
            detail=(
                "One network card answering for several addresses is what ARP "
                "spoofing looks like: a machine on this WiFi is telling everyone it "
                "is the router, so your traffic flows through it first."
                + (" The default gateway is one of the impersonated addresses, which "
                   "makes this almost certainly an active interception."
                   if gateway_involved else
                   " This can also be a router with several interfaces, so confirm "
                   "before acting.")
            ),
            evidence=evidence,
            remediation=(
                "Disconnect from this network. Use cellular data or a trusted VPN "
                "until you are off it, and do not enter credentials while connected."
            ),
            probe="arp",
        ))

    if gateway:
        gw_mac = next((mac for ip, mac in table if ip == gateway), "")
        if gw_mac:
            snap.record("settings", "gateway", {"ip": gateway, "mac": gw_mac})
            findings.append(Finding(
                id="net.gateway",
                title=f"Default gateway {gateway} at {gw_mac}",
                severity="INFO",
                category="network",
                detail=(
                    "Recorded for comparison. If this MAC changes while the network "
                    "name stays the same, you are on a different router than before - "
                    "the signature of an evil-twin access point."
                ),
                probe="arp",
            ))
    return findings


def probe_dns(snap) -> list:
    """Resolve a name whose correct answer is fixed worldwide."""
    try:
        local = sorted({r[4][0] for r in socket.getaddrinfo(CANARY_DNS_NAME, None, socket.AF_INET)})
    except (socket.gaierror, OSError) as exc:
        return [Finding(
            id="net.dns.unreachable",
            title=f"Could not resolve {CANARY_DNS_NAME}: {exc}",
            severity="INFO",
            category="network",
            probe="dns",
        )]

    snap.record("settings", "dns_canary", {"answer": local})

    if not set(local) & CANARY_DNS_EXPECTED:
        return [Finding(
            id="net.dns.hijack",
            title=f"DNS returned an unexpected answer for {CANARY_DNS_NAME}",
            severity="HIGH",
            category="network",
            detail=(
                f"{CANARY_DNS_NAME} resolves to 1.1.1.1 and 1.0.0.1 everywhere in the "
                f"world. This network answered with {', '.join(local)} instead, which "
                "means a resolver here is rewriting DNS - the usual setup for a "
                "captive portal, a filtering appliance, or redirection to a fake site."
            ),
            evidence=[f"resolved: {', '.join(local)}", "expected: 1.1.1.1, 1.0.0.1"],
            remediation=(
                "If you did not expect a captive portal, leave this network. "
                "Set DNS-over-HTTPS in your browser and phone to make rewriting harder."
            ),
            probe="dns",
        )]
    return [Finding(
        id="net.dns.clean",
        title="DNS resolution is not being rewritten",
        severity="OK",
        category="network",
        probe="dns",
    )]


def probe_tls_interception(snap) -> list:
    """Read the certificate chain of a known host and inspect its issuer."""
    context = ssl.create_default_context()
    try:
        with socket.create_connection((CANARY_HOST, 443), timeout=12) as sock:
            with context.wrap_socket(sock, server_hostname=CANARY_HOST) as tls:
                cert = tls.getpeercert()
    except ssl.SSLCertVerificationError as exc:
        return [Finding(
            id="net.tls.verifyfail",
            title=f"TLS certificate for {CANARY_HOST} failed verification",
            severity="CRITICAL",
            category="network",
            detail=(
                "The certificate this network served for a major site does not "
                "validate. Either something is actively impersonating it, or an "
                "interception proxy is present whose root certificate this computer "
                "does not trust."
            ),
            evidence=[str(exc)],
            remediation="Leave this network now. Do not click through the warning.",
            probe="tls",
        )]
    except (OSError, ssl.SSLError) as exc:
        return [Finding(
            id="net.tls.unreachable",
            title=f"Could not complete a TLS handshake with {CANARY_HOST}: {exc}",
            severity="INFO",
            category="network",
            probe="tls",
        )]

    issuer_parts = []
    for rdn in cert.get("issuer", ()):
        for key, value in rdn:
            if key in ("organizationName", "commonName"):
                issuer_parts.append(str(value))
    issuer = " / ".join(issuer_parts) or "unknown"
    snap.record("certificates", CANARY_HOST, {"issuer": issuer})

    named = next((n for n in INTERCEPTOR_HINTS if n.lower() in issuer.lower()), None)
    if named:
        return [Finding(
            id="net.tls.interceptor",
            title=f"HTTPS is being intercepted by {named}",
            severity="CRITICAL",
            category="network",
            detail=(
                "The certificate for a major public site was issued by an "
                "interception product, not a public certificate authority. Everything "
                "you send over HTTPS on this connection is being decrypted and "
                "re-encrypted by whoever runs it."
            ),
            evidence=[f"issuer: {issuer}"],
            remediation=(
                "Leave this network. Then check your trust store for a root "
                "certificate you did not install and remove it."
            ),
            probe="tls",
        )]

    if not any(hint.lower() in issuer.lower() for hint in PUBLIC_CA_HINTS):
        return [Finding(
            id="net.tls.unknownca",
            title=f"HTTPS certificate issued by an unrecognised authority: {issuer}",
            severity="HIGH",
            category="network",
            detail=(
                "The issuer of this certificate is not one of the public authorities "
                "that normally sign major sites. That points to a locally installed "
                "root certificate re-signing your traffic."
            ),
            evidence=[f"issuer: {issuer}"],
            remediation="Inspect your system and browser trust stores for an unfamiliar root CA.",
            probe="tls",
        )]

    return [Finding(
        id="net.tls.clean",
        title=f"HTTPS is not being intercepted (issuer: {issuer})",
        severity="OK",
        category="network",
        probe="tls",
    )]


def run(snap) -> list:
    findings = []
    for probe in (lambda: probe_arp(snap), lambda: probe_dns(snap), lambda: probe_tls_interception(snap)):
        try:
            findings.extend(probe())
        except Exception as exc:
            findings.append(Finding(
                id="net.probe.error",
                title=f"A network probe failed: {exc}",
                severity="INFO",
                category="network",
                probe="internal",
            ))
    return findings
