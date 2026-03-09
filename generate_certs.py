"""
Generate a self-signed TLS certificate and private key for local testing.

Outputs:
    certs/server.crt  — certificate (given to clients to trust)
    certs/server.key  — private key  (kept on the server)

Usage:
    python generate_certs.py
"""

import ipaddress
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

CERTS_DIR = Path("certs")
CERT_FILE = CERTS_DIR / "server.crt"
KEY_FILE  = CERTS_DIR / "server.key"


def generate():
    CERTS_DIR.mkdir(exist_ok=True)

    # 1. Generate private key (RSA 2048)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # 2. Build certificate
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MCP Traffic Classification"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
        # Allow it to be used for localhost and 127.0.0.1
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    # 3. Write private key
    KEY_FILE.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    # 4. Write certificate
    CERT_FILE.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    print(f"Certificate : {CERT_FILE}")
    print(f"Private key : {KEY_FILE}")
    print(f"Valid until : {datetime.now(timezone.utc) + timedelta(days=365):%Y-%m-%d}")
    print("Done — certificates ready for use.")


if __name__ == "__main__":
    generate()
