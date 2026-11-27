"""Prepare isolated local validation config; never reset the existing VMS database."""
from pathlib import Path
from datetime import datetime, timedelta, timezone
import base64
import ipaddress
import secrets
import sys

import psycopg
from psycopg import sql
from dotenv import dotenv_values
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]


def main():
    destination = ROOT / "storage" / "deployment-validation"
    destination.mkdir(parents=True, exist_ok=True)
    env_path = destination / "validation.env"
    if env_path.exists():
        print("Existing validation configuration preserved")
        return
    original = dotenv_values(ROOT / ".env")
    database = "intelligent_vms_validation_20261126"
    with psycopg.connect(host=original.get("POSTGRES_HOST", "127.0.0.1"),
                         port=original.get("POSTGRES_PORT", "5432"),
                         user=original["POSTGRES_USER"], password=original["POSTGRES_PASSWORD"],
                         dbname=original["POSTGRES_DB"], connect_timeout=5) as connection:
        connection.execute("SELECT 1").fetchone()
        print("Existing PostgreSQL reachable read-only; validation will use an isolated unexposed test container")
    media_password = secrets.token_hex(24)
    config = {
        "COMPOSE_PROJECT_NAME": "intelligent-vms-validation",
        "POSTGRES_HOST": "validation-db", "POSTGRES_PORT": "5432",
        "POSTGRES_USER": "vms_validation", "POSTGRES_PASSWORD": secrets.token_hex(24),
        "POSTGRES_DB": database,
        "VMS_OPERATOR_USERNAME": "validation-admin", "VMS_OPERATOR_PASSWORD": secrets.token_hex(20),
        "VMS_SESSION_SECRET": secrets.token_hex(48), "MEDIAMTX_API_PASSWORD": secrets.token_hex(24),
        "MEDIAMTX_MEDIA_PASSWORD": media_password,
        "VMS_MEDIA_AUTH": base64.b64encode(("vms-media:" + media_password).encode()).decode(),
        "VMS_CAMERA_NETWORKS": "172.30.86.10/32", "VMS_PUBLIC_HOST": "localhost",
        "VMS_TLS_DIRECTORY": (destination / "tls").as_posix(),
        "VMS_HTTPS_PORT": "8443", "VMS_BIND_ADDRESS": "127.0.0.1",
        "RECORDING_SEGMENT_SECONDS": "1800", "VMS_MAX_RECORDERS": "16",
        "VMS_RECORDING_VOLUME": "intelligent-vms-validation-recordings",
        "VMS_REDIS_VOLUME": "intelligent-vms-validation-redis",
    }
    # Single quoted dotenv values preserve '$' in passwords instead of Compose interpolation.
    env_path.write_text("\n".join(f"{k}='{v.replace(chr(39), chr(92)+chr(39))}'" for k, v in config.items()) + "\n")
    tls = destination / "tls"
    tls.mkdir(exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=30)).add_extension(x509.SubjectAlternativeName([
                x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .sign(key, hashes.SHA256()))
    (tls / "privkey.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (tls / "fullchain.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print("Private validation config and localhost-only test certificate written; no secrets printed")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("Validation preparation failed:", type(error).__name__, file=sys.stderr)
        sys.exit(1)
