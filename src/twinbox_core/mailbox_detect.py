#!/usr/bin/env python3
"""
Mailbox server auto-detection with TLS validation.

Priority:
1. mail.* host that serves both IMAP and SMTP (simplest config)
2. imap.* + smtp.* separate hosts (standard naming)
3. mx.* fallback
"""
import socket
import ssl
from dataclasses import dataclass
from typing import Optional


@dataclass
class ServerCandidate:
    host: str
    port: int
    protocol: str  # "imap" or "smtp"
    tcp_ok: bool = False
    tls_ok: bool = False
    protocol_ok: bool = False
    error: Optional[str] = None


@dataclass
class DetectedConfig:
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    confidence: str  # "high" | "medium" | "low"
    note: str = ""


def extract_domain(email: str) -> str:
    return email.split("@")[-1]


def generate_candidates(domain: str) -> list[ServerCandidate]:
    """Generate candidate hosts in priority order."""
    candidates = []
    # mail.* first (often single-host for both IMAP+SMTP, common in enterprise)
    for port in [993, 143]:
        candidates.append(ServerCandidate(f"mail.{domain}", port, "imap"))
    for port in [465, 587]:
        candidates.append(ServerCandidate(f"mail.{domain}", port, "smtp"))
    # standard imap.*/smtp.* naming
    for port in [993, 143]:
        candidates.append(ServerCandidate(f"imap.{domain}", port, "imap"))
    for port in [465, 587]:
        candidates.append(ServerCandidate(f"smtp.{domain}", port, "smtp"))
    # mx.* fallback
    candidates.append(ServerCandidate(f"mx.{domain}", 993, "imap"))
    candidates.append(ServerCandidate(f"mx.{domain}", 465, "smtp"))
    return candidates


def probe_tcp(host: str, port: int, timeout: float = 3.0) -> tuple[bool, Optional[str]]:
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True, None
    except socket.gaierror as e:
        return False, f"DNS: {e}"
    except socket.timeout:
        return False, "timeout"
    except OSError as e:
        return False, str(e)


def probe_tls(host: str, port: int, timeout: float = 5.0) -> tuple[bool, Optional[str]]:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host):
                return True, None
    except ssl.SSLError as e:
        return False, f"TLS: {e.reason}"
    except OSError as e:
        return False, str(e)


def probe_imap_banner(host: str, port: int, timeout: float = 5.0) -> tuple[bool, Optional[str]]:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                banner = ssock.recv(1024).decode("utf-8", errors="ignore")
                if "* OK" in banner or "IMAP" in banner.upper():
                    return True, None
                return False, f"bad banner: {banner[:60]!r}"
    except OSError as e:
        return False, str(e)


def probe_smtp_banner(host: str, port: int, timeout: float = 5.0) -> tuple[bool, Optional[str]]:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                banner = ssock.recv(1024).decode("utf-8", errors="ignore")
                if banner.startswith("220") or "ESMTP" in banner:
                    return True, None
                return False, f"bad banner: {banner[:60]!r}"
    except OSError as e:
        return False, str(e)


def probe_candidate(c: ServerCandidate) -> ServerCandidate:
    c.tcp_ok, err = probe_tcp(c.host, c.port)
    if not c.tcp_ok:
        c.error = err
        return c
    c.tls_ok, err = probe_tls(c.host, c.port)
    if not c.tls_ok:
        c.error = err
        return c
    if c.protocol == "imap":
        c.protocol_ok, err = probe_imap_banner(c.host, c.port)
    else:
        c.protocol_ok, err = probe_smtp_banner(c.host, c.port)
    if not c.protocol_ok:
        c.error = err
    return c


def detect(email: str, verbose: bool = False) -> Optional[DetectedConfig]:
    """
    Probe candidates and return the best config.
    Prefers mail.* unified host when it works for both protocols.
    """
    domain = extract_domain(email)
    candidates = generate_candidates(domain)

    results: list[ServerCandidate] = []
    for c in candidates:
        r = probe_candidate(c)
        results.append(r)
        if verbose:
            status = "OK" if r.protocol_ok else ("TLS_FAIL" if r.tcp_ok else "TCP_FAIL")
            print(f"  {r.protocol.upper():4} {r.host}:{r.port}  {status}  {r.error or ''}")

    ok_imap = [r for r in results if r.protocol == "imap" and r.protocol_ok]
    ok_smtp = [r for r in results if r.protocol == "smtp" and r.protocol_ok]

    if not ok_imap or not ok_smtp:
        return None

    best_imap = ok_imap[0]
    best_smtp = ok_smtp[0]

    # If mail.* works for both, prefer unified host (simpler config)
    mail_imap = next((r for r in ok_imap if r.host.startswith("mail.")), None)
    mail_smtp = next((r for r in ok_smtp if r.host.startswith("mail.")), None)

    if mail_imap and mail_smtp and mail_imap.host == mail_smtp.host:
        best_imap = mail_imap
        best_smtp = mail_smtp
        confidence = "high"
        note = f"Unified host {mail_imap.host} serves both IMAP and SMTP"
    elif best_imap.host == best_smtp.host:
        confidence = "high"
        note = f"Unified host {best_imap.host}"
    else:
        confidence = "medium"
        note = f"Separate hosts: IMAP={best_imap.host}, SMTP={best_smtp.host}"

    return DetectedConfig(
        imap_host=best_imap.host,
        imap_port=best_imap.port,
        smtp_host=best_smtp.host,
        smtp_port=best_smtp.port,
        confidence=confidence,
        note=note,
    )


def detect_to_env(email: str, verbose: bool = False) -> Optional[dict]:
    """Return env-ready dict for the detected config."""
    cfg = detect(email, verbose=verbose)
    if cfg is None:
        return None
    return {
        "IMAP_HOST": cfg.imap_host,
        "IMAP_PORT": str(cfg.imap_port),
        "IMAP_ENCRYPTION": "tls" if cfg.imap_port in (993, 465) else "starttls",
        "SMTP_HOST": cfg.smtp_host,
        "SMTP_PORT": str(cfg.smtp_port),
        "SMTP_ENCRYPTION": "tls" if cfg.smtp_port in (465, 993) else "starttls",
        "_confidence": cfg.confidence,
        "_note": cfg.note,
    }
