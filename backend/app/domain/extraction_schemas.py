"""Pydantic schemas for structured document extraction via Google GenAI / Gemini."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class InvoiceLineExtractionItem(BaseModel):
    """Line item extracted from a supplier invoice."""

    line_no: int = Field(..., description="1-based item line number as printed on the invoice.")
    description: str = Field(..., description="Item material or service description.")
    invoiced_qty: str = Field(
        ...,
        description="Exact invoiced quantity as a string without decimal rounding (e.g. '36.00', '20.00').",
    )
    unit: str = Field(..., description="Measurement unit (e.g. 'm3', 'tonne', 't', 'kg', 'pcs').")
    unit_price: str = Field(
        ...,
        description="Exact agreed unit rate as a string (e.g. '240.00', '3100.00').",
    )
    line_amount: str = Field(
        ...,
        description="Exact total line amount in AED as a string (e.g. '8640.00', '62000.00').",
    )


class InvoiceExtractionResult(BaseModel):
    """Structured extraction result for a commercial construction supplier invoice."""

    document_type: Literal["INVOICE"] = "INVOICE"
    invoice_number: str | None = Field(default=None, description="Commercial invoice reference number.")
    supplier_name: str | None = Field(default=None, description="Full registered legal name of supplier.")
    supplier_trn: str | None = Field(
        default=None, description="UAE 15-digit Tax Registration Number (TRN) if present on invoice."
    )
    document_date: str | None = Field(default=None, description="Invoice date formatted as YYYY-MM-DD if available.")
    currency: str = Field(default="AED", description="Invoice currency. Must be AED for UAE construction.")
    lpo_number: str | None = Field(default=None, description="Referenced Local Purchase Order (LPO) number, if stated.")
    lines: list[InvoiceLineExtractionItem] = Field(
        default_factory=list, description="Extracted invoice material line items."
    )
    subtotal: str | None = Field(default=None, description="Subtotal amount before VAT.")
    tax_amount: str | None = Field(default=None, description="Stated UAE 5% VAT amount.")
    grand_total: str | None = Field(default=None, description="Stated invoice grand total.")
    notes: str | None = Field(default=None, description="Notable commercial remarks, payment terms, or delivery notes.")


class DeliveryNoteLineExtractionItem(BaseModel):
    """Line item extracted from a physical site delivery note / delivery ticket."""

    line_no: int = Field(..., description="1-based item line number.")
    description: str = Field(..., description="Material description as received at the construction gate.")
    delivered_qty: str = Field(
        ...,
        description="Exact physical quantity delivered as a string without rounding (e.g. '36.00', '15.00').",
    )
    unit: str = Field(..., description="Measurement unit (e.g. 'm3', 'tonne', 't', 'kg', 'pcs').")
    rejected_qty: str | None = Field(
        default=None,
        description=(
            "Explicitly recorded rejected or returned quantity on this ticket, if any. "
            "MUST be null/None if no rejection or return is written. NEVER default to 0."
        ),
    )
    rejection_reason: str | None = Field(
        default=None,
        description="Stated reason for site rejection (e.g. 'Slump test failure', 'Damaged bundles').",
    )
    ticket_number: str | None = Field(
        default=None, description="Batch, weighbridge, or site gate ticket identifier."
    )


class DeliveryNoteExtractionResult(BaseModel):
    """Structured extraction result for a site delivery note."""

    document_type: Literal["DELIVERY_NOTE"] = "DELIVERY_NOTE"
    dn_number: str | None = Field(default=None, description="Delivery note reference number printed on ticket.")
    supplier_name: str | None = Field(default=None, description="Supplier or transporter name.")
    document_date: str | None = Field(default=None, description="Delivery receipt date formatted as YYYY-MM-DD.")
    project_name: str | None = Field(default=None, description="Delivery site or project designation.")
    storekeeper_ticket_no: str | None = Field(default=None, description="Site gate entry ticket or pass number.")
    lines: list[DeliveryNoteLineExtractionItem] = Field(
        default_factory=list, description="Extracted delivered items."
    )
    notes: str | None = Field(default=None, description="Site receipt notes, driver signatures, or inspection remarks.")


class LpoLineExtractionItem(BaseModel):
    """Line item extracted from a Local Purchase Order agreement."""

    line_no: int = Field(..., description="1-based line number.")
    description: str = Field(..., description="Contractual material description.")
    ordered_qty: str = Field(..., description="Authorized ordered quantity cap.")
    unit: str = Field(..., description="Contractual measurement unit.")
    agreed_unit_price: str = Field(..., description="Contractual agreed unit rate in AED.")
    line_amount_cap: str | None = Field(default=None, description="Authorized line financial cap in AED.")


class LpoExtractionResult(BaseModel):
    """Structured extraction result for a Local Purchase Order (LPO)."""

    document_type: Literal["LPO"] = "LPO"
    lpo_number: str | None = Field(default=None, description="Official LPO contract number.")
    supplier_name: str | None = Field(default=None, description="Contracted vendor name.")
    document_date: str | None = Field(default=None, description="LPO issue date formatted as YYYY-MM-DD.")
    currency: str = Field(default="AED", description="Contract currency.")
    total_amount_cap: str | None = Field(default=None, description="Total order financial ceiling.")
    lines: list[LpoLineExtractionItem] = Field(default_factory=list, description="Authorized line items.")
    notes: str | None = Field(default=None, description="Contractual scope notes or delivery terms.")
