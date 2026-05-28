"""Shared test fixtures and helpers."""
import json
from unittest.mock import MagicMock

NINE_FINDINGS = [
    {
        "category": cat,
        "display_name": label,
        "severity": sev,
        "headline": headline,
        "clause_excerpt": excerpt,
        "plain_english": plain,
        "negotiation_tip": tip,
    }
    for cat, label, sev, headline, excerpt, plain, tip in [
        ("auto_renewal",            "Auto-Renewal",        "high",      "Annual auto-renewal, 60-day notice",          "Agreement renews automatically each year.",      "You must cancel 60 days before renewal.",          "Push for 30-day notice window."),
        ("price_escalation",        "Price Increases",     "medium",    "Price may increase up to 10% annually",       "Fees may increase by up to 10% per year.",      "Annual increases capped at 10%.",                  "Cap at CPI or 5% whichever is lower."),
        ("data_ownership",          "Data Ownership",      "ok",        "Customer owns all submitted data",            "All data you submit remains your property.",    "Your data stays yours throughout.",                None),
        ("termination_rights",      "Termination Rights",  "medium",    "30-day termination for convenience",          "Either party may terminate with 30 days notice.","Standard termination terms apply.",                "Request immediate termination for material breach."),
        ("liability_cap",           "Liability Cap",       "high",      "Liability capped at 3 months fees",           "Vendor's liability is capped at 3 months fees.","You cannot recover more than 3 months of fees.",  "Negotiate cap to 12 months of fees."),
        ("data_portability",        "Data Portability",    "low",       "Full data export within 30 days",             "Customer data exported within 30 days on exit.", "You can get your data back on exit.",             None),
        ("unilateral_modification", "Unilateral Changes",  "high",      "Vendor may modify terms with 30-day notice",  "Vendor may update terms with 30 days notice.",  "Vendor can change terms unilaterally.",            "Require mutual consent for material changes."),
        ("governing_law",           "Governing Law",       "medium",    "Delaware law, AAA arbitration",               "Disputes governed by Delaware law.",            "Arbitration required for disputes.",               "Request governing law in your jurisdiction."),
        ("sla_remedies",            "SLA & Remedies",      "medium",    "99.9% uptime with service credits",           "99.9% monthly uptime SLA with service credits.","Credits issued for downtime exceeding SLA.",      "Request termination right for repeated SLA breach."),
    ]
]

VALID_SCAN_RESPONSE = json.dumps({
    "vendor_name": "Acme SaaS Inc.",
    "overall_risk_score": 55,
    "overall_grade": "B",
    "executive_summary": (
        "This contract contains several buyer-unfavorable terms including a high liability cap "
        "and unilateral modification rights. Overall risk is moderate."
    ),
    "findings": NINE_FINDINGS,
    "key_dates": [
        {"label": "Renewal Date", "value": "Annual, 60 days notice required"},
        {"label": "Data Retention", "value": "30 days post-termination"},
    ],
    "favorable_terms": [
        "Customer retains data ownership",
        "Full data export provided on exit within 30 days",
    ],
})


def make_groq_mock(content: str = VALID_SCAN_RESPONSE) -> MagicMock:
    """Return a mock Groq client that returns `content` from chat completions."""
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = content
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_resp
    return mock_client


MIN_VALID_TEXT = "A" * 100

SAMPLE_CONTRACT = """
SAAS SUBSCRIPTION AGREEMENT

1. TERM AND RENEWAL
This Agreement commences on the Effective Date and automatically renews for successive
one-year terms unless either party provides written notice of non-renewal at least
60 days prior to the end of the then-current term.

2. FEES AND PAYMENT
Subscription fees are due annually in advance. Provider reserves the right to increase
fees by up to 15% upon each renewal term with 30 days written notice.

3. DATA OWNERSHIP
Customer retains all rights, title, and interest in Customer Data. Provider shall not
use Customer Data for any purpose other than providing the Services.

4. TERMINATION
Either party may terminate this Agreement for convenience upon 30 days written notice.
Provider may terminate immediately upon Customer's material breach.

5. LIMITATION OF LIABILITY
Provider's aggregate liability shall not exceed the total fees paid in the 3 months
preceding the claim. Neither party shall be liable for indirect or consequential damages.

6. DATA PORTABILITY
Upon termination, Provider will make Customer Data available for export for 30 days
in standard CSV format at no additional charge.

7. MODIFICATIONS
Provider may modify these terms with 30 days advance written notice. Continued use
constitutes acceptance. Customer may terminate if they do not accept modified terms.

8. GOVERNING LAW
This Agreement shall be governed by the laws of the State of Delaware. Disputes shall
be resolved by binding arbitration under AAA rules.

9. SERVICE LEVELS
Provider guarantees 99.9% monthly uptime. In the event of breach, Customer shall
receive service credits equal to 10x the downtime prorated against monthly fees.
""".strip()
