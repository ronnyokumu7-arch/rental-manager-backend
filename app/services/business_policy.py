# app/services/business_policy.py
"""
✅ BUSINESS POLICY DOCUMENT MERGE — single source of truth for contract clauses.

Emits the full 3-category document:
  - agency_policies       → Section 4: Specific Agency Policies & Liability Clauses
  - statutory_declaration → Statutory Declaration bullets
  - general_conditions    → General Conditions articles (numbering is positional)

Per category:
  - every default clause (overridden only where the tenant customized it)
  - plus active custom clauses (clause_key NULL) appended in display_order.

Inactive overrides fall back to the default; inactive custom clauses are
hidden. The contract template renders each block with CSS
`white-space: pre-line`, so textarea line breaks survive into the PDF.
"""
from typing import Any, Dict, List, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant_policies import (
    DEFAULT_POLICY_DOCUMENT,
    PolicyCategory,
    TenantPolicy,
)

# ✅ Human-readable labels for the settings UI tabs
CATEGORY_LABELS: Dict[str, str] = {
    PolicyCategory.agency_policies.value: "Agency Policies",
    PolicyCategory.statutory_declaration.value: "Statutory Declaration",
    PolicyCategory.general_conditions.value: "General Terms & Conditions",
}


def category_labels() -> List[Dict[str, str]]:
    """Ordered [{value, label}] for the frontend tab switcher."""
    return [
        {"value": cat.value, "label": CATEGORY_LABELS[cat.value]}
        for cat in PolicyCategory
    ]


def _clause_view(cat: PolicyCategory, d: Dict[str, Any]) -> Dict[str, Any]:
    """A default clause, view-shaped (is_custom=False)."""
    return {
        "category": cat.value,
        "clause_key": d["clause_key"],
        "title": d["title"],
        "content": d["content"],
        "display_order": d["display_order"],
        "is_custom": False,
        "policy_id": None,
    }


def default_document() -> Dict[str, List[Dict[str, Any]]]:
    """The platform default document, in contract order, flagged is_custom=False."""
    return {
        cat.value: [_clause_view(cat, d) for d in sorted(clauses, key=lambda x: x["display_order"])]
        for cat, clauses in DEFAULT_POLICY_DOCUMENT.items()
    }


async def get_effective_policy_document(
    db: AsyncSession, tenant_id: int
) -> Dict[str, List[Dict[str, Any]]]:
    """
    ✅ MERGE for contract rendering + settings preview.
    Missing/inactive override ⇒ default inherited verbatim.
    Inactive custom clause ⇒ hidden.
    """
    stmt = (
        select(TenantPolicy)
        .where(
            TenantPolicy.tenant_id == tenant_id,
            TenantPolicy.is_active == True,  # noqa: E712
        )
        .order_by(TenantPolicy.category, TenantPolicy.display_order)
    )
    rows = (await db.execute(stmt)).scalars().all()

    # Index active overrides by (category, clause_key); collect customs per category
    overrides: Dict[Tuple[str, str], TenantPolicy] = {}
    customs: Dict[str, List[TenantPolicy]] = {}
    for r in rows:
        if r.clause_key:
            overrides[(r.category, r.clause_key)] = r
        else:
            customs.setdefault(r.category, []).append(r)

    document: Dict[str, List[Dict[str, Any]]] = {}
    for cat, clauses in DEFAULT_POLICY_DOCUMENT.items():
        merged: List[Dict[str, Any]] = []

        # 1. Default clauses, overridden only where an ACTIVE override exists
        for d in sorted(clauses, key=lambda x: x["display_order"]):
            override = overrides.get((cat.value, d["clause_key"]))
            if override:
                merged.append({
                    "category": cat.value,
                    "clause_key": d["clause_key"],
                    "title": override.title,
                    "content": override.content,
                    "display_order": d["display_order"],
                    "is_custom": True,
                    "policy_id": override.id,
                })
            else:
                merged.append(_clause_view(cat, d))

        # 2. ✅ Custom clauses appended within their category
        for r in customs.get(cat.value, []):
            merged.append({
                "category": cat.value,
                "clause_key": None,
                "title": r.title,
                "content": r.content,
                "display_order": r.display_order,
                "is_custom": True,
                "policy_id": r.id,
            })

        document[cat.value] = merged

    return document
