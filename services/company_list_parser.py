from __future__ import annotations

"""
Utilities for normalizing corporate connect company lists.
"""

import csv
import tempfile
from typing import Iterable, List, Tuple, Union

SEPARATORS = [",", ";", "|", "\n"]


def parse_company_list(raw: Union[str, Iterable[str]]) -> List[str]:
    """Normalize an inline company list into a cleaned sequence."""

    if isinstance(raw, str):
        entries = [raw]
    else:
        entries = list(raw)

    normalized: List[str] = []
    seen = set()

    for entry in entries:
        if not entry:
            continue

        cleaned = (
            entry.replace("•", " ")
            .replace("–", " ")
            .replace("—", " ")
            .strip()
        )

        if not cleaned:
            continue

        segments = [cleaned]
        for separator in SEPARATORS:
            new_segments: List[str] = []
            for segment in segments:
                new_segments.extend(part.strip() for part in segment.split(separator))
            segments = new_segments

        for segment in segments:
            if not segment:
                continue

            segment = segment.lstrip("0123456789.-) ").strip()
            if not segment:
                continue

            identifier = segment.lower()
            if identifier not in seen:
                seen.add(identifier)
                normalized.append(segment)

    return normalized


def create_company_csv(raw: Union[str, Iterable[str]]) -> Tuple[str, int]:
    """Create a temporary CSV file from inline company input."""

    companies = parse_company_list(raw)
    if not companies:
        raise ValueError("No company names detected. Provide at least one company.")

    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".csv",
        prefix="corporate_companies_",
        delete=False,
        newline="",
    )
    writer = csv.writer(tmp)
    writer.writerow(["company", "executive_name"])
    for company in companies:
        writer.writerow([company, "TBD"])
    tmp.flush()
    tmp.close()
    return tmp.name, len(companies)

