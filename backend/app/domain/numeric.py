"""Numeric comparison policies: strict separation of quantity comparison vs financial comparison.

Policy Specifications:
- Quantity Comparison (CONFIRMED):
  * Exact Decimal arithmetic.
  * Zero tolerance.
  * Never rounded before or during comparison.
  * diff = invoiced - delivered. diff == 0 -> MATCH; diff != 0 -> MISMATCH.

- Financial Comparison (PROVISIONAL):
  * Computed products (e.g. qty * unit_price) are rounded to 2 decimal places (ROUND_HALF_UP)
    before exact comparison with the stated amount.
  * Stated amounts are NEVER rounded.
  * Stored and displayed with unrounded computed value, rounded computed value, and stated amount.
  * Tagged with RuleStatus.PROVISIONAL and NumericPolicy.MONEY_ROUND_2DP_HALF_UP.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.domain.models import NumericPolicy, RuleStatus


@dataclass(frozen=True)
class QuantityComparisonResult:
    is_exact_match: bool
    diff: Decimal
    diff_pct: Decimal | None
    invoiced: Decimal
    delivered: Decimal
    rule_status: RuleStatus = RuleStatus.CONFIRMED
    numeric_policy: NumericPolicy = NumericPolicy.QTY_EXACT


def compare_quantity(invoiced: Decimal, delivered: Decimal) -> QuantityComparisonResult:
    """Compare quantities strictly and exactly without any rounding or tolerance."""
    diff = invoiced - delivered
    is_exact = (diff == Decimal(0))
    
    diff_pct: Decimal | None = None
    if delivered != Decimal(0):
        diff_pct = (diff / delivered) * Decimal(100)
        
    return QuantityComparisonResult(
        is_exact_match=is_exact,
        diff=diff,
        diff_pct=diff_pct,
        invoiced=invoiced,
        delivered=delivered,
        rule_status=RuleStatus.CONFIRMED,
        numeric_policy=NumericPolicy.QTY_EXACT,
    )


@dataclass(frozen=True)
class AmountComparisonResult:
    is_match: bool
    diff: Decimal
    stated_amount: Decimal
    unrounded_computed_amount: Decimal
    rounded_computed_amount: Decimal
    rule_status: RuleStatus = RuleStatus.PROVISIONAL
    numeric_policy: NumericPolicy = NumericPolicy.MONEY_ROUND_2DP_HALF_UP


def compare_amount(stated: Decimal, computed: Decimal) -> AmountComparisonResult:
    """Compare money amounts using provisional 2-dp half-up rounding on computed value."""
    # Round computed value to 2 decimal places using ROUND_HALF_UP
    rounded_computed = computed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    diff = stated - rounded_computed
    is_match = (diff == Decimal("0.00"))

    return AmountComparisonResult(
        is_match=is_match,
        diff=diff,
        stated_amount=stated,
        unrounded_computed_amount=computed,
        rounded_computed_amount=rounded_computed,
        rule_status=RuleStatus.PROVISIONAL,
        numeric_policy=NumericPolicy.MONEY_ROUND_2DP_HALF_UP,
    )
