"""Unit tests for M1 domain verification rules:
- Exact quantity matching (zero tolerance, never rounded)
- Invoiced vs delivered mismatches
- Evidence incompleteness / unconfirmed values -> UNCERTAIN or MISSING_EVIDENCE
- Unit incompatibility without confirmed conversion
- Delivery note reuse detection (permanent audit finding)
- Delivery note line linked to multiple invoice lines (provisional rule P2)
- Accepted delivery quantity (delivered - documented rejected; unevidenced rejection -> UNCERTAIN)
- Charge lines excluded from quantity checks
- Financial arithmetic separation and provisional 2-dp half-up rounding
- Automated VAT validation NOT_CHECKED
"""

from decimal import Decimal

from app.domain.engine import verify_case
from app.domain.models import (
    CaseSnapshot,
    DNLineSnapshot,
    FieldStatus,
    FindingCategory,
    FindingOutcome,
    InvoiceLineSnapshot,
    NumericPolicy,
    RuleStatus,
    ValueWithTrust,
)
from app.domain.numeric import compare_amount, compare_quantity
from app.domain.units import normalize_unit, resolve_unit_conversion


def make_trusted_val(val, doc_id="doc-1", field_key="field", page=1):
    return ValueWithTrust(
        value=val,
        status=FieldStatus.CONFIRMED,
        confidence=1.0,
        document_id=doc_id,
        page=page,
        field_key=field_key,
    )


def make_untrusted_val(val, doc_id="doc-1", field_key="field", page=1):
    return ValueWithTrust(
        value=val,
        status=FieldStatus.EXTRACTED,
        confidence=0.80,
        document_id=doc_id,
        page=page,
        field_key=field_key,
    )


def make_base_snapshot(
    invoice_lines=None,
    dn_lines=None,
    confirmed_links=None,
    lpo_required=False,
    lpo_lines=None,
    currency="AED",
    subtotal="1000.00",
    tax="50.00",
    grand_total="1050.00",
    cross_case_dn_index=None,
    cross_case_sha_index=None,
    dn_file_hashes=None,
):
    return CaseSnapshot(
        case_id="case-001",
        project_id="proj-1",
        project_name="Dubai Creek Harbor Plot 4",
        supplier_id="sup-1",
        supplier_name="Emirates Ready Mix Concrete LLC",
        supplier_trn=make_trusted_val("100234567800003"),
        invoice_number=make_trusted_val("INV-2026-901"),
        invoice_date=make_trusted_val("15/03/2026"),
        invoice_currency=make_trusted_val(currency),
        subtotal=make_trusted_val(Decimal(subtotal)),
        tax_amount=make_trusted_val(Decimal(tax)),
        grand_total=make_trusted_val(Decimal(grand_total)),
        lpo_required=lpo_required,
        lpo_reason_code="NOT_REQUIRED_CONTRACT_SUPPLY" if not lpo_required else None,
        lpo_reason_text="Direct rate call-off contract" if not lpo_required else None,
        invoice_lines=invoice_lines or [],
        dn_lines=dn_lines or [],
        lpo_lines=lpo_lines or [],
        confirmed_links=confirmed_links or {},
        cross_case_dn_index=cross_case_dn_index or {},
        cross_case_sha_index=cross_case_sha_index or {},
        dn_file_hashes=dn_file_hashes or {},
    )


# =========================================================================
# 1. Numeric Policies: Exact Quantity vs Provisional Financial Rounding
# =========================================================================

def test_quantity_comparison_is_exact_and_never_rounds():
    """Quantity differences even as tiny as 0.0001 must be flagged as MISMATCH."""
    res_exact = compare_quantity(Decimal("100.000"), Decimal("100.000"))
    assert res_exact.is_exact_match is True
    assert res_exact.diff == Decimal(0)
    assert res_exact.numeric_policy == NumericPolicy.QTY_EXACT
    assert res_exact.rule_status == RuleStatus.CONFIRMED

    # 99.999 vs 100.000 MUST NOT be rounded to match
    res_diff = compare_quantity(Decimal("99.999"), Decimal("100.000"))
    assert res_diff.is_exact_match is False
    assert res_diff.diff == Decimal("-0.001")


def test_financial_comparison_applies_provisional_2dp_half_up_rounding():
    """Computed money products are rounded half-up to 2 dp before exact match."""
    # 3 * 33.333 = 99.999 -> rounds to 100.00
    res = compare_amount(stated=Decimal("100.00"), computed=Decimal("99.999"))
    assert res.is_match is True
    assert res.rounded_computed_amount == Decimal("100.00")
    assert res.unrounded_computed_amount == Decimal("99.999")
    assert res.rule_status == RuleStatus.PROVISIONAL
    assert res.numeric_policy == NumericPolicy.MONEY_ROUND_2DP_HALF_UP

    # 100.00 vs 100.02 (discrepancy exceeds 2-dp rounding) -> MISMATCH
    res_mismatch = compare_amount(stated=Decimal("100.00"), computed=Decimal("100.02"))
    assert res_mismatch.is_match is False


# =========================================================================
# 2. Units & Normalization
# =========================================================================

def test_unit_normalization_and_bare_ton():
    assert normalize_unit("cum") == "m3"
    assert normalize_unit("M³") == "m3"
    assert normalize_unit("MT") == "t"
    assert normalize_unit("tonne") == "t"
    # Bare ton is ambiguous/untrusted -> None
    assert normalize_unit("ton") is None


def test_unit_conversions_same_and_cross_dimension():
    # Same canonical
    res_same = resolve_unit_conversion("cum", "m3")
    assert res_same.is_compatible is True
    assert res_same.factor == Decimal(1)

    # Same dimension (t <-> kg)
    res_dim = resolve_unit_conversion("t", "kg")
    assert res_dim.is_compatible is True
    assert res_dim.factor == Decimal(1000)

    # Cross dimension without confirmed rule -> Incompatible
    res_incomp = resolve_unit_conversion("bag", "t", material_code="CEM-OPC")
    assert res_incomp.is_compatible is False
    assert "requires a confirmed material-specific conversion rule" in res_incomp.error_message

    # Cross dimension with confirmed rule (e.g. 1 bag = 0.05 t)
    conversions = {("CEM-OPC", "bag", "t"): Decimal("0.05")}
    res_comp = resolve_unit_conversion("bag", "t", material_code="CEM-OPC", material_conversions=conversions)
    assert res_comp.is_compatible is True
    assert res_comp.factor == Decimal("0.05")


# =========================================================================
# 3. Quantity Matching Scenarios (Exact, Multiple DNs, Mismatches)
# =========================================================================

def test_scenario_clean_exact_match_across_three_delivery_notes():
    """Invoiced 18.0 m3 concrete matches 3 DNs (6.0 + 6.0 + 6.0 = 18.0 m3)."""
    inv_line = InvoiceLineSnapshot(
        line_id="inv-l1",
        document_id="doc-inv",
        invoice_number="INV-101",
        line_no=1,
        material_code="CONC-C30",
        description="Ready-Mix Concrete C30/20",
        invoiced_qty=make_trusted_val(Decimal("18.0")),
        unit="m3",
        unit_price=make_trusted_val(Decimal("250.00")),
        line_amount=make_trusted_val(Decimal("4500.00")),
    )

    dn1 = DNLineSnapshot("dn-l1", "doc-dn1", "DN-1001", 1, "CONC-C30", "Ready-Mix Concrete C30", make_trusted_val(Decimal("6.0")), unit="m3")
    dn2 = DNLineSnapshot("dn-l2", "doc-dn2", "DN-1002", 1, "CONC-C30", "Ready-Mix Concrete C30", make_trusted_val(Decimal("6.0")), unit="m3")
    dn3 = DNLineSnapshot("dn-l3", "doc-dn3", "DN-1003", 1, "CONC-C30", "Ready-Mix Concrete C30", make_trusted_val(Decimal("6.0")), unit="m3")

    snap = make_base_snapshot(
        invoice_lines=[inv_line],
        dn_lines=[dn1, dn2, dn3],
        confirmed_links={"inv-l1": ["dn-l1", "dn-l2", "dn-l3"]},
        subtotal="4500.00",
        tax="225.00",
        grand_total="4725.00",
    )

    findings = verify_case(snap)
    qty_findings = [f for f in findings if f.category == FindingCategory.QTY_LINE and f.rule_code == "QTY_003"]
    assert len(qty_findings) == 1
    assert qty_findings[0].outcome == FindingOutcome.MATCH
    assert "matches supported delivery note accepted quantity exactly" in qty_findings[0].message
    assert len(qty_findings[0].sources) == 4  # 1 invoice + 3 DNs


def test_scenario_quantity_overbilling_mismatch():
    """Invoiced 20.0 m3, but 3 DNs deliver 18.0 m3 -> MISMATCH (+2.0 m3)."""
    inv_line = InvoiceLineSnapshot(
        line_id="inv-l1",
        document_id="doc-inv",
        invoice_number="INV-101",
        line_no=1,
        material_code="CONC-C30",
        description="Ready-Mix Concrete C30",
        invoiced_qty=make_trusted_val(Decimal("20.0")),
        unit="m3",
        unit_price=make_trusted_val(Decimal("250.00")),
        line_amount=make_trusted_val(Decimal("5000.00")),
    )

    dn1 = DNLineSnapshot("dn-l1", "doc-dn1", "DN-1001", 1, "CONC-C30", "C30", make_trusted_val(Decimal("6.0")), unit="m3")
    dn2 = DNLineSnapshot("dn-l2", "doc-dn2", "DN-1002", 1, "CONC-C30", "C30", make_trusted_val(Decimal("6.0")), unit="m3")
    dn3 = DNLineSnapshot("dn-l3", "doc-dn3", "DN-1003", 1, "CONC-C30", "C30", make_trusted_val(Decimal("6.0")), unit="m3")

    snap = make_base_snapshot(
        invoice_lines=[inv_line],
        dn_lines=[dn1, dn2, dn3],
        confirmed_links={"inv-l1": ["dn-l1", "dn-l2", "dn-l3"]},
    )

    findings = verify_case(snap)
    mismatches = [f for f in findings if f.rule_code == "QTY_004"]
    assert len(mismatches) == 1
    assert mismatches[0].outcome == FindingOutcome.MISMATCH
    assert mismatches[0].difference == "2.0"
    assert "differs from accepted delivered quantity" in mismatches[0].message


# =========================================================================
# 4. Accepted Delivery Quantity: Documented vs Undocumented Rejections (D2)
# =========================================================================

def test_documented_rejection_is_deducted():
    """DN delivered 10.0, rejected 2.0 with documented evidence -> Accepted = 8.0 m3."""
    inv_line = InvoiceLineSnapshot(
        line_id="inv-l1",
        document_id="doc-inv",
        invoice_number="INV-101",
        line_no=1,
        material_code="CONC-C30",
        description="Ready-Mix Concrete C30",
        invoiced_qty=make_trusted_val(Decimal("8.0")),
        unit="m3",
        unit_price=make_trusted_val(Decimal("250.00")),
        line_amount=make_trusted_val(Decimal("2000.00")),
    )

    dn = DNLineSnapshot(
        line_id="dn-l1",
        document_id="doc-dn1",
        dn_number="DN-1001",
        line_no=1,
        material_code="CONC-C30",
        description="C30",
        delivered_qty=make_trusted_val(Decimal("10.0")),
        rejected_qty=make_trusted_val(Decimal("2.0")),
        rejection_evidence_type="DN_SIGNED_REMARK",
        has_rejection_evidence=True,
        unit="m3",
    )

    snap = make_base_snapshot(
        invoice_lines=[inv_line],
        dn_lines=[dn],
        confirmed_links={"inv-l1": ["dn-l1"]},
    )

    findings = verify_case(snap)
    match_findings = [f for f in findings if f.rule_code == "QTY_003"]
    assert len(match_findings) == 1
    assert match_findings[0].outcome == FindingOutcome.MATCH


def test_undocumented_rejection_is_not_deducted_and_flags_uncertain():
    """DN has rejection noted without documented evidence -> No deduction made, flags UNCERTAIN."""
    inv_line = InvoiceLineSnapshot(
        line_id="inv-l1",
        document_id="doc-inv",
        invoice_number="INV-101",
        line_no=1,
        material_code="CONC-C30",
        description="Ready-Mix Concrete C30",
        invoiced_qty=make_trusted_val(Decimal("8.0")),
        unit="m3",
        unit_price=make_trusted_val(Decimal("250.00")),
        line_amount=make_trusted_val(Decimal("2000.00")),
    )

    dn = DNLineSnapshot(
        line_id="dn-l1",
        document_id="doc-dn1",
        dn_number="DN-1001",
        line_no=1,
        material_code="CONC-C30",
        description="C30",
        delivered_qty=make_trusted_val(Decimal("10.0")),
        rejected_qty=make_trusted_val(Decimal("2.0")),
        has_rejection_evidence=False,  # Evidence MISSING
        unit="m3",
    )

    snap = make_base_snapshot(
        invoice_lines=[inv_line],
        dn_lines=[dn],
        confirmed_links={"inv-l1": ["dn-l1"]},
    )

    findings = verify_case(snap)
    rej_warns = [f for f in findings if f.rule_code == "REJ_001"]
    assert len(rej_warns) == 1
    assert rej_warns[0].outcome == FindingOutcome.UNCERTAIN
    assert "lacks documented supporting evidence" in rej_warns[0].message

    # Comparison itself becomes UNCERTAIN
    qty_unc = [f for f in findings if f.rule_code == "QTY_002"]
    assert len(qty_unc) == 1
    assert qty_unc[0].outcome == FindingOutcome.UNCERTAIN


# =========================================================================
# 5. Delivery Note Reuse Detection (Decision D3 & Clarification C1)
# =========================================================================

def test_delivery_note_reuse_is_flagged_as_critical_mismatch():
    """DN-1001 already associated with another case -> MISMATCH (DN_REUSE)."""
    inv_line = InvoiceLineSnapshot(
        line_id="inv-l1",
        document_id="doc-inv",
        invoice_number="INV-101",
        line_no=1,
        material_code="CONC-C30",
        description="C30",
        invoiced_qty=make_trusted_val(Decimal("6.0")),
        unit="m3",
        unit_price=make_trusted_val(Decimal("250.00")),
        line_amount=make_trusted_val(Decimal("1500.00")),
    )
    dn = DNLineSnapshot("dn-l1", "doc-dn1", "DN-1001", 1, "CONC-C30", "C30", make_trusted_val(Decimal("6.0")), unit="m3")

    snap = make_base_snapshot(
        invoice_lines=[inv_line],
        dn_lines=[dn],
        confirmed_links={"inv-l1": ["dn-l1"]},
        cross_case_dn_index={"sup-1:DN1001": ["VC-2026-00031"]},
    )

    findings = verify_case(snap)
    reuse_findings = [f for f in findings if f.category == FindingCategory.DN_REUSE]
    assert len(reuse_findings) == 1
    assert reuse_findings[0].outcome == FindingOutcome.MISMATCH
    assert "VC-2026-00031" in reuse_findings[0].message
    assert reuse_findings[0].rule_code == "DN_REUSE_001"


# =========================================================================
# 6. Prototype Rule P2: Linking a DN Line to Multiple Invoice Lines
# =========================================================================

def test_dn_line_linked_twice_is_flagged_and_rejected():
    """Linking the same DN line to two invoice lines violates rule P2."""
    inv_l1 = InvoiceLineSnapshot("inv-1", "doc-inv", "INV-101", 1, "CONC", "C30", make_trusted_val(Decimal("3.0")), "m3", make_trusted_val(Decimal(100)), make_trusted_val(Decimal(300)))
    inv_l2 = InvoiceLineSnapshot("inv-2", "doc-inv", "INV-101", 2, "CONC", "C30", make_trusted_val(Decimal("3.0")), "m3", make_trusted_val(Decimal(100)), make_trusted_val(Decimal(300)))
    dn = DNLineSnapshot("dn-1", "doc-dn1", "DN-1001", 1, "CONC", "C30", make_trusted_val(Decimal("6.0")), unit="m3")

    snap = make_base_snapshot(
        invoice_lines=[inv_l1, inv_l2],
        dn_lines=[dn],
        confirmed_links={"inv-1": ["dn-1"], "inv-2": ["dn-1"]},  # Linked twice!
    )

    findings = verify_case(snap)
    p2_findings = [f for f in findings if f.rule_code == "LINK_002"]
    assert len(p2_findings) == 1
    assert p2_findings[0].outcome == FindingOutcome.MISMATCH
    assert "rule P2 forbids linking a single delivery note line to multiple invoice lines" in p2_findings[0].message


# =========================================================================
# 7. Currency, Gated VAT, and Charge Line Behavior
# =========================================================================

def test_non_aed_currency_is_flagged():
    snap = make_base_snapshot(currency="USD")
    findings = verify_case(snap)
    curr_findings = [f for f in findings if f.category == FindingCategory.CURRENCY]
    assert len(curr_findings) == 1
    assert curr_findings[0].outcome == FindingOutcome.MISMATCH
    assert "Invoice currency is 'USD'" in curr_findings[0].message


def test_automated_vat_is_always_not_checked():
    snap = make_base_snapshot()
    findings = verify_case(snap)
    vat_findings = [f for f in findings if f.category == FindingCategory.VAT]
    assert len(vat_findings) == 1
    assert vat_findings[0].outcome == FindingOutcome.NOT_CHECKED
    assert vat_findings[0].rule_code == "VAT_UAE_000"


def test_charge_lines_are_excluded_from_quantity_checks():
    inv_charge = InvoiceLineSnapshot(
        line_id="inv-chg",
        document_id="doc-inv",
        invoice_number="INV-101",
        line_no=2,
        material_code="PUMP",
        description="Concrete Pumping Service",
        invoiced_qty=make_trusted_val(Decimal("1.0")),
        unit="load",
        unit_price=make_trusted_val(Decimal("500.00")),
        line_amount=make_trusted_val(Decimal("500.00")),
        kind="CHARGE",
    )
    snap = make_base_snapshot(invoice_lines=[inv_charge])
    findings = verify_case(snap)
    charge_findings = [f for f in findings if f.rule_code == "QTY_CHARGE_001"]
    assert len(charge_findings) == 1
    assert charge_findings[0].outcome == FindingOutcome.NOT_APPLICABLE
