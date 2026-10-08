"""Pure rule-based verification engine for construction invoices against delivery notes.

Strict Specifications (Revisions 2 & 3):
- Value trust rule: MATCH requires all participating inputs to be CONFIRMED/trusted.
  Unconfirmed -> UNCERTAIN. Missing -> MISSING_EVIDENCE.
- Exact quantity comparison: 0 tolerance. diff != 0 -> MISMATCH.
- Accepted delivery quantity = delivered - documented rejected/returned quantity.
  If rejection lacks documented evidence -> UNCERTAIN, no deduction.
- Delivery note reuse: flagged as MISMATCH (category DN_REUSE, severity CRITICAL).
  The finding is permanent in the audit trail.
- One invoice line per DN line (provisional rule P2). Linking a DN line twice -> rejected.
- Currency check: non-AED -> MISMATCH (CURRENCY).
- Automated VAT check -> NOT_CHECKED.
- No automatic approval or payment initiation.
"""

from __future__ import annotations

from decimal import Decimal

from app.domain.models import (
    CaseSnapshot,
    Finding,
    FindingCategory,
    FindingOutcome,
    NumericPolicy,
    ProvenanceRef,
    RuleStatus,
    Severity,
)
from app.domain.numeric import compare_amount, compare_quantity
from app.domain.units import resolve_unit_conversion


def normalize_dn_number(raw: str) -> str:
    """Normalize delivery note number for reuse lookup."""
    return "".join(c for c in raw if c.isalnum()).upper()


def verify_case(
    snapshot: CaseSnapshot,
    material_conversions: dict[tuple[str, str, str], Decimal] | None = None,
) -> list[Finding]:
    """Execute rule-based verification over a case snapshot. Pure function."""
    findings: list[Finding] = []

    # -------------------------------------------------------------
    # 1. COMPLETENESS & PRECONDITIONS
    # -------------------------------------------------------------
    if snapshot.invoice_number.is_absent:
        findings.append(
            Finding(
                category=FindingCategory.COMPLETENESS,
                rule_code="COMP_001",
                outcome=FindingOutcome.MISSING_EVIDENCE,
                severity=Severity.CRITICAL,
                message="Invoice document or invoice number is absent.",
                rule_status=RuleStatus.CONFIRMED,
            )
        )
        return findings

    if not snapshot.dn_lines:
        findings.append(
            Finding(
                category=FindingCategory.COMPLETENESS,
                rule_code="COMP_002",
                outcome=FindingOutcome.MISSING_EVIDENCE,
                severity=Severity.CRITICAL,
                message="No delivery notes uploaded. Quantity verification requires at least one delivery note.",
                rule_status=RuleStatus.CONFIRMED,
            )
        )

    # LPO Requirement Check
    if not snapshot.lpo_required:
        reason_desc = snapshot.lpo_reason_text or snapshot.lpo_reason_code or "No reason provided"
        findings.append(
            Finding(
                category=FindingCategory.LPO,
                rule_code="LPO_001",
                outcome=FindingOutcome.NOT_APPLICABLE,
                severity=Severity.INFO,
                message=f"LPO check not applicable for this invoice case (Reason: {reason_desc}).",
                details={"reason_code": snapshot.lpo_reason_code, "reason_text": snapshot.lpo_reason_text},
                rule_status=RuleStatus.CONFIRMED,
            )
        )
    else:
        if not snapshot.lpo_lines:
            reason_desc = snapshot.lpo_reason_text or snapshot.lpo_reason_code or "LPO pending"
            findings.append(
                Finding(
                    category=FindingCategory.LPO,
                    rule_code="LPO_002",
                    outcome=FindingOutcome.MISSING_EVIDENCE,
                    severity=Severity.CRITICAL,
                    message=f"LPO is marked as required, but no LPO document is attached (Reason: {reason_desc}).",
                    details={"reason_code": snapshot.lpo_reason_code, "reason_text": snapshot.lpo_reason_text},
                    rule_status=RuleStatus.CONFIRMED,
                )
            )
        else:
            # 3-Way Reconciliation Rules (M4B Phase 1)
            lpo_map = {l.line_id: l for l in snapshot.lpo_lines}

            # 1. Cumulative LPO Quantity Cap Check
            for lpo_line in snapshot.lpo_lines:
                ordered_qty = Decimal(str(lpo_line.ordered_qty.value)) if lpo_line.ordered_qty.value else Decimal(0)
                prev_invoiced = lpo_line.previously_invoiced_qty or Decimal(0)
                current_invoiced = Decimal(0)

                for inv_line in snapshot.invoice_lines:
                    if snapshot.lpo_line_links.get(inv_line.line_id) == lpo_line.line_id and inv_line.invoiced_qty.value:
                        try:
                            current_invoiced += Decimal(str(inv_line.invoiced_qty.value))
                        except Exception:
                            pass

                total_invoiced = prev_invoiced + current_invoiced
                if total_invoiced > ordered_qty:
                    diff = total_invoiced - ordered_qty
                    findings.append(
                        Finding(
                            category=FindingCategory.LPO,
                            rule_code="LPO_CAP_EXCEEDED",
                            outcome=FindingOutcome.MISMATCH,
                            severity=Severity.CRITICAL,
                            message=(
                                f"Cumulative LPO quantity cap exceeded for LPO Line {lpo_line.line_no}: "
                                f"ordered cap is {ordered_qty} {lpo_line.unit}, but total cumulative invoiced "
                                f"is {total_invoiced} {lpo_line.unit} (previous: {prev_invoiced}, current: {current_invoiced}, "
                                f"excess: {diff} {lpo_line.unit})."
                            ),
                            subject_type="LPO_LINE",
                            subject_id=lpo_line.line_id,
                            expected_value=str(ordered_qty),
                            actual_value=str(total_invoiced),
                            difference=str(diff),
                            unit=lpo_line.unit,
                            rule_status=RuleStatus.CONFIRMED,
                        )
                    )
                elif current_invoiced > 0:
                    findings.append(
                        Finding(
                            category=FindingCategory.LPO,
                            rule_code="LPO_CAP_OK",
                            outcome=FindingOutcome.MATCH,
                            severity=Severity.INFO,
                            message=(
                                f"LPO Line {lpo_line.line_no} within authorized quantity cap: "
                                f"{total_invoiced} / {ordered_qty} {lpo_line.unit}."
                            ),
                            subject_type="LPO_LINE",
                            subject_id=lpo_line.line_id,
                            expected_value=str(ordered_qty),
                            actual_value=str(total_invoiced),
                            unit=lpo_line.unit,
                            rule_status=RuleStatus.CONFIRMED,
                        )
                    )

            # 2. Contractual Unit Rate Check
            for inv_line in snapshot.invoice_lines:
                lpo_line_id = snapshot.lpo_line_links.get(inv_line.line_id)
                if lpo_line_id and lpo_line_id in lpo_map:
                    lpo_line = lpo_map[lpo_line_id]
                    if inv_line.unit_price.value and lpo_line.unit_price.value:
                        inv_rate = Decimal(str(inv_line.unit_price.value))
                        lpo_rate = Decimal(str(lpo_line.unit_price.value))
                        if inv_rate != lpo_rate:
                            findings.append(
                                Finding(
                                    category=FindingCategory.PRICE,
                                    rule_code="RATE_MISMATCH",
                                    outcome=FindingOutcome.MISMATCH,
                                    severity=Severity.CRITICAL,
                                    message=(
                                        f"Invoice Line {inv_line.line_no} unit rate mismatch: stated rate is {inv_rate} AED/{inv_line.unit}, "
                                        f"but contractual LPO rate is {lpo_rate} AED/{lpo_line.unit}."
                                    ),
                                    subject_type="INVOICE_LINE",
                                    subject_id=inv_line.line_id,
                                    expected_value=str(lpo_rate),
                                    actual_value=str(inv_rate),
                                    difference=str(inv_rate - lpo_rate),
                                    unit="AED",
                                    rule_status=RuleStatus.CONFIRMED,
                                )
                            )
                        else:
                            findings.append(
                                Finding(
                                    category=FindingCategory.PRICE,
                                    rule_code="RATE_MATCH",
                                    outcome=FindingOutcome.MATCH,
                                    severity=Severity.INFO,
                                    message=(
                                        f"Invoice Line {inv_line.line_no} unit rate matches contractual LPO rate ({inv_rate} AED/{inv_line.unit})."
                                    ),
                                    subject_type="INVOICE_LINE",
                                    subject_id=inv_line.line_id,
                                    expected_value=str(lpo_rate),
                                    actual_value=str(inv_rate),
                                    unit="AED",
                                    rule_status=RuleStatus.CONFIRMED,
                                )
                            )

    # -------------------------------------------------------------
    # 2. CURRENCY & PARTY CHECKS
    # -------------------------------------------------------------
    curr_val = str(snapshot.invoice_currency.value or "").strip().upper()
    if curr_val != "AED":
        findings.append(
            Finding(
                category=FindingCategory.CURRENCY,
                rule_code="CURR_001",
                outcome=FindingOutcome.MISMATCH,
                severity=Severity.CRITICAL,
                message=f"Invoice currency is '{curr_val}'. The system is configured for UAE (AED) only. No foreign exchange conversions allowed.",
                expected_value="AED",
                actual_value=curr_val,
                rule_status=RuleStatus.CONFIRMED,
            )
        )

    # -------------------------------------------------------------
    # 3. DELIVERY NOTE REUSE CHECKS (Permanent audit finding)
    # -------------------------------------------------------------
    # Look up by normalized DN number and by file SHA-256
    dn_map = {dn.line_id: dn for dn in snapshot.dn_lines}
    seen_dn_numbers: set[str] = set()

    for dn in snapshot.dn_lines:
        norm_num = normalize_dn_number(dn.dn_number)
        if norm_num in seen_dn_numbers:
            continue
        seen_dn_numbers.add(norm_num)

        # Check by supplier TRN + DN number in other cases
        supplier_key = f"{snapshot.supplier_id}:{norm_num}"
        other_cases = snapshot.cross_case_dn_index.get(supplier_key, [])
        file_sha = snapshot.dn_file_hashes.get(dn.document_id)
        other_sha_cases = snapshot.cross_case_sha_index.get(file_sha, []) if file_sha else []

        conflicts = list(set(other_cases + other_sha_cases))
        if conflicts:
            findings.append(
                Finding(
                    category=FindingCategory.DN_REUSE,
                    rule_code="DN_REUSE_001",
                    outcome=FindingOutcome.MISMATCH,
                    severity=Severity.CRITICAL,
                    message=(
                        f"Delivery note '{dn.dn_number}' is already associated with other case(s): "
                        f"{', '.join(conflicts)}. One invoice per delivery note rule violated."
                    ),
                    subject_type="DELIVERY_NOTE",
                    subject_id=dn.document_id,
                    sources=[
                        ProvenanceRef(
                            document_id=dn.document_id,
                            label=f"Delivery Note {dn.dn_number}",
                            value=dn.dn_number,
                        )
                    ],
                    details={"conflicting_cases": conflicts, "dn_number": dn.dn_number},
                    rule_status=RuleStatus.CONFIRMED,
                )
            )

    # -------------------------------------------------------------
    # 4. LINE-BY-LINE QUANTITY RECONCILIATION
    # -------------------------------------------------------------
    # Track which DN lines have been linked to ensure no DN line is linked to multiple invoice lines (P2)
    linked_dn_line_counts: dict[str, int] = {}
    for dn_line_ids in snapshot.confirmed_links.values():
        for dn_lid in dn_line_ids:
            linked_dn_line_counts[dn_lid] = linked_dn_line_counts.get(dn_lid, 0) + 1

    for dn_lid, count in linked_dn_line_counts.items():
        if count > 1:
            dn_item = dn_map.get(dn_lid)
            dn_desc = f"DN Line {dn_item.line_no} ({dn_item.dn_number})" if dn_item else dn_lid
            findings.append(
                Finding(
                    category=FindingCategory.REFERENCE,
                    rule_code="LINK_002",
                    outcome=FindingOutcome.MISMATCH,
                    severity=Severity.CRITICAL,
                    message=(
                        f"{dn_desc} is linked to {count} different invoice lines. "
                        "Prototype rule P2 forbids linking a single delivery note line to multiple invoice lines."
                    ),
                    subject_type="DN_LINE",
                    subject_id=dn_lid,
                    rule_status=RuleStatus.PROVISIONAL,
                )
            )

    # Reconcile each invoice line
    for inv_line in snapshot.invoice_lines:
        if inv_line.kind == "CHARGE":
            findings.append(
                Finding(
                    category=FindingCategory.QTY_LINE,
                    rule_code="QTY_CHARGE_001",
                    outcome=FindingOutcome.NOT_APPLICABLE,
                    severity=Severity.INFO,
                    message=f"Line {inv_line.line_no} ('{inv_line.description}') is classified as a CHARGE line. Excluded from quantity verification.",
                    subject_type="INVOICE_LINE",
                    subject_id=inv_line.line_id,
                    rule_status=RuleStatus.CONFIRMED,
                )
            )
            continue

        linked_dn_ids = snapshot.confirmed_links.get(inv_line.line_id, [])
        if not linked_dn_ids:
            findings.append(
                Finding(
                    category=FindingCategory.QTY_LINE,
                    rule_code="QTY_001",
                    outcome=FindingOutcome.MISSING_EVIDENCE,
                    severity=Severity.CRITICAL,
                    message=f"Invoice Line {inv_line.line_no} ('{inv_line.description}') has no confirmed delivery note links.",
                    subject_type="INVOICE_LINE",
                    subject_id=inv_line.line_id,
                    expected_value=str(inv_line.invoiced_qty.value or "0"),
                    actual_value="0",
                    unit=inv_line.unit,
                    rule_status=RuleStatus.CONFIRMED,
                )
            )
            continue

        # Check trust of invoiced quantity
        if not inv_line.invoiced_qty.is_trusted:
            findings.append(
                Finding(
                    category=FindingCategory.QTY_LINE,
                    rule_code="TRUST_001",
                    outcome=FindingOutcome.UNCERTAIN,
                    severity=Severity.WARNING,
                    message=f"Invoice Line {inv_line.line_no} quantity value has not been human-confirmed.",
                    subject_type="INVOICE_LINE",
                    subject_id=inv_line.line_id,
                    actual_value=str(inv_line.invoiced_qty.value),
                    unit=inv_line.unit,
                    rule_status=RuleStatus.CONFIRMED,
                )
            )
            continue

        invoiced_qty_dec = Decimal(str(inv_line.invoiced_qty.value))
        total_delivered_converted = Decimal(0)
        line_sources: list[ProvenanceRef] = [
            ProvenanceRef(
                document_id=inv_line.document_id,
                label=f"Invoice Line {inv_line.line_no}",
                page=inv_line.invoiced_qty.page,
                value=f"{inv_line.invoiced_qty.value} {inv_line.unit}",
            )
        ]

        has_uncertain_dn = False
        unit_incompatible_found = False

        for dn_lid in linked_dn_ids:
            dn_line = dn_map.get(dn_lid)
            if not dn_line:
                continue

            # Check unit compatibility
            conv_res = resolve_unit_conversion(
                from_unit=dn_line.unit,
                to_unit=inv_line.unit,
                material_code=inv_line.material_code,
                material_conversions=material_conversions,
            )

            if not conv_res.is_compatible:
                unit_incompatible_found = True
                findings.append(
                    Finding(
                        category=FindingCategory.UNIT,
                        rule_code="UNIT_001",
                        outcome=FindingOutcome.UNIT_INCOMPATIBLE,
                        severity=Severity.CRITICAL,
                        message=(
                            f"Unit mismatch between Invoice Line {inv_line.line_no} ('{inv_line.unit}') and "
                            f"Delivery Note '{dn_line.dn_number}' Line {dn_line.line_no} ('{dn_line.unit}'): "
                            f"{conv_res.error_message}"
                        ),
                        subject_type="INVOICE_LINE",
                        subject_id=inv_line.line_id,
                        rule_status=RuleStatus.CONFIRMED,
                    )
                )
                break

            # Calculate accepted delivery quantity (D2)
            if not dn_line.delivered_qty.is_trusted:
                has_uncertain_dn = True
                findings.append(
                    Finding(
                        category=FindingCategory.QTY_LINE,
                        rule_code="TRUST_002",
                        outcome=FindingOutcome.UNCERTAIN,
                        severity=Severity.WARNING,
                        message=f"Delivered quantity on DN '{dn_line.dn_number}' Line {dn_line.line_no} is not human-confirmed.",
                        subject_type="DN_LINE",
                        subject_id=dn_line.line_id,
                        rule_status=RuleStatus.CONFIRMED,
                    )
                )
                continue

            deliv_dec = Decimal(str(dn_line.delivered_qty.value))
            rej_dec = Decimal(0)

            if dn_line.rejected_qty and not dn_line.rejected_qty.is_absent:
                if dn_line.has_rejection_evidence and dn_line.rejected_qty.is_trusted:
                    rej_dec = Decimal(str(dn_line.rejected_qty.value))
                    if rej_dec > deliv_dec or rej_dec < Decimal(0):
                        findings.append(
                            Finding(
                                category=FindingCategory.QTY_LINE,
                                rule_code="REJ_002",
                                outcome=FindingOutcome.MISMATCH,
                                severity=Severity.CRITICAL,
                                message=(
                                    f"Invalid rejection on DN '{dn_line.dn_number}' Line {dn_line.line_no}: "
                                    f"rejected qty ({rej_dec}) cannot exceed delivered qty ({deliv_dec})."
                                ),
                                subject_type="DN_LINE",
                                subject_id=dn_line.line_id,
                                rule_status=RuleStatus.CONFIRMED,
                            )
                        )
                        has_uncertain_dn = True
                        continue
                else:
                    # Documented rejection evidence missing or untrusted
                    findings.append(
                        Finding(
                            category=FindingCategory.QTY_LINE,
                            rule_code="REJ_001",
                            outcome=FindingOutcome.UNCERTAIN,
                            severity=Severity.WARNING,
                            message=(
                                f"Rejected quantity ({dn_line.rejected_qty.value}) noted on DN '{dn_line.dn_number}' "
                                "Line " f"{dn_line.line_no} lacks documented supporting evidence on the delivery note. "
                                "No deduction made; human verification required."
                            ),
                            subject_type="DN_LINE",
                            subject_id=dn_line.line_id,
                            rule_status=RuleStatus.PROVISIONAL,
                        )
                    )
                    has_uncertain_dn = True
                    rej_dec = Decimal(0)  # No deduction when evidence missing

            accepted_dec = deliv_dec - rej_dec
            total_delivered_converted += (accepted_dec * conv_res.factor)

            line_sources.append(
                ProvenanceRef(
                    document_id=dn_line.document_id,
                    label=f"DN {dn_line.dn_number} Line {dn_line.line_no}",
                    page=dn_line.delivered_qty.page,
                    value=f"Delivered: {deliv_dec}, Rej: {rej_dec}, Acc: {accepted_dec} {dn_line.unit}",
                )
            )

        if unit_incompatible_found:
            continue

        if has_uncertain_dn:
            # Output provisional result
            qty_res = compare_quantity(invoiced_qty_dec, total_delivered_converted)
            findings.append(
                Finding(
                    category=FindingCategory.QTY_LINE,
                    rule_code="QTY_002",
                    outcome=FindingOutcome.UNCERTAIN,
                    severity=Severity.WARNING,
                    message=f"Line {inv_line.line_no} comparison provisional: one or more delivery note values are unconfirmed or uncertain.",
                    subject_type="INVOICE_LINE",
                    subject_id=inv_line.line_id,
                    expected_value=str(invoiced_qty_dec),
                    actual_value=str(total_delivered_converted),
                    difference=str(qty_res.diff),
                    difference_pct=str(qty_res.diff_pct) if qty_res.diff_pct is not None else None,
                    unit=inv_line.unit,
                    sources=line_sources,
                    rule_status=RuleStatus.CONFIRMED,
                    numeric_policy=NumericPolicy.QTY_EXACT,
                )
            )
            continue

        # Exact Quantity Comparison (Decision D1)
        qty_res = compare_quantity(invoiced_qty_dec, total_delivered_converted)
        if qty_res.is_exact_match:
            findings.append(
                Finding(
                    category=FindingCategory.QTY_LINE,
                    rule_code="QTY_003",
                    outcome=FindingOutcome.MATCH,
                    severity=Severity.INFO,
                    message=f"Invoice Line {inv_line.line_no} quantity matches supported delivery note accepted quantity exactly ({invoiced_qty_dec} {inv_line.unit}).",
                    subject_type="INVOICE_LINE",
                    subject_id=inv_line.line_id,
                    expected_value=str(invoiced_qty_dec),
                    actual_value=str(total_delivered_converted),
                    difference="0",
                    unit=inv_line.unit,
                    sources=line_sources,
                    rule_status=RuleStatus.CONFIRMED,
                    numeric_policy=NumericPolicy.QTY_EXACT,
                )
            )
        else:
            diff_msg = (
                f"Invoiced quantity ({invoiced_qty_dec} {inv_line.unit}) differs from "
                f"accepted delivered quantity ({total_delivered_converted} {inv_line.unit}) "
                f"by {qty_res.diff:+f} {inv_line.unit}."
            )
            findings.append(
                Finding(
                    category=FindingCategory.QTY_LINE,
                    rule_code="QTY_004",
                    outcome=FindingOutcome.MISMATCH,
                    severity=Severity.CRITICAL,
                    message=diff_msg,
                    subject_type="INVOICE_LINE",
                    subject_id=inv_line.line_id,
                    expected_value=str(total_delivered_converted),
                    actual_value=str(invoiced_qty_dec),
                    difference=str(qty_res.diff),
                    difference_pct=str(qty_res.diff_pct) if qty_res.diff_pct is not None else None,
                    unit=inv_line.unit,
                    sources=line_sources,
                    rule_status=RuleStatus.CONFIRMED,
                    numeric_policy=NumericPolicy.QTY_EXACT,
                )
            )

    # -------------------------------------------------------------
    # 5. FINANCIAL ARITHMETIC CHECKS (Separate from Quantity)
    # -------------------------------------------------------------
    running_subtotal = Decimal(0)
    for inv_line in snapshot.invoice_lines:
        if (
            inv_line.invoiced_qty.is_trusted
            and inv_line.unit_price.is_trusted
            and inv_line.line_amount.is_trusted
        ):
            qty = Decimal(str(inv_line.invoiced_qty.value))
            price = Decimal(str(inv_line.unit_price.value))
            stated_amt = Decimal(str(inv_line.line_amount.value))
            running_subtotal += stated_amt

            comp_amt = qty * price
            amt_res = compare_amount(stated=stated_amt, computed=comp_amt)
            if not amt_res.is_match:
                findings.append(
                    Finding(
                        category=FindingCategory.ARITHMETIC,
                        rule_code="ARITH_001",
                        outcome=FindingOutcome.MISMATCH,
                        severity=Severity.CRITICAL,
                        message=(
                            f"Invoice Line {inv_line.line_no} arithmetic discrepancy: "
                            f"{qty} x {price} = computed {amt_res.rounded_computed_amount} AED "
                            f"(unrounded {amt_res.unrounded_computed_amount}), but stated is {stated_amt} AED."
                        ),
                        subject_type="INVOICE_LINE",
                        subject_id=inv_line.line_id,
                        expected_value=str(amt_res.rounded_computed_amount),
                        actual_value=str(stated_amt),
                        difference=str(amt_res.diff),
                        unit="AED",
                        rule_status=RuleStatus.PROVISIONAL,
                        numeric_policy=NumericPolicy.MONEY_ROUND_2DP_HALF_UP,
                    )
                )

    # Stated Subtotal check
    if snapshot.subtotal.is_trusted:
        stated_subtotal = Decimal(str(snapshot.subtotal.value))
        amt_sub_res = compare_amount(stated=stated_subtotal, computed=running_subtotal)
        if not amt_sub_res.is_match:
            findings.append(
                Finding(
                    category=FindingCategory.ARITHMETIC,
                    rule_code="ARITH_002",
                    outcome=FindingOutcome.MISMATCH,
                    severity=Severity.CRITICAL,
                    message=(
                        f"Invoice subtotal discrepancy: sum of line items is {running_subtotal} AED, "
                        f"but stated subtotal is {stated_subtotal} AED."
                    ),
                    expected_value=str(running_subtotal),
                    actual_value=str(stated_subtotal),
                    difference=str(amt_sub_res.diff),
                    unit="AED",
                    rule_status=RuleStatus.PROVISIONAL,
                    numeric_policy=NumericPolicy.MONEY_ROUND_2DP_HALF_UP,
                )
            )

    # Grand total arithmetic check: subtotal + stated VAT = grand total
    if (
        snapshot.subtotal.is_trusted
        and snapshot.tax_amount.is_trusted
        and snapshot.grand_total.is_trusted
    ):
        sub_d = Decimal(str(snapshot.subtotal.value))
        tax_d = Decimal(str(snapshot.tax_amount.value))
        grand_d = Decimal(str(snapshot.grand_total.value))
        expected_grand = sub_d + tax_d
        amt_gt_res = compare_amount(stated=grand_d, computed=expected_grand)
        if not amt_gt_res.is_match:
            findings.append(
                Finding(
                    category=FindingCategory.ARITHMETIC,
                    rule_code="ARITH_003",
                    outcome=FindingOutcome.MISMATCH,
                    severity=Severity.CRITICAL,
                    message=(
                        f"Grand total discrepancy: stated subtotal ({sub_d}) + stated VAT ({tax_d}) = "
                        f"{expected_grand} AED, but stated grand total is {grand_d} AED."
                    ),
                    expected_value=str(expected_grand),
                    actual_value=str(grand_d),
                    difference=str(amt_gt_res.diff),
                    unit="AED",
                    rule_status=RuleStatus.PROVISIONAL,
                    numeric_policy=NumericPolicy.MONEY_ROUND_2DP_HALF_UP,
                )
            )

    # -------------------------------------------------------------
    # 6. UAE VAT GATED CHECK (Decision D5 & Clarification C4)
    # -------------------------------------------------------------
    findings.append(
        Finding(
            category=FindingCategory.VAT,
            rule_code="VAT_UAE_000",
            outcome=FindingOutcome.NOT_CHECKED,
            severity=Severity.INFO,
            message="Automated VAT validation not performed: rules pending verification (Milestone M14). Manual VAT check may be documented by reviewer.",
            rule_status=RuleStatus.CONFIRMED,
        )
    )

    return findings
