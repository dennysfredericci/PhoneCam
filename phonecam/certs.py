"""Local IP detection and the self-signed HTTPS certificate.

Mobile browsers only allow getUserMedia() on secure (HTTPS) pages, so we
serve HTTPS with a self-signed certificate. Its subjectAltName lists the
Mac's current LAN IPs; if the IP changes (new network, DHCP), the cert no
longer matches and is regenerated on the next start.
"""

import datetime
import ipaddress
import logging
import socket
from pathlib import Path

import ifaddr  # pure-Python, already installed as an aioice dependency
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from .paths import support_dir

log = logging.getLogger(__name__)


def primary_ip() -> str | None:
    """IP of the interface used for the default route (no packet is actually sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))  # TEST-NET address, never routed anywhere
            return s.getsockname()[0]
        except OSError:
            return None


def local_ips() -> list[str]:
    """Private IPv4 addresses of this Mac, the default-route one first."""
    ips = []
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            if not isinstance(ip.ip, str):  # IPv6 entries are tuples; LAN IPv4 is enough
                continue
            addr = ipaddress.ip_address(ip.ip)
            if addr.is_private and not addr.is_loopback and not addr.is_link_local:
                ips.append(ip.ip)
    first = primary_ip()
    if first in ips:
        ips.remove(first)
        ips.insert(0, first)
    return ips


def _cert_ips(cert_path: Path) -> set[str]:
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    return {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}


def ensure_certificate(ips: list[str]) -> tuple[Path, Path]:
    """Return (cert, key) paths, regenerating when a current IP isn't covered."""
    cert_path = support_dir() / "cert.pem"
    key_path = support_dir() / "key.pem"
    if cert_path.exists() and key_path.exists():
        try:
            if set(ips) <= _cert_ips(cert_path):
                return cert_path, key_path
            log.info("Local IP changed, regenerating certificate")
        except Exception as exc:
            log.warning("Unreadable certificate, regenerating: %s", exc)

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PhoneCam")])
    san = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    san += [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ips]
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        # Apple rejects TLS certs valid longer than 825 days, even self-signed ones.
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        # CA=True lets an iPhone "trust" it via a profile if the warning page ever isn't enough.
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    key_path.chmod(0o600)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    log.info("Generated certificate for %s", ", ".join(["localhost"] + ips))
    return cert_path, key_path
