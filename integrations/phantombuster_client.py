import time
import requests
import logging
import csv
import io
import json
from typing import Any, Dict, List, Optional
from core.settings import settings
import hmac, hashlib, base64, os

logger = logging.getLogger(__name__)

PHANTOMBUSTER_API = "https://api.phantombuster.com/api/v2"

def extract_li_at_for_phantombuster(cookie_string: str) -> str:
    """
    Extract ONLY the raw li_at token for PhantomBuster sessionCookie field.
    
    PhantomBuster requires the bare li_at value (150-300 chars), not JSON/headers.
    This function aggressively extracts just the token value.
    
    Args:
        cookie_string: Any format cookie data
    
    Returns:
        Raw li_at token suitable for PhantomBuster sessionCookie
        
    Raises:
        ValueError: If no valid li_at token can be extracted
    """
    import re
    import base64
    
    if not cookie_string:
        raise ValueError("Empty cookie string provided")
    
    s = cookie_string.strip().strip('"').strip("'")
    
    # Try base64 decoding first (some UIs store cookie JSON base64-encoded)
    try:
        if re.fullmatch(r'[A-Za-z0-9+/=]{20,}', s) and not any(x in s for x in ['{','}','[',']',';','=']):
            raw = base64.b64decode(s + '===')
            if raw.strip()[:1] in (b'{', b'['):
                s = raw.decode('utf-8', 'ignore')
    except Exception:
        pass
    
    # Try JSON parsing (array or object of cookies)
    try:
        obj = json.loads(s)
        if isinstance(obj, list):
            # Array of cookie objects - find li_at
            for c in obj:
                if isinstance(c, dict) and str(c.get('name', '')).lower() == 'li_at':
                    li_at_value = str(c.get('value', '')).strip()
                    if li_at_value and 150 <= len(li_at_value) <= 500:
                        logger.info(f"✅ Extracted li_at from JSON array: {len(li_at_value)} chars")
                        return li_at_value
        elif isinstance(obj, dict):
            # Single cookie object or dict of cookies
            if 'li_at' in obj:
                li_at_value = str(obj['li_at']).strip()
                if li_at_value and 150 <= len(li_at_value) <= 500:
                    return li_at_value
            if obj.get('name', '').lower() == 'li_at' and 'value' in obj:
                li_at_value = str(obj['value']).strip()
                if li_at_value and 150 <= len(li_at_value) <= 500:
                    return li_at_value
    except json.JSONDecodeError:
        # Try fixing escaped quotes
        try:
            fixed_json = s.replace('\\"', '"').replace('\\\"', '"')
            obj = json.loads(fixed_json)
            if isinstance(obj, list):
                for c in obj:
                    if isinstance(c, dict) and str(c.get('name', '')).lower() == 'li_at':
                        li_at_value = str(c.get('value', '')).strip()
                        if li_at_value and 150 <= len(li_at_value) <= 500:
                            logger.info(f"✅ Extracted li_at from fixed JSON: {len(li_at_value)} chars")
                            return li_at_value
        except Exception:
            pass
    except Exception:
        pass
    
    # Try cookie header format (li_at=VALUE; other=...)
    m = re.search(r'li_at=([^;]+)', s)
    if m:
        li_at_value = m.group(1).strip()
        if li_at_value and 150 <= len(li_at_value) <= 500:
            logger.info(f"✅ Extracted li_at from header: {len(li_at_value)} chars")
            return li_at_value
    
    # Check if it's already a raw token (relaxed validation)
    if 150 <= len(s) <= 500 and s.startswith(('AQE', 'AQED', 'AQEF')):
        logger.info(f"✅ Using raw li_at token: {len(s)} chars")
        return s
    
    # If we get here, extraction failed
    logger.error(f"❌ Failed to extract valid li_at token from {len(cookie_string)} char input")
    logger.error(f"❌ Input preview: {cookie_string[:100]}...")
    raise ValueError(f"Could not extract valid li_at token (150-500 chars) from provided cookie data")

# Keep old function name for backward compatibility but make it safer
def sanitize_li_at_for_phantombuster(cookie_string: str) -> str:
    """Legacy function - use extract_li_at_for_phantombuster instead"""
    try:
        return extract_li_at_for_phantombuster(cookie_string)
    except ValueError as e:
        logger.error(f"Cookie extraction failed: {e}")
        return ""  # Return empty string to prevent crashes

class PhantomBusterClient:
    """Enhanced PhantomBuster client for LinkedIn automation"""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Construct safely at import time:
        - Do NOT raise if API key missing (so the app can boot).
        - Methods will check and return error dicts when misconfigured.
        """
        self.api_key = (api_key or getattr(settings, "PHANTOMBUSTER_API_KEY", None) or "").strip() or None
        
        if self.api_key:
            self.headers = {"X-Phantombuster-Key-1": self.api_key}
        else:
            self.headers = {}
        
        # Known phantom IDs (may be None) – do not reference undefined names
        # Support both new and legacy environment variable names
        self.phantoms: Dict[str, Optional[str]] = {
            "LINKEDIN_MESSAGE_SENDER_ID": getattr(settings, "PB_LINKEDIN_MESSAGE_SENDER_ID", None),
            "PROFILE_VISITOR_ID": getattr(settings, "PB_PROFILE_VISITOR_ID", None),
            "LINKEDIN_CONNECTIONS_EXPORT_ID": (
                getattr(settings, "PB_LINKEDIN_CONNECTIONS_EXPORT_ID", None) or
                getattr(settings, "LINKEDIN_CONNECTIONS_PHANTOM_ID", None)
            ),
            "PROFILE_SCRAPER_ID": getattr(settings, "PB_PROFILE_SCRAPER_ID", None),
            "LINKEDIN_SEARCH_EXPORT_ID": (
                getattr(settings, "PB_LINKEDIN_SEARCH_EXPORT_ID", None) or
                getattr(settings, "LINKEDIN_SEARCH_PHANTOM_ID", None)
            ),
        }

        # Legacy attributes for backwards compatibility
        self.linkedin_search_export_id = self.phantoms["LINKEDIN_SEARCH_EXPORT_ID"]
        self.connections_export_id = self.phantoms["LINKEDIN_CONNECTIONS_EXPORT_ID"]
        self.profile_scraper_id = self.phantoms["PROFILE_SCRAPER_ID"]
        self.linkedin_message_sender_id = self.phantoms["LINKEDIN_MESSAGE_SENDER_ID"]

        # Soft-validate IDs (log, don't raise)
        for name, value in self.phantoms.items():
            if value is not None and not str(value).strip().isdigit():
                logger.warning("PhantomBuster %s looks non-numeric: %r", name, value)

    def is_configured(self) -> bool:
        return bool(self.api_key)
    
    def launch_search_export(self, search_url: str, phantom_name: str = "search") -> str:
        """
        Launch LinkedIn Search Export or LinkedIn Search Export
        Returns container_id for tracking
        """
        if not self.api_key:
            raise Exception("PHANTOMBUSTER_API_KEY not configured")

        phantom_id = self.phantoms.get("LINKEDIN_SEARCH_EXPORT_ID")
        if not phantom_id:
            raise Exception("PB_LINKEDIN_SEARCH_EXPORT_ID not configured")

        try:
            # Fetch phantom's current saved input to preserve sessionCookie
            get_response = requests.get(
                f"{PHANTOMBUSTER_API}/agents/fetch",
                headers=self.headers,
                params={"id": phantom_id},
                timeout=30
            )
            get_response.raise_for_status()
            
            phantom_data = get_response.json()
            argument_str = phantom_data.get("argument", "{}")
            
            # Parse the argument string as JSON (PhantomBuster returns it as a string)
            try:
                saved_argument = json.loads(argument_str) if isinstance(argument_str, str) else argument_str
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse phantom argument as JSON: {argument_str[:100]}...")
                saved_argument = {}
            
            # Merge saved input with our dynamic data
            merged_argument = saved_argument.copy()
            merged_argument.update({
                "search": search_url,
                "numberOfProfiles": 500,
                "csvName": f"mutual_connections_{int(time.time())}"
            })
            
            payload = {
                "id": phantom_id,
                "argument": merged_argument
            }
            
            response = requests.post(
                f"{PHANTOMBUSTER_API}/agents/launch",
                headers=self.headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            
            container_id = response.json()["containerId"]
            logger.info(f"Launched {phantom_name}: {container_id}")
            return container_id
            
        except Exception as e:
            logger.error(f"Failed to launch PhantomBuster search export: {e}")
            raise
    
    def launch_connections_export(self) -> str:
        """
        Launch LinkedIn Connections Export to update our 1st-degree network
        Returns container_id for tracking
        """
        if not self.api_key:
            raise Exception("PHANTOMBUSTER_API_KEY not configured")

        phantom_id = self.phantoms.get("LINKEDIN_CONNECTIONS_EXPORT_ID")
        if not phantom_id:
            raise Exception("PB_LINKEDIN_CONNECTIONS_EXPORT_ID not configured")

        try:
            # Fetch phantom's current saved input to preserve sessionCookie
            get_response = requests.get(
                f"{PHANTOMBUSTER_API}/agents/fetch",
                headers=self.headers,
                params={"id": phantom_id},
                timeout=30
            )
            get_response.raise_for_status()
            
            phantom_data = get_response.json()
            argument_str = phantom_data.get("argument", "{}")
            
            # Parse the argument string as JSON (PhantomBuster returns it as a string)
            try:
                saved_argument = json.loads(argument_str) if isinstance(argument_str, str) else argument_str
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse phantom argument as JSON: {argument_str[:100]}...")
                saved_argument = {}
            
            # Merge saved input with our dynamic data
            merged_argument = saved_argument.copy()
            merged_argument.update({
                "csvName": f"connections_export_{int(time.time())}",
                "numberOfConnections": 10000
            })
            
            payload = {
                "id": phantom_id,
                "argument": merged_argument
            }
            
            response = requests.post(
                f"{PHANTOMBUSTER_API}/agents/launch",
                headers=self.headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            
            container_id = response.json()["containerId"]
            logger.info(f"Launched LinkedIn Connections Export: {container_id}")
            return container_id
            
        except Exception as e:
            logger.error(f"Failed to launch connections export: {e}")
            raise
    
    def poll_and_fetch_results(self, container_id: str, timeout_sec: int = None) -> List[Dict]:
        """
        Poll for job completion and fetch results
        Returns list of result items
        """
        if timeout_sec is None:
            timeout_sec = settings.PHANTOMBUSTER_TIMEOUT_SECONDS
            
        try:
            deadline = time.time() + timeout_sec
            
            # Poll for completion
            while time.time() < deadline:
                # Use containers/fetch to check status of a specific run
                status_response = requests.get(
                    f"{PHANTOMBUSTER_API}/containers/fetch",
                    headers=self.headers,
                    params={"id": container_id},
                    timeout=30
                )
                if status_response.status_code == 404:
                    logger.info(f"PhantomBuster job {container_id} not found yet, waiting...")
                    time.sleep(10)
                    continue
                try:
                    status_response.raise_for_status()
                except Exception as e:
                    logger.warning(f"Status check error for {container_id}: {e}")
                    time.sleep(10)
                    continue

                status_data = status_response.json() or {}
                job_status = status_data.get("status")

                logger.info(f"PhantomBuster job {container_id} status: {job_status}")

                if job_status in ("success", "failed", "aborted", "finished", "completed"):
                    break
                time.sleep(10)
            else:
                logger.warning(f"PhantomBuster job {container_id} timed out after {timeout_sec} seconds")
                return []
            
            # Check final status
            # Treat 'success', 'finished', and 'completed' as terminal success states
            if job_status not in ("success", "finished", "completed"):
                logger.error(f"PhantomBuster job {container_id} failed with status: {job_status}")
                # Still attempt to fetch result object for diagnostic details
                # Do not return early
            
            # Fetch results
            result_response = requests.get(
                f"{PHANTOMBUSTER_API}/containers/fetch-result-object",
                headers=self.headers,
                params={"id": container_id},
                timeout=60
            )
            try:
                result_response.raise_for_status()
            except Exception as e:
                logger.error(f"Failed to fetch results for {container_id}: {e}")
                return []
            
            results = self._parse_phantombuster_results(result_response)
            if not results:
                try:
                    data = result_response.json()
                    # Log error details if present
                    if isinstance(data, dict) and data.get('error'):
                        logger.error(f"PB result error for {container_id}: {data.get('error')}")
                except Exception:
                    pass
            return results
            
        except Exception as e:
            logger.error(f"Failed to poll and fetch PhantomBuster results: {e}")
            return []
    
    def _parse_phantombuster_results(self, response: requests.Response) -> List[Dict]:
        """Parse PhantomBuster results from various formats"""
        try:
            data = response.json()
            
            # Handle direct JSON array
            if isinstance(data, list):
                return data
            
            # Handle object with CSV URL
            if isinstance(data, dict) and "csvUrl" in data:
                csv_response = requests.get(data["csvUrl"], timeout=60)
                csv_response.raise_for_status()
                return self._parse_csv_content(csv_response.text)
            
            # Handle object with data array
            if isinstance(data, dict) and "data" in data:
                return data["data"]
            
            logger.warning("Unknown PhantomBuster result format")
            return []
            
        except Exception as e:
            logger.error(f"Failed to parse PhantomBuster results: {e}")
            return []
    
    def _parse_csv_content(self, csv_content: str) -> List[Dict]:
        """Parse CSV content into list of dictionaries"""
        try:
            reader = csv.DictReader(io.StringIO(csv_content))
            return [row for row in reader]
        except Exception as e:
            logger.error(f"Failed to parse CSV content: {e}")
            return []
    
    def normalize_search_result(self, item: Dict) -> Dict:
        """Normalize PhantomBuster search results to standard format"""
        return {
            "full_name": (item.get("fullName") or 
                         item.get("name") or 
                         item.get("firstName", "") + " " + item.get("lastName", "")).strip(),
            "linkedin_url": (item.get("profileUrl") or 
                           item.get("linkedin_url") or 
                           item.get("linkedinUrl") or 
                           item.get("url", "")),
            "headline": (item.get("jobTitle") or 
                        item.get("headline") or 
                        item.get("title", "")),
            "company": (item.get("company") or 
                       item.get("companyName") or 
                       item.get("currentCompany", "")),
            "network_distance": (item.get("connectionDegree") or 
                               item.get("network") or 
                               item.get("degree", "")),
            "location": item.get("location", ""),
            "profile_image": item.get("profileImageUrl", "")
        }
    
    def normalize_connection_export(self, item: Dict) -> Dict:
        """Normalize PhantomBuster connection export to contacts format"""
        return {
            "full_name": (item.get("fullName") or 
                         item.get("name") or 
                         f"{item.get('firstName', '')} {item.get('lastName', '')}").strip(),
            "linkedin_url": (item.get("profileUrl") or 
                           item.get("linkedin_url") or 
                           item.get("url", "")),
            "headline": (item.get("headline") or 
                        item.get("jobTitle") or 
                        item.get("title", "")),
            "company": (item.get("company") or 
                       item.get("companyName", "")),
            "email": item.get("email", ""),
            "location": item.get("location", ""),
            "connected_on": item.get("connectedOn", "")
        }

    def launch_profile_scraper(
        self,
        profile_urls: List[str],
        tenant_id: Optional[int] = None,
        spreadsheet_url: Optional[str] = None,
        column_name: str = "profileUrl",
    ) -> str:
        """
        Launch LinkedIn Profile Scraper for one or more profile URLs.
        Returns a container_id used to poll for results.
        """
        if not self.api_key:
            raise Exception("PHANTOMBUSTER_API_KEY not configured")

        phantom_id = self.phantoms.get("PROFILE_SCRAPER_ID")
        if not phantom_id:
            raise Exception("PB_PROFILE_SCRAPER_ID not configured")

        try:
            # Build minimal argument and prefer spreadsheetUrl for this agent
            merged_argument: Dict[str, Any] = {
                "numberOfProfiles": max(1, len(profile_urls)),
            }

            # If a public spreadsheetUrl is provided, use it (recommended by PB)
            if spreadsheet_url:
                merged_argument.update({
                    "spreadsheetUrl": spreadsheet_url,
                    "columnName": column_name,
                })
            else:
                # No spreadsheet provided: attempt in-order fallbacks
                csv_content = 'profileUrl\n' + '\n'.join(profile_urls) + '\n'
                base_url = (getattr(settings, 'APP_BASE_URL', '') or '').strip()
                tried = []

                # 1) Try app-served signed CSV if publicly reachable
                if base_url and not any(x in base_url for x in ['localhost', '127.0.0.1']):
                    try:
                        from .csv_uploader import build_app_csv_url
                        signed_url = build_app_csv_url(base_url, csv_content)
                        merged_argument.update({
                            'spreadsheetUrl': signed_url,
                            'columnName': column_name,
                        })
                    except Exception as e:
                        tried.append(f"app_csv:{e}")
                        # Clear any partial values
                        merged_argument.pop('spreadsheetUrl', None)
                        merged_argument.pop('columnName', None)

                # 2) Try S3 upload if configured
                if 'spreadsheetUrl' not in merged_argument:
                    try:
                        from .csv_uploader import upload_csv_to_s3
                        s3_url = upload_csv_to_s3(csv_content)
                        merged_argument.update({
                            'spreadsheetUrl': s3_url,
                            'columnName': column_name,
                        })
                    except Exception as e:
                        tried.append(f"s3:{e}")

                # 3) Try GitHub Gist if token provided
                if 'spreadsheetUrl' not in merged_argument:
                    try:
                        from .csv_uploader import upload_csv_to_gist
                        gist_url = upload_csv_to_gist(csv_content)
                        merged_argument.update({
                            'spreadsheetUrl': gist_url,
                            'columnName': column_name,
                        })
                    except Exception as e:
                        tried.append(f"gist:{e}")

                if 'spreadsheetUrl' not in merged_argument:
                    raise RuntimeError(
                        "Unable to prepare spreadsheetUrl automatically. Set APP_BASE_URL to a public HTTPS domain, "
                        "or configure AWS_S3_BUCKET_NAME (+ creds), or GITHUB_TOKEN, or pass spreadsheet_url directly. "
                        f"Tried: {', '.join(tried) if tried else 'none'}"
                    )

            # Enforce user's LinkedIn cookie; override any saved config
            li_at = ''
            try:
                from integrations.apify_client import get_tenant_integration_settings
                ts = get_tenant_integration_settings(tenant_id) if tenant_id else {}
                cookie_sources = [
                    ts.get('linkedin_cookies_json'),
                    ts.get('phantombuster_linkedin_cookie'),
                    ts.get('linkedin_li_at'),
                    ts.get('li_at'),
                ]
                for src in cookie_sources:
                    if src:
                        try:
                            li_at = extract_li_at_for_phantombuster(src)
                            break
                        except Exception:
                            continue
            except Exception as e:
                logger.warning(f"Could not load tenant LinkedIn cookie: {e}")
            # Environment fallback (admin-provided user cookie)
            if not li_at:
                env_cookie = os.getenv('LINKEDIN_SESSION_COOKIE') or os.getenv('LINKEDIN_COOKIES_JSON')
                if env_cookie:
                    try:
                        li_at = extract_li_at_for_phantombuster(env_cookie)
                    except Exception:
                        li_at = ''
            if not li_at:
                raise Exception("LinkedIn session cookie required. Add linkedin_cookies_json/linkedin_li_at to tenant integrations or set LINKEDIN_SESSION_COOKIE.")
            merged_argument['sessionCookie'] = li_at
            # Remove conflicting identities if present, then add our own with userAgent
            if 'identities' in merged_argument:
                try:
                    del merged_argument['identities']
                except Exception:
                    pass
            # Determine userAgent: prefer tenant-provided, then saved agent UA, else default
            tenant_user_agent = None
            try:
                from integrations.apify_client import get_tenant_integration_settings
                ts = get_tenant_integration_settings(tenant_id) if tenant_id else {}
                tenant_user_agent = ts.get('linkedin_user_agent')
            except Exception:
                pass
            # Fallback to a stable modern Chrome UA if none provided
            user_agent = tenant_user_agent or 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
            merged_argument['userAgent'] = user_agent
            merged_argument['identities'] = [{
                "sessionCookie": li_at,
                "userAgent": user_agent
            }]

            # Optional quality-of-life flags (safe no-ops if agent ignores them)
            merged_argument.setdefault("enrichWithCompanyData", False)
            merged_argument.setdefault("pushResultToCRM", True)
            merged_argument.setdefault("numberOfAddsPerLaunch", 200)

            payload = {
                "id": phantom_id,
                # Prefer object form; this agent accepts JSON object directly.
                "argument": merged_argument
            }

            response = requests.post(
                f"{PHANTOMBUSTER_API}/agents/launch",
                headers=self.headers,
                json=payload,
                timeout=60
            )
            response.raise_for_status()

            container_id = response.json().get("containerId")
            if not container_id:
                raise RuntimeError("Profile scraper launch did not return a containerId")
            logger.info(f"Launched LinkedIn Profile Scraper: {container_id}")
            return container_id

        except Exception as e:
            logger.error(f"Failed to launch profile scraper: {e}")
            raise

    def normalize_profile_result(self, item: Dict) -> Dict:
        """
        Normalize LinkedIn Profile Scraper results to standard fields.
        Attempts to map common PB output keys into our schema.
        """
        def _extract_aco_id(d: Dict) -> Optional[str]:
            """Extract an ACo-style ID from common fields or any string value."""
            try:
                import re
                candidates = [
                    d.get("entityUrn"), d.get("urn"), d.get("urn_id"), d.get("urnId"),
                    d.get("profileId"), d.get("linkedinId"), d.get("publicIdentifier"),
                ]
                for c in candidates:
                    if not c:
                        continue
                    s = str(c)
                    m = re.search(r"urn:li:fsd_profile:([A-Za-z0-9_-]+)", s)
                    if m:
                        return m.group(1)
                    m = re.search(r"\bACo[A-Za-z0-9_-]+\b", s)
                    if m:
                        return m.group(0)
                for v in d.values():
                    if isinstance(v, str):
                        m = re.search(r"\bACo[A-Za-z0-9_-]+\b", v)
                        if m:
                            return m.group(0)
                return None
            except Exception:
                return None

        full_name = (
            item.get("fullName") or
            (item.get("firstName", "").strip() + " " + item.get("lastName", "").strip()).strip() or
            item.get("name") or
            ""
        )
        headline = item.get("headline") or item.get("summary") or item.get("jobTitle") or ""
        company = item.get("companyName") or item.get("company") or item.get("currentCompany") or ""
        title = item.get("title") or item.get("currentTitle") or item.get("jobTitle") or ""
        location = item.get("location") or item.get("city") or item.get("country") or ""
        linkedin_url = (
            item.get("profileUrl") or item.get("linkedinUrl") or item.get("publicProfileUrl") or item.get("url") or ""
        )
        aco_id = _extract_aco_id(item)
        # Attempt to extract an email if PB provides any
        email = (
            item.get("email") or
            item.get("work_email") or
            item.get("business_email") or
            item.get("contact_email") or
            (item.get("contact", {}) or {}).get("email") if isinstance(item.get("contact"), dict) else None
        )

        return {
            "full_name": full_name,
            "headline": headline,
            "company": company,
            "title": title,
            "location": location,
            "linkedin_url": linkedin_url,
            "linkedin_aco_id": aco_id,
            "email": email
        }

    def list_agents(self, query: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
        """List PhantomBuster agents in the account, optionally filter by query substring."""
        if not self.api_key:
            raise Exception("PHANTOMBUSTER_API_KEY not configured")
        try:
            resp = requests.get(
                f"{PHANTOMBUSTER_API}/agents/fetch-all",
                headers=self.headers,
                params={"limit": limit},
                timeout=30
            )
            resp.raise_for_status()
            data = resp.json().get('data') or resp.json()
            if not isinstance(data, list):
                return []
            results = []
            for it in data:
                name = it.get('name') or it.get('title') or ''
                if query and query.lower() not in name.lower():
                    continue
                results.append({
                    'id': it.get('id'),
                    'name': name,
                    'visibility': it.get('visibility'),
                    'workspaceId': it.get('workspaceId'),
                })
            return results
        except Exception as e:
            logger.error(f"Failed to list PhantomBuster agents: {e}")
            return []
    
    def get_container_status(self, container_id: str) -> Dict:
        """Get current status of a PhantomBuster container"""
        try:
            # First try the containers API endpoint to get basic status
            response = requests.get(
                f"{PHANTOMBUSTER_API}/containers",
                headers=self.headers,
                timeout=30
            )
            
            if response.status_code == 200:
                containers = response.json()
                for container in containers:
                    if str(container.get("id")) == str(container_id):
                        status = container.get("status", "unknown")
                        return {
                            "status": status,
                            "containerId": container_id,
                            "message": f"Container status: {status}"
                        }
                
                # Container not found in list - might be too new
                return {"status": "running", "message": "Container launching or too new to appear in list"}
            
            else:
                # Fallback: assume it's running if we can't get status immediately
                logger.warning(f"Could not get container list (status {response.status_code}), assuming running")
                return {"status": "running", "message": "Status check unavailable, assuming running"}
            
        except Exception as e:
            logger.error(f"Failed to get container status: {e}")
            # Don't fail the whole process - just assume it's running
            return {"status": "running", "message": "Status check failed, assuming running"}
    
    def launch_message_sender_linkedin(self, messages: List[Dict[str, str]], tenant_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Expects each item: {"profileUrl": "...", "message": "..."}
        
        Args:
            messages: List of message data with profileUrl and message
            tenant_id: Tenant ID for multi-tenant LinkedIn cookie configuration
        """
        if not self.api_key:
            return {"success": False, "error": "PHANTOMBUSTER_API_KEY not configured"}

        phantom_id = self.phantoms.get("LINKEDIN_MESSAGE_SENDER_ID")
        if not phantom_id:
            return {"success": False, "error": "PB_LINKEDIN_MESSAGE_SENDER_ID not configured"}

        try:
            logger.info(f"Launching LinkedIn Message Sender for {len(messages)} messages")
            
            # STEP 1: Fetch the phantom's current saved input to preserve sessionCookie
            get_response = requests.get(
                f"{PHANTOMBUSTER_API}/agents/fetch",
                headers=self.headers,
                params={"id": phantom_id},
                timeout=30
            )
            get_response.raise_for_status()
            
            phantom_data = get_response.json()
            argument_str = phantom_data.get("argument", "{}")
            
            # Parse the argument string as JSON (PhantomBuster returns it as a string)
            try:
                saved_argument = json.loads(argument_str) if isinstance(argument_str, str) else argument_str
                logger.info(f"Retrieved phantom's saved configuration with {len(saved_argument)} fields")
                if 'sessionCookie' in saved_argument:
                    logger.info("✅ sessionCookie found in saved config")
                else:
                    logger.warning("❌ sessionCookie missing from saved config")
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse phantom argument as JSON: {argument_str[:100]}...")
                saved_argument = {}
            
            # STEP 2: For LinkedIn Message Sender, we need to pass individual message parameters
            # instead of CSV content, since PhantomBuster expects URLs not raw CSV
            
            # For single message, extract the profile URL and message directly
            if len(messages) == 1:
                message_data = messages[0]
                profile_url = message_data.get('profileUrl', '')
                message_text = message_data.get('message', '')
                
                logger.info(f"Sending single message to: {profile_url}")
                
                # STEP 3: Create fresh argument with clean li_at token
                # DON'T merge with saved config - override sessionCookie completely
                
                # Get LinkedIn cookie from tenant integration settings instead of phantom config
                if tenant_id:
                    try:
                        from integrations.apify_client import get_tenant_integration_settings
                        tenant_settings = get_tenant_integration_settings(tenant_id)
                        
                        # Try to get li_at from various possible setting keys
                        saved_cookie = (
                            tenant_settings.get('linkedin_li_at') or 
                            tenant_settings.get('linkedin_cookie') or
                            tenant_settings.get('phantombuster_linkedin_cookie') or
                            tenant_settings.get('linkedin_cookies_json', '')
                        )
                        
                        if saved_cookie:
                            logger.info(f"✅ Found LinkedIn cookie in tenant {tenant_id} integration settings")
                        else:
                            logger.warning(f"⚠️ No LinkedIn cookie found in tenant {tenant_id} settings, falling back to phantom config")
                            saved_cookie = saved_argument.get('sessionCookie', '')
                            
                    except Exception as e:
                        logger.error(f"❌ Failed to retrieve tenant integration settings: {e}")
                        saved_cookie = saved_argument.get('sessionCookie', '')
                else:
                    # Fallback to phantom's saved sessionCookie for backwards compatibility
                    saved_cookie = saved_argument.get('sessionCookie', '')
                
                if not saved_cookie:
                    # Environment fallback for single-tenant/dev usage
                    env_cookie = os.getenv('LINKEDIN_SESSION_COOKIE') or os.getenv('LINKEDIN_COOKIES_JSON')
                    if env_cookie:
                        logger.info("Using environment LinkedIn cookie fallback (LINKEDIN_SESSION_COOKIE/COOKIES_JSON)")
                        saved_cookie = env_cookie
                if not saved_cookie:
                    error_msg = (
                        f"No LinkedIn cookie configured. Please configure li_at cookie in "
                        f"{'tenant integration settings' if tenant_id else 'PhantomBuster phantom or environment'}"
                    )
                    logger.error(f"🚨 {error_msg}")
                    return {"success": False, "error": error_msg}
                
                # Extract and validate the li_at token with relaxed validation
                try:
                    clean_li_at = extract_li_at_for_phantombuster(saved_cookie)
                    
                    # Relaxed validation - accept tokens between 150-500 chars (was 150-300)
                    if not (150 <= len(clean_li_at) <= 500):
                        logger.error(f"🚨 li_at token invalid length: {len(clean_li_at)} chars (expected 150-500)")
                        return {"success": False, "error": f"LinkedIn cookie invalid length: {len(clean_li_at)} characters. Expected 150-500."}
                    
                    # Only check for obvious format issues, not strict character validation
                    if clean_li_at.startswith('{') or clean_li_at.endswith('}'):
                        logger.error(f"🚨 li_at token appears to be JSON: {clean_li_at[:50]}...")
                        return {"success": False, "error": "LinkedIn cookie appears to be JSON. Paste only the value of li_at."}
                    
                    # Most li_at tokens start with AQE but be flexible for different LinkedIn implementations
                    if not clean_li_at.startswith(('AQE', 'AQED', 'AQEF')):
                        logger.warning(f"⚠️ li_at token has unusual prefix: {clean_li_at[:10]}... (continuing anyway)")
                    
                    logger.info(f"✅ Validated li_at token: {len(clean_li_at)} chars")
                except ValueError as e:
                    logger.error(f"🚨 Failed to extract li_at token: {e}")
                    return {"success": False, "error": f"Invalid LinkedIn cookie format: {e}"}
                
                # Create fresh argument - don't merge, override completely
                merged_argument = {
                    "sessionCookie": clean_li_at,    # ONLY the raw li_at token
                    "profileUrls": [profile_url],    # Use direct profile URLs list
                    "message": message_text,         # Custom message text
                    "numberOfMessages": 1,
                    "enableScraping": True
                }
            else:
                # For multiple messages, we'd need a different approach
                # For now, just handle the first message
                logger.warning(f"Multiple messages ({len(messages)}) - sending first only")
                message_data = messages[0]
                profile_url = message_data.get('profileUrl', '')
                message_text = message_data.get('message', '')
                
                merged_argument = saved_argument.copy()
                merged_argument.update({
                    "spreadsheetUrl": profile_url,  # Use the actual profile URL
                    "message": message_text,
                    "numberOfMessages": 1,
                    "columnName": "profileUrl",
                    "messageColumn": "message"
                })
            
            # STEP 4: Validate clean argument and launch
            # Try sending argument as JSON string (like PhantomBuster stores it)
            argument_json_str = json.dumps(merged_argument)
            
            payload = {
                "id": phantom_id,
                "argument": argument_json_str  # Send as JSON string, not object
            }
            
            # Debug: Log the clean payload being sent
            logger.info(f"🚀 Sending clean payload to PhantomBuster:")
            logger.info(f"   - Phantom ID: {phantom_id}")
            logger.info(f"   - Clean li_at token: {len(merged_argument.get('sessionCookie', ''))} chars")
            logger.info(f"   - Profile URL: {merged_argument.get('profileUrls', ['unknown'])[0] if merged_argument.get('profileUrls') else 'unknown'}")
            logger.info(f"   - Using profileUrls instead of spreadsheetUrl for better compatibility")
            
            response = requests.post(
                f"{PHANTOMBUSTER_API}/agents/launch",
                headers=self.headers,
                json=payload,
                timeout=60
            )
            if response.status_code == 200:
                result = response.json()
                container_id = result.get("containerId")
                
                if container_id:
                    logger.info(f"LinkedIn Message Sender launched: {container_id}")
                    return {"success": True, "containerId": container_id}
                else:
                    error_msg = result.get("error", "Unknown error launching message sender")
                    logger.error(f"Failed to launch LinkedIn Message Sender: {error_msg}")
                    return {"success": False, "error": error_msg}
            else:
                # Get the actual error response for debugging
                error_text = response.text
                logger.error(f"PhantomBuster API Error ({response.status_code}): {error_text}")
                return {"success": False, "error": f"HTTP {response.status_code}: {error_text}"}
                
        except Exception as e:
            logger.error(f"Error launching LinkedIn Message Sender: {e}")
            return {"success": False, "error": str(e)}
    
    def launch_linkedin_message_sender(self, profile_url: str, message: str) -> str:
        """Launch LinkedIn Message Sender for a single message"""
        try:
            logger.info(f"Launching LinkedIn Message Sender for {profile_url}")
            
            # Create single message list
            messages = [{"profileUrl": profile_url, "message": message}]
            
            # Use existing bulk message sender
            result = self.launch_message_sender_linkedin(messages)
            
            if result.get("success"):
                return result.get("containerId", "")
            else:
                raise Exception(result.get("error", "Failed to launch message sender"))
                
        except Exception as e:
            logger.error(f"Error launching single LinkedIn message: {e}")
            raise e
    
    def _messages_to_csv(self, messages: List[Dict]) -> str:
        """Convert messages list to CSV content for PhantomBuster"""
        try:
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['profileUrl', 'message'])
            
            # Write message data
            for msg in messages:
                writer.writerow([
                    msg.get('profileUrl', ''),
                    msg.get('message', '')
                ])
            
            csv_content = output.getvalue()
            output.close()
            
            return csv_content
            
        except Exception as e:
            logger.error(f"Error converting messages to CSV: {e}")
            return ""


# Module-level singleton, but safe
_phb_singleton: Optional[PhantomBusterClient] = None

def get_client() -> PhantomBusterClient:
    global _phb_singleton
    if _phb_singleton is None:
        _phb_singleton = PhantomBusterClient()
    return _phb_singleton

# Backwards-compatible name for existing imports
phantombuster_client = get_client()
