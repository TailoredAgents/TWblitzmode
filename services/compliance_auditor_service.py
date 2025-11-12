"""
Compliance Auditor Service - Regulatory and Ethics Compliance
Provides comprehensive compliance checking for corporate outreach activities

Features:
- GDPR, CAN-SPAM, and international privacy law compliance
- Industry-specific regulation adherence (financial services, healthcare, etc.)
- Corporate ethics and professional conduct standards
- Data handling and privacy protection protocols
- Audit trail maintenance and compliance documentation
- Do-Not-Contact list verification
- Email suppression list integration
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

from api.database import get_db_connection

logger = logging.getLogger(__name__)

class ComplianceStatus(Enum):
    """Compliance check status levels"""
    APPROVED = "approved"
    WARNING = "warning"
    REJECTED = "rejected"
    REQUIRES_REVIEW = "requires_review"

class ComplianceRisk(Enum):
    """Risk levels for compliance violations"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class RegulationType(Enum):
    """Types of regulations to check"""
    GDPR = "gdpr"
    CAN_SPAM = "can_spam"
    CCPA = "ccpa"
    FINANCIAL_SERVICES = "financial_services"
    HEALTHCARE = "healthcare"
    CORPORATE_ETHICS = "corporate_ethics"
    INDUSTRY_SPECIFIC = "industry_specific"

@dataclass
class ComplianceViolation:
    """Individual compliance violation details"""
    regulation: RegulationType
    severity: ComplianceRisk
    description: str
    recommendation: str
    reference: Optional[str] = None

@dataclass
class ComplianceAuditResult:
    """Result of compliance audit"""
    status: ComplianceStatus
    overall_risk: ComplianceRisk
    violations: List[ComplianceViolation]
    recommendations: List[str]
    audit_notes: str
    requires_human_approval: bool
    valid_until: Optional[datetime] = None

class ComplianceAuditorService:
    """
    Compliance Auditor Service for VouchLink outreach activities

    Ensures all outreach activities comply with relevant regulations,
    industry standards, and corporate ethics requirements.
    """

    def __init__(self):
        # Industry-specific compliance rules
        self.industry_rules = {
            "financial_services": {
                "requires_disclosure": True,
                "restricted_claims": ["guaranteed returns", "risk-free", "insider information"],
                "mandatory_disclaimers": True,
                "record_retention_years": 7
            },
            "healthcare": {
                "hipaa_compliance": True,
                "restricted_claims": ["medical advice", "treatment recommendation", "cure"],
                "requires_professional_qualification": True,
                "patient_data_restrictions": True
            },
            "technology": {
                "data_privacy_focus": True,
                "security_disclosure": True,
                "restricted_claims": ["guaranteed security", "unbreakable encryption"]
            }
        }

        # GDPR compliance rules
        self.gdpr_rules = {
            "eu_jurisdictions": [
                "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
                "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
                "SI", "ES", "SE", "IS", "LI", "NO"
            ],
            "requires_consent": True,
            "data_retention_limits": True,
            "right_to_erasure": True,
            "data_portability": True
        }

        # CAN-SPAM compliance rules
        self.can_spam_rules = {
            "clear_sender_identity": True,
            "truthful_subject_lines": True,
            "clear_commercial_nature": True,
            "unsubscribe_mechanism": True,
            "physical_address_required": True,
            "honor_unsubscribe_within_days": 10
        }

        logger.info("ComplianceAuditorService initialized with comprehensive regulatory framework")

    async def audit_outreach_campaign(
        self,
        campaign_data: Dict[str, Any],
        organization_id: int,
        user_id: int
    ) -> ComplianceAuditResult:
        """
        Perform comprehensive compliance audit of outreach campaign

        Args:
            campaign_data: Campaign details including emails, targets, content
            organization_id: Organization identifier for tenant isolation
            user_id: User initiating the campaign

        Returns:
            ComplianceAuditResult with status and recommendations
        """
        logger.info(f"Starting compliance audit for campaign (org: {organization_id}, user: {user_id})")

        try:
            violations = []
            recommendations = []

            # Extract campaign components
            email_content = campaign_data.get("email_content", "")
            target_list = campaign_data.get("targets", [])
            sender_info = campaign_data.get("sender", {})
            campaign_type = campaign_data.get("type", "introduction")

            # Check Do-Not-Contact list
            dnc_violations = await self._check_do_not_contact_list(target_list, organization_id)
            violations.extend(dnc_violations)

            # Check email suppression list
            suppression_violations = await self._check_email_suppression_list(target_list, organization_id)
            violations.extend(suppression_violations)

            # GDPR compliance check
            gdpr_violations = self._check_gdpr_compliance(campaign_data, target_list)
            violations.extend(gdpr_violations)

            # CAN-SPAM compliance check
            can_spam_violations = self._check_can_spam_compliance(campaign_data, email_content, sender_info)
            violations.extend(can_spam_violations)

            # Industry-specific compliance
            industry_violations = self._check_industry_compliance(campaign_data, email_content)
            violations.extend(industry_violations)

            # Corporate ethics check
            ethics_violations = self._check_corporate_ethics(campaign_data, email_content)
            violations.extend(ethics_violations)

            # Content compliance check
            content_violations = self._check_content_compliance(email_content)
            violations.extend(content_violations)

            # Determine overall status and risk
            overall_risk = self._calculate_overall_risk(violations)
            status = self._determine_compliance_status(violations, overall_risk)

            # Generate recommendations
            recommendations = self._generate_compliance_recommendations(violations, campaign_data)

            # Determine if human approval is required
            requires_approval = self._requires_human_approval(violations, overall_risk, campaign_data)

            # Set validity period
            valid_until = datetime.now(timezone.utc) + timedelta(days=30) if status == ComplianceStatus.APPROVED else None

            audit_notes = self._generate_audit_notes(violations, recommendations, campaign_data)

            result = ComplianceAuditResult(
                status=status,
                overall_risk=overall_risk,
                violations=violations,
                recommendations=recommendations,
                audit_notes=audit_notes,
                requires_human_approval=requires_approval,
                valid_until=valid_until
            )

            # Log audit completion
            logger.info(f"Compliance audit completed: {status.value} (risk: {overall_risk.value}, violations: {len(violations)})")

            return result

        except Exception as e:
            logger.error(f"Compliance audit failed: {e}")

            # Return restrictive result on audit failure
            return ComplianceAuditResult(
                status=ComplianceStatus.REJECTED,
                overall_risk=ComplianceRisk.HIGH,
                violations=[ComplianceViolation(
                    regulation=RegulationType.CORPORATE_ETHICS,
                    severity=ComplianceRisk.HIGH,
                    description=f"Compliance audit system failure: {str(e)}",
                    recommendation="Manual compliance review required before proceeding"
                )],
                recommendations=["Obtain manual compliance approval", "Review system configuration"],
                audit_notes=f"Automated compliance audit failed. Manual review required. Error: {str(e)}",
                requires_human_approval=True,
                valid_until=None
            )

    async def _check_do_not_contact_list(self, targets: List[Dict], organization_id: int) -> List[ComplianceViolation]:
        """Check targets against Do-Not-Contact list"""
        violations = []

        try:
            # Get DNC list from database

            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT email, reason, added_date
                    FROM do_not_contact_list
                    WHERE tenant_id = ? AND active = 1
                    """,
                    (organization_id,),
                )
                dnc_records = cursor.fetchall()
            dnc_emails = {record[0].lower() for record in dnc_records}

            # Check each target
            for target in targets:
                target_email = target.get("email", "").lower()
                if target_email in dnc_emails:
                    violations.append(ComplianceViolation(
                        regulation=RegulationType.CORPORATE_ETHICS,
                        severity=ComplianceRisk.HIGH,
                        description=f"Target {target_email} is on Do-Not-Contact list",
                        recommendation="Remove target from campaign or obtain explicit consent"
                    ))

        except Exception as e:
            logger.warning(f"DNC check failed: {e}")
            violations.append(ComplianceViolation(
                regulation=RegulationType.CORPORATE_ETHICS,
                severity=ComplianceRisk.MEDIUM,
                description="Unable to verify Do-Not-Contact status",
                recommendation="Manual DNC verification required"
            ))

        return violations

    async def _check_email_suppression_list(self, targets: List[Dict], organization_id: int) -> List[ComplianceViolation]:
        """Check targets against email suppression list"""
        violations = []

        try:
            # Check existing email suppression list

            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT email, reason, type
                    FROM email_suppression_list
                    WHERE tenant_id = ?
                      AND (expires_at IS NULL OR expires_at > datetime('now'))
                    """,
                    (organization_id,),
                )
                suppressed_records = cursor.fetchall()
            suppressed_emails = {record[0].lower(): (record[1], record[2]) for record in suppressed_records}

            # Check each target
            for target in targets:
                target_email = target.get("email", "").lower()
                if target_email in suppressed_emails:
                    reason, suppression_type = suppressed_emails[target_email]
                    violations.append(ComplianceViolation(
                        regulation=RegulationType.CAN_SPAM,
                        severity=ComplianceRisk.HIGH if suppression_type == "permanent" else ComplianceRisk.MEDIUM,
                        description=f"Target {target_email} is on email suppression list (reason: {reason})",
                        recommendation="Remove target from campaign - email suppression must be honored"
                    ))

        except Exception as e:
            logger.warning(f"Email suppression check failed: {e}")

        return violations

    def _check_gdpr_compliance(self, campaign_data: Dict, targets: List[Dict]) -> List[ComplianceViolation]:
        """Check GDPR compliance for EU targets"""
        violations = []

        # Check for EU targets
        eu_targets = []
        for target in targets:
            # Check country codes, domains, or explicit EU indicators
            country = target.get("country", "").upper()
            email_domain = target.get("email", "").split("@")[-1] if target.get("email") else ""

            if (country in self.gdpr_rules["eu_jurisdictions"] or
                any(eu_tld in email_domain for eu_tld in [".de", ".fr", ".it", ".es", ".nl", ".be"])):
                eu_targets.append(target)

        if eu_targets:
            # Check GDPR requirements
            consent_mechanism = campaign_data.get("consent_mechanism")
            if not consent_mechanism:
                violations.append(ComplianceViolation(
                    regulation=RegulationType.GDPR,
                    severity=ComplianceRisk.HIGH,
                    description=f"GDPR consent mechanism not specified for {len(eu_targets)} EU targets",
                    recommendation="Implement explicit consent mechanism for EU prospects",
                    reference="GDPR Article 6 - Lawfulness of processing"
                ))

            # Check for data retention policy
            data_retention_policy = campaign_data.get("data_retention_policy")
            if not data_retention_policy:
                violations.append(ComplianceViolation(
                    regulation=RegulationType.GDPR,
                    severity=ComplianceRisk.MEDIUM,
                    description="Data retention policy not specified",
                    recommendation="Define clear data retention and deletion policies",
                    reference="GDPR Article 5 - Principles of processing"
                ))

        return violations

    def _check_can_spam_compliance(self, campaign_data: Dict, email_content: str, sender_info: Dict) -> List[ComplianceViolation]:
        """Check CAN-SPAM Act compliance"""
        violations = []

        # Check sender identification
        if not sender_info.get("name") or not sender_info.get("email"):
            violations.append(ComplianceViolation(
                regulation=RegulationType.CAN_SPAM,
                severity=ComplianceRisk.HIGH,
                description="Clear sender identification required",
                recommendation="Include clear sender name and valid email address",
                reference="CAN-SPAM Act Section 5(a)(1)"
            ))

        # Check for physical address
        physical_address = sender_info.get("physical_address") or campaign_data.get("physical_address")
        if not physical_address:
            violations.append(ComplianceViolation(
                regulation=RegulationType.CAN_SPAM,
                severity=ComplianceRisk.HIGH,
                description="Physical postal address required in commercial emails",
                recommendation="Include valid physical postal address in email signature",
                reference="CAN-SPAM Act Section 5(a)(3)"
            ))

        # Check for unsubscribe mechanism
        if "unsubscribe" not in email_content.lower():
            violations.append(ComplianceViolation(
                regulation=RegulationType.CAN_SPAM,
                severity=ComplianceRisk.HIGH,
                description="Unsubscribe mechanism not found in email content",
                recommendation="Include clear and conspicuous unsubscribe instructions",
                reference="CAN-SPAM Act Section 5(a)(4)"
            ))

        # Check subject line authenticity
        subject_line = campaign_data.get("subject_line", "")
        if any(spam_word in subject_line.lower() for spam_word in ["free", "urgent", "act now", "limited time"]):
            violations.append(ComplianceViolation(
                regulation=RegulationType.CAN_SPAM,
                severity=ComplianceRisk.MEDIUM,
                description="Subject line may be misleading or spam-like",
                recommendation="Use clear, non-deceptive subject lines",
                reference="CAN-SPAM Act Section 5(a)(2)"
            ))

        return violations

    def _check_industry_compliance(self, campaign_data: Dict, email_content: str) -> List[ComplianceViolation]:
        """Check industry-specific compliance requirements"""
        violations = []

        industry = campaign_data.get("industry", "").lower()
        industry_rules = self.industry_rules.get(industry, {})

        if industry_rules:
            # Check restricted claims
            restricted_claims = industry_rules.get("restricted_claims", [])
            for claim in restricted_claims:
                if claim.lower() in email_content.lower():
                    violations.append(ComplianceViolation(
                        regulation=RegulationType.INDUSTRY_SPECIFIC,
                        severity=ComplianceRisk.HIGH,
                        description=f"Restricted claim '{claim}' found in email content",
                        recommendation=f"Remove or modify restricted claim for {industry} industry"
                    ))

            # Check for required disclaimers
            if industry_rules.get("requires_disclosure") and "disclosure" not in email_content.lower():
                violations.append(ComplianceViolation(
                    regulation=RegulationType.INDUSTRY_SPECIFIC,
                    severity=ComplianceRisk.MEDIUM,
                    description=f"Required disclosure missing for {industry} industry",
                    recommendation=f"Include appropriate disclaimer for {industry} communications"
                ))

        return violations

    def _check_corporate_ethics(self, campaign_data: Dict, email_content: str) -> List[ComplianceViolation]:
        """Check corporate ethics and professional conduct"""
        violations = []

        # Check for misleading claims
        misleading_patterns = [
            r"guaranteed\s+results?",
            r"exclusive\s+offer",
            r"limited\s+time\s+only",
            r"act\s+now\s+or",
            r"risk[\s-]?free"
        ]

        for pattern in misleading_patterns:
            if re.search(pattern, email_content, re.IGNORECASE):
                violations.append(ComplianceViolation(
                    regulation=RegulationType.CORPORATE_ETHICS,
                    severity=ComplianceRisk.MEDIUM,
                    description=f"Potentially misleading claim detected: {pattern}",
                    recommendation="Review and modify potentially misleading language"
                ))

        # Check for professional tone
        unprofessional_words = ["awesome", "amazing", "incredible", "unbelievable", "mind-blowing"]
        for word in unprofessional_words:
            if word.lower() in email_content.lower():
                violations.append(ComplianceViolation(
                    regulation=RegulationType.CORPORATE_ETHICS,
                    severity=ComplianceRisk.LOW,
                    description=f"Potentially unprofessional language: '{word}'",
                    recommendation="Consider more professional language for corporate communications"
                ))

        return violations

    def _check_content_compliance(self, email_content: str) -> List[ComplianceViolation]:
        """Check email content for compliance issues"""
        violations = []

        # Check content length (avoid wall of text)
        if len(email_content) > 2000:
            violations.append(ComplianceViolation(
                regulation=RegulationType.CORPORATE_ETHICS,
                severity=ComplianceRisk.LOW,
                description="Email content is very long (>2000 characters)",
                recommendation="Consider shortening email for better readability and compliance"
            ))

        # Check for excessive links
        link_count = len(re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', email_content))
        if link_count > 3:
            violations.append(ComplianceViolation(
                regulation=RegulationType.CORPORATE_ETHICS,
                severity=ComplianceRisk.MEDIUM,
                description=f"High number of links ({link_count}) may trigger spam filters",
                recommendation="Reduce number of links in email content"
            ))

        return violations

    def _calculate_overall_risk(self, violations: List[ComplianceViolation]) -> ComplianceRisk:
        """Calculate overall compliance risk level"""
        if not violations:
            return ComplianceRisk.LOW

        # Count violations by severity
        critical_count = sum(1 for v in violations if v.severity == ComplianceRisk.CRITICAL)
        high_count = sum(1 for v in violations if v.severity == ComplianceRisk.HIGH)
        medium_count = sum(1 for v in violations if v.severity == ComplianceRisk.MEDIUM)

        if critical_count > 0:
            return ComplianceRisk.CRITICAL
        elif high_count >= 2:
            return ComplianceRisk.CRITICAL
        elif high_count >= 1:
            return ComplianceRisk.HIGH
        elif medium_count >= 3:
            return ComplianceRisk.HIGH
        elif medium_count >= 1:
            return ComplianceRisk.MEDIUM
        else:
            return ComplianceRisk.LOW

    def _determine_compliance_status(self, violations: List[ComplianceViolation], overall_risk: ComplianceRisk) -> ComplianceStatus:
        """Determine compliance status based on violations and risk"""
        if overall_risk == ComplianceRisk.CRITICAL:
            return ComplianceStatus.REJECTED
        elif overall_risk == ComplianceRisk.HIGH:
            return ComplianceStatus.REQUIRES_REVIEW
        elif overall_risk == ComplianceRisk.MEDIUM:
            return ComplianceStatus.WARNING
        else:
            return ComplianceStatus.APPROVED

    def _generate_compliance_recommendations(self, violations: List[ComplianceViolation], campaign_data: Dict) -> List[str]:
        """Generate compliance recommendations"""
        recommendations = []

        # Aggregate recommendations from violations
        for violation in violations:
            if violation.recommendation not in recommendations:
                recommendations.append(violation.recommendation)

        # Add general recommendations
        if violations:
            recommendations.append("Review all compliance violations before proceeding")
            recommendations.append("Consider legal consultation for high-risk campaigns")
            recommendations.append("Implement compliance monitoring for future campaigns")

        return recommendations

    def _requires_human_approval(self, violations: List[ComplianceViolation], overall_risk: ComplianceRisk, campaign_data: Dict) -> bool:
        """Determine if human approval is required"""
        # Always require approval for critical or high risk
        if overall_risk in [ComplianceRisk.CRITICAL, ComplianceRisk.HIGH]:
            return True

        # Require approval for certain violation types
        high_risk_regulations = [RegulationType.GDPR, RegulationType.FINANCIAL_SERVICES, RegulationType.HEALTHCARE]
        for violation in violations:
            if violation.regulation in high_risk_regulations:
                return True

        # Require approval for large campaigns
        target_count = len(campaign_data.get("targets", []))
        if target_count > 100:
            return True

        return False

    def _generate_audit_notes(self, violations: List[ComplianceViolation], recommendations: List[str], campaign_data: Dict) -> str:
        """Generate comprehensive audit notes"""
        notes = []

        notes.append(f"Compliance audit performed on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        notes.append(f"Campaign type: {campaign_data.get('type', 'unknown')}")
        notes.append(f"Target count: {len(campaign_data.get('targets', []))}")
        notes.append(f"Violations found: {len(violations)}")

        if violations:
            notes.append("\nViolations by regulation:")
            for reg_type in RegulationType:
                reg_violations = [v for v in violations if v.regulation == reg_type]
                if reg_violations:
                    notes.append(f"- {reg_type.value}: {len(reg_violations)} violations")

        if recommendations:
            notes.append(f"\nRecommendations: {len(recommendations)} items")

        notes.append(f"\nAudit completed successfully")

        return "\n".join(notes)

    async def get_compliance_status(self, campaign_id: str, organization_id: int) -> Optional[ComplianceAuditResult]:
        """Get existing compliance status for a campaign"""
        try:
            # Query compliance audit results from database

            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT audit_result, created_at, valid_until
                    FROM compliance_audits
                    WHERE campaign_id = ? AND tenant_id = ?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (campaign_id, organization_id),
                )
                result = cursor.fetchone()
            if result:
                # Parse stored audit result
                import json
                audit_data = json.loads(result[0])

                # Check if still valid
                valid_until_str = result[2]
                if valid_until_str:
                    valid_until = datetime.fromisoformat(valid_until_str)
                    if datetime.now(timezone.utc) > valid_until:
                        return None  # Expired

                # Reconstruct audit result
                return ComplianceAuditResult(
                    status=ComplianceStatus(audit_data["status"]),
                    overall_risk=ComplianceRisk(audit_data["overall_risk"]),
                    violations=[],  # Could reconstruct if needed
                    recommendations=audit_data.get("recommendations", []),
                    audit_notes=audit_data.get("audit_notes", ""),
                    requires_human_approval=audit_data.get("requires_human_approval", False),
                    valid_until=valid_until if valid_until_str else None
                )

        except Exception as e:
            logger.error(f"Error retrieving compliance status: {e}")

        return None

# Global service instance
compliance_auditor = ComplianceAuditorService()
