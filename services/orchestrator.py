import asyncio
import datetime
import json
import logging
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from core.settings import settings
from core.db import normalize_linkedin_url
from api.database import get_db, using_native_adapter
from integrations.apify_client import (
    apify_client,
    get_tenant_apify_client,
)
# PhantomBuster removed - using Apify-only strategy
from services.mutuals_service import mutuals_service

logger = logging.getLogger(__name__)

class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"

class ErrorType(Enum):
    EMPTY_RESULTS = "empty_results"
    PRIVACY_BLOCKED = "privacy_blocked"  
    SESSION_INVALID = "session_invalid"
    CAPTCHA_REQUIRED = "captcha_required"
    RATE_LIMITED = "rate_limited"
    NETWORK_ERROR = "network_error"
    PROVIDER_ERROR = "provider_error"
    CANNOT_CONSTRUCT_FALLBACK = "cannot_construct_fallback_url"
    UNKNOWN_ERROR = "unknown_error"

@dataclass
class JobResult:
    status: JobStatus
    provider: str
    result_count: int
    data: List[Dict]
    error: Optional[str] = None
    error_details: Optional[Dict] = None
    run_id: Optional[str] = None

class MutualsOrchestrator:
    """
    Orchestrates mutual connections discovery using Apify LinkedIn scraping
    Implements single-provider strategy with CUFinder email enrichment
    """
    
    def __init__(self):
        self.running_jobs = {}  # track concurrent jobs
        self.max_concurrent = settings.MAX_CONCURRENT_JOBS
    
    async def find_introducers(self, prospect_url: str, prospect_name: str = None, 
                             prospect_company: str = None, connections_of_url: str = None,
                             warm_up_profile_visits: bool = True, auto_send_intros: bool = False,
                             tenant_id: int = None, user_id: int = None) -> Dict:
        """
        Main entry point for finding introducers
        Returns ranked list of potential introducers with draft messages
        """
        resolved_tenant_id = str(tenant_id).strip() if tenant_id is not None else ""
        if not resolved_tenant_id:
            raise ValueError("tenant_id is required")

        if user_id in (None, ""):
            raise ValueError("user_id is required")

        resolved_user_id = int(user_id)
        tenant_id = resolved_tenant_id
        user_id = resolved_user_id

        try:
            # PHASE 1: Intake & Idempotency Check
            from services.idempotency_service import idempotency_service
            from services.error_classifier import error_classifier
            from services.warmup_service import warmup_service
            
            logger.info(f"🚀 Starting bulletproof introducer search for: {prospect_name} ({prospect_url})")
            
            # Create or update prospect first to get prospect_id
            prospect_id = mutuals_service.upsert_prospect(
                linkedin_url=prospect_url,
                full_name=prospect_name,
                company=prospect_company,
                tenant_id=tenant_id,
                user_id=user_id
            )
            
            # Check for existing job with enhanced idempotency
            idempotency_check = idempotency_service.check_job_idempotency(
                prospect_url, 'find_introducers', prospect_id, tenant_id
            )
            
            if not idempotency_check['can_proceed']:
                if idempotency_check.get('cached'):
                    logger.info(f"📋 Returning cached result for {prospect_url}")
                    result = idempotency_check['result_data']
                    result['diagnostics']['cache_hit'] = True
                    return result
                else:
                    logger.info(f"⏳ Job already running for {prospect_url}")
                    return {
                        "status": "in_progress",
                        "message": "Job already in progress",
                        "idempotency_key": idempotency_check['idempotency_key']
                    }
            
            idempotency_key = idempotency_check['idempotency_key']
            
            # Create job record and mark as running
            job_record_id = idempotency_service.create_job_record(
                idempotency_key, prospect_id, 'find_introducers', tenant_id
            )
            idempotency_service.update_job_status(idempotency_key, 'running')
            
            # Record job start for legacy tracking
            job_id = self._record_job_start(tenant_id, prospect_id, "find_introducers")
            
            # Strategy: Run Apify to find actual LinkedIn mutual connections
            logger.info("🔍 Starting Apify LinkedIn mutual connections scrape...")
            
            try:
                from utils.linkedin import get_linkedin_url_variants
                tenant_apify_client = get_tenant_apify_client(
                    tenant_id,
                    user_id,
                    fail_on_missing=False,
                )
                if tenant_apify_client is None or not tenant_apify_client.is_configured:
                    reason = (
                        tenant_apify_client.configuration_reason
                        if tenant_apify_client is not None
                        else "Apify token is not configured for this environment."
                    )
                    logger.warning(f"Apify disabled for tenant {tenant_id}: {reason}")
                    result = {
                        "providers_used": ["apify"],
                        "primary_provider": "apify",
                        "total_mutuals": 0,
                        "approach": "apify_disabled",
                        "winner_latency_ms": 0,
                        "error_details": reason,
                    }
                else:
                    url_variants = get_linkedin_url_variants(prospect_url)
                    logger.info(f"🔄 Will try {len(url_variants)} URL variants for LinkedIn scraping")

                    overall_start = time.time()
                    results: List[Dict] = []
                    successful_url = None
                    last_error = None

                    for attempt, url_variant in enumerate(url_variants, 1):
                        logger.info(f"🎯 Attempt {attempt}/{len(url_variants)}: {url_variant}")
                        try:
                            run_result = await tenant_apify_client.start_mutuals_run_async(
                                url_variant,
                                prospect_id,
                                tenant_id,
                            )
                            if run_result.get("disabled"):
                                logger.warning(
                                    "Apify run skipped for tenant %s (disabled): %s",
                                    tenant_id,
                                    run_result.get("reason"),
                                )
                                last_error = run_result.get("reason")
                                break
                            run_id = run_result.get("runId")
                            if not run_id:
                                raise RuntimeError("Apify did not return a runId")

                            start_time = time.time()
                            timeout_sec = 120  # 2 minutes per variant
                            poll_interval = 10
                            variant_results: List[Dict] = []

                            while (time.time() - start_time) < timeout_sec:
                                run_info = await tenant_apify_client.get_run_info_async(run_id)
                                if not run_info:
                                    logger.debug("Apify run info unavailable, retrying poll")
                                    await asyncio.sleep(poll_interval)
                                    continue

                                run_status = run_info.get("status", "UNKNOWN")
                                logger.info(f"Apify run status: {run_status}")

                                if run_status == "SUCCEEDED":
                                    dataset_id = run_info.get("defaultDatasetId")
                                    if not dataset_id:
                                        last_error = "No dataset ID returned for completed run"
                                        break

                                    variant_results = await tenant_apify_client.fetch_dataset_items_async(dataset_id)
                                    logger.info(
                                        f"✅ URL variant {attempt} found {len(variant_results)} mutual connections"
                                    )
                                    results = variant_results
                                    successful_url = url_variant
                                    break

                                if run_status in {"FAILED", "ABORTED", "TIMED-OUT", "TIMED_OUT"}:
                                    failure_details = await tenant_apify_client.get_run_failure_details_async(run_id)
                                    error_msg = (
                                        failure_details.get("statusMessage")
                                        or failure_details.get("errorMessage")
                                        or "Unknown error"
                                    )
                                    logger.error(f"Apify failure details for URL variant {attempt}: {error_msg}")
                                    last_error = error_msg
                                    break

                                await asyncio.sleep(poll_interval)

                            if results:
                                break

                            if not results and (time.time() - start_time) >= timeout_sec:
                                logger.warning(f"⏰ URL variant {attempt} timed out after {timeout_sec} seconds")
                                last_error = f"URL variant {attempt} timed out"

                        except Exception as variant_error:
                            logger.error(f"Error trying URL variant {attempt}: {variant_error}")
                            last_error = str(variant_error)
                            continue

                    if not results:
                        logger.error(
                            f"❌ All {len(url_variants)} URL variants failed. Last error: {last_error}"
                        )
                        result = {
                            "providers_used": ["apify"],
                            "primary_provider": "apify",
                            "total_mutuals": 0,
                            "approach": "apify_all_variants_failed",
                            "error_details": f"All URL variants failed. Last error: {last_error}",
                            "url_variants_tried": url_variants,
                        }
                    else:
                        logger.info(f"🎉 Successfully scraped {len(results)} mutuals using URL: {successful_url}")
                        logger.info(f"🔄 Processing {len(results)} Apify results...")

                        normalized_items = []
                        for i, item in enumerate(results):
                            logger.debug(f"Processing item {i+1}: {item.get('full_name', 'Unknown')}")
                            normalized_items.append(
                                tenant_apify_client.normalize_mutual_connection(item)
                            )

                        if normalized_items:
                            logger.info(f"📦 Storing {len(normalized_items)} normalized items to database...")
                            try:
                                stored_count = mutuals_service.store_mutual_connections(
                                    prospect_id,
                                    normalized_items,
                                    "apify",
                                    run_id,
                                    tenant_id,
                                )
                                logger.info(f"✅ Apify found {len(results)} connections, stored {stored_count}")

                                result = {
                                    "providers_used": ["apify"],
                                    "primary_provider": "apify",
                                    "total_mutuals": stored_count,
                                    "approach": "apify",
                                    "winner_latency_ms": int((time.time() - overall_start) * 1000),
                                }
                            except Exception as db_error:
                                logger.error(f"❌ Database storage failed: {db_error}")
                                result = {
                                    "providers_used": ["apify"],
                                    "primary_provider": "apify",
                                    "total_mutuals": 0,
                                    "approach": "apify_db_error",
                                    "winner_latency_ms": int((time.time() - overall_start) * 1000),
                                    "error": str(db_error),
                                }
                        else:
                            logger.warning("⚠️ Apify returned no normalizable results")
                            result = {
                                "providers_used": ["apify"],
                                "primary_provider": "apify",
                                "total_mutuals": 0,
                                "approach": "apify_empty",
                                "winner_latency_ms": int((time.time() - overall_start) * 1000),
                            }
                
            except Exception as e:
                logger.error(f"❌ Apify failed: {e}")
                
                # Classify the error for better user feedback
                error_message = str(e)
                if "400 Client Error" in error_message and "localhost" in error_message:
                    error_type = "webhook_localhost_error"
                    user_message = "Apify cannot reach localhost webhook URL. Deploy to production or configure public webhook URL."
                elif "400 Client Error" in error_message and "cookies" in error_message:
                    error_type = "authentication_error" 
                    user_message = "LinkedIn authentication failed. Check that both li_at cookie and JSESSIONID are properly configured in admin settings."
                elif "400 Client Error" in error_message and "url" in error_message:
                    error_type = "invalid_input_error"
                    user_message = "Invalid input provided to Apify. Check the LinkedIn profile URL format."
                elif "401" in error_message or "Unauthorized" in error_message:
                    error_type = "api_key_error"
                    user_message = "Apify API key is invalid or expired. Please check the API token in admin settings."
                elif "403" in error_message or "Forbidden" in error_message:
                    error_type = "permission_error"
                    user_message = "Apify API access denied. Check API key permissions or account limits."
                elif "429" in error_message or "rate limit" in error_message.lower():
                    error_type = "rate_limit_error"
                    user_message = "Apify API rate limit exceeded. Please wait before trying again."
                elif "timeout" in error_message.lower() or "connection" in error_message.lower():
                    error_type = "network_error"
                    user_message = "Network connection to Apify failed. Please check internet connection and try again."
                else:
                    error_type = "unknown_apify_error"
                    user_message = f"Apify integration failed: {error_message}"
                
                result = {
                    "providers_used": ["apify"],
                    "primary_provider": "apify", 
                    "total_mutuals": 0,
                    "approach": "apify_failed",
                    "winner_latency_ms": 0,
                    "error": {
                        "type": error_type,
                        "message": user_message,
                        "technical_details": error_message
                    }
                }
            
            # Get final introducers - use all mutual connections, not just ones in contacts
            logger.info(f"🔍 Retrieving introducers for prospect_id: {prospect_id}")
            try:
                introducers = mutuals_service.get_all_mutual_connections(prospect_id, limit=5, tenant_id=tenant_id)
                logger.info(f"👥 Found {len(introducers)} introducers to return")
                
                # PHASE 4: CUFinder Email Enrichment (run whenever we have introducers)
                if introducers:
                    logger.info(f"🔍 Starting CUFinder email enrichment for {len(introducers)} introducers...")
                    try:
                        from services.email_service import email_service
                        
                        # Prepare introducer data for enrichment (only those without emails)
                        introducers_needing_enrichment = [
                            introducer for introducer in introducers 
                            if not introducer.get('email') or introducer.get('email_confidence', 0) < 0.8
                        ]
                        
                        if introducers_needing_enrichment:
                            logger.info(f"📧 Enriching emails for {len(introducers_needing_enrichment)} introducers without reliable emails")
                            
                            # Convert to the format expected by email enrichment
                            contacts_for_enrichment = []
                            for introducer in introducers_needing_enrichment:
                                contact = {
                                    'id': introducer.get('id'),
                                    'full_name': introducer.get('full_name'),
                                    'company': introducer.get('company'),
                                    'title': introducer.get('title'),
                                    'linkedin_url': introducer.get('linkedin_url'),
                                    'email': introducer.get('email'),  # Existing email (if any)
                                    'email_confidence': introducer.get('email_confidence', 0)
                                }
                                contacts_for_enrichment.append(contact)
                            
                            # Perform bulk email enrichment via CUFinder
                            # Fix method name - should be enrich_contacts, not enrich_contact_emails
                            contact_ids = [contact['id'] for contact in contacts_for_enrichment]
                            enrichment_results = await email_service.enrich_contacts(
                                contact_ids,
                                tenant_id=tenant_id
                            )
                            if enrichment_results.get('status') == 'configuration_required':
                                message = enrichment_results.get('message') or "CUFinder email enrichment is not configured."
                                logger.warning(f"📧 CUFinder disabled for tenant {tenant_id}: {message}")
                                result['email_enrichment'] = {
                                    'attempted': len(introducers_needing_enrichment),
                                    'enriched': 0,
                                    'cost': 0,
                                    'status': 'disabled',
                                    'message': message
                                }
                                enrichment_results = None
                            
                            if enrichment_results:
                                logger.info(f"✅ CUFinder enrichment completed: {enrichment_results.get('enriched_count', 0)} emails found")
                                
                                # Update introducers with enriched email data
                                enriched_emails = enrichment_results.get('results', [])
                                email_lookup = {contact['id']: contact for contact in enriched_emails}
                                
                                for introducer in introducers:
                                    if introducer.get('id') in email_lookup:
                                        enriched_data = email_lookup[introducer['id']]
                                        if enriched_data.get('email') and enriched_data.get('email') != introducer.get('email'):
                                            introducer['email'] = enriched_data['email']
                                            introducer['email_confidence'] = enriched_data.get('email_confidence', 0.8)
                                            introducer['email_enriched'] = True
                                            logger.debug(f"📧 Updated {introducer['full_name']} with email: {enriched_data['email']}")
                                
                                # Store enrichment info in result for user feedback
                                result['email_enrichment'] = {
                                    'attempted': len(introducers_needing_enrichment),
                                    'enriched': enrichment_results.get('enriched_count', 0),
                                    'cost': enrichment_results.get('total_cost', 0),
                                    'high_confidence': enrichment_results.get('high_confidence_count', 0)
                                }
                        else:
                            logger.info("📧 All introducers already have reliable emails, skipping CUFinder enrichment")
                            result['email_enrichment'] = {
                                'attempted': 0,
                                'enriched': 0, 
                                'cost': 0,
                                'message': 'All introducers already have reliable emails'
                            }
                            
                    except Exception as enrichment_error:
                        logger.error(f"❌ CUFinder email enrichment failed: {enrichment_error}")
                        # Don't fail the whole workflow for enrichment errors
                        result['email_enrichment'] = {
                            'attempted': len(introducers_needing_enrichment) if 'introducers_needing_enrichment' in locals() else 0,
                            'enriched': 0,
                            'cost': 0,
                            'error': str(enrichment_error)
                        }
                else:
                    logger.info("📧 Skipping CUFinder enrichment (no introducers found)")
                
                # Generate intro drafts for top introducers
                for i, introducer in enumerate(introducers):
                    logger.debug(f"Generating intro draft for introducer {i+1}: {introducer.get('full_name', 'Unknown')}")
                    introducer["intro_draft"] = mutuals_service.generate_intro_draft(
                        introducer_name=introducer["full_name"],
                        prospect_name=prospect_name or "this contact",
                        prospect_company=prospect_company
                    )
            except Exception as retrieval_error:
                logger.error(f"❌ Failed to retrieve introducers: {retrieval_error}")
                introducers = []  # Fallback to empty list
            
            # PHASE 5: Profile Warm-up (Optional) with Batch Processing
            warmup_items = []
            if warm_up_profile_visits and introducers:
                try:
                    logger.info(f"⚡ Importing batch_service for warmup processing...")
                    from services.batch_service import batch_service, BatchType
                    logger.info(f"✅ batch_service imported successfully")
                    
                    # Check daily quota before queuing
                    introducer_urls = [intro.get('linkedin_url') for intro in introducers 
                                     if intro.get('linkedin_url')][:settings.WARMUP_VISITOR_TOP_N]
                    
                    quota_check = batch_service.check_daily_quota(1, BatchType.WARM_UP_VISITS, len(introducer_urls))
                    
                    if quota_check['can_proceed'] and introducer_urls:
                        warmup_items = warmup_service.queue_profile_warmup(
                            prospect_id=prospect_id,
                            linkedin_urls=introducer_urls,
                            delay_hours=settings.WARMUP_DELAY_HOURS,
                            tenant_id=tenant_id
                        )
                        logger.info(f"👀 Queued profile warm-up for {len(warmup_items)} introducers (quota: {quota_check['remaining']} remaining)")
                        
                        # Add warm-up info to introducers
                        for introducer in introducers:
                            url = introducer.get('linkedin_url')
                            if any(w['linkedin_url'] == url for w in warmup_items):
                                introducer['warmup_queued'] = True
                                introducer['warmup_delay_hours'] = settings.WARMUP_DELAY_HOURS
                    else:
                        logger.warning(f"Daily warm-up quota exceeded: {quota_check}")
                        # Still add quota info to response
                        warmup_items = [{
                            'status': 'quota_exceeded',
                            'quota_info': quota_check,
                            'message': f"Daily limit reached ({quota_check['used_today']}/{quota_check['daily_limit']})"
                        }]
                        
                except Exception as e:
                    logger.error(f"Error queuing profile warm-up: {e}")
                    # Don't fail the whole job for warm-up errors
            
            # OUTREACH STAGE: Queue warm introductions if introducers found
            outreach_items = []
            logger.info(f"Outreach stage: introducers={len(introducers)}, auto_send_intros={auto_send_intros}")
            
            if introducers and auto_send_intros:
                try:
                    logger.info(f"⚡ Importing outreach_service for outreach processing...")
                    from services.outreach_service import outreach_service
                    logger.info(f"✅ outreach_service imported successfully")
                    
                    # Import batch_service if not already imported
                    if 'batch_service' not in locals():
                        from services.batch_service import batch_service, BatchType
                    
                    # Check daily quota before queuing outreach
                    quota_check = batch_service.check_daily_quota(1, BatchType.OUTREACH_MESSAGES, len(introducers))
                    
                    prospect_data = {
                        "id": prospect_id,
                        "full_name": prospect_name or "this contact", 
                        "company": prospect_company
                    }
                    
                    if quota_check['can_proceed']:
                        logger.info(f"Queuing outreach for {len(introducers)} introducers (quota: {quota_check['remaining']} remaining)")
                        
                        # Queue outreach messages (auto-approve if enabled)
                        outreach_items = outreach_service.queue_outreach(
                            introducers=introducers,
                            prospect=prospect_data,
                            template_name='intro_default',
                            auto_approve=auto_send_intros,  # User preference for auto-sending
                            tenant_id=tenant_id  # CRITICAL: Include tenant_id for isolation
                        )
                        
                        logger.info(f"Successfully queued {len(outreach_items)} outreach messages for {prospect_name}")
                    else:
                        logger.warning(f"Daily outreach quota exceeded: {quota_check}")
                        # Still add quota info to response
                        outreach_items = [{
                            'status': 'quota_exceeded',
                            'quota_info': quota_check,
                            'message': f"Daily limit reached ({quota_check['used_today']}/{quota_check['daily_limit']})"
                        }]
                    
                except Exception as e:
                    logger.error(f"Error queuing outreach: {e}")
                    import traceback
                    logger.error(f"Outreach error traceback: {traceback.format_exc()}")
                    # Don't fail the whole request if outreach queuing fails
            else:
                if not introducers:
                    logger.info("No introducers found - skipping outreach")
                if not auto_send_intros:
                    logger.info("Auto-send intros disabled - skipping outreach")
            
            # Initialize default result if not set (for existing data scenarios)
            if 'result' not in locals():
                result = {
                    "providers_used": ["existing_data"],
                    "primary_provider": "existing_data", 
                    "total_mutuals": len(introducers),
                    "approach": "existing_data",
                    "winner_latency_ms": 0
                }

            # Update job completion
            logger.info(f"📊 Recording job completion...")
            self._record_job_completion(job_id, len(introducers), result.get("primary_provider"))
            
            # Get prospect summary
            logger.info(f"📋 Getting prospect summary...")
            summary = mutuals_service.get_prospect_summary(prospect_id)
            
            # PHASE 7: Final Result Assembly with Bulletproof Features
            logger.info(f"🔧 Assembling final result...")
            final_result = {
                "status": "success",
                "prospect_id": prospect_id,
                "prospect_summary": summary,
                "introducers": introducers,
                "providers_used": result.get("providers_used", []),
                "primary_provider": result.get("primary_provider"),
                "total_mutuals_found": result.get("total_mutuals", 0),
                "email_enrichment": result.get("email_enrichment", None),  # CUFinder enrichment results
                "outreach_queued": len(outreach_items),
                "outreach_items": outreach_items,
                "warmup_queued": len(warmup_items),
                "warmup_items": warmup_items,
                "idempotency_key": idempotency_key,
                "apify_run_id": result.get("apify_run_id"),
                "diagnostics": {
                    "approach": result.get("approach", "sequential"),
                    "winner_latency_ms": result.get("winner_latency_ms", 0),
                    "cache_hit": False,
                    "introducers_count": len(introducers),
                    "warm_up_enabled": warm_up_profile_visits,
                    "auto_send_enabled": auto_send_intros,
                    "email_enrichment_enabled": result.get("email_enrichment") is not None
                }
            }
            
            # Mark job as completed and cache result with new idempotency service
            idempotency_service.update_job_status(idempotency_key, 'completed', final_result)
            
            # Legacy caching (keep for compatibility)
            if len(introducers) > 0:
                self._cache_result(idempotency_key, prospect_id, final_result)
            
            logger.info(f"✅ Bulletproof workflow completed for {prospect_name}: "
                       f"{len(introducers)} introducers, {len(outreach_items)} queued, "
                       f"{len(warmup_items)} warm-ups")
            
            logger.info(f"🚀 Returning final result to frontend...")
            return final_result
            
        except Exception as e:
            logger.error(f"Failed to find introducers: {e}")
            
            # Enhanced error classification - don't classify DB errors as provider errors
            try:
                error_message = str(e)
                
                # Don't treat database errors as provider health issues
                if any(db_error in error_message for db_error in [
                    'Database upsert failed', 'upsert returned no ID', 'RuntimeError', 
                    'constraint', 'duplicate key', 'relation does not exist'
                ]):
                    logger.error(f"Database/application error (not provider): {error_message}")
                    error_code, user_message = 'database_error', 'Database operation failed. Please try again.'
                    # Don't record as provider error - this is application/DB issue
                else:
                    # Classify as provider error and record for health tracking
                    error_code, user_message = error_classifier.classify_error(error_message, 'system')
                    error_classifier.record_provider_error('system', error_code, error_message, tenant_id=tenant_id)
                
                # Mark job as failed with error details
                if 'idempotency_key' in locals():
                    idempotency_service.update_job_status(idempotency_key, 'failed', {
                        'error_code': error_code,
                        'error_message': str(e),
                        'user_message': user_message
                    })
            except Exception as err_ex:
                logger.error(f"Error in error handling: {err_ex}")
                error_code, user_message = 'unknown_error', 'An unexpected error occurred'
            
            # Initialize prospect_id if not already set
            if 'prospect_id' not in locals():
                prospect_id = None
            
            return {
                "status": "error",
                "error_code": error_code,
                "error_message": user_message,
                "prospect_id": prospect_id,
                "idempotency_key": idempotency_key if 'idempotency_key' in locals() else None,
                "diagnostics": {
                    "raw_error": str(e),
                    "approach": "unknown",
                    "providers_attempted": []
                }
            }
    
    async def _run_dual_approach(self, prospect_id: int, prospect_url: str):
        """Run Apify job (PhantomBuster deprecated, using Apify-only strategy)"""
        try:
            logger.info("Running Apify-only approach (PhantomBuster deprecated)")

            # Start Apify job
            apify_task = asyncio.create_task(self._run_apify_job(prospect_id, prospect_url))

            # Get result from Apify
            providers_used = []
            total_mutuals = 0
            primary_provider = None
            winner_result = None

            try:
                # Wait for Apify completion
                result = await apify_task

                # Process the Apify result
                if result.status == JobStatus.COMPLETED and result.result_count > 0:
                    primary_provider = result.provider
                    providers_used.append(result.provider)
                    total_mutuals = result.result_count
                    winner_result = result
                    logger.info(f"Apify job completed successfully with {result.result_count} results")
                else:
                    logger.warning(f"Apify job completed with status {result.status} and {result.result_count} results")

            except Exception as e:
                logger.error(f"Error in Apify job execution: {e}")
                # Cancel Apify task if still running
                if not apify_task.done():
                    apify_task.cancel()
            
            apify_run_id = getattr(winner_result, "run_id", None) if winner_result else None
            return {
                "providers_used": providers_used,
                "primary_provider": primary_provider or "none",
                "total_mutuals": total_mutuals,
                "winner_latency_ms": getattr(winner_result, 'latency_ms', 0) if winner_result else 0,
                "approach": "apify_only",
                "apify_run_id": apify_run_id,
            }
            
        except Exception as e:
            logger.error(f"Dual approach failed: {e}")
            return {
                "providers_used": [],
                "primary_provider": "none", 
                "total_mutuals": 0,
                "error": str(e)
            }
    
        """Try Apify first, fallback to PhantomBuster if needed"""
        try:
            logger.info("Running sequential approach: Apify -> PhantomBuster fallback")
            
            # Try Apify first
            apify_result = await self._run_apify_job(prospect_id, prospect_url)
            
            if apify_result.status == JobStatus.COMPLETED and apify_result.result_count > 0:
                return {
                    "providers_used": ["apify"],
                    "primary_provider": "apify",
                    "total_mutuals": apify_result.result_count,
                    "results": [apify_result],
                    "apify_run_id": getattr(apify_result, "run_id", None),
                }
            
            # Apify failed or returned no results, try PhantomBuster fallback
            logger.info("Apify failed or returned no results, trying PhantomBuster fallback")
            
            # Generate a basic connections-of URL for PhantomBuster
            
            return {
                "providers_used": ["apify", "phantombuster"],
                "primary_provider": "phantombuster" if pb_result.status == JobStatus.COMPLETED else "none",
                "total_mutuals": pb_result.result_count,
                "results": [apify_result, pb_result],
                "apify_run_id": getattr(apify_result, "run_id", None),
            }
            
        except Exception as e:
            logger.error(f"Sequential approach failed: {e}")
            return {
                "providers_used": [],
                "primary_provider": "none",
                "total_mutuals": 0,
                "error": str(e)
            }
    
    async def _run_apify_job(self, prospect_id: int, prospect_url: str) -> JobResult:
        """Run Apify mutual connections job with webhook-first approach"""
        try:
            logger.info(f"Starting Apify job for prospect {prospect_id}")
            if apify_client is None or not apify_client.is_configured:
                reason = (
                    apify_client.configuration_reason
                    if apify_client is not None
                    else "Apify token is not configured for this environment."
                )
                return JobResult(
                    status=JobStatus.FAILED,
                    provider="apify",
                    result_count=0,
                    error=reason,
                )

            # Start the Apify run
            run_info = await apify_client.start_mutuals_run_async(prospect_url, prospect_id)
            if run_info.get("disabled"):
                return JobResult(
                    status=JobStatus.FAILED,
                    provider="apify",
                    result_count=0,
                    error=run_info.get("reason"),
                )
            run_id = run_info["runId"]
            
            # Record job mapping for webhook processing
            self._record_apify_job_mapping(prospect_id, run_id, prospect_url)
            
            # Wait for webhook completion or polling fallback
            timeout = settings.APIFY_TIMEOUT_SECONDS
            start_time = time.time()
            poll_interval = 10
            webhook_timeout = 30  # Give webhook 30s advantage over polling
            
            # First, wait for webhook with short polling backup
            while time.time() - start_time < timeout:
                # Check if webhook already processed this job
                job_status = self._get_job_status(run_id)
                if job_status and job_status.get("webhook_received_at"):
                    # Webhook processed - get results from database
                    stored_count = job_status.get("result_count", 0)
                    if stored_count > 0:
                        return JobResult(
                            status=JobStatus.COMPLETED,
                            provider="apify", 
                            result_count=stored_count,
                            data=[],  # Data already in DB
                            run_id=run_id
                        )
                    else:
                        return JobResult(
                            status=JobStatus.FAILED,
                            provider="apify",
                            result_count=0,
                            data=[],
                            error="webhook_processed_empty_results",
                            run_id=run_id
                        )
                
                # After webhook timeout, start checking Apify API directly
                if time.time() - start_time > webhook_timeout:
                    run_status = await apify_client.get_run_info_async(run_id)
                    status = run_status.get("status")
                    
                    if status == "SUCCEEDED":
                        # Process results via polling fallback
                        dataset_id = run_status.get("defaultDatasetId")
                        if dataset_id:
                            items = await apify_client.fetch_dataset_items_async(dataset_id)
                            normalized_items = [apify_client.normalize_mutual_connection(item) for item in items]
                            
                            # Store results
                            stored_count = mutuals_service.store_mutual_connections(
                                prospect_id, normalized_items, "apify", run_id, tenant_id
                            )
                            
                            return JobResult(
                                status=JobStatus.COMPLETED,
                                provider="apify",
                                result_count=stored_count,
                                data=normalized_items,
                                run_id=run_id
                            )
                    elif status in ["FAILED", "ABORTED"]:
                        error_msg = run_status.get("statusMessage", "Unknown error")
                        return JobResult(
                            status=JobStatus.FAILED,
                            provider="apify",
                            result_count=0,
                            data=[],
                            error=error_msg,
                            run_id=run_id
                        )
                
                await asyncio.sleep(poll_interval)
            
            # Timeout
            return JobResult(
                status=JobStatus.TIMEOUT,
                provider="apify",
                result_count=0,
                data=[],
                error="Apify job timed out",
                run_id=run_id
            )
            
        except Exception as e:
            logger.error(f"Apify job failed: {e}")
            return JobResult(
                status=JobStatus.FAILED,
                provider="apify",
                result_count=0,
                data=[],
                error=str(e)
            )
    
        """Run PhantomBuster search export job"""
        try:
            logger.info(f"Starting PhantomBuster job for prospect {prospect_id}")
            
            # Launch PhantomBuster search export
            
            # Poll for results
            results = phantombuster_client.poll_and_fetch_results(
                container_id, 
                settings.PHANTOMBUSTER_TIMEOUT_SECONDS
            )
            
            if results:
                # Normalize results
                normalized_items = [phantombuster_client.normalize_search_result(item) for item in results]
                
                # Store results
                stored_count = mutuals_service.store_mutual_connections(
                    prospect_id, normalized_items, "phantombuster", container_id, tenant_id
                )
                
                return JobResult(
                    status=JobStatus.COMPLETED,
                    provider="phantombuster",
                    result_count=stored_count,
                    data=normalized_items,
                    run_id=container_id
                )
            else:
                return JobResult(
                    status=JobStatus.FAILED,
                    provider="phantombuster",
                    result_count=0,
                    data=[],
                    error="No results returned",
                    run_id=container_id
                )
            
        except Exception as e:
            logger.error(f"PhantomBuster job failed: {e}")
            return JobResult(
                status=JobStatus.FAILED,
                provider="phantombuster",
                result_count=0,
                data=[],
                error=str(e)
            )
    
        """Run PhantomBuster as fallback without a specific connections-of URL"""
        try:
            # Try to resolve ACo LinkedIn ID for the prospect
            aco_id = await self._resolve_linkedin_aco_id(prospect_url)
            
            if aco_id:
                # Create connections-of URL with ACo ID
                # Try Sales Navigator format first, then regular LinkedIn
                search_url = f"https://www.linkedin.com/sales/search/people/?facetNetwork=%5B%22F%22%5D&facetConnectionOf=%5B%22{aco_id}%22%5D"
                
                logger.info(f"Using ACo ID fallback URL: {search_url}")
            else:
                # Cannot construct valid fallback URL without ACo ID
                return JobResult(
                    status=JobStatus.FAILED,
                    provider="phantombuster",
                    result_count=0,
                    data=[],
                    error="cannot_construct_fallback_url",
                    error_details={
                        "message": "Need UI-generated 'Connections of' URL or ACo LinkedIn ID",
                        "solution": "Please provide connections_of_url parameter or contact admin to resolve ACo ID"
                    }
                )
            
        except Exception as e:
            logger.error(f"PhantomBuster fallback failed: {e}")
            return JobResult(
                status=JobStatus.FAILED,
                provider="phantombuster",
                result_count=0,
                data=[],
                error=str(e)
            )
    
    async def _resolve_linkedin_aco_id(self, prospect_url: str) -> Optional[str]:
        """
        Attempt to resolve LinkedIn ACo ID for a profile URL
        This is a placeholder - in practice you'd need to:
        1. Use LinkedIn's API if available
        2. Query your database if you've seen this profile before
        3. Use a profile scraper to get the ACo ID
        4. Return None if unavailable (forcing user to provide UI URL)
        """
        try:
            # Check if we have the ACo ID cached in database
            normalized_url = normalize_linkedin_url(prospect_url)
            with get_db() as conn:
                cursor = conn.execute(
                    "SELECT linkedin_aco_id FROM prospects WHERE linkedin_url = ?",
                    (normalized_url,)
                )
                row = cursor.fetchone()
                if row and row["linkedin_aco_id"]:
                    return row["linkedin_aco_id"]
            
            # TODO: Implement ACo ID resolution via a supported source if needed
            logger.info(f"No ACo ID cached for {prospect_url}, requiring UI-generated connections_of_url")
            return None
            
        except Exception as e:
            logger.error(f"Failed to resolve ACo ID: {e}")
            return None
    
    def _record_apify_job_mapping(self, prospect_id: int, run_id: str, prospect_url: str):
        """Record Apify job mapping for webhook processing"""
        try:
            with get_db() as conn:
                payload = json.dumps({"prospect_url": prospect_url})
                timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
                if using_native_adapter():
                    conn.execute("DELETE FROM job_runs WHERE external_id = %s", (run_id,))
                    conn.execute(
                        """
                        INSERT INTO job_runs 
                        (provider, job_type, external_id, prospect_id, status, input_data, started_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        ("apify", "mutual_connections", run_id, prospect_id, "running", payload, timestamp),
                    )
                else:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO job_runs 
                        (provider, job_type, external_id, prospect_id, status, input_data, started_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        ("apify", "mutual_connections", run_id, prospect_id, "running", payload, timestamp),
                    )
                logger.info("Recorded Apify job mapping: %s -> prospect %s", run_id, prospect_id)
        except Exception as e:
            logger.error("Failed to record Apify job mapping: %s", e)
    
    def _get_job_status(self, external_id: str) -> Optional[Dict]:
        """Get job status from database"""
        try:
            with get_db() as conn:
                cursor = conn.execute(
                    "SELECT * FROM job_runs WHERE external_id = ?", 
                    (external_id,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get job status: {e}")
            return None
    
    def _classify_provider_error(self, provider: str, error_msg: str, status_code: int = None) -> ErrorType:
        """Classify provider errors into actionable categories"""
        if not error_msg:
            return ErrorType.UNKNOWN_ERROR
            
        error_lower = error_msg.lower()
        
        # Common error patterns
        if "no results" in error_lower or "empty" in error_lower:
            return ErrorType.EMPTY_RESULTS
        elif "connections are hidden" in error_lower or "privacy" in error_lower:
            return ErrorType.PRIVACY_BLOCKED
        elif "session" in error_lower or "cookie" in error_lower or "unauthorized" in error_lower:
            return ErrorType.SESSION_INVALID
        elif "captcha" in error_lower or "challenge" in error_lower:
            return ErrorType.CAPTCHA_REQUIRED
        elif "rate limit" in error_lower or "429" in str(status_code):
            return ErrorType.RATE_LIMITED
        elif "network" in error_lower or "timeout" in error_lower or "connection" in error_lower:
            return ErrorType.NETWORK_ERROR
        elif "cannot_construct_fallback_url" in error_lower:
            return ErrorType.CANNOT_CONSTRUCT_FALLBACK
        else:
            return ErrorType.PROVIDER_ERROR
    
    def _get_user_message(self, error_type: ErrorType, provider: str) -> Dict[str, str]:
        """Get user-friendly error messages and suggested actions"""
        messages = {
            ErrorType.EMPTY_RESULTS: {
                "message": "No mutual connections found for this prospect",
                "suggestion": "Try connecting with the prospect directly, or ask shared contacts for an introduction",
                "action": "search_other_prospects"
            },
            ErrorType.PRIVACY_BLOCKED: {
                "message": "This person's connections are hidden due to privacy settings",
                "suggestion": "Some results may still be available. Try LinkedIn or connect directly",
            },
            ErrorType.SESSION_INVALID: {
                "message": "LinkedIn session expired - please refresh authentication",
                "suggestion": "Contact admin to update LinkedIn cookies",
                "action": "refresh_auth"
            },
            ErrorType.CAPTCHA_REQUIRED: {
                "message": "LinkedIn requires manual verification",
                "suggestion": "Please complete CAPTCHA on LinkedIn and try again in a few minutes",
                "action": "complete_captcha"
            },
            ErrorType.RATE_LIMITED: {
                "message": "Rate limit reached - please wait before trying again",
                "suggestion": f"Wait 1-3 hours before searching again with {provider}",
                "action": "wait_and_retry"
            },
            ErrorType.CANNOT_CONSTRUCT_FALLBACK: {
                "message": "Need 'Connections of' URL to search this prospect",
                "suggestion": "Please provide the LinkedIn connections-of URL for this person",
                "action": "provide_connections_url"
            },
            ErrorType.NETWORK_ERROR: {
                "message": "Network connection issue",
                "suggestion": "Check internet connection and try again",
                "action": "retry"
            },
            ErrorType.PROVIDER_ERROR: {
                "message": f"{provider.title()} service temporarily unavailable",
                "suggestion": "Try again in a few minutes, or use alternative provider",
                "action": "try_alternative"
            },
            ErrorType.UNKNOWN_ERROR: {
                "message": "An unexpected error occurred",
                "suggestion": "Please try again or contact support",
                "action": "contact_support"
            }
        }
        
        return messages.get(error_type, messages[ErrorType.UNKNOWN_ERROR])

    def _check_cached_result(self, idempotency_key: str) -> Optional[Dict]:
        """Check if we have a valid cached result for this request"""
        try:
            with get_db() as conn:
                cursor = conn.execute("""
                    SELECT jr.*, p.full_name, p.company 
                    FROM job_runs jr
                    LEFT JOIN prospects p ON p.id = jr.prospect_id
                    WHERE jr.idempotency_key = ? 
                    AND jr.status = 'completed'
                    AND (jr.cache_expires_at IS NULL OR jr.cache_expires_at > NOW())
                    ORDER BY jr.completed_at DESC
                    LIMIT 1
                """, (idempotency_key,))
                
                row = cursor.fetchone()
                if not row:
                    return None
                
                # Get introducers for this prospect
                introducers = mutuals_service.intersect_and_rank_introducers(row["prospect_id"], limit=5)
                
                # Add intro drafts
                for introducer in introducers:
                    introducer["intro_draft"] = mutuals_service.generate_intro_draft(
                        introducer_name=introducer["full_name"],
                        prospect_name=row["full_name"] or "this contact",
                        prospect_company=row["company"]
                    )
                
                return {
                    "status": "success",
                    "prospect_id": row["prospect_id"],
                    "introducers": introducers,
                    "total_mutuals_found": row["result_count"],
                    "primary_provider": json.loads(row["input_data"] or "{}").get("primary_provider", "cached"),
                    "providers_used": ["cached"],
                    "apify_run_id": row["external_id"] if row["provider"] == "apify" else None,
                    "diagnostics": {
                        "approach": "cached",
                        "cache_hit": True,
                        "cached_at": row["completed_at"],
                        "introducers_count": len(introducers)
                    }
                }
        except Exception as e:
            logger.error(f"Failed to check cached result: {e}")
            return None
    
    def _is_provider_on_cooldown(self, provider: str) -> Tuple[bool, Optional[str]]:
        """Check if provider is on cooldown due to errors"""
        try:
            with get_db() as conn:
                cursor = conn.execute("""
                    SELECT error_type, cooldown_until 
                    FROM provider_cooldowns 
                    WHERE provider = ? 
                    AND cooldown_until > NOW()
                """, (provider,))
                
                row = cursor.fetchone()
                if row:
                    return True, row["error_type"]
                else:
                    return False, None
        except Exception as e:
            logger.error(f"Failed to check cooldown: {e}")
            return False, None
    
    def _set_provider_cooldown(self, provider: str, error_type: ErrorType, hours: int = 1):
        """Set cooldown for provider due to errors"""
        try:
            cooldown_until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=hours)
            with get_db() as conn:
                if using_native_adapter():
                    conn.execute(
                        "DELETE FROM provider_cooldowns WHERE provider = %s",
                        (provider,),
                    )
                    conn.execute(
                        """
                        INSERT INTO provider_cooldowns 
                        (provider, error_type, cooldown_until)
                        VALUES (%s, %s, %s)
                        """,
                        (provider, error_type.value, cooldown_until.isoformat()),
                    )
                else:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO provider_cooldowns 
                        (provider, error_type, cooldown_until)
                        VALUES (?, ?, ?)
                        """,
                        (provider, error_type.value, cooldown_until.isoformat()),
                    )
                
            logger.info(f"Set {provider} cooldown for {error_type.value} until {cooldown_until}")
        except Exception as e:
            logger.error(f"Failed to set cooldown: {e}")
    
    def _cache_result(self, idempotency_key: str, prospect_id: int, result: Dict, ttl_days: int = 7):
        """Cache successful result with TTL"""
        try:
            cache_expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=ttl_days)
            with get_db() as conn:
                # Find the most recent completed job for this prospect
                cursor = conn.execute("""
                    SELECT id FROM job_runs 
                    WHERE prospect_id = ? AND status = 'completed'
                    ORDER BY completed_at DESC
                    LIMIT 1
                """, (prospect_id,))
                row = cursor.fetchone()
                
                if row:
                    # Update the specific job
                    # GPT5's fix: Handle datetime serialization in JSON
                    def json_default(obj):
                        if isinstance(obj, (datetime.datetime, datetime.date)):
                            return obj.isoformat()
                        return str(obj)
                    
                    conn.execute("""
                        UPDATE job_runs 
                        SET idempotency_key = ?, cache_expires_at = ?, input_data = ?
                        WHERE id = ?
                    """, (
                        idempotency_key,
                        cache_expires_at.isoformat(),
                        json.dumps(result, default=json_default),
                        row["id"]
                    ))
        except Exception as e:
            logger.error(f"Failed to cache result: {e}")
    
    def _record_job_start(self, tenant_id: int, prospect_id: int, job_type: str) -> int:
        """Record job start in database"""
        try:
            with get_db() as conn:
                # Detect database type for proper parameter syntax
                param_placeholder = '%s' if using_native_adapter() else '?'
                
                cursor = conn.execute(f"""
                    INSERT INTO job_runs (tenant_id, provider, job_type, external_id, prospect_id, status, started_at)
                    VALUES ({param_placeholder}, {param_placeholder}, {param_placeholder}, {param_placeholder}, {param_placeholder}, {param_placeholder}, {param_placeholder})
                """, (tenant_id, "orchestrator", job_type, f"job_{int(time.time())}", prospect_id, "running", 
                      time.strftime('%Y-%m-%d %H:%M:%S')))
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Failed to record job start: {e}")
            return 0
    
    def _record_job_completion(self, job_id: int, result_count: int, primary_provider: str):
        """Record job completion in database"""
        try:
            if job_id == 0:
                return
                
            with get_db() as conn:
                conn.execute("""
                    UPDATE job_runs 
                    SET status = ?, result_count = ?, completed_at = ?, 
                        input_data = ?
                    WHERE id = ?
                """, ("completed", result_count, time.strftime('%Y-%m-%d %H:%M:%S'),
                      f'{{"primary_provider": "{primary_provider}"}}', job_id))
        except Exception as e:
            logger.error(f"Failed to record job completion: {e}")

# Global orchestrator instance
orchestrator = MutualsOrchestrator()
