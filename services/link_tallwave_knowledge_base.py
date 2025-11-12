"""
Tallwave Process Knowledge Base for Link Master Agent.

Provides curated responses for frequently asked Tallwave operational
questions while enforcing role-aware guardrails between standard users
and administrators.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Pattern

from core.roles import normalize_role


LINK_SYSTEM_PROMPT = (
    "You are Link, the Tallwave conversational operator. Honor role-based guardrails at all times. "
    "Standard users may view high-level guidance, but only administrators can receive detailed or "
    "actionable runbook steps for Tallwave processes (cookie vault rotation, automation reconfiguration, "
    "workflow resets, or credentials management). Never display secrets, raw cookies, API keys, or vault "
    "contents. When a request exceeds the caller's role, politely decline and direct them to Tallwave "
    "operations."
)


@dataclass(frozen=True)
class KnowledgeEntry:
    """Pattern-driven entry for the Link knowledge base."""

    topic: str
    patterns: Iterable[str]
    responses: Dict[str, str]
    references: Iterable[str]
    admin_only: bool = False
    guardrail_hint: Optional[str] = None

    def compiled_patterns(self) -> List[Pattern[str]]:
        return [re.compile(pattern, re.IGNORECASE) for pattern in self.patterns]


@dataclass
class KnowledgeResult:
    """Lookup result returned to the caller."""

    topic: str
    answer: Optional[str]
    audience: str
    references: List[str]
    guardrail: Optional[str] = None
    requires_admin: bool = False

    @property
    def is_guardrail(self) -> bool:
        return self.answer is None and bool(self.guardrail)


class LinkKnowledgeBase:
    """Lightweight knowledge base for Tallwave process guidance."""

    def __init__(self) -> None:
        self.system_prompt = LINK_SYSTEM_PROMPT
        self._entries: List[tuple[KnowledgeEntry, List[Pattern[str]]]] = []
        for entry in self._build_entries():
            self._entries.append((entry, entry.compiled_patterns()))

    def lookup(self, question: str, role: Optional[str]) -> Optional[KnowledgeResult]:
        """Return a role-aware answer if the question matches a known topic."""

        normalized_role = normalize_role(role)
        text = question.strip().lower()
        if not text:
            return None

        for entry, patterns in self._entries:
            if any(pattern.search(text) for pattern in patterns):
                if entry.admin_only and normalized_role != "admin":
                    guardrail = (
                        entry.guardrail_hint
                        or "This workflow is limited to Tallwave administrators. "
                        "Please route the request to the operations team."
                    )
                    return KnowledgeResult(
                        topic=entry.topic,
                        answer=None,
                        audience=normalized_role,
                        references=list(entry.references),
                        guardrail=guardrail,
                        requires_admin=True,
                    )

                answer = (
                    entry.responses.get(normalized_role)
                    or entry.responses.get("user")
                    or entry.responses.get("admin")
                )
                if answer is None:
                    return None

                return KnowledgeResult(
                    topic=entry.topic,
                    answer=answer,
                    audience=normalized_role,
                    references=list(entry.references),
                    guardrail=entry.guardrail_hint if normalized_role != "admin" else None,
                    requires_admin=False,
                )

        return None

    def _build_entries(self) -> Iterable[KnowledgeEntry]:
        """Define curated Tallwave knowledge base entries."""

        cookie_rotation_admin = (
            "To rotate LinkedIn cookies for the tenant:\n"
            "1. Review `Settings → Cookie Vault` to confirm the current vault inventory.\n"
            "2. Ask team members to submit fresh `li_at` + `JSESSIONID` in JSON via the secure upload form.\n"
            "3. Verify each submission and link it to the teammate's profile. Audit entries appear in the vault ledger.\n"
            "4. Run the `collect org cookies` command to refresh cached sessions and retire any expired jars.\n"
            "5. Update the rotation tracker so Tallwave operations can confirm compliance."
        )
        cookie_rotation_user = (
            "Tallwave rotates LinkedIn cookies through the secure vault. "
            "Upload your fresh `li_at` and `JSESSIONID` in JSON via `Settings → Cookie Jar`. "
            "Link confirms receipt, but an administrator finalizes the rotation for the organization."
        )

        workflow_guardrail = (
            "I can outline the approvals flow, but orchestration changes require a Tallwave administrator. "
            "Please escalate through the operations queue if you need a workflow edited or cancelled."
        )

        automation_admin = (
            "Administrators can adjust automation runs by opening the Workflow Console, pausing the active run, "
            "editing the playbook, and re-validating guardrails before resuming. All edits are logged for Tallwave compliance."
        )

        automation_user = (
            "Automation playbooks are managed by Tallwave operations. Share your requested change and an admin "
            "will update the playbook after a guardrail review."
        )

        approval_admin = (
            "Warm-intro drafts follow Tallwave's approval ladder:\n"
            "• Drafted by Link or a teammate.\n"
            "• Reviewed by an operator for context and phrasing.\n"
            "• Approved by an administrator or the owning partner before release.\n"
            "Use the Prospects dashboard to nudge reviewers or fast-track time-sensitive intros."
        )

        approval_user = (
            "Introduction drafts wait for Tallwave operator review. You can comment inside the Prospects dashboard "
            "to provide context, but only administrators can approve or bypass the queue."
        )

        return [
            KnowledgeEntry(
                topic="Tallwave LinkedIn Cookie Rotation",
                patterns=[
                    r"cookie rotation",
                    r"refresh (?:our )?linkedin cookies",
                    r"replace (?:the )?li[_-]?at",
                    r"cookie (?:vault|status) process",
                    r"rotate (?:my|our|the)?\s*(?:linkedin )?cookies",
                ],
                responses={
                    "admin": cookie_rotation_admin,
                    "user": cookie_rotation_user,
                },
                references=[
                    "Reference: PHASE_4_PLAN.md → Cookie Governance",
                    "Reference: RENDER_DEPLOYMENT_GUIDE.md → Vault Operations",
                ],
                admin_only=False,
                guardrail_hint="Only administrators can finalize organization-wide cookie rotations.",
            ),
            KnowledgeEntry(
                topic="Workflow Approval Ladder",
                patterns=[
                    r"(?:tallwave )?approval (?:process|flow)",
                    r"who approves (?:introductions|intros)",
                    r"escalate intro approval",
                ],
                responses={
                    "admin": approval_admin,
                    "user": approval_user,
                },
                references=[
                    "Reference: MASTER_GAME_PLAN_COMPLETION_REPORT.md → Intro Queue Governance",
                ],
                admin_only=False,
                guardrail_hint=workflow_guardrail,
            ),
            KnowledgeEntry(
                topic="Adjusting Automation Playbooks",
                patterns=[
                    r"update automation",
                    r"change (?:the )?workflow playbook",
                    r"modify introducer automation",
                ],
                responses={
                    "admin": automation_admin,
                    "user": automation_user,
                },
                references=[
                    "Reference: PRODUCTION_READY.md → Automation Guardrails",
                ],
                admin_only=True,
                guardrail_hint=(
                    "Automation changes impact Tallwave guardrails. An administrator must review and apply the update."
                ),
            ),
            KnowledgeEntry(
                topic="Roster Sign-Up and Add Team Member",
                patterns=[
                    r"add (?:a )?team member",
                    r"join (?:the )?roster",
                    r"universal password",
                    r"new (?:user|teammate) signup",
                    r"promote user",
                    r"make.*admin",
                    r"change role",
                    r"demote user",
                ],
                responses={
                    "user": (
                        "Use the universal Tallwave password on the login screen, click “Add team member,” and submit your "
                        "Name and Email. Link adds you to the public roster so you can immediately log in as a standard user. "
                        "Role changes must be performed by an administrator."
                    ),
                    "admin": (
                        "Confirm the universal password flow, review the new roster entry, and use the seeded admin panel to "
                        "promote or demote seats. Guardrails log every role change and revoke access when a seat is demoted."
                    ),
                },
                references=[
                    "README.md → Sign Up, Account Creation, and Roles",
                    "legacy/link_agent_roadmap.md → Roster-first rollout",
                ],
                guardrail_hint="Only administrators can elevate or demote roles after roster entry.",
            ),
            KnowledgeEntry(
                topic="Cookie Upload and Status",
                patterns=[
                    r"upload (?:my )?cookies",
                    r"cookie status",
                    r"validate (?:linkedin )?cookie",
                    r"cookie jar",
                ],
                responses={
                    "user": (
                        "Use the Cookie Jar upload to submit your `li_at` (and optional `JSESSIONID`). Link stores them in the "
                        "Cookie Vault and confirms by echoing the LinkedIn username plus account name when you run `cookie status`."
                    ),
                    "admin": (
                        "You can upload on behalf of teammates via the Cookie Vault controls; Link still validates by returning the "
                        "cookie’s username and account name so audits stay clean."
                    ),
                },
                references=[
                    "README.md → Core Capabilities → Cookie intake and validation",
                    "legacy/observability_metrics.md → Cookie vault ledger",
                ],
            ),
            KnowledgeEntry(
                topic="Executive Research and CUFinder Enrichment",
                patterns=[
                    r"find executives",
                    r"executive search",
                    r"cufinder",
                    r"prospects tab",
                ],
                responses={
                    "user": (
                        "Ask Link to research executives at your target company. Link runs web search, enriches with CUFinder using "
                        "full names, captures LinkedIn URLs, and saves each record so it appears in the Prospects tab."
                    ),
                    "admin": (
                        "Admins see the same flow plus audit visibility for CUFinder runs; saved prospects immediately populate the "
                        "Prospects tab for every teammate."
                    ),
                },
                references=[
                    "README.md → Typical Workflow (steps 4–6)",
                    "legacy/link_agent_roadmap.md → Research and enrichment",
                ],
            ),
            KnowledgeEntry(
                topic="Prospect Save and Delete",
                patterns=[
                    r"save prospect",
                    r"delete prospect",
                    r"remove prospect",
                ],
                responses={
                    "user": (
                        "Use prospect commands or the Prospects tab to save new executives. You can delete records you created; Link "
                        "logs every deletion and refreshes the Prospects tab."
                    ),
                    "admin": (
                        "Admins can delete any prospect across the tenant. Every action is audited with the actor, prospect, and timestamp."
                    ),
                },
                references=[
                    "README.md → Prospect management",
                    "legacy/support_runbook.md → Prospect hygiene",
                ],
            ),
            KnowledgeEntry(
                topic="Connector Ranking and Mutual Connections",
                patterns=[
                    r"rank connectors",
                    r"mutual connections",
                    r"connector pairing",
                ],
                responses={
                    "user": (
                        "Link runs the Apify Saswave mutuals scraper to discover shared connections, then ranks connectors and pairs the "
                        "right teammate with each prospect."
                    ),
                    "admin": (
                        "Admins can see runbook-level details for Saswave runs plus final connector rankings before approving introductions."
                    ),
                },
                references=[
                    "README.md → Mutual connectors (Apify Saswave — mandatory)",
                    "legacy/link_agent_roadmap.md → Connector graph",
                ],
            ),
            KnowledgeEntry(
                topic="Run Corporate Connect",
                patterns=[
                    r"run corporate connect",
                    r"corporate connect button",
                    r"org[- ]wide connect",
                ],
                responses={
                    "admin": (
                        "Use chat (“run corporate connect”) or the Corporate Connect button. Link pulls each user’s cookies, executes Saswave "
                        "runs across the org, respects rate limits, and records audits for every action."
                    ),
                },
                references=[
                    "README.md → Corporate Connect (Admin)",
                    "legacy/runbooks/dev-portal-compliance-exports.md → Org-wide runs (archived)",
                ],
                admin_only=True,
                guardrail_hint="Corporate Connect is restricted to Tallwave administrators.",
            ),
            KnowledgeEntry(
                topic="Delete User Seat",
                patterns=[
                    r"delete user",
                    r"remove teammate",
                    r"deactivate seat",
                ],
                responses={
                    "admin": (
                        "Open the admin panel, select the teammate, and run the delete command. Link confirms the role, removes cookies, "
                        "and writes the audit entry before freeing the seat."
                    ),
                },
                references=[
                    "README.md → Roles",
                    "legacy/runbooks/dev-portal-emergency-lockout.md → Seat removal",
                ],
                admin_only=True,
                guardrail_hint="Only administrators can delete Tallwave users.",
            ),
            KnowledgeEntry(
                topic="Send Introduction Email via SendGrid",
                patterns=[
                    r"send introduction email",
                    r"intro email via",
                    r"sendgrid",
                ],
                responses={
                    "user": (
                        "Draft your intro and request approval. Only admins can fire the SendGrid-powered `send_introduction_email` tool."
                    ),
                    "admin": (
                        "Use `send_introduction_email` to deliver intros exclusively through SendGrid. Link surfaces the preview, collects "
                        "approvals, and records delivery status."
                    ),
                },
                references=[
                    "README.md → Email sending (SendGrid — mandatory)",
                    "legacy/link_agent_roadmap.md → Intro approvals (archived)",
                ],
                guardrail_hint="SendGrid is the only allowed mailer; alternate providers are declined automatically.",
            ),
            KnowledgeEntry(
                topic="Run Apify Saswave Mutuals",
                patterns=[
                    r"run (?:saswave|apify) mutuals",
                    r"saswave scraper",
                    r"apify mutuals",
                ],
                responses={
                    "user": (
                        "Use `run_saswave_mutuals` to kick off the Apify Saswave mutuals scraper. Link authenticates with Apify, finds shared "
                        "connections, and pairs teammates accordingly."
                    ),
                    "admin": (
                        "Admins see detailed progress and audit exports for every Saswave run and can re-rank connectors before emailing."
                    ),
                },
                references=[
                    "README.md → Mutual connectors (Apify Saswave — mandatory)",
                    "legacy/observability_metrics.md → Saswave counters",
                ],
            ),
            KnowledgeEntry(
                topic="PhantomBuster Secondary Enrichment",
                patterns=[
                    r"use phantombuster",
                    r"phantom enrichment",
                    r"ph-?buster",
                ],
                responses={
                    "user": (
                        "PhantomBuster is optional and only runs after you approve a detailed confirmation. Use `run_phantombuster_enrichment` "
                        "with a dry-run preview when you need more evidence—the tool records the approval ID, enforces the Saswave-first rule, "
                        "and redacts tokens during the audit."
                    ),
                    "admin": (
                        "Admins can review approval IDs, dry-run previews, and audit entries for every PhantomBuster job. Without a recorded approval "
                        "or a prior Saswave run, Link declines the request."
                    ),
                },
                references=[
                    "README.md → Optional Integrations (PhantomBuster)",
                    "legacy/link_agent_roadmap.md → Enrichment fallbacks",
                ],
                guardrail_hint="PhantomBuster requires explicit user approval before execution.",
            ),
            KnowledgeEntry(
                topic="Autopilot Mode",
                patterns=[
                    r"set_autopilot",
                    r"autopilot mode",
                    r"agentic mode",
                ],
                responses={
                    "user": (
                        "Run `set_autopilot safe|full` to control how proactive Link is. Safe mode asks for confirmations; full mode stays upbeat but "
                        "still confirms destructive actions."
                    ),
                    "admin": (
                        "Admins can switch modes for larger workflows while retaining guardrail confirmations for destructive operations."
                    ),
                },
                references=[
                    "README.md → Agentic Experience",
                    "legacy/link_agent_roadmap.md → Autopilot experiments",
                ],
            ),
            KnowledgeEntry(
                topic="Plan Objective and Live Progress",
                patterns=[
                    r"plan objective",
                    r"stepwise plan",
                    r"progress updates",
                ],
                responses={
                    "user": (
                        "Ask Link to `plan_objective <goal>` to create a checkpointed plan. Link tracks each step, reports progress cards, and adapts "
                        "as work completes."
                    ),
                    "admin": (
                        "Admins can pair plan objectives with org-wide automations and approvals for more complex runs."
                    ),
                },
                references=[
                    "README.md → Agentic Experience → Goal planning in chat",
                    "legacy/link_agent_roadmap.md → Planning prototypes",
                ],
            ),
            KnowledgeEntry(
                topic="Scheduling Background Jobs",
                patterns=[
                    r"schedule (?:a )?job",
                    r"schedule_task",
                    r"schedule_research_job",
                ],
                responses={
                    "user": (
                        "Use `schedule_task` for reminders or `schedule_research_job` for queued enrichment. Link confirms the schedule and posts "
                        "status updates in chat."
                    ),
                    "admin": (
                        "Admins can schedule organization-wide research batches and monitor their status cards from the activity feed."
                    ),
                },
                references=[
                    "README.md → Agentic Experience → Scheduling",
                    "legacy/runbooks/dev-portal-sandbox-mirroring.md → Scheduled jobs (archived)",
                ],
            ),
            KnowledgeEntry(
                topic="Dry Run Corporate Connect",
                patterns=[
                    r"dry run corporate connect",
                    r"dry_run_corporate_connect",
                    r"corporate connect preview",
                ],
                responses={
                    "admin": (
                        "Run `dry_run_corporate_connect` to preview scope, cookies, and projected limits before executing the guarded corporate connect job."
                    ),
                },
                references=[
                    "README.md → Corporate Connect (Admin)",
                    "legacy/observability_metrics.md → Corporate run previews",
                ],
                admin_only=True,
                guardrail_hint="Corporate previews include tenant-wide data and are limited to administrators.",
            ),
            KnowledgeEntry(
                topic="Approvals and Governance Export",
                patterns=[
                    r"request introduction approval",
                    r"approval ladder",
                    r"governance export",
                    r"export conversation",
                ],
                responses={
                    "user": (
                        "Use `request_introduction_approval` to capture edits and approvals. For incident response, export your conversation via `/history export` "
                        "and share it with Tallwave operations."
                    ),
                    "admin": (
                        "Admins can also run `export_governance_bundle` for redacted transcripts plus audits covering a date range."
                    ),
                },
                references=[
                    "README.md → Training Checklist → Dry-run & Approvals",
                    "legacy/runbooks/dev-portal-compliance-exports.md → Governance bundles",
                ],
                guardrail_hint="Governance bundles may include tenant-wide audits; admins should handle distribution.",
            ),
            KnowledgeEntry(
                topic="Tone and Context Controls",
                patterns=[
                    r"set tone",
                    r"pin context",
                    r"forget context",
                ],
                responses={
                    "user": (
                        "Use `set_tone` to nudge Link’s writing style, `pin_context` to keep crucial notes in memory, and `forget_context` to clear it when the topic changes."
                    ),
                    "admin": (
                        "Admins can use the same controls plus `/pin context` macros to share guidance across runs."
                    ),
                },
                references=[
                    "README.md → Agentic Experience → set_tone / pin_context / forget_context",
                    "legacy/docs_archive/context.md → Session memory (archived)",
                ],
            ),
        ]


__all__ = [
    "LinkKnowledgeBase",
    "KnowledgeEntry",
    "KnowledgeResult",
    "LINK_SYSTEM_PROMPT",
]
