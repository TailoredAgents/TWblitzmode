"""
SendGrid send example with correlation id in custom_args.
"""
from __future__ import annotations
import os
from typing import Any, Dict, List


def build_send_payload(to: List[Dict[str, str]], subject: str, html: str, corr_id: str) -> Dict[str, Any]:
    return {
        "personalizations": [
            {
                "to": to,
                "custom_args": {"corr_id": corr_id},
            }
        ],
        "from": {
            "email": os.getenv("SENDGRID_VERIFIED_SENDER", "notifications@example.com"),
            "name": "Link"
        },
        "subject": subject,
        "content": [{"type": "text/html", "value": html}],
        "tracking_settings": {"click_tracking": {"enable": True}, "open_tracking": {"enable": True}},
    }

