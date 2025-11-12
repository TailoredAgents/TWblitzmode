"""
SSL Verification Service for VouchLink AI
Implements comprehensive SSL/TLS certificate validation for external services.
"""

import ssl
import socket
import logging
import asyncio
import aiohttp
import certifi
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
import urllib3

logger = logging.getLogger(__name__)

# Disable urllib3 warnings for unverified HTTPS requests during development
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class SSLValidationResult(Enum):
    """SSL validation results."""
    VALID = "valid"
    EXPIRED = "expired"
    INVALID_CHAIN = "invalid_chain"
    SELF_SIGNED = "self_signed"
    HOSTNAME_MISMATCH = "hostname_mismatch"
    WEAK_CIPHER = "weak_cipher"
    CONNECTION_ERROR = "connection_error"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class CertificateInfo:
    """Certificate information."""
    subject: str
    issuer: str
    serial_number: str
    not_before: datetime
    not_after: datetime
    signature_algorithm: str
    version: int
    extensions: Dict[str, Any]


@dataclass
class SSLValidationReport:
    """SSL validation report."""
    hostname: str
    port: int
    is_valid: bool
    result: SSLValidationResult
    certificate: Optional[CertificateInfo]
    cipher_suite: Optional[str]
    protocol_version: Optional[str]
    days_until_expiry: Optional[int]
    warnings: List[str]
    errors: List[str]
    timestamp: datetime


class SSLVerificationService:
    """Service for SSL/TLS certificate verification."""

    def __init__(self):
        """Initialize the SSL verification service."""
        self.weak_ciphers = {
            'RC4', 'DES', '3DES', 'NULL', 'EXPORT', 'ADH', 'AECDH',
            'MD5', 'SHA1'  # Weak hashing algorithms
        }
        self.min_rsa_key_size = 2048
        self.certificate_cache: Dict[str, SSLValidationReport] = {}
        self.cache_duration = timedelta(hours=1)

    async def verify_ssl_endpoint(self, hostname: str, port: int = 443, timeout: int = 10) -> SSLValidationReport:
        """Verify SSL certificate for a specific endpoint."""
        cache_key = f"{hostname}:{port}"

        # Check cache first
        if cache_key in self.certificate_cache:
            cached_report = self.certificate_cache[cache_key]
            if datetime.now(timezone.utc) - cached_report.timestamp < self.cache_duration:
                return cached_report

        try:
            # Create SSL context with proper verification
            context = ssl.create_default_context(cafile=certifi.where())
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED

            # Connect and get certificate
            with socket.create_connection((hostname, port), timeout=timeout) as sock:
                with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert_der = ssock.getpeercert(binary_form=True)
                    cert_info = ssock.getpeercert()
                    cipher = ssock.cipher()
                    version = ssock.version()

            # Parse certificate information
            certificate = self._parse_certificate_info(cert_info) if cert_info else None

            # Validate certificate
            validation_result, warnings, errors = self._validate_certificate(
                hostname, port, certificate, cipher, version
            )

            # Calculate days until expiry
            days_until_expiry = None
            if certificate and certificate.not_after:
                delta = certificate.not_after - datetime.now(timezone.utc)
                days_until_expiry = delta.days

            report = SSLValidationReport(
                hostname=hostname,
                port=port,
                is_valid=validation_result == SSLValidationResult.VALID,
                result=validation_result,
                certificate=certificate,
                cipher_suite=cipher[0] if cipher else None,
                protocol_version=version,
                days_until_expiry=days_until_expiry,
                warnings=warnings,
                errors=errors,
                timestamp=datetime.now(timezone.utc)
            )

            # Cache the result
            self.certificate_cache[cache_key] = report

            logger.info(f"SSL verification completed for {hostname}:{port}", extra={
                "hostname": hostname,
                "port": port,
                "is_valid": report.is_valid,
                "result": report.result.value,
                "days_until_expiry": days_until_expiry
            })

            return report

        except ssl.SSLError as e:
            error_msg = str(e)
            result = SSLValidationResult.INVALID_CHAIN

            if "certificate verify failed" in error_msg:
                if "self signed" in error_msg:
                    result = SSLValidationResult.SELF_SIGNED
                elif "hostname mismatch" in error_msg:
                    result = SSLValidationResult.HOSTNAME_MISMATCH

            report = SSLValidationReport(
                hostname=hostname,
                port=port,
                is_valid=False,
                result=result,
                certificate=None,
                cipher_suite=None,
                protocol_version=None,
                days_until_expiry=None,
                warnings=[],
                errors=[error_msg],
                timestamp=datetime.now(timezone.utc)
            )

            logger.warning(f"SSL error for {hostname}:{port}: {error_msg}")
            return report

        except (socket.timeout, socket.gaierror, ConnectionRefusedError) as e:
            error_msg = f"Connection error: {str(e)}"

            report = SSLValidationReport(
                hostname=hostname,
                port=port,
                is_valid=False,
                result=SSLValidationResult.CONNECTION_ERROR,
                certificate=None,
                cipher_suite=None,
                protocol_version=None,
                days_until_expiry=None,
                warnings=[],
                errors=[error_msg],
                timestamp=datetime.now(timezone.utc)
            )

            logger.error(f"Connection error for {hostname}:{port}: {error_msg}")
            return report

        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"

            report = SSLValidationReport(
                hostname=hostname,
                port=port,
                is_valid=False,
                result=SSLValidationResult.UNKNOWN_ERROR,
                certificate=None,
                cipher_suite=None,
                protocol_version=None,
                days_until_expiry=None,
                warnings=[],
                errors=[error_msg],
                timestamp=datetime.now(timezone.utc)
            )

            logger.error(f"Unexpected SSL verification error for {hostname}:{port}: {error_msg}")
            return report

    def _parse_certificate_info(self, cert_info: Dict[str, Any]) -> CertificateInfo:
        """Parse certificate information from SSL socket."""
        # Parse subject and issuer
        subject = dict(x[0] for x in cert_info.get('subject', []))
        issuer = dict(x[0] for x in cert_info.get('issuer', []))

        # Parse dates
        not_before = datetime.strptime(cert_info['notBefore'], '%b %d %H:%M:%S %Y %Z')
        not_after = datetime.strptime(cert_info['notAfter'], '%b %d %H:%M:%S %Y %Z')

        return CertificateInfo(
            subject=subject.get('commonName', 'Unknown'),
            issuer=issuer.get('commonName', 'Unknown'),
            serial_number=cert_info.get('serialNumber', 'Unknown'),
            not_before=not_before,
            not_after=not_after,
            signature_algorithm=cert_info.get('signatureAlgorithm', 'Unknown'),
            version=cert_info.get('version', 0),
            extensions=cert_info.get('extensions', {})
        )

    def _validate_certificate(
        self,
        hostname: str,
        port: int,
        certificate: Optional[CertificateInfo],
        cipher: Optional[Tuple],
        version: Optional[str]
    ) -> Tuple[SSLValidationResult, List[str], List[str]]:
        """Validate certificate and connection security."""
        warnings = []
        errors = []

        if not certificate:
            errors.append("No certificate information available")
            return SSLValidationResult.INVALID_CHAIN, warnings, errors

        # Check expiry
        now = datetime.now(timezone.utc)
        if certificate.not_after < now:
            errors.append(f"Certificate expired on {certificate.not_after}")
            return SSLValidationResult.EXPIRED, warnings, errors

        if certificate.not_before > now:
            errors.append(f"Certificate not yet valid (valid from {certificate.not_before})")
            return SSLValidationResult.INVALID_CHAIN, warnings, errors

        # Check expiry warning (30 days)
        days_until_expiry = (certificate.not_after - now).days
        if days_until_expiry <= 30:
            warnings.append(f"Certificate expires in {days_until_expiry} days")

        # Check cipher suite
        if cipher:
            cipher_name = cipher[0]
            if any(weak in cipher_name.upper() for weak in self.weak_ciphers):
                errors.append(f"Weak cipher suite: {cipher_name}")
                return SSLValidationResult.WEAK_CIPHER, warnings, errors

        # Check protocol version
        if version:
            if version in ['SSLv2', 'SSLv3', 'TLSv1', 'TLSv1.1']:
                warnings.append(f"Using deprecated protocol: {version}")

        # Check signature algorithm
        if 'SHA1' in certificate.signature_algorithm:
            warnings.append("Certificate uses SHA-1 signature algorithm (deprecated)")

        return SSLValidationResult.VALID, warnings, errors

    async def verify_url_ssl(self, url: str, timeout: int = 10) -> SSLValidationReport:
        """Verify SSL for a complete URL."""
        from urllib.parse import urlparse

        parsed = urlparse(url)
        hostname = parsed.hostname
        port = parsed.port

        if not hostname:
            raise ValueError(f"Invalid URL: {url}")

        # Default ports
        if port is None:
            port = 443 if parsed.scheme == 'https' else 80

        if parsed.scheme != 'https':
            # Create a report for non-HTTPS URLs
            return SSLValidationReport(
                hostname=hostname,
                port=port,
                is_valid=False,
                result=SSLValidationResult.CONNECTION_ERROR,
                certificate=None,
                cipher_suite=None,
                protocol_version=None,
                days_until_expiry=None,
                warnings=[],
                errors=[f"URL is not HTTPS: {url}"],
                timestamp=datetime.now(timezone.utc)
            )

        return await self.verify_ssl_endpoint(hostname, port, timeout)

    async def verify_multiple_endpoints(
        self,
        endpoints: List[Tuple[str, int]],
        timeout: int = 10
    ) -> Dict[str, SSLValidationReport]:
        """Verify SSL for multiple endpoints concurrently."""
        tasks = []
        for hostname, port in endpoints:
            task = asyncio.create_task(
                self.verify_ssl_endpoint(hostname, port, timeout),
                name=f"ssl_verify_{hostname}_{port}"
            )
            tasks.append((f"{hostname}:{port}", task))

        results = {}
        for key, task in tasks:
            try:
                results[key] = await task
            except Exception as e:
                logger.error(f"Failed to verify SSL for {key}: {e}")
                hostname, port = key.split(':')
                results[key] = SSLValidationReport(
                    hostname=hostname,
                    port=int(port),
                    is_valid=False,
                    result=SSLValidationResult.UNKNOWN_ERROR,
                    certificate=None,
                    cipher_suite=None,
                    protocol_version=None,
                    days_until_expiry=None,
                    warnings=[],
                    errors=[f"Verification failed: {str(e)}"],
                    timestamp=datetime.now(timezone.utc)
                )

        return results

    def create_secure_http_client(self) -> aiohttp.ClientSession:
        """Create an HTTP client with proper SSL verification."""
        # Create SSL context
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED

        # Configure cipher suites (remove weak ones)
        ssl_context.set_ciphers('ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:!aNULL:!MD5:!DSS')

        # Create connector with SSL verification
        connector = aiohttp.TCPConnector(
            ssl=ssl_context,
            ssl_context=ssl_context,
            enable_cleanup_closed=True,
            limit=100,
            limit_per_host=10,
            ttl_dns_cache=300,
            use_dns_cache=True,
        )

        # Create session with security headers
        headers = {
            'User-Agent': 'VouchLink-AI/1.0 (SSL-Verification-Service)',
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }

        timeout = aiohttp.ClientTimeout(total=30, connect=10)

        return aiohttp.ClientSession(
            connector=connector,
            headers=headers,
            timeout=timeout,
            raise_for_status=False
        )

    async def get_certificate_chain(self, hostname: str, port: int = 443) -> List[Dict[str, Any]]:
        """Get the full certificate chain for a hostname."""
        try:
            context = ssl.create_default_context()
            context.check_hostname = False  # We just want the chain
            context.verify_mode = ssl.CERT_NONE

            with socket.create_connection((hostname, port), timeout=10) as sock:
                with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                    cert_chain = ssock.getpeercert_chain()

            if not cert_chain:
                return []

            chain_info = []
            for cert in cert_chain:
                # Extract certificate information
                subject = cert.subject.rfc4514_string()
                issuer = cert.issuer.rfc4514_string()
                serial = str(cert.serial_number)
                not_before = cert.not_valid_before
                not_after = cert.not_valid_after

                chain_info.append({
                    'subject': subject,
                    'issuer': issuer,
                    'serial_number': serial,
                    'not_before': not_before.isoformat(),
                    'not_after': not_after.isoformat(),
                    'is_expired': not_after < datetime.now(timezone.utc),
                    'days_until_expiry': (not_after - datetime.now(timezone.utc)).days
                })

            return chain_info

        except Exception as e:
            logger.error(f"Failed to get certificate chain for {hostname}:{port}: {e}")
            return []

    def clear_cache(self):
        """Clear the certificate cache."""
        self.certificate_cache.clear()
        logger.info("SSL certificate cache cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        now = datetime.now(timezone.utc)
        valid_entries = 0
        expired_entries = 0

        for report in self.certificate_cache.values():
            if now - report.timestamp < self.cache_duration:
                valid_entries += 1
            else:
                expired_entries += 1

        return {
            'total_entries': len(self.certificate_cache),
            'valid_entries': valid_entries,
            'expired_entries': expired_entries,
            'cache_duration_hours': self.cache_duration.total_seconds() / 3600
        }


# Global instance
ssl_verification_service = SSLVerificationService()


async def verify_external_service_ssl(hostname: str, port: int = 443) -> SSLValidationReport:
    """Convenience function to verify SSL for external services."""
    return await ssl_verification_service.verify_ssl_endpoint(hostname, port)


def create_secure_http_session() -> aiohttp.ClientSession:
    """Convenience function to create a secure HTTP session."""
    return ssl_verification_service.create_secure_http_client()