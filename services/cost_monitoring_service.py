"""
Cost Monitoring Service for SendGrid Usage Tracking
Tracks per-tenant email costs for Tailored Agents administrative oversight
Based on 2025 SendGrid pricing structure
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from decimal import Decimal

from api.database import get_db
from core.settings import settings

logger = logging.getLogger(__name__)

@dataclass
class SendGridPricing:
    """2025 SendGrid pricing structure"""
    
    # Free tier limits
    FREE_TIER_DAILY_LIMIT = 100
    FREE_TIER_MONTHLY_LIMIT = 3000  # 100 * 30 days
    
    # Essentials plan ($19.95/month) - up to 40,000 emails
    ESSENTIALS_MONTHLY_COST = 19.95
    ESSENTIALS_EMAIL_LIMIT = 40000
    ESSENTIALS_PER_EMAIL = ESSENTIALS_MONTHLY_COST / ESSENTIALS_EMAIL_LIMIT  # ~$0.0005
    
    # Pro plan (estimated $89.95/month) - up to 100,000 emails
    PRO_MONTHLY_COST = 89.95
    PRO_EMAIL_LIMIT = 100000
    PRO_PER_EMAIL = PRO_MONTHLY_COST / PRO_EMAIL_LIMIT  # ~$0.0009
    
    # Premier plan (custom pricing, estimate $249+/month) - 1M+ emails
    PREMIER_MONTHLY_BASE = 249.00
    PREMIER_EMAIL_LIMIT = 1000000
    PREMIER_PER_EMAIL = PREMIER_MONTHLY_BASE / PREMIER_EMAIL_LIMIT  # ~$0.0002
    
    # Overage fees (when exceeding plan limits)
    OVERAGE_PER_EMAIL = 0.001  # $0.001 per extra email
    
    # Marketing Campaigns (if used)
    MARKETING_BASIC_COST = 15.00  # $15/month for up to 100,000 contacts
    MARKETING_ADVANCED_COST = 60.00  # $60/month for advanced features
    
    # Additional features
    DEDICATED_IP_COST = 30.00  # $30/month per dedicated IP
    EMAIL_VALIDATION_PER_EMAIL = 0.0008  # $0.0008 per validation

@dataclass
class TenantCostSummary:
    """Cost summary for a specific tenant"""
    tenant_id: int
    tenant_name: str
    period_start: datetime
    period_end: datetime
    
    # Email volume
    total_emails_sent: int
    successful_emails: int
    failed_emails: int
    
    # Cost breakdown
    base_email_cost: Decimal
    overage_cost: Decimal
    validation_cost: Decimal
    dedicated_ip_cost: Decimal
    total_cost: Decimal
    
    # Efficiency metrics
    cost_per_successful_email: Decimal
    success_rate: float
    
    # Plan recommendation
    recommended_plan: str
    potential_savings: Decimal

class CostMonitoringService:
    """Service for tracking and analyzing SendGrid costs per tenant"""
    
    def __init__(self):
        self.pricing = SendGridPricing()
        
    def calculate_email_cost(self, email_count: int, plan_tier: str = "essentials") -> Decimal:
        """
        Calculate cost for given email volume based on plan tier
        
        Args:
            email_count: Number of emails sent
            plan_tier: SendGrid plan tier (essentials, pro, premier)
            
        Returns:
            Total cost for emails
        """
        if plan_tier == "free":
            if email_count <= self.pricing.FREE_TIER_MONTHLY_LIMIT:
                return Decimal("0.00")
            else:
                # Overage on free tier
                overage = email_count - self.pricing.FREE_TIER_MONTHLY_LIMIT
                return Decimal(str(overage * self.pricing.OVERAGE_PER_EMAIL))
                
        elif plan_tier == "essentials":
            base_cost = Decimal(str(self.pricing.ESSENTIALS_MONTHLY_COST))
            if email_count <= self.pricing.ESSENTIALS_EMAIL_LIMIT:
                return base_cost
            else:
                overage = email_count - self.pricing.ESSENTIALS_EMAIL_LIMIT
                overage_cost = Decimal(str(overage * self.pricing.OVERAGE_PER_EMAIL))
                return base_cost + overage_cost
                
        elif plan_tier == "pro":
            base_cost = Decimal(str(self.pricing.PRO_MONTHLY_COST))
            if email_count <= self.pricing.PRO_EMAIL_LIMIT:
                return base_cost
            else:
                overage = email_count - self.pricing.PRO_EMAIL_LIMIT
                overage_cost = Decimal(str(overage * self.pricing.OVERAGE_PER_EMAIL))
                return base_cost + overage_cost
                
        elif plan_tier == "premier":
            base_cost = Decimal(str(self.pricing.PREMIER_MONTHLY_BASE))
            # Premier usually includes higher volume, minimal overage
            return base_cost + Decimal(str(email_count * self.pricing.PREMIER_PER_EMAIL))
            
        else:
            # Default to per-email pricing
            return Decimal(str(email_count * self.pricing.ESSENTIALS_PER_EMAIL))
    
    async def track_email_cost(self, tenant_id: int, email_count: int, 
                             email_type: str = "transactional", 
                             additional_features: Dict[str, Any] = None):
        """
        Track email costs for a tenant
        
        Args:
            tenant_id: Tenant ID
            email_count: Number of emails sent
            email_type: Type of email (transactional, marketing)
            additional_features: Dict of additional features used
        """
        conn = None
        try:
            conn = get_db()
            with conn.cursor() as cursor:
                # Get tenant's current plan
                cursor.execute(
                    """
                    SELECT plan_name, custom_domain_enabled, dedicated_ip_enabled
                    FROM tenant_email_plans
                    WHERE tenant_id = ?
                    """,
                    (tenant_id,),
                )

                plan_info = cursor.fetchone()
                if plan_info:
                    plan_tier = plan_info["plan_name"] if "plan_name" in plan_info.keys() else "essentials"
                    has_dedicated_ip = plan_info["dedicated_ip_enabled"] if "dedicated_ip_enabled" in plan_info.keys() else False
                else:
                    plan_tier = "essentials"
                    has_dedicated_ip = False

                # Calculate costs
                email_cost = self.calculate_email_cost(email_count, plan_tier)

                # Additional feature costs
                validation_cost = Decimal("0.00")
                dedicated_ip_cost = Decimal("0.00")

                if additional_features:
                    if additional_features.get("email_validation_count", 0) > 0:
                        validation_count = additional_features["email_validation_count"]
                        validation_cost = Decimal(str(validation_count * self.pricing.EMAIL_VALIDATION_PER_EMAIL))

                    if has_dedicated_ip:
                        dedicated_ip_cost = Decimal(str(self.pricing.DEDICATED_IP_COST))

                total_cost = email_cost + validation_cost + dedicated_ip_cost

                # Record cost entry
                import json

                metadata = json.dumps(
                    {
                        "plan_tier": plan_tier,
                        "email_cost": float(email_cost),
                        "validation_cost": float(validation_cost),
                        "dedicated_ip_cost": float(dedicated_ip_cost),
                        "additional_features": additional_features or {},
                    }
                )

                unit_cost = float(email_cost / email_count) if email_count > 0 else 0.0

                cursor.execute(
                    """
                    INSERT INTO email_costs (
                        tenant_id,
                        date,
                        service,
                        operation,
                        count,
                        unit_cost,
                        total_cost,
                        metadata
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (tenant_id, date, service, operation)
                    DO UPDATE SET
                        count = EXCLUDED.count,
                        unit_cost = EXCLUDED.unit_cost,
                        total_cost = EXCLUDED.total_cost,
                        metadata = EXCLUDED.metadata,
                        updated_at = NOW()
                    """,
                    (
                        tenant_id,
                        datetime.now().date(),
                        "sendgrid",
                        email_type,
                        email_count,
                        unit_cost,
                        float(total_cost),
                        metadata,
                    ),
                )

            conn.commit()

            logger.info(f"Tracked ${total_cost:.4f} cost for tenant {tenant_id} ({email_count} emails)")

        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Failed to track email cost for tenant {tenant_id}: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    async def get_tenant_cost_summary(self, tenant_id: int, 
                                    start_date: datetime, 
                                    end_date: datetime) -> TenantCostSummary:
        """
        Get comprehensive cost summary for a tenant
        
        Args:
            tenant_id: Tenant ID
            start_date: Start of period
            end_date: End of period
            
        Returns:
            TenantCostSummary with all cost details
        """
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            # Get tenant info
            cursor.execute("""
                SELECT u.tenant_id, 'Tenant ' || ? as tenant_name
                FROM users u
                WHERE u.tenant_id = ?
                LIMIT 1
            """, (tenant_id, tenant_id))
            
            tenant_info = cursor.fetchone()
            if tenant_info and "tenant_name" in tenant_info.keys():
                tenant_name = tenant_info["tenant_name"]
            else:
                tenant_name = f"Tenant {tenant_id}"
            
            # Get email stats for period
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_emails,
                    COUNT(CASE WHEN status IN ('delivered', 'opened', 'clicked') THEN 1 END) as successful_emails,
                    COUNT(CASE WHEN status IN ('bounced', 'dropped', 'blocked') THEN 1 END) as failed_emails
                FROM tenant_email_logs
                WHERE tenant_id = ? 
                AND sent_at >= ? 
                AND sent_at <= ?
            """, (tenant_id, start_date, end_date))
            
            email_stats = cursor.fetchone()
            if email_stats:
                total_emails = email_stats["total_emails"] or 0
                successful_emails = email_stats["successful_emails"] or 0
                failed_emails = email_stats["failed_emails"] or 0
            else:
                total_emails = successful_emails = failed_emails = 0
            
            # Get cost breakdown
            cursor.execute("""
                SELECT 
                    SUM(total_cost) as total_cost,
                    SUM(count) as total_count,
                    service,
                    operation,
                    metadata
                FROM email_costs
                WHERE tenant_id = ? 
                AND date >= ? 
                AND date <= ?
                GROUP BY service, operation, metadata
            """, (tenant_id, start_date.date(), end_date.date()))
            
            cost_records = cursor.fetchall()
            
            # Calculate cost components
            base_email_cost = Decimal("0.00")
            overage_cost = Decimal("0.00")
            validation_cost = Decimal("0.00")
            dedicated_ip_cost = Decimal("0.00")
            
            for record in cost_records:
                try:
                    metadata = record["metadata"] if record["metadata"] else "{}"
                except (KeyError, IndexError):
                    metadata = "{}"
                    
                if isinstance(metadata, str):
                    import json
                    try:
                        metadata = json.loads(metadata)
                    except:
                        metadata = {}
                base_email_cost += Decimal(str(metadata.get("email_cost", 0)))
                validation_cost += Decimal(str(metadata.get("validation_cost", 0)))
                dedicated_ip_cost += Decimal(str(metadata.get("dedicated_ip_cost", 0)))
            
            total_cost = base_email_cost + overage_cost + validation_cost + dedicated_ip_cost
            
            # Calculate efficiency metrics
            cost_per_successful = total_cost / successful_emails if successful_emails > 0 else Decimal("0.00")
            success_rate = (successful_emails / total_emails) * 100 if total_emails > 0 else 0.0
            
            # Plan recommendation
            recommended_plan, potential_savings = self._recommend_plan(total_emails, total_cost)
            
            return TenantCostSummary(
                tenant_id=tenant_id,
                tenant_name=tenant_name,
                period_start=start_date,
                period_end=end_date,
                total_emails_sent=total_emails,
                successful_emails=successful_emails,
                failed_emails=failed_emails,
                base_email_cost=base_email_cost,
                overage_cost=overage_cost,
                validation_cost=validation_cost,
                dedicated_ip_cost=dedicated_ip_cost,
                total_cost=total_cost,
                cost_per_successful_email=cost_per_successful,
                success_rate=success_rate,
                recommended_plan=recommended_plan,
                potential_savings=potential_savings
            )
            
        except Exception as e:
            logger.error(f"Failed to get cost summary for tenant {tenant_id}: {e}")
            raise
        finally:
            conn.close()
    
    def _recommend_plan(self, monthly_emails: int, current_cost: Decimal) -> tuple[str, Decimal]:
        """
        Recommend optimal SendGrid plan based on usage
        
        Args:
            monthly_emails: Average monthly email volume
            current_cost: Current monthly cost
            
        Returns:
            Tuple of (recommended_plan, potential_savings)
        """
        plans_cost = {
            "free": self.calculate_email_cost(monthly_emails, "free"),
            "essentials": self.calculate_email_cost(monthly_emails, "essentials"),
            "pro": self.calculate_email_cost(monthly_emails, "pro"),
            "premier": self.calculate_email_cost(monthly_emails, "premier")
        }
        
        # Find most cost-effective plan
        optimal_plan = min(plans_cost.items(), key=lambda x: x[1])
        recommended_plan = optimal_plan[0]
        optimal_cost = optimal_plan[1]
        
        potential_savings = current_cost - optimal_cost
        
        return recommended_plan, potential_savings
    
    async def get_all_tenants_cost_overview(self, start_date: datetime, end_date: datetime) -> List[TenantCostSummary]:
        """
        Get cost overview for all tenants
        
        Args:
            start_date: Start of period
            end_date: End of period
            
        Returns:
            List of TenantCostSummary for all active tenants
        """
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            # Get all tenants with email activity
            cursor.execute("""
                SELECT DISTINCT tel.tenant_id
                FROM tenant_email_logs tel
                WHERE tel.sent_at >= ? AND tel.sent_at <= ?
                ORDER BY tel.tenant_id
            """, (start_date, end_date))
            
            tenant_rows = cursor.fetchall()
            tenant_ids = [row["tenant_id"] for row in tenant_rows] if tenant_rows else []
            
            summaries = []
            for tenant_id in tenant_ids:
                try:
                    summary = await self.get_tenant_cost_summary(tenant_id, start_date, end_date)
                    summaries.append(summary)
                except Exception as e:
                    logger.error(f"Failed to get summary for tenant {tenant_id}: {e}")
                    continue
            
            return summaries
            
        except Exception as e:
            logger.error(f"Failed to get all tenants cost overview: {e}")
            raise
        finally:
            conn.close()
    
    async def get_cost_trends(self, tenant_id: Optional[int] = None, days: int = 30) -> Dict[str, Any]:
        """
        Get cost trends over time
        
        Args:
            tenant_id: Specific tenant ID (None for all tenants)
            days: Number of days to analyze
            
        Returns:
            Dict with trend data for visualization
        """
        conn = get_db()
        cursor = conn.cursor()
        
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            if tenant_id:
                cursor.execute("""
                    SELECT 
                        date,
                        SUM(total_cost) as daily_cost,
                        SUM(count) as daily_emails
                    FROM email_costs
                    WHERE tenant_id = ? 
                    AND date >= ? 
                    AND date <= ?
                    GROUP BY date
                    ORDER BY date
                """, (tenant_id, start_date.date(), end_date.date()))
            else:
                cursor.execute("""
                    SELECT 
                        date,
                        SUM(total_cost) as daily_cost,
                        SUM(count) as daily_emails,
                        COUNT(DISTINCT tenant_id) as active_tenants
                    FROM email_costs
                    WHERE date >= ? 
                    AND date <= ?
                    GROUP BY date
                    ORDER BY date
                """, (start_date.date(), end_date.date()))
            
            trend_data = []
            rows = cursor.fetchall()
            for row in rows:
                date_val = row["date"]
                if hasattr(date_val, 'isoformat'):
                    date_str = date_val.isoformat()
                else:
                    date_str = str(date_val)
                
                daily_cost = float(row["daily_cost"]) if row["daily_cost"] else 0
                daily_emails = int(row["daily_emails"]) if row["daily_emails"] else 0
                try:
                    active_tenants = int(row["active_tenants"]) if row["active_tenants"] else 1
                except (KeyError, IndexError):
                    active_tenants = 1
                
                trend_data.append({
                    "date": date_str,
                    "cost": daily_cost,
                    "emails": daily_emails,
                    "active_tenants": active_tenants,
                    "cost_per_email": daily_cost / daily_emails if daily_emails > 0 else 0
                })
            
            # Calculate summary statistics
            total_cost = sum(d["cost"] for d in trend_data)
            total_emails = sum(d["emails"] for d in trend_data)
            avg_daily_cost = total_cost / len(trend_data) if trend_data else 0
            avg_cost_per_email = total_cost / total_emails if total_emails > 0 else 0
            
            return {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "days": days
                },
                "summary": {
                    "total_cost": total_cost,
                    "total_emails": total_emails,
                    "avg_daily_cost": avg_daily_cost,
                    "avg_cost_per_email": avg_cost_per_email
                },
                "trend_data": trend_data
            }
            
        except Exception as e:
            logger.error(f"Failed to get cost trends: {e}")
            raise
        finally:
            conn.close()

# Global instance
cost_monitoring_service = CostMonitoringService()
