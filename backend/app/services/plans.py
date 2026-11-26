"""The plans on sale. Prices are in kobo (1 naira = 100 kobo), the unit Paystack charges in.

Change a price here and nothing else. Past payments keep the amount that was actually paid.
"""

from dataclasses import dataclass
from typing import Literal

CURRENCY = "NGN"
MAX_MONTHS = 12
TRIAL_PLAN = "trial"


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    kind: Literal["individual", "institution"]
    seats: int | None  # people who can have their own login; None for individual plans
    monthly_kobo: int


PLANS: dict[str, Plan] = {
    p.code: p
    for p in (
        Plan("individual", "Individual", "individual", None, 15_000 * 100),
        Plan("institution_10", "Institution, 10 people", "institution", 10, 80_000 * 100),
        Plan("institution_20", "Institution, 20 people", "institution", 20, 150_000 * 100),
    )
}


def get_plan(code: str) -> Plan | None:
    return PLANS.get(code)
