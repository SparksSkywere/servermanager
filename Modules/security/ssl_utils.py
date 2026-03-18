# SSL/TLS certificate utilities for Server Manager
import os
import sys
import socket
from datetime import datetime, timedelta
from typing import Any
import logging

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from Modules.core.common import setup_module_path, setup_module_logging, REGISTRY_PATH, get_server_manager_dir, get_registry_value, set_registry_value
setup_module_path()

logger: logging.Logger = setup_module_logging("SSLUtils")

# Type stubs for conditionally imported cryptography modules
x509: Any = None
NameOID: Any = None
ExtendedKeyUsageOID: Any = None
hashes: Any = None
serialization: Any = None
rsa: Any = None
default_backend: Any = None

# Lazy load cryptography to avoid import errors if not installed
_cryptography_available = False
try:
    from cryptography import x509 as _x509
    from cryptography.x509.oid import NameOID as _NameOID, ExtendedKeyUsageOID as _ExtendedKeyUsageOID
    from cryptography.hazmat.primitives import hashes as _hashes, serialization as _serialization
    from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
    from cryptography.hazmat.backends import default_backend as _default_backend
    # Assign to module-level variables
    x509 = _x509
    NameOID = _NameOID
    ExtendedKeyUsageOID = _ExtendedKeyUsageOID
    hashes = _hashes
    serialization = _serialization
    rsa = _rsa
    default_backend = _default_backend
    _cryptography_available = True
except ImportError:
    logger.warning("cryptography package not available - SSL certificate generation disabled")

def get_ssl_directory():
    # Get the SSL certificates directory from registry or default location.
    try:
        server_manager_dir = get_server_manager_dir()
        ssl_dir = os.path.join(server_manager_dir, "ssl")
    except Exception:
        # Fallback to script directory
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ssl_dir = os.path.join(script_dir, "ssl")

    # Create directory if it doesn't exist
    # Directories are now created in Start-ServerManager.pyw
    return ssl_dir

def get_ssl_config_from_registry():
    # Get SSL configuration from Windows registry.
    config = {
        "enabled": False,
        "cert_path": None,
        "key_path": None,
        "auto_generate": True
    }

    try:
        ssl_enabled = get_registry_value(REGISTRY_PATH, "SSLEnabled", "false")
        config["enabled"] = ssl_enabled.lower() == "true" if ssl_enabled else False

        cert_path = get_registry_value(REGISTRY_PATH, "SSLCertPath", None)
        if cert_path:
            config["cert_path"] = cert_path

        key_path = get_registry_value(REGISTRY_PATH, "SSLKeyPath", None)
        if key_path:
            config["key_path"] = key_path

        auto_gen = get_registry_value(REGISTRY_PATH, "SSLAutoGenerate", "true")
        config["auto_generate"] = auto_gen.lower() == "true" if auto_gen else True
    except Exception as e:
        logger.debug(f"Could not read SSL config from registry: {e}")

    return config

def set_ssl_config_in_registry(enabled=None, cert_path=None, key_path=None, auto_generate=None):
    # Set SSL configuration in Windows registry
    try:
        if enabled is not None:
            set_registry_value(REGISTRY_PATH, "SSLEnabled", "true" if enabled else "false")
        if cert_path is not None:
            set_registry_value(REGISTRY_PATH, "SSLCertPath", cert_path)
        if key_path is not None:
            set_registry_value(REGISTRY_PATH, "SSLKeyPath", key_path)
        if auto_generate is not None:
            set_registry_value(REGISTRY_PATH, "SSLAutoGenerate", "true" if auto_generate else "false")
        logger.info("SSL configuration saved to registry")
        return True
    except Exception as e:
        logger.error(f"Failed to save SSL config to registry: {e}")
        return False

def get_local_hostnames():
    # Get list of local hostnames and IP addresses for certificate SANs
    hostnames = set()

    # Always include localhost
    hostnames.add("localhost")
    hostnames.add("127.0.0.1")

    # Get computer hostname
    try:
        hostname = socket.gethostname()
        hostnames.add(hostname)
        hostnames.add(hostname.lower())
    except Exception:
        pass

    # Get all local IP addresses
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = str(info[4][0])  # Convert to string explicitly
            if ip and not ip.startswith("::"):  # Skip IPv6 link-local
                hostnames.add(ip)
    except Exception:
        pass

    # Try to get all network interface IPs
    try:
        import psutil
        for iface_name, iface_addrs in psutil.net_if_addrs().items():
            for addr in iface_addrs:
                if addr.family == socket.AF_INET:  # IPv4
                    hostnames.add(addr.address)
    except ImportError:
        pass
    except Exception:
        pass

    return list(hostnames)

def generate_self_signed_certificate(
    cert_path=None,
    key_path=None,
    common_name=None,
    organization="Server Manager",
    validity_days=365,
    key_size=2048
):
    # Generate a self-signed SSL certificate and private key
    if not _cryptography_available:
        logger.error("Cannot generate certificate - cryptography package not installed")
        return None, None

    try:
        ssl_dir = get_ssl_directory()

        if cert_path is None:
            cert_path = os.path.join(ssl_dir, "server.crt")
        if key_path is None:
            key_path = os.path.join(ssl_dir, "server.key")

        if common_name is None:
            common_name = socket.gethostname()

        logger.info(f"Generating self-signed certificate for {common_name}...")

        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=key_size,
            backend=default_backend()
        )

        # Build certificate subject
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Server"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Manager"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ])

        # Build Subject Alternative Names (SANs)
        hostnames = get_local_hostnames()
        san_list = []
        for hostname in hostnames:
            try:
                # Try to parse as IP address
                import ipaddress
                ip = ipaddress.ip_address(hostname)
                san_list.append(x509.IPAddress(ip))
            except ValueError:
                # It's a DNS name
                san_list.append(x509.DNSName(hostname))

        # Build certificate
        cert_builder = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.utcnow())
            .not_valid_after(datetime.utcnow() + timedelta(days=validity_days))
            .add_extension(
                x509.SubjectAlternativeName(san_list),
                critical=False
            )
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True
            )
            .add_extension(
                x509.ExtendedKeyUsage([
                    ExtendedKeyUsageOID.SERVER_AUTH,
                    ExtendedKeyUsageOID.CLIENT_AUTH
                ]),
                critical=False
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    key_encipherment=True,
                    content_commitment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False
                ),
                critical=True
            )
        )

        # Sign certificate
        certificate = cert_builder.sign(private_key, hashes.SHA256(), default_backend())

        # Write private key
        with open(key_path, "wb") as f:
            f.write(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))

        # Set restrictive permissions on private key (Windows)
        try:
            import stat
            os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            pass

        # Write certificate
        with open(cert_path, "wb") as f:
            f.write(certificate.public_bytes(serialization.Encoding.PEM))

        logger.info(f"Certificate generated successfully:")
        logger.info(f"  Certificate: {cert_path}")
        logger.info(f"  Private Key: {key_path}")
        logger.info(f"  Valid for: {validity_days} days")
        logger.info(f"  SANs: {', '.join(hostnames)}")

        # Save paths to registry
        set_ssl_config_in_registry(cert_path=cert_path, key_path=key_path)

        return cert_path, key_path

    except Exception as e:
        logger.error(f"Failed to generate certificate: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return None, None

def verify_certificate(cert_path, key_path):
    # Verify that a certificate and key pair are valid and match
    if not _cryptography_available:
        return {"valid": False, "error": "cryptography package not installed", "info": None}

    result = {"valid": False, "error": None, "info": {}}

    try:
        # Check files exist
        if not os.path.exists(cert_path):
            result["error"] = f"Certificate file not found: {cert_path}"
            return result
        if not os.path.exists(key_path):
            result["error"] = f"Private key file not found: {key_path}"
            return result

        # Load certificate
        with open(cert_path, "rb") as f:
            cert_pem = f.read()
        cert = x509.load_pem_x509_certificate(cert_pem, default_backend())

        # Load private key
        with open(key_path, "rb") as f:
            key_pem = f.read()
        private_key = serialization.load_pem_private_key(key_pem, password=None, backend=default_backend())

        # Verify key matches certificate
        cert_public_key = cert.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        private_public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )

        if cert_public_key != private_public_key:
            result["error"] = "Certificate and private key do not match"
            return result

        # Check expiration - use UTC-aware properties when available
        from datetime import timezone
        now = datetime.now(timezone.utc)

        # Try to use UTC-aware certificate properties (cryptography 42.0+)
        try:
            not_valid_before = cert.not_valid_before_utc
            not_valid_after = cert.not_valid_after_utc
        except AttributeError:
            # Fallback for older cryptography versions - convert naive to UTC
            not_valid_before = cert.not_valid_before.replace(tzinfo=timezone.utc)
            not_valid_after = cert.not_valid_after.replace(tzinfo=timezone.utc)

        if now < not_valid_before:
            result["error"] = f"Certificate not yet valid (valid from {not_valid_before})"
            return result
        if now > not_valid_after:
            result["error"] = f"Certificate has expired (expired {not_valid_after})"
            return result

        # Extract certificate info
        result["info"] = {
            "subject": cert.subject.rfc4514_string(),
            "issuer": cert.issuer.rfc4514_string(),
            "serial_number": str(cert.serial_number),
            "not_valid_before": not_valid_before.isoformat(),
            "not_valid_after": not_valid_after.isoformat(),
            "days_until_expiry": (not_valid_after - now).days,
            "self_signed": cert.subject == cert.issuer
        }

        # Extract SANs
        try:
            san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            sans = []
            for name in san_ext.value:
                if isinstance(name, x509.DNSName):
                    sans.append(f"DNS:{name.value}")
                elif isinstance(name, x509.IPAddress):
                    sans.append(f"IP:{name.value}")
            result["info"]["subject_alt_names"] = sans
        except x509.ExtensionNotFound:
            result["info"]["subject_alt_names"] = []

        result["valid"] = True
        logger.debug(f"Certificate verification successful: {result['info']}")
        return result

    except Exception as e:
        result["error"] = f"Certificate verification failed: {e}"
        return result

def ensure_ssl_certificate():
    # Ensure SSL certificate exists, generating one if needed
    config = get_ssl_config_from_registry()

    if not config["enabled"]:
        logger.debug("SSL is not enabled in configuration")
        return None, None

    cert_path = config["cert_path"]
    key_path = config["key_path"]

    # If paths are specified, verify them
    if cert_path and key_path:
        result = verify_certificate(cert_path, key_path)
        if result["valid"]:
            logger.info(f"Using existing SSL certificate (expires in {result['info']['days_until_expiry']} days)")
            return cert_path, key_path
        else:
            logger.warning(f"Existing certificate invalid: {result['error']}")
            if not config["auto_generate"]:
                logger.error("Auto-generate disabled - cannot create new certificate")
                return None, None

    # Generate new certificate
    if config["auto_generate"]:
        logger.info("Generating new self-signed SSL certificate...")
        return generate_self_signed_certificate()

    return None, None

def disable_ssl():
    # Disable SSL in configuration
    set_ssl_config_in_registry(enabled=False)

# CLI interface for manual certificate management
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SSL Certificate Management")
    parser.add_argument("--generate", action="store_true", help="Generate new self-signed certificate")
    parser.add_argument("--verify", action="store_true", help="Verify existing certificate")
    parser.add_argument("--enable", action="store_true", help="Enable SSL")
    parser.add_argument("--disable", action="store_true", help="Disable SSL")
    parser.add_argument("--status", action="store_true", help="Show SSL status")
    parser.add_argument("--days", type=int, default=365, help="Certificate validity in days")
    parser.add_argument("--cert", type=str, help="Certificate path")
    parser.add_argument("--key", type=str, help="Private key path")

    args = parser.parse_args()

    if args.generate:
        cert, key = generate_self_signed_certificate(
            cert_path=args.cert,
            key_path=args.key,
            validity_days=args.days
        )
        if cert and key:
            print(f"Certificate: {cert}")
            print(f"Private Key: {key}")
        else:
            print("Failed to generate certificate")
            sys.exit(1)

    elif args.verify:
        config = get_ssl_config_from_registry()
        cert_path = args.cert or config["cert_path"]
        key_path = args.key or config["key_path"]

        if not cert_path or not key_path:
            print("Certificate and key paths not specified")
            sys.exit(1)

        result = verify_certificate(cert_path, key_path)
        if result["valid"]:
            print("Certificate is VALID")
            for key, value in result["info"].items():
                print(f"  {key}: {value}")
        else:
            print(f"Certificate is INVALID: {result['error']}")
            sys.exit(1)

    elif args.enable:
        set_ssl_config_in_registry(enabled=True, auto_generate=True)
        cert, key = ensure_ssl_certificate()
        if cert and key:
            print("SSL enabled successfully")
            print(f"Certificate: {cert}")
            print(f"Private Key: {key}")
        else:
            print("SSL enabled but certificate generation failed")

    elif args.disable:
        disable_ssl()
        print("SSL disabled")

    elif args.status:
        config = get_ssl_config_from_registry()
        print(f"SSL Enabled: {config['enabled']}")
        print(f"Certificate Path: {config['cert_path'] or 'Not set'}")
        print(f"Key Path: {config['key_path'] or 'Not set'}")
        print(f"Auto Generate: {config['auto_generate']}")

        if config["cert_path"] and config["key_path"]:
            result = verify_certificate(config["cert_path"], config["key_path"])
            if result["valid"]:
                print(f"Certificate Status: Valid (expires in {result['info']['days_until_expiry']} days)")
            else:
                print(f"Certificate Status: Invalid - {result['error']}")

    else:
        parser.print_help()


