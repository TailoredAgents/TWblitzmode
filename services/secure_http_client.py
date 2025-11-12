"""
Secure HTTP Client Service for VouchLink AI
Provides secure HTTP client with SSL verification for external services.
"""

import logging
import aiohttp
import requests
import ssl
import certifi
from typing import Dict, Any, Optional, Union
from services.ssl_verification_service import ssl_verification_service

logger = logging.getLogger(__name__)


class SecureHTTPClient:
    """Secure HTTP client with SSL verification for external services."""

    def __init__(self, service_name: str):
        """Initialize secure HTTP client for a specific service."""
        self.service_name = service_name
        self.session = None
        self.sync_session = None

    def get_sync_session(self) -> requests.Session:
        """Get a secure requests session for synchronous operations."""
        if self.sync_session is None:
            session = requests.Session()

            # Configure SSL verification
            session.verify = certifi.where()

            # Set secure headers
            session.headers.update({
                'User-Agent': f'VouchLink-AI/{self.service_name}/1.0',
                'Accept': 'application/json',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
            })

            # Configure adapters with SSL settings
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry

            # Retry strategy
            retry_strategy = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "OPTIONS", "POST", "PUT"]
            )

            adapter = HTTPAdapter(max_retries=retry_strategy)
            session.mount("http://", adapter)
            session.mount("https://", adapter)

            self.sync_session = session

        return self.sync_session

    async def get_async_session(self) -> aiohttp.ClientSession:
        """Get a secure aiohttp session for asynchronous operations."""
        if self.session is None:
            self.session = ssl_verification_service.create_secure_http_client()

        return self.session

    def sync_request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        data: Optional[Union[Dict, str]] = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
        verify_ssl: bool = True
    ) -> requests.Response:
        """Make a secure synchronous HTTP request."""
        session = self.get_sync_session()

        # Add service-specific headers
        request_headers = session.headers.copy()
        if headers:
            request_headers.update(headers)

        try:
            # Pre-verify SSL if requested
            if verify_ssl and url.startswith('https://'):
                from urllib.parse import urlparse
                parsed = urlparse(url)
                hostname = parsed.hostname
                port = parsed.port or 443

                if hostname:
                    logger.debug(f"Pre-verifying SSL for {hostname}:{port}")
                    # Note: This is async, so we'll skip pre-verification in sync context
                    # SSL will still be verified by requests session

            response = session.request(
                method=method,
                url=url,
                headers=request_headers,
                data=data,
                json=json,
                timeout=timeout,
                verify=certifi.where()
            )

            # Log request for audit
            logger.info(
                f"Secure HTTP request completed",
                extra={
                    "service": self.service_name,
                    "method": method,
                    "url": url,
                    "status_code": response.status_code,
                    "ssl_verified": True
                }
            )

            return response

        except requests.exceptions.SSLError as e:
            logger.error(
                f"SSL verification failed for {self.service_name}",
                extra={
                    "service": self.service_name,
                    "url": url,
                    "error": str(e)
                }
            )
            raise

        except requests.exceptions.RequestException as e:
            logger.error(
                f"HTTP request failed for {self.service_name}",
                extra={
                    "service": self.service_name,
                    "method": method,
                    "url": url,
                    "error": str(e)
                }
            )
            raise

    async def async_request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        data: Optional[Union[Dict, str]] = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
        verify_ssl: bool = True
    ) -> aiohttp.ClientResponse:
        """Make a secure asynchronous HTTP request."""
        session = await self.get_async_session()

        # Add service-specific headers
        request_headers = {}
        if headers:
            request_headers.update(headers)

        try:
            # Pre-verify SSL if requested
            if verify_ssl and url.startswith('https://'):
                from urllib.parse import urlparse
                parsed = urlparse(url)
                hostname = parsed.hostname
                port = parsed.port or 443

                if hostname:
                    logger.debug(f"Pre-verifying SSL for {hostname}:{port}")
                    ssl_report = await ssl_verification_service.verify_ssl_endpoint(hostname, port)

                    if not ssl_report.is_valid:
                        logger.error(
                            f"SSL verification failed for {hostname}:{port}",
                            extra={
                                "service": self.service_name,
                                "hostname": hostname,
                                "port": port,
                                "ssl_result": ssl_report.result.value,
                                "errors": ssl_report.errors
                            }
                        )
                        raise aiohttp.ClientSSLError(
                            f"SSL verification failed: {ssl_report.result.value}"
                        )

                    # Log SSL warnings
                    if ssl_report.warnings:
                        logger.warning(
                            f"SSL warnings for {hostname}:{port}",
                            extra={
                                "service": self.service_name,
                                "warnings": ssl_report.warnings
                            }
                        )

            # Create timeout
            timeout_obj = aiohttp.ClientTimeout(total=timeout)

            async with session.request(
                method=method,
                url=url,
                headers=request_headers,
                data=data,
                json=json,
                timeout=timeout_obj
            ) as response:
                # Log request for audit
                logger.info(
                    f"Secure async HTTP request completed",
                    extra={
                        "service": self.service_name,
                        "method": method,
                        "url": url,
                        "status_code": response.status,
                        "ssl_verified": True
                    }
                )

                return response

        except aiohttp.ClientSSLError as e:
            logger.error(
                f"SSL error for {self.service_name}",
                extra={
                    "service": self.service_name,
                    "url": url,
                    "error": str(e)
                }
            )
            raise

        except aiohttp.ClientError as e:
            logger.error(
                f"HTTP client error for {self.service_name}",
                extra={
                    "service": self.service_name,
                    "method": method,
                    "url": url,
                    "error": str(e)
                }
            )
            raise

    async def close(self):
        """Close the async session."""
        if self.session:
            await self.session.close()
            self.session = None

    def close_sync(self):
        """Close the sync session."""
        if self.sync_session:
            self.sync_session.close()
            self.sync_session = None

    def __del__(self):
        """Cleanup sessions on deletion."""
        self.close_sync()


# Service-specific secure clients
class PhantomBusterSecureClient(SecureHTTPClient):
    """Secure HTTP client specifically for PhantomBuster API."""

    def __init__(self):
        super().__init__("PhantomBuster")

    def launch_phantom(self, phantom_id: str, argument: Dict[str, Any], api_key: str) -> str:
        """Launch a PhantomBuster phantom with secure SSL verification."""
        url = "https://api.phantombuster.com/api/v2/agents/launch"
        headers = {
            'X-Phantombuster-Key': api_key,
            'Content-Type': 'application/json'
        }
        payload = {
            "id": phantom_id,
            "argument": argument
        }

        response = self.sync_request(
            method="POST",
            url=url,
            headers=headers,
            json=payload,
            timeout=30,
            verify_ssl=True
        )

        response.raise_for_status()
        result = response.json()
        return result.get("containerId", "")


class ApifySecureClient(SecureHTTPClient):
    """Secure HTTP client specifically for Apify API."""

    def __init__(self):
        super().__init__("Apify")

    def run_actor(self, actor_id: str, run_input: Dict[str, Any], api_key: str) -> Dict[str, Any]:
        """Run an Apify actor with secure SSL verification."""
        url = f"https://api.apify.com/v2/acts/{actor_id}/runs"
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        response = self.sync_request(
            method="POST",
            url=url,
            headers=headers,
            json=run_input,
            timeout=30,
            verify_ssl=True
        )

        response.raise_for_status()
        return response.json()


class SendGridSecureClient(SecureHTTPClient):
    """Secure HTTP client specifically for SendGrid API."""

    def __init__(self):
        super().__init__("SendGrid")

    def send_email(self, email_data: Dict[str, Any], api_key: str) -> Dict[str, Any]:
        """Send email via SendGrid with secure SSL verification."""
        url = "https://api.sendgrid.com/v3/mail/send"
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        response = self.sync_request(
            method="POST",
            url=url,
            headers=headers,
            json=email_data,
            timeout=30,
            verify_ssl=True
        )

        # SendGrid returns 202 for successful sends
        if response.status_code not in [200, 202]:
            response.raise_for_status()

        return {"status": "sent", "status_code": response.status_code}


class CUFinderSecureClient(SecureHTTPClient):
    """Secure HTTP client specifically for CUFinder API."""

    def __init__(self):
        super().__init__("CUFinder")

    def search_contacts(self, query: Dict[str, Any], api_key: str) -> Dict[str, Any]:
        """Search contacts via CUFinder with secure SSL verification."""
        url = "https://api.cufinder.io/v1/search"
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

        response = self.sync_request(
            method="POST",
            url=url,
            headers=headers,
            json=query,
            timeout=30,
            verify_ssl=True
        )

        response.raise_for_status()
        return response.json()


# Global instances
phantombuster_secure_client = PhantomBusterSecureClient()
apify_secure_client = ApifySecureClient()
sendgrid_secure_client = SendGridSecureClient()
cufinder_secure_client = CUFinderSecureClient()


def get_secure_client(service_name: str) -> SecureHTTPClient:
    """Get a secure HTTP client for a specific service."""
    clients = {
        "phantombuster": phantombuster_secure_client,
        "apify": apify_secure_client,
        "sendgrid": sendgrid_secure_client,
        "cufinder": cufinder_secure_client,
    }

    return clients.get(service_name.lower(), SecureHTTPClient(service_name))


async def verify_external_services() -> Dict[str, Dict[str, Any]]:
    """Verify SSL certificates for all external services."""
    services = [
        ("api.phantombuster.com", 443),
        ("api.apify.com", 443),
        ("api.sendgrid.com", 443),
        ("api.cufinder.io", 443),
        ("linkedin.com", 443),
        ("api.openai.com", 443),
    ]

    results = {}
    for hostname, port in services:
        try:
            report = await ssl_verification_service.verify_ssl_endpoint(hostname, port)
            results[f"{hostname}:{port}"] = {
                "is_valid": report.is_valid,
                "result": report.result.value,
                "days_until_expiry": report.days_until_expiry,
                "warnings": report.warnings,
                "errors": report.errors
            }
        except Exception as e:
            results[f"{hostname}:{port}"] = {
                "is_valid": False,
                "result": "error",
                "error": str(e)
            }

    return results