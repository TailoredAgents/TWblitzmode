import asyncio
import time
import hmac
import hashlib
import json
import logging
from datetime import datetime
from collections import deque
from threading import Lock
from typing import Any, Dict, List, Optional

import httpx
import requests
from urllib.parse import urlencode
from core.settings import settings

logger = logging.getLogger(__name__)

APIFY_API = "https://api.apify.com/v2"

_PENDING_RUNS: Dict[str, deque] = {}
_PENDING_RUNS_LOCK = Lock()


def _queue_key(tenant_id: Optional[int]) -> str:
    return str(tenant_id) if tenant_id is not None else "global"


def _record_pending_run(tenant_id: Optional[int], payload: Dict[str, Any]) -> None:
    entry = {
        "requested_at": datetime.utcnow().isoformat() + "Z",
        "tenant_id": tenant_id,
        "profile_url": payload.get("profile_url"),
        "note": payload.get("note", "apify_disabled"),
    }
    key = _queue_key(tenant_id)
    with _PENDING_RUNS_LOCK:
        queue = _PENDING_RUNS.setdefault(key, deque(maxlen=200))
        queue.appendleft(entry)


def get_deferred_apify_runs(tenant_id: Optional[int]) -> Dict[str, Any]:
    key = _queue_key(tenant_id)
    with _PENDING_RUNS_LOCK:
        queue = list(_PENDING_RUNS.get(key, []))
    latest = queue[0] if queue else None
    return {
        "pending": len(queue),
        "latest": latest,
    }


def clear_deferred_apify_runs(tenant_id: Optional[int] = None) -> None:
    with _PENDING_RUNS_LOCK:
        if tenant_id is None:
            _PENDING_RUNS.clear()
        else:
            _PENDING_RUNS.pop(_queue_key(tenant_id), None)


class ApifyConfigurationError(RuntimeError):
    """Raised when Apify is not configured for the active tenant."""

    def __init__(self, message: str, tenant_id: Optional[int] = None):
        super().__init__(message)
        self.tenant_id = tenant_id


class ApifyClient:
    """Client for Apify LinkedIn Mutual Connections Parser"""
    
    def __init__(
        self,
        api_token: Optional[str] = None,
        webhook_secret: Optional[str] = None,
        li_cookie_secret_name: Optional[str] = None,
        li_at: Optional[str] = None,
        jsessionid: Optional[str] = None,
        cookies_json: Optional[str] = None,
        tenant_id: Optional[int] = None,
        fail_on_missing: bool = False,
    ):
        """Initialize with tenant-specific credentials or fall back to global settings"""
        self.api_token = (api_token or settings.APIFY_TOKEN or "").strip()
        self.actor_id = settings.APIFY_ACTOR_ID
        self.webhook_secret = webhook_secret or settings.APIFY_WEBHOOK_SECRET
        self.base_url = settings.APP_BASE_URL
        self.tenant_id = tenant_id
        self.fail_on_missing = fail_on_missing
        self.disabled_reason: Optional[str] = None
        self._pending_queue_key = _queue_key(tenant_id)
        
        # LinkedIn authentication - tenant-specific overrides
        self.li_cookie_secret_name = li_cookie_secret_name or settings.APIFY_LI_COOKIE_SECRET_NAME
        self.cookies_json = cookies_json
        self._async_client: Optional[httpx.AsyncClient] = None
        
        if not self.api_token:
            logger.warning(
                "⚠️ [APIFY AUTH] Missing API token; Apify automation disabled "
                f"for tenant {tenant_id or 'default environment'}"
            )
            self.disabled_reason = (
                "Apify automation is disabled: configure an Apify API token in tenant settings."
            )
            if fail_on_missing:
                raise ApifyConfigurationError(self.disabled_reason, tenant_id=tenant_id)

        # Extract li_at and JSESSIONID from cookies JSON if individual cookies are missing
        if cookies_json:
            try:
                cookies_array = json.loads(cookies_json)
                if isinstance(cookies_array, list):
                    for cookie in cookies_array:
                        cookie_name = cookie.get("name", "")
                        cookie_value = cookie.get("value", "")
                        
                        if cookie_name == "li_at" and not li_at and cookie_value:
                            li_at = cookie_value
                            logger.info("✅ Extracted li_at from cookies JSON")
                        elif cookie_name == "JSESSIONID" and not jsessionid and cookie_value:
                            jsessionid = cookie_value
                            logger.info("✅ Extracted JSESSIONID from cookies JSON")
                    
                    # Log what we found for debugging
                    cookie_names = [c.get("name") for c in cookies_array if c.get("name")]
                    logger.info(f"Found {len(cookies_array)} cookies in JSON: {cookie_names}")
                    
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Could not extract cookies from JSON: {e}")
        
        self.li_at = li_at or settings.APIFY_LI_AT
        self.jsessionid = jsessionid or settings.APIFY_JSESSIONID

    async def _get_async_client(self) -> httpx.AsyncClient:
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        return self._async_client

    async def aclose(self) -> None:
        if self._async_client is not None:
            await self._async_client.aclose()
            self._async_client = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_token)

    @property
    def configuration_reason(self) -> Optional[str]:
        return self.disabled_reason

    def _handle_disabled(self, context: Dict[str, Any], *, return_type: str) -> Any:
        reason = self.disabled_reason or (
            "Apify automation is disabled until an API token is configured."
        )
        context_payload = {
            "profile_url": context.get("profile_url"),
            "note": context.get("note", reason),
        }
        _record_pending_run(self.tenant_id, context_payload)
        if self.fail_on_missing:
            raise ApifyConfigurationError(reason, tenant_id=self.tenant_id)

        if return_type == "dict":
            return {"disabled": True, "reason": reason}
        if return_type == "list":
            return []
        return None

    def _prepare_actor_run(
        self,
        profile_url: str,
        prospect_id: Optional[int] = None,
        tenant_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        from utils.linkedin import clean_linkedin_url_for_api

        cleaned_url = clean_linkedin_url_for_api(profile_url)
        logger.info(f"Cleaned LinkedIn URL for Apify: {profile_url} -> {cleaned_url}")

        input_payload: Dict[str, Any] = {
            "url": cleaned_url,
            "maxMutuals": 500,
            "includeDetails": True,
        }

        if self.li_cookie_secret_name:
            input_payload["cookieSecretName"] = self.li_cookie_secret_name
            logger.info("Using Apify secret store for LinkedIn cookies")
        else:
            self._set_individual_cookies(input_payload, tenant_id=tenant_id)

        params: Dict[str, Any] = {"token": self.api_token}

        if self.webhook_secret and self.base_url and not self.base_url.startswith("http://localhost"):
            import base64

            webhook_url = f"{self.base_url}/webhooks/apify?secret={self.webhook_secret}"
            webhook_config = [{
                "eventTypes": [
                    "ACTOR.RUN.SUCCEEDED",
                    "ACTOR.RUN.FAILED",
                    "ACTOR.RUN.ABORTED",
                ],
                "requestUrl": webhook_url,
                "payloadTemplate": json.dumps({
                    "runId": "{{resource.id}}",
                    "status": "{{resource.status}}",
                }),
            }]
            webhook_json = json.dumps(webhook_config)
            params["webhooks"] = base64.b64encode(webhook_json.encode("utf-8")).decode("utf-8")
            logger.info("Configured Base64-encoded webhook with URL secret for Apify job")
        else:
            if self.base_url and self.base_url.startswith("http://localhost"):
                logger.info("Skipping webhook configuration for localhost - will poll for results")
            else:
                logger.warning("No webhook configured - results will need to be polled manually")

        api_url = f"{APIFY_API}/acts/{self.actor_id}/runs"
        logger.info(f"Making Apify request to: {api_url}")

        safe_params = params.copy()
        if "token" in safe_params:
            safe_params["token"] = self._mask_sensitive(str(safe_params["token"]))
        logger.info(f"Request params: {safe_params}")

        safe_payload = input_payload.copy()
        if "cookies" in safe_payload:
            if isinstance(input_payload["cookies"], dict):
                safe_payload["cookies"] = {
                    key: self._mask_sensitive(str(value))
                    for key, value in input_payload["cookies"].items()
                }
            else:
                masked_cookies = []
                for cookie in input_payload["cookies"]:
                    safe_cookie = cookie.copy()
                    if "value" in safe_cookie:
                        safe_cookie["value"] = self._mask_sensitive(str(safe_cookie["value"]))
                    masked_cookies.append(safe_cookie)
                safe_payload["cookies"] = masked_cookies
        logger.info(f"Request payload: {json.dumps(safe_payload, indent=2)}")

        return {
            "api_url": api_url,
            "params": params,
            "payload": input_payload,
        }

    def start_mutuals_run(self, profile_url: str, prospect_id: Optional[int] = None, tenant_id: Optional[int] = None) -> Dict[str, str]:
        """
        Start the Apify actor to parse mutual connections.
        Returns {"runId": "...", "webhookId": "..."}
        """
        if not self.is_configured:
            return self._handle_disabled(
                {"profile_url": profile_url, "note": "run_skipped_missing_api_token"},
                return_type="dict",
            )
        try:
            request_parts = self._prepare_actor_run(
                profile_url,
                prospect_id=prospect_id,
                tenant_id=tenant_id,
            )

            response = requests.post(
                request_parts["api_url"],
                params=request_parts["params"],
                json=request_parts["payload"],
                headers={
                    "Content-Type": "application/json"
                },
                timeout=60
            )
            response.raise_for_status()
            
            data = response.json()
            run_id = data["data"]["id"]
            
            logger.info(f"Started Apify mutual connections run: {run_id}")
            return {"runId": run_id}
            
        except requests.HTTPError as e:
            error_details = ""
            try:
                error_response = e.response.json() if e.response else {}
                error_details = f" - Response: {error_response}"
            except:
                error_details = f" - Raw response: {e.response.text if e.response else 'N/A'}"
            logger.error(f"Failed to start Apify run: {e}{error_details}")
            raise
        except Exception as e:
            logger.error(f"Failed to start Apify run: {e}")
            raise
    
    def verify_webhook_signature(self, signature_header: str, body_bytes: bytes) -> bool:
        """Verify webhook signature from Apify using HMAC SHA256"""
        try:
            if not signature_header:
                logger.warning("Missing webhook signature header")
                return False
                
            if not self.webhook_secret:
                logger.error("APIFY_WEBHOOK_SECRET not configured")
                return False
                
            # Calculate expected signature
            mac = hmac.new(
                self.webhook_secret.encode("utf-8"),
                msg=body_bytes,
                digestmod=hashlib.sha256
            )
            expected_signature = mac.hexdigest()
            
            # Secure comparison to prevent timing attacks
            is_valid = hmac.compare_digest(expected_signature, signature_header)
            
            if is_valid:
                logger.info("Apify webhook signature verified successfully")
            else:
                logger.warning(f"Webhook signature verification failed. "
                             f"Expected: {expected_signature[:10]}..., "
                             f"Received: {signature_header[:10] if signature_header else 'None'}...")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"Error during webhook signature verification: {e}")
            return False
    
    def fetch_dataset_items(self, dataset_id: str) -> List[Dict]:
        """Fetch items from an Apify dataset"""
        if not self.is_configured:
            return self._handle_disabled(
                {"note": f"dataset_fetch_skipped_{dataset_id}"},
                return_type="list",
            )
        try:
            response = requests.get(
                f"{APIFY_API}/datasets/{dataset_id}/items",
                params={
                    "token": self.api_token,
                    "format": "json",
                    "clean": "true"
                },
                timeout=60
            )
            response.raise_for_status()
            
            items = response.json()
            logger.info(f"Fetched {len(items)} items from Apify dataset {dataset_id}")
            return items
            
        except Exception as e:
            logger.error(f"Failed to fetch dataset items: {e}")
            return []
    
    def get_run_info(self, run_id: str) -> Dict:
        """Get information about an Apify run"""
        if not self.is_configured:
            return self._handle_disabled(
                {"note": f"run_info_skipped_{run_id}"},
                return_type="dict",
            )
        try:
            response = requests.get(
                f"{APIFY_API}/actor-runs/{run_id}",
                params={"token": self.api_token},
                timeout=30
            )
            response.raise_for_status()
            return response.json()["data"]
            
        except Exception as e:
            logger.error(f"Failed to get run info: {e}")
            return {}
    
    def get_run_failure_details(self, run_id: str) -> Dict:
        """Get detailed failure information from a failed Apify run"""
        if not self.is_configured:
            return self._handle_disabled(
                {"note": f"failure_details_skipped_{run_id}"},
                return_type="dict",
            )
        try:
            run_info = self.get_run_info(run_id)
            if not run_info:
                return {"error": "Could not fetch run details", "details": "Run info unavailable"}
            
            status = run_info.get("status", "UNKNOWN")
            if status == "FAILED":
                # Extract meaningful error details
                error_details = {
                    "status": status,
                    "statusMessage": run_info.get("statusMessage", ""),
                    "errorMessage": run_info.get("errorMessage", ""),
                    "exitCode": run_info.get("exitCode"),
                    "finishedAt": run_info.get("finishedAt"),
                    "stats": run_info.get("stats", {})
                }
                
                # Try to get more specific error from stats
                stats = run_info.get("stats", {})
                if stats.get("requestsFailed", 0) > 0:
                    error_details["likely_cause"] = "LinkedIn page failed to load - possibly malformed URL"
                
                return error_details
            
            return {"status": status, "message": f"Run is {status}, not failed"}
            
        except Exception as e:
            logger.error(f"Failed to get failure details for run {run_id}: {e}")
            return {"error": "Could not fetch failure details", "exception": str(e)}

    def normalize_mutual_connection(self, item: Dict) -> Dict:
        """Normalize Apify mutual connection data to standard format"""
        return {
            "full_name": item.get("full_name") or item.get("name") or item.get("displayName", ""),
            "linkedin_url": item.get("linkedin") or item.get("profileUrl") or item.get("linkedin_url") or item.get("url", ""),
            "headline": item.get("jobtitle") or item.get("headline") or item.get("title") or item.get("jobTitle", ""),
            "company": item.get("company") or item.get("companyName", ""),
            "network_distance": item.get("network_distance") or item.get("connectionDegree") or item.get("degree", ""),
            "location": item.get("location", ""),
            "profile_image": item.get("profileImage") or item.get("avatar", "")
        }
    
    def _mask_sensitive(self, value: str) -> str:
        """Mask sensitive values for logging"""
        if not value or len(value) < 12:
            return "****"
        return f"{value[:4]}...{value[-4:]}"
    
    def _get_linkedin_cookies_for_tenant(self, tenant_id: int = None) -> dict:
        """Get LinkedIn cookies in the format expected by the actor (GPT5's approach)"""
        # GPT5's fix: Get cookies from instance first, then direct tenant settings lookup
        li_at = self.li_at
        jsessionid = self.jsessionid
        
        # GPT5's approach: If missing, try direct tenant settings lookup with decrypt fallback
        if (not li_at or not jsessionid) and tenant_id:
            try:
                tenant_settings = get_tenant_integration_settings(tenant_id)
                if not li_at:
                    li_at = tenant_settings.get("linkedin_li_at")
                if not jsessionid:
                    jsessionid = tenant_settings.get("linkedin_jsessionid")
                logger.info(f"Direct tenant lookup found: li_at={bool(li_at)}, jsessionid={bool(jsessionid)}")
            except Exception as e:
                logger.warning(f"Direct tenant settings lookup failed: {e}")
        
        # If individual cookies are missing but we have cookies_json, try extracting
        if (not li_at or not jsessionid) and self.cookies_json:
            try:
                cookies_array = json.loads(self.cookies_json)
                if isinstance(cookies_array, list):
                    for cookie in cookies_array:
                        cookie_name = cookie.get("name", "")
                        cookie_value = cookie.get("value", "")
                        
                        if cookie_name == "li_at" and not li_at and cookie_value:
                            li_at = cookie_value
                            logger.info("✅ Extracted li_at from tenant cookies JSON")
                        elif cookie_name == "JSESSIONID" and not jsessionid and cookie_value:
                            jsessionid = cookie_value
                            logger.info("✅ Extracted JSESSIONID from tenant cookies JSON")
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Could not extract cookies from tenant JSON: {e}")
        
        # GPT5's fix: Environment variable fallbacks as safety net
        import os
        if not li_at:
            li_at = os.getenv("LINKEDIN_LI_AT")
            if li_at:
                logger.info(f"Using LINKEDIN_LI_AT environment fallback for tenant {tenant_id}")
        if not jsessionid:
            jsessionid = os.getenv("LINKEDIN_JSESSIONID")
            if jsessionid:
                logger.info(f"Using LINKEDIN_JSESSIONID environment fallback for tenant {tenant_id}")
            
        if not li_at or not jsessionid:
            # GPT5's debug approach - log what we actually have
            logger.error(f"LinkedIn cookie debugging for tenant {tenant_id}:")
            logger.error(f"  self.li_at: {bool(self.li_at)} ({len(self.li_at) if self.li_at else 0} chars)")
            logger.error(f"  self.jsessionid: {bool(self.jsessionid)} ({len(self.jsessionid) if self.jsessionid else 0} chars)")
            logger.error(f"  cookies_json: {bool(self.cookies_json)} ({len(self.cookies_json) if self.cookies_json else 0} chars)")
            
            # Try alternative extraction from tenant settings directly
            if tenant_id and (not li_at or not jsessionid):
                try:
                    logger.info(f"Attempting direct tenant settings lookup for tenant {tenant_id}")
                    tenant_settings = get_tenant_integration_settings(tenant_id)
                    logger.error(f"Direct tenant settings keys: {list(tenant_settings.keys())}")
                    
                    # GPT5's multi-key approach
                    if not li_at:
                        li_at = (tenant_settings.get("linkedin_li_at") or 
                                tenant_settings.get("li_at") or
                                tenant_settings.get("linkedin_li_at_cookie"))
                    if not jsessionid:
                        jsessionid = (tenant_settings.get("linkedin_jsessionid") or 
                                    tenant_settings.get("linkedin_jsession_id") or
                                    tenant_settings.get("JSESSIONID") or
                                    tenant_settings.get("jsessionid"))
                        
                    logger.error(f"After direct lookup - li_at: {bool(li_at)}, jsessionid: {bool(jsessionid)}")
                except Exception as e:
                    logger.error(f"Direct tenant lookup failed: {e}")
            
            # Final check
            if not li_at or not jsessionid:
                missing = []
                if not li_at:
                    missing.append("linkedin_li_at")
                if not jsessionid:
                    missing.append("linkedin_jsessionid")
                
                error_msg = f"LinkedIn cookies missing for tenant {tenant_id}: {', '.join(missing)}. Please configure both li_at and JSESSIONID in admin settings."
                logger.error(error_msg)
                raise ValueError(error_msg)
            
        # Return cookies in dictionary format that the actor expects
        # Strip surrounding quotes from JSESSIONID if present (LinkedIn sets it with quotes)
        clean_jsessionid = jsessionid.strip('"') if jsessionid and jsessionid.startswith('"') and jsessionid.endswith('"') else jsessionid
        
        return {
            "li_at": li_at,
            "JSESSIONID": clean_jsessionid  # Actor expects value without surrounding quotes
        }
    
    def _set_individual_cookies(self, input_payload: dict, tenant_id: int = None):
        """Set cookies in array format expected by actor (corrected based on API error)"""
        try:
            cookies_dict = self._get_linkedin_cookies_for_tenant(tenant_id)
            
            # IMPORTANT: Actor expects cookies as array, not dict! (API error: "Field input.cookies must be array")
            cookies_array = [
                {
                    "name": "li_at",
                    "value": cookies_dict["li_at"],
                    "domain": ".linkedin.com"
                },
                {
                    "name": "JSESSIONID",
                    "value": cookies_dict["JSESSIONID"],
                    "domain": ".www.linkedin.com"
                }
            ]
            
            input_payload["cookies"] = cookies_array
            
            logger.info(f"Using LinkedIn cookies array for authentication: li_at ({self._mask_sensitive(cookies_dict['li_at'])}), JSESSIONID ({self._mask_sensitive(cookies_dict['JSESSIONID'])})")
            
        except ValueError as e:
            # Re-raise with more context for error classification
            raise RuntimeError(f"LinkedIn authentication misconfigured: {e}")

    async def start_mutuals_run_async(
        self,
        profile_url: str,
        prospect_id: Optional[int] = None,
        tenant_id: Optional[int] = None,
    ) -> Dict[str, str]:
        if not self.is_configured:
            return self._handle_disabled(
                {"profile_url": profile_url, "note": "run_skipped_missing_api_token"},
                return_type="dict",
            )
        request_parts = self._prepare_actor_run(
            profile_url,
            prospect_id=prospect_id,
            tenant_id=tenant_id,
        )

        client = await self._get_async_client()

        try:
            response = await client.post(
                request_parts["api_url"],
                params=request_parts["params"],
                json=request_parts["payload"],
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                f"Failed to start Apify run (async) [{exc.response.status_code}]: {exc.response.text}"
            )
            raise
        except httpx.HTTPError as exc:
            logger.error(f"HTTP error while starting Apify run (async): {exc}")
            raise

        data = response.json()
        run_id = data["data"]["id"]
        logger.info(f"Started Apify mutual connections run (async): {run_id}")
        return {"runId": run_id}

    async def fetch_dataset_items_async(self, dataset_id: str) -> List[Dict]:
        if not self.is_configured:
            return self._handle_disabled(
                {"note": f"dataset_fetch_skipped_{dataset_id}"},
                return_type="list",
            )
        client = await self._get_async_client()
        try:
            response = await client.get(
                f"{APIFY_API}/datasets/{dataset_id}/items",
                params={
                    "token": self.api_token,
                    "format": "json",
                    "clean": "true",
                },
            )
            response.raise_for_status()
            items = response.json()
            logger.info(f"Fetched {len(items)} items from Apify dataset {dataset_id} (async)")
            return items
        except httpx.HTTPStatusError as exc:
            logger.error(
                f"Failed to fetch dataset items (async) [{exc.response.status_code}]: {exc.response.text}"
            )
            return []
        except httpx.HTTPError as exc:
            logger.error(f"Failed to fetch dataset items (async): {exc}")
            return []

    async def get_run_info_async(self, run_id: str) -> Dict:
        if not self.is_configured:
            return self._handle_disabled(
                {"note": f"run_info_skipped_{run_id}"},
                return_type="dict",
            )
        client = await self._get_async_client()
        try:
            response = await client.get(
                f"{APIFY_API}/actor-runs/{run_id}",
                params={"token": self.api_token},
            )
            response.raise_for_status()
            return response.json()["data"]
        except httpx.HTTPStatusError as exc:
            logger.error(
                f"Failed to get run info (async) [{exc.response.status_code}]: {exc.response.text}"
            )
            return {}
        except httpx.HTTPError as exc:
            logger.error(f"Failed to get run info (async): {exc}")
            return {}

    async def get_run_failure_details_async(self, run_id: str) -> Dict:
        if not self.is_configured:
            return self._handle_disabled(
                {"note": f"failure_details_skipped_{run_id}"},
                return_type="dict",
            )
        client = await self._get_async_client()
        try:
            response = await client.get(
                f"{APIFY_API}/actor-runs/{run_id}",
                params={"token": self.api_token},
            )
            response.raise_for_status()
            run_info = response.json().get("data", {})
        except httpx.HTTPError as exc:
            logger.error(f"Failed to get failure details for run {run_id} (async): {exc}")
            return {"error": "Could not fetch failure details", "exception": str(exc)}

        status = run_info.get("status", "UNKNOWN")
        if status == "FAILED":
            error_details = {
                "status": status,
                "statusMessage": run_info.get("statusMessage", ""),
                "errorMessage": run_info.get("errorMessage", ""),
                "exitCode": run_info.get("exitCode"),
                "finishedAt": run_info.get("finishedAt"),
                "stats": run_info.get("stats", {}),
            }
            stats = run_info.get("stats", {})
            if stats.get("requestsFailed", 0) > 0:
                error_details["likely_cause"] = "LinkedIn page failed to load - possibly malformed URL"
            return error_details

        return {"status": status, "message": f"Run is {status}, not failed"}

    def is_configured(self) -> bool:
        return bool(self.api_token)

def _rows_to_settings(rows, decrypt_func, key_col="setting_key", value_col="setting_value"):
    """GPT5's fix: Properly process database rows to decrypt values, not column names"""
    out = {}
    for r in rows:
        # Handle SQLite Row objects, dict-like, and tuple-like rows
        try:
            if hasattr(r, 'keys') and hasattr(r, '__getitem__'):
                # SQLite Row object or dict-like object
                try:
                    key = r[key_col] if key_col in r.keys() else (r["key"] if "key" in r.keys() else None)
                    val = r[value_col] if value_col in r.keys() else (r["value"] if "value" in r.keys() else None)
                    encrypted = r["encrypted"] if "encrypted" in r.keys() else 0
                except (KeyError, TypeError):
                    # Fallback to positional indexing
                    if key_col == "setting_key":
                        key, val, encrypted = r[0], r[1], r[2] if len(r) > 2 else 0
                    else:  # provider/key format
                        key, val, encrypted = r[0], r[1], r[2] if len(r) > 2 else 0
            elif hasattr(r, '__getitem__') and hasattr(r, '__len__'):
                # Tuple or list format - use positional indexing
                if key_col == "setting_key":
                    key, val, encrypted = r[0], r[1], r[2] if len(r) > 2 else 0
                else:  # provider/key format
                    key, val, encrypted = r[0], r[1], r[2] if len(r) > 2 else 0
            else:
                logger.warning(f"Unrecognized row format: {type(r)}")
                continue
                
        except Exception as row_error:
            logger.warning(f"Error processing row {r}: {row_error}")
            continue
        
        if not key or val is None:
            continue
            
        # Only decrypt if encrypted flag is set and we have a value
        if encrypted and val:
            try:
                val = decrypt_func(val)
            except Exception as e:
                logger.warning(f"Failed to decrypt {key}: {e}, treating as plaintext")
                # Keep original value as plaintext fallback
                pass
        
        if val:  # Only include non-empty values
            out[key] = val
    return out

def get_tenant_integration_settings(tenant_id: int, user_id: Optional[int] = None) -> Dict[str, str]:
    """Get tenant-specific integration settings from database, with user-specific LinkedIn cookie overrides"""
    try:
        from api.mt_db import get_db
        from api.security import dec  # encryption/decryption
        
        # Map provider names to expected setting keys
        provider_to_setting = {
            'apify': 'apify_token',
            'apify_token': 'apify_token', 
            'phantombuster': 'phantombuster_api_key',
            'phantombuster_api_key': 'phantombuster_api_key',
            'linkedin': 'linkedin_li_at',
            'linkedin_li_at': 'linkedin_li_at',
            'linkedin_jsessionid': 'linkedin_jsessionid',
            'linkedin_cookies_json': 'linkedin_cookies_json',
            'apify_webhook_secret': 'apify_webhook_secret',
            # Add OpenAI and CUFinder settings for readiness checks
            'openai': 'openai_api_key',
            'openai_api_key': 'openai_api_key',
            'cufinder': 'cufinder_api_key', 
            'cufinder_api_key': 'cufinder_api_key',
            'sendgrid': 'sendgrid_api_key',
            'sendgrid_api_key': 'sendgrid_api_key'
        }
        
        with get_db() as conn:
            cursor = conn.cursor()
            
            settings_dict = {}
            
            # Detect database type by trying to get connection info
            is_postgresql = hasattr(conn, 'info') and 'postgresql' in str(type(conn)).lower()
            param_placeholder = '%s' if is_postgresql else '?'
            
            # First check tenant_settings table (preferred for tenant-wide settings)
            try:
                cursor.execute(
                    f"SELECT setting_key, setting_value, encrypted FROM tenant_settings WHERE tenant_id = {param_placeholder}",
                    (tenant_id,)
                )
                tenant_rows = cursor.fetchall()
                
                # GPT5's fix: Use proper row processing to decrypt values, not column names
                tenant_settings = _rows_to_settings(tenant_rows, dec)
                settings_dict.update(tenant_settings)
            except Exception as e:
                logger.warning(f"Could not query tenant_settings for tenant {tenant_id}: {e}")
            
            # Also check user_integrations table for backwards compatibility
            try:
                cursor.execute(
                    f"SELECT provider, key, encrypted FROM user_integrations WHERE tenant_id = {param_placeholder}",
                    (tenant_id,)
                )
                user_rows = cursor.fetchall()
                
                # GPT5's fix: Use proper row processing for user integrations too
                user_settings = _rows_to_settings(user_rows, dec, key_col="provider", value_col="key")
                
                # Map provider names to expected setting keys and merge
                for provider, value in user_settings.items():
                    setting_key = provider_to_setting.get(provider, provider)
                    # Only add if not already in tenant settings (tenant_settings takes precedence)
                    if setting_key not in settings_dict:
                        settings_dict[setting_key] = value
            except Exception as e:
                logger.warning(f"Could not query user_integrations for tenant {tenant_id}: {e}")
            
            # Get user-specific LinkedIn cookies if user_id is provided
            if user_id:
                try:
                    cursor.execute(
                        f"""SELECT li_at_encrypted, jsessionid_encrypted
                           FROM linkedin_sessions
                           WHERE user_id = {param_placeholder} AND is_active = 1
                           ORDER BY created_at DESC LIMIT 1""",
                        (user_id,)
                    )
                    cookie_row = cursor.fetchone()

                    if cookie_row:
                        li_at_encrypted = None
                        jsessionid_encrypted = None

                        if hasattr(cookie_row, "keys"):
                            try:
                                mapping_row = dict(cookie_row)  # Handles sqlite3.Row and RealDictRow
                            except TypeError:
                                mapping_row = {key: cookie_row[key] for key in cookie_row.keys()}  # type: ignore[index]

                            li_at_encrypted = mapping_row.get("li_at_encrypted")
                            jsessionid_encrypted = mapping_row.get("jsessionid_encrypted")
                        else:
                            try:
                                row_length = len(cookie_row)
                            except TypeError:
                                row_length = 0

                            if row_length > 0:
                                li_at_encrypted = cookie_row[0]
                            if row_length > 1:
                                jsessionid_encrypted = cookie_row[1]

                        if li_at_encrypted:
                            try:
                                settings_dict['linkedin_li_at'] = dec(li_at_encrypted)
                                logger.info(f"✅ Loaded user-specific li_at for user {user_id}")
                            except Exception as e:
                                logger.warning(f"Failed to decrypt user li_at: {e}")

                        if jsessionid_encrypted:
                            try:
                                settings_dict['linkedin_jsessionid'] = dec(jsessionid_encrypted)
                                logger.info(f"✅ Loaded user-specific JSESSIONID for user {user_id}")
                            except Exception as e:
                                logger.warning(f"Failed to decrypt user JSESSIONID: {e}")

                        # Also build a cookies_json for compatibility
                        if li_at_encrypted:
                            try:
                                li_at_value = dec(li_at_encrypted)
                                jsessionid_value = dec(jsessionid_encrypted) if jsessionid_encrypted else None

                                cookies_array = [
                                    {"name": "li_at", "value": li_at_value}
                                ]
                                if jsessionid_value:
                                    cookies_array.append({"name": "JSESSIONID", "value": jsessionid_value})

                                settings_dict['linkedin_cookies_json'] = json.dumps(cookies_array)
                                logger.info(f"✅ Built user-specific cookies_json for user {user_id}")
                            except Exception as e:
                                logger.warning(f"Failed to build user cookies_json: {e}")

                except Exception as e:
                    logger.warning(f"Failed to load user-specific LinkedIn cookies for user {user_id}: {e}")

            logger.info(f"Retrieved {len(settings_dict)} integration settings for tenant {tenant_id} (user: {user_id})")
            return settings_dict
            
    except Exception as e:
        logger.error(f"Failed to get tenant integration settings for tenant {tenant_id}: {e}")
        return {}

def get_tenant_apify_client(
    tenant_id: int,
    user_id: Optional[int] = None,
    *,
    fail_on_missing: bool = False,
) -> ApifyClient:
    """Get tenant-specific ApifyClient with their integration settings and user-specific LinkedIn cookies"""
    tenant_settings = get_tenant_integration_settings(tenant_id, user_id)

    # Map admin panel setting keys to expected keys
    return ApifyClient(
        api_token=tenant_settings.get('apify_token') or tenant_settings.get('apify'),  # Admin saves as 'apify'
        webhook_secret=tenant_settings.get('apify_webhook_secret'),
        li_cookie_secret_name=tenant_settings.get('apify_li_cookie_secret_name'),
        li_at=tenant_settings.get('linkedin_li_at'),
        jsessionid=tenant_settings.get('linkedin_jsessionid'),
        cookies_json=tenant_settings.get('linkedin_cookies_json'),
        tenant_id=tenant_id,
        fail_on_missing=fail_on_missing,
    )

# Global client instance (fallback for backwards compatibility)
try:
    apify_client = ApifyClient(tenant_id=None)
except ApifyConfigurationError:
    apify_client = None
