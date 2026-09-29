"""VensureHR brand palette and standard proposal copy."""

from reportlab.lib import colors

NAVY = colors.HexColor("#0E1E3A")
NAVY_2 = colors.HexColor("#1B2F55")
ORANGE = colors.HexColor("#F26522")
TEAL = colors.HexColor("#00A9C0")
GREEN = colors.HexColor("#1E8E5A")
RED = colors.HexColor("#C0392B")
INK = colors.HexColor("#2B3140")
MUTED = colors.HexColor("#6B7280")
LIGHT = colors.HexColor("#F3F4F6")
RULE = colors.HexColor("#D9DDE3")
PEACH = colors.HexColor("#FDE6D8")
PEACH_2 = colors.HexColor("#FDEEE7")
WHITE = colors.white

DISCLAIMER = "Rates are estimates for comparison and subject to final underwriting. Carrier documents prevail."

# Core services from the VensureHR Pricing Illustration (condensed for the one-page summary).
DEFAULT_SERVICES = {
    "payroll": [
        "Dedicated Payroll Specialist",
        "Tax filing & remittance (W-2/1099)",
        "New state & pay group setup",
        "Garnishments & new hire reporting",
        "Unlimited standard & custom reports",
    ],
    "hr": [
        "Dedicated HR Partner",
        "Dedicated Client Relations Manager",
        "Handbook review & development",
        "Harassment & discrimination training",
        "Unemployment claims assistance",
    ],
    "benefits": [
        "Master plan benefit administration",
        "COBRA, FSA/HSA/HRA, ACA reporting",
        "401(k) plan access & administration",
        "24/7 online payroll & HR access",
        "Employee self-service portal",
    ],
}

# Optional add-ons listed on the 2026 Pricing Illustration template.
DEFAULT_ADDONS = [
    {"name": "401(k) Program", "rate": "$49 - $89 / mo + $500 one time"},
    {"name": "Time & Attendance", "rate": "$6 PEPM + $350 one time"},
    {"name": "E-Verify", "rate": "$6 per verification"},
    {"name": "QuickBooks Online Integration", "rate": "$500 one time"},
    {"name": "Report Center Access", "rate": "$5 viewer / $20 explorer"},
    {"name": "Applicant Tracking / Performance Mgmt", "rate": "Tiered by group size"},
]

DEFAULT_THINGS_TO_KNOW = [
    "**Don't cancel current coverage early.** Keep {incumbent} benefits in force until VensureHR underwriting approves final enrollment.",
    "**COBRA participants:** anyone already on COBRA from a prior PEO before the VensureHR start date cannot move onto the VensureHR master plans.",
    "**Rates are time-limited:** medical quotes are typically valid for 90 days and final rates can change if the census or enrollment changes.",
    "**Workers' comp:** final WC pricing requires a completed Risk Questionnaire and 3-5 years of loss runs.",
]

DEFAULT_SERVICE_CALLOUT = (
    "**Why the service side matters to the cost:** payroll or tax errors cost time and penalties. With a named "
    "Payroll Specialist, Client Relations Manager and HR Partner, {client} has specific people accountable for "
    "getting it right, plus annual client reviews to check what is and isn't working."
)
