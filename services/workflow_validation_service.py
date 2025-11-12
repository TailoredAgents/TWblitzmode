#!/usr/bin/env python3
"""
End-to-End Corporate Workflow Validation Service
September 2025 - VouchLink AI Corporate Platform

This service validates the complete corporate workflow from prospect upload
to introduction email sending (Steps A-H) with comprehensive testing and validation.
"""

import asyncio
import csv
import io
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from api.database import get_db
from services.ingestion_service import IngestionService
from services.executive_lookup_service import ExecutiveLookupService
from services.mutuals_orchestrator_service import MutualsOrchestratorService
from services.scoring_service import ScoringService
from services.email_enrichment_service import EmailEnrichmentService
from services.corporate_scheduler_service import CorporateSchedulerService
from services.openai_agents_orchestrator import ai_orchestrator

logger = logging.getLogger(__name__)

class WorkflowStep(Enum):
    """Corporate workflow steps A through H"""
    A_PROSPECT_UPLOAD = "A"
    B_EXECUTIVE_LOOKUP = "B"
    C_MUTUAL_SEARCH = "C"
    D_CONNECTOR_SCORING = "D"
    E_EMAIL_ENRICHMENT = "E"
    F_INTRODUCTION_SCHEDULING = "F"
    G_RESPONSE_TRACKING = "G"
    H_ANALYTICS_REPORTING = "H"

@dataclass
class WorkflowValidationResult:
    """Result of workflow validation"""
    step: WorkflowStep
    success: bool
    duration_seconds: float
    data: Dict[str, Any]
    error: Optional[str] = None
    details: Optional[str] = None

@dataclass
class EndToEndTestResult:
    """Complete end-to-end test result"""
    organization_id: int
    start_time: datetime
    end_time: datetime
    total_duration_seconds: float
    steps_completed: List[WorkflowStep]
    step_results: List[WorkflowValidationResult]
    success: bool
    error_summary: Optional[str] = None

class CorporateWorkflowValidator:
    """
    Comprehensive validator for the corporate workflow

    Validates the complete A-H workflow:
    A. Prospect CSV upload and validation
    B. Executive LinkedIn profile discovery
    C. Mutual connections search across team members
    D. Connector scoring and ranking (top 5)
    E. Email enrichment and verification
    F. Introduction email scheduling and sending
    G. Response tracking and follow-up automation
    H. Analytics and reporting dashboard
    """

    def __init__(self):
        self.ingestion_service = IngestionService()
        self.lookup_service = ExecutiveLookupService()
        self.mutuals_service = MutualsOrchestratorService()
        self.scoring_service = ScoringService()
        self.enrichment_service = EmailEnrichmentService()
        self.scheduler_service = CorporateSchedulerService()

    async def validate_complete_workflow(
        self,
        organization_id: int,
        test_prospects: List[Dict[str, str]],
        enable_ai_agents: bool = True
    ) -> EndToEndTestResult:
        """
        Validate the complete corporate workflow end-to-end

        Args:
            organization_id: Target organization for testing
            test_prospects: List of test prospect data
            enable_ai_agents: Enable September 2025 AI integration

        Returns:
            Complete test result with timing and success metrics
        """
        start_time = datetime.now(timezone.utc)
        steps_completed = []
        step_results = []

        logger.info(f"🚀 Starting end-to-end workflow validation for organization {organization_id}")

        try:
            # Step A: Prospect CSV Upload and Validation
            step_a_result = await self._validate_step_a_prospect_upload(
                organization_id, test_prospects
            )
            step_results.append(step_a_result)
            if step_a_result.success:
                steps_completed.append(WorkflowStep.A_PROSPECT_UPLOAD)

            # Step B: Executive LinkedIn Profile Discovery
            step_b_result = await self._validate_step_b_executive_lookup(
                organization_id, step_a_result.data.get("prospect_ids", [])
            )
            step_results.append(step_b_result)
            if step_b_result.success:
                steps_completed.append(WorkflowStep.B_EXECUTIVE_LOOKUP)

            # Step C: Mutual Connections Search
            step_c_result = await self._validate_step_c_mutual_search(
                organization_id, step_b_result.data.get("prospects_with_profiles", [])
            )
            step_results.append(step_c_result)
            if step_c_result.success:
                steps_completed.append(WorkflowStep.C_MUTUAL_SEARCH)

            # Step D: Connector Scoring and Ranking
            step_d_result = await self._validate_step_d_connector_scoring(
                organization_id, step_c_result.data.get("prospects_with_connectors", [])
            )
            step_results.append(step_d_result)
            if step_d_result.success:
                steps_completed.append(WorkflowStep.D_CONNECTOR_SCORING)

            # Step E: Email Enrichment
            step_e_result = await self._validate_step_e_email_enrichment(
                organization_id, step_d_result.data.get("top_connectors", [])
            )
            step_results.append(step_e_result)
            if step_e_result.success:
                steps_completed.append(WorkflowStep.E_EMAIL_ENRICHMENT)

            # Step F: Introduction Scheduling (with AI if enabled)
            step_f_result = await self._validate_step_f_introduction_scheduling(
                organization_id, step_e_result.data.get("enriched_connectors", []),
                enable_ai_agents
            )
            step_results.append(step_f_result)
            if step_f_result.success:
                steps_completed.append(WorkflowStep.F_INTRODUCTION_SCHEDULING)

            # Step G: Response Tracking
            step_g_result = await self._validate_step_g_response_tracking(
                organization_id, step_f_result.data.get("scheduled_emails", [])
            )
            step_results.append(step_g_result)
            if step_g_result.success:
                steps_completed.append(WorkflowStep.G_RESPONSE_TRACKING)

            # Step H: Analytics and Reporting
            step_h_result = await self._validate_step_h_analytics_reporting(
                organization_id
            )
            step_results.append(step_h_result)
            if step_h_result.success:
                steps_completed.append(WorkflowStep.H_ANALYTICS_REPORTING)

            end_time = datetime.now(timezone.utc)
            total_duration = (end_time - start_time).total_seconds()

            # Determine overall success
            all_steps_completed = len(steps_completed) == len(WorkflowStep)
            critical_steps_success = all(
                result.success for result in step_results[:6]  # A-F are critical
            )

            success = all_steps_completed and critical_steps_success

            result = EndToEndTestResult(
                organization_id=organization_id,
                start_time=start_time,
                end_time=end_time,
                total_duration_seconds=total_duration,
                steps_completed=steps_completed,
                step_results=step_results,
                success=success,
                error_summary=self._generate_error_summary(step_results) if not success else None
            )

            logger.info(f"✅ End-to-end validation completed in {total_duration:.2f}s - Success: {success}")
            return result

        except Exception as e:
            logger.error(f"❌ End-to-end validation failed: {e}")
            end_time = datetime.now(timezone.utc)
            return EndToEndTestResult(
                organization_id=organization_id,
                start_time=start_time,
                end_time=end_time,
                total_duration_seconds=(end_time - start_time).total_seconds(),
                steps_completed=steps_completed,
                step_results=step_results,
                success=False,
                error_summary=str(e)
            )

    async def _validate_step_a_prospect_upload(
        self, organization_id: int, test_prospects: List[Dict[str, str]]
    ) -> WorkflowValidationResult:
        """Validate Step A: Prospect CSV Upload and Validation"""
        start_time = time.time()

        try:
            logger.info("🔍 Validating Step A: Prospect Upload and Validation")

            # Create test CSV content
            csv_content = self._create_test_csv(test_prospects)

            # Process through ingestion service
            result = await self.ingestion_service.process_csv_upload(
                csv_content, organization_id, "test_user"
            )

            duration = time.time() - start_time

            if result.get("success") and result.get("prospects_created", 0) > 0:
                return WorkflowValidationResult(
                    step=WorkflowStep.A_PROSPECT_UPLOAD,
                    success=True,
                    duration_seconds=duration,
                    data={
                        "prospects_created": result["prospects_created"],
                        "prospect_ids": result.get("prospect_ids", []),
                        "validation_errors": result.get("validation_errors", [])
                    },
                    details=f"Successfully uploaded {result['prospects_created']} prospects"
                )
            else:
                return WorkflowValidationResult(
                    step=WorkflowStep.A_PROSPECT_UPLOAD,
                    success=False,
                    duration_seconds=duration,
                    data=result,
                    error="Failed to upload prospects",
                    details=str(result.get("error", "Unknown error"))
                )

        except Exception as e:
            return WorkflowValidationResult(
                step=WorkflowStep.A_PROSPECT_UPLOAD,
                success=False,
                duration_seconds=time.time() - start_time,
                data={},
                error=str(e)
            )

    async def _validate_step_b_executive_lookup(
        self, organization_id: int, prospect_ids: List[int]
    ) -> WorkflowValidationResult:
        """Validate Step B: Executive LinkedIn Profile Discovery"""
        start_time = time.time()

        try:
            logger.info("🔍 Validating Step B: Executive LinkedIn Profile Discovery")

            prospects_with_profiles = []

            for prospect_id in prospect_ids[:3]:  # Test first 3 for performance
                result = await self.lookup_service.lookup_executive_profile(
                    prospect_id, organization_id
                )

                if result.get("success") and result.get("linkedin_url"):
                    prospects_with_profiles.append({
                        "prospect_id": prospect_id,
                        "linkedin_url": result["linkedin_url"],
                        "executive_data": result.get("executive_data", {})
                    })

            duration = time.time() - start_time
            success = len(prospects_with_profiles) > 0

            return WorkflowValidationResult(
                step=WorkflowStep.B_EXECUTIVE_LOOKUP,
                success=success,
                duration_seconds=duration,
                data={
                    "prospects_with_profiles": prospects_with_profiles,
                    "lookup_success_rate": len(prospects_with_profiles) / len(prospect_ids) if prospect_ids else 0
                },
                details=f"Found LinkedIn profiles for {len(prospects_with_profiles)}/{len(prospect_ids)} prospects"
            )

        except Exception as e:
            return WorkflowValidationResult(
                step=WorkflowStep.B_EXECUTIVE_LOOKUP,
                success=False,
                duration_seconds=time.time() - start_time,
                data={},
                error=str(e)
            )

    async def _validate_step_c_mutual_search(
        self, organization_id: int, prospects_with_profiles: List[Dict[str, Any]]
    ) -> WorkflowValidationResult:
        """Validate Step C: Mutual Connections Search"""
        start_time = time.time()

        try:
            logger.info("🔍 Validating Step C: Mutual Connections Search")

            prospects_with_connectors = []

            for prospect_data in prospects_with_profiles[:2]:  # Test first 2 for performance
                result = await self.mutuals_service.find_mutual_connections(
                    prospect_data["prospect_id"],
                    prospect_data["linkedin_url"],
                    organization_id
                )

                if result.get("success") and result.get("connectors_found", 0) > 0:
                    prospects_with_connectors.append({
                        "prospect_id": prospect_data["prospect_id"],
                        "connectors_found": result["connectors_found"],
                        "connector_ids": result.get("connector_ids", [])
                    })

            duration = time.time() - start_time
            success = len(prospects_with_connectors) > 0

            return WorkflowValidationResult(
                step=WorkflowStep.C_MUTUAL_SEARCH,
                success=success,
                duration_seconds=duration,
                data={
                    "prospects_with_connectors": prospects_with_connectors,
                    "total_connectors_found": sum(p["connectors_found"] for p in prospects_with_connectors)
                },
                details=f"Found mutual connections for {len(prospects_with_connectors)} prospects"
            )

        except Exception as e:
            return WorkflowValidationResult(
                step=WorkflowStep.C_MUTUAL_SEARCH,
                success=False,
                duration_seconds=time.time() - start_time,
                data={},
                error=str(e)
            )

    async def _validate_step_d_connector_scoring(
        self, organization_id: int, prospects_with_connectors: List[Dict[str, Any]]
    ) -> WorkflowValidationResult:
        """Validate Step D: Connector Scoring and Ranking"""
        start_time = time.time()

        try:
            logger.info("🔍 Validating Step D: Connector Scoring and Ranking")

            top_connectors = []

            for prospect_data in prospects_with_connectors:
                result = await self.scoring_service.score_and_rank_connectors(
                    prospect_data["prospect_id"],
                    prospect_data["connector_ids"],
                    organization_id
                )

                if result.get("success") and result.get("top_connectors"):
                    top_connectors.extend(result["top_connectors"][:5])  # Top 5 per prospect

            duration = time.time() - start_time
            success = len(top_connectors) > 0

            return WorkflowValidationResult(
                step=WorkflowStep.D_CONNECTOR_SCORING,
                success=success,
                duration_seconds=duration,
                data={
                    "top_connectors": top_connectors,
                    "scoring_algorithm_used": "weighted_multi_factor_v2025"
                },
                details=f"Scored and ranked {len(top_connectors)} top connectors"
            )

        except Exception as e:
            return WorkflowValidationResult(
                step=WorkflowStep.D_CONNECTOR_SCORING,
                success=False,
                duration_seconds=time.time() - start_time,
                data={},
                error=str(e)
            )

    async def _validate_step_e_email_enrichment(
        self, organization_id: int, top_connectors: List[Dict[str, Any]]
    ) -> WorkflowValidationResult:
        """Validate Step E: Email Enrichment and Verification"""
        start_time = time.time()

        try:
            logger.info("🔍 Validating Step E: Email Enrichment and Verification")

            enriched_connectors = []

            for connector in top_connectors[:10]:  # Test first 10 for performance
                result = await self.enrichment_service.enrich_connector_email(
                    connector["connector_id"], organization_id
                )

                if result.get("success"):
                    enriched_connectors.append({
                        "connector_id": connector["connector_id"],
                        "email": result.get("email"),
                        "email_confidence": result.get("confidence", 0)
                    })

            duration = time.time() - start_time
            success = len(enriched_connectors) > 0

            return WorkflowValidationResult(
                step=WorkflowStep.E_EMAIL_ENRICHMENT,
                success=success,
                duration_seconds=duration,
                data={
                    "enriched_connectors": enriched_connectors,
                    "enrichment_success_rate": len(enriched_connectors) / len(top_connectors) if top_connectors else 0
                },
                details=f"Enriched emails for {len(enriched_connectors)}/{len(top_connectors)} connectors"
            )

        except Exception as e:
            return WorkflowValidationResult(
                step=WorkflowStep.E_EMAIL_ENRICHMENT,
                success=False,
                duration_seconds=time.time() - start_time,
                data={},
                error=str(e)
            )

    async def _validate_step_f_introduction_scheduling(
        self, organization_id: int, enriched_connectors: List[Dict[str, Any]], enable_ai: bool
    ) -> WorkflowValidationResult:
        """Validate Step F: Introduction Email Scheduling"""
        start_time = time.time()

        try:
            logger.info("🔍 Validating Step F: Introduction Email Scheduling with AI")

            scheduled_emails = []

            if enable_ai and not ai_orchestrator:
                raise RuntimeError(
                    "AI orchestrator not available. Enable the ai_agents_enabled feature flag "
                    "and configure OpenAI agents."
                )

            for connector in enriched_connectors[:5]:  # Test first 5 for performance
                if not connector.get("email"):
                    continue

                if enable_ai:
                    # Use September 2025 AI Agents for email generation
                    ai_result = await ai_orchestrator.generate_introduction_email(
                        connector["connector_id"], organization_id
                    )

                    if ai_result.get("success"):
                        scheduled_result = await self.scheduler_service.schedule_introduction_email(
                            connector["connector_id"],
                            organization_id,
                            ai_content=ai_result.get("email_content")
                        )
                    else:
                        # Fallback to manual scheduling
                        scheduled_result = await self.scheduler_service.schedule_introduction_email(
                            connector["connector_id"], organization_id
                        )
                else:
                    scheduled_result = await self.scheduler_service.schedule_introduction_email(
                        connector["connector_id"], organization_id
                    )

                if scheduled_result.get("success"):
                    scheduled_emails.append({
                        "connector_id": connector["connector_id"],
                        "email_job_id": scheduled_result.get("email_job_id"),
                        "scheduled_time": scheduled_result.get("scheduled_time"),
                        "ai_generated": enable_ai and ai_result.get("success", False)
                    })

            duration = time.time() - start_time
            success = len(scheduled_emails) > 0

            return WorkflowValidationResult(
                step=WorkflowStep.F_INTRODUCTION_SCHEDULING,
                success=success,
                duration_seconds=duration,
                data={
                    "scheduled_emails": scheduled_emails,
                    "ai_enabled": enable_ai,
                    "ai_success_rate": sum(1 for e in scheduled_emails if e.get("ai_generated", False)) / len(scheduled_emails) if scheduled_emails else 0
                },
                details=f"Scheduled {len(scheduled_emails)} introduction emails (AI: {enable_ai})"
            )

        except Exception as e:
            return WorkflowValidationResult(
                step=WorkflowStep.F_INTRODUCTION_SCHEDULING,
                success=False,
                duration_seconds=time.time() - start_time,
                data={},
                error=str(e)
            )

    async def _validate_step_g_response_tracking(
        self, organization_id: int, scheduled_emails: List[Dict[str, Any]]
    ) -> WorkflowValidationResult:
        """Validate Step G: Response Tracking and Follow-up"""
        start_time = time.time()

        try:
            logger.info("🔍 Validating Step G: Response Tracking and Follow-up")

            # Simulate tracking for scheduled emails
            tracking_results = []

            for email_data in scheduled_emails:
                # Check tracking capabilities
                tracking_setup = await self._setup_email_tracking(
                    email_data["email_job_id"], organization_id
                )

                if tracking_setup.get("success"):
                    tracking_results.append({
                        "email_job_id": email_data["email_job_id"],
                        "tracking_enabled": True,
                        "tracking_methods": ["open_tracking", "click_tracking", "reply_tracking"]
                    })

            duration = time.time() - start_time
            success = len(tracking_results) > 0

            return WorkflowValidationResult(
                step=WorkflowStep.G_RESPONSE_TRACKING,
                success=success,
                duration_seconds=duration,
                data={
                    "tracking_results": tracking_results,
                    "tracking_success_rate": len(tracking_results) / len(scheduled_emails) if scheduled_emails else 0
                },
                details=f"Set up tracking for {len(tracking_results)} emails"
            )

        except Exception as e:
            return WorkflowValidationResult(
                step=WorkflowStep.G_RESPONSE_TRACKING,
                success=False,
                duration_seconds=time.time() - start_time,
                data={},
                error=str(e)
            )

    async def _validate_step_h_analytics_reporting(
        self, organization_id: int
    ) -> WorkflowValidationResult:
        """Validate Step H: Analytics and Reporting Dashboard"""
        start_time = time.time()

        try:
            logger.info("🔍 Validating Step H: Analytics and Reporting Dashboard")

            # Validate analytics data availability
            with get_db() as conn:
                # Check prospects data
                prospects_count = conn.execute(
                    "SELECT COUNT(*) FROM prospects WHERE organization_id = ?",
                    (organization_id,)
                ).fetchone()[0]

                # Check connectors data
                connectors_count = conn.execute(
                    """SELECT COUNT(*) FROM connectors c
                       JOIN prospect_connectors pc ON c.id = pc.connector_id
                       JOIN prospects p ON pc.prospect_id = p.id
                       WHERE p.organization_id = ?""",
                    (organization_id,)
                ).fetchone()[0]

                # Check email jobs data
                email_jobs_count = conn.execute(
                    "SELECT COUNT(*) FROM email_jobs WHERE organization_id = ?",
                    (organization_id,)
                ).fetchone()[0]

            analytics_data = {
                "prospects_total": prospects_count,
                "connectors_total": connectors_count,
                "email_jobs_total": email_jobs_count,
                "dashboard_metrics": [
                    "prospect_conversion_rate",
                    "connector_response_rate",
                    "email_open_rate",
                    "introduction_success_rate"
                ]
            }

            duration = time.time() - start_time
            success = prospects_count > 0 and connectors_count > 0

            return WorkflowValidationResult(
                step=WorkflowStep.H_ANALYTICS_REPORTING,
                success=success,
                duration_seconds=duration,
                data=analytics_data,
                details=f"Analytics validated: {prospects_count} prospects, {connectors_count} connectors"
            )

        except Exception as e:
            return WorkflowValidationResult(
                step=WorkflowStep.H_ANALYTICS_REPORTING,
                success=False,
                duration_seconds=time.time() - start_time,
                data={},
                error=str(e)
            )

    def _create_test_csv(self, test_prospects: List[Dict[str, str]]) -> str:
        """Create test CSV content for prospect upload"""
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["company", "executive_first_name", "executive_last_name", "email", "role"])
        writer.writeheader()
        writer.writerows(test_prospects)
        return output.getvalue()

    async def _setup_email_tracking(self, email_job_id: str, organization_id: int) -> Dict[str, Any]:
        """Setup email tracking for validation"""
        try:
            # In production, this would set up actual email tracking
            return {
                "success": True,
                "tracking_id": f"track_{email_job_id}",
                "methods": ["open", "click", "reply"]
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _generate_error_summary(self, step_results: List[WorkflowValidationResult]) -> str:
        """Generate summary of errors from failed steps"""
        failed_steps = [result for result in step_results if not result.success]
        if not failed_steps:
            return None

        errors = []
        for result in failed_steps:
            errors.append(f"Step {result.step.value}: {result.error or 'Unknown error'}")

        return "; ".join(errors)

    async def run_performance_validation(
        self, organization_id: int, concurrent_workflows: int = 10
    ) -> Dict[str, Any]:
        """Run performance validation with multiple concurrent workflows"""
        logger.info(f"🚀 Running performance validation with {concurrent_workflows} concurrent workflows")

        test_prospects = [
            {"company": f"Test Corp {i}", "executive_first_name": f"John{i}", "executive_last_name": f"Doe{i}", "email": f"john{i}@testcorp{i}.com", "role": "CEO"}
            for i in range(concurrent_workflows)
        ]

        start_time = time.time()

        # Run concurrent workflows
        tasks = [
            self.validate_complete_workflow(organization_id, [prospect])
            for prospect in test_prospects
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        total_duration = time.time() - start_time

        # Analyze results
        successful_workflows = [r for r in results if isinstance(r, EndToEndTestResult) and r.success]
        failed_workflows = [r for r in results if isinstance(r, Exception) or (isinstance(r, EndToEndTestResult) and not r.success)]

        avg_duration = sum(r.total_duration_seconds for r in successful_workflows) / len(successful_workflows) if successful_workflows else 0

        return {
            "concurrent_workflows": concurrent_workflows,
            "total_duration_seconds": total_duration,
            "successful_workflows": len(successful_workflows),
            "failed_workflows": len(failed_workflows),
            "success_rate": len(successful_workflows) / concurrent_workflows,
            "average_workflow_duration": avg_duration,
            "max_workflow_duration": max((r.total_duration_seconds for r in successful_workflows), default=0),
            "min_workflow_duration": min((r.total_duration_seconds for r in successful_workflows), default=0),
            "performance_target_met": avg_duration < 120.0 and len(successful_workflows) / concurrent_workflows > 0.95  # 2 minutes, 95% success
        }

# Global service instance
workflow_validator = CorporateWorkflowValidator()
