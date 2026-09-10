# Instructor + Pydantic v2 Structured Extraction Spike (Tier-1 Dependency)

## 1. Overview
RateGuard AI requires 100% syntactically valid JSON extraction from messy freight PDFs. Standard LLM completions frequently hallucinate formatting, omit keys, or return invalid numerical types.

`instructor` (https://github.com/jxnl/instructor) wraps frontier model APIs (OpenAI, Anthropic, Gemini) with Pydantic v2 validation loops. If an extraction violates schema constraints, Instructor automatically passes the validation error back to the model for inline self-correction.

## 2. Core Invoice Extraction Architecture

```python
import instructor
from openai import OpenAI
from pydantic import BaseModel, Field
from typing import List, Optional

client = instructor.from_openai(OpenAI())

class LineItem(BaseModel):
    description: str = Field(description="Description of line charge")
    charge_code: Optional[str] = Field(None, description="Standard charge code if present (e.g. 400, FSC, LGT)")
    amount: float = Field(description="Dollar amount of line item")

class InvoiceExtraction(BaseModel):
    carrier: str = Field(description="Carrier name: ABF, XPO, Roadrunner, etc.")
    pro_number: str = Field(description="Carrier PRO tracking number")
    invoice_number: str = Field(description="Carrier invoice number")
    invoice_date: str = Field(description="Invoice date in YYYY-MM-DD format")
    origin_zip: str = Field(description="Origin 5-digit or 3-digit zip code")
    dest_zip: str = Field(description="Destination 5-digit or 3-digit zip code")
    billed_weight: float = Field(description="Total billed weight in pounds")
    billed_class: Optional[float] = Field(None, description="NMFC freight class, e.g. 50, 70, 92.5")
    fsc_amount: Optional[float] = Field(None, description="Billed fuel surcharge amount")
    fsc_pct: Optional[float] = Field(None, description="Billed fuel surcharge percentage")
    line_items: List[LineItem] = Field(default_factory=list)
    invoice_total: float = Field(description="Total billed invoice amount")

def extract_invoice_from_markdown(document_markdown: str) -> InvoiceExtraction:
    return client.chat.completions.create(
        model="gpt-4o-mini", # Cheap model first ($0.15/1M tokens)
        response_model=InvoiceExtraction,
        max_retries=2,
        messages=[
            {"role": "system", "content": "You are an expert LTL freight audit document parser. Extract structured fields accurately."},
            {"role": "user", "content": document_markdown}
        ]
    )
```

## 3. Cost-Control Model Ladder (PRD §9 Enforcer)
To strictly enforce our $200/mo operating budget:
1. **Tier 1 (Cheap Default):** Run extraction through `gpt-4o-mini` or `claude-3-5-haiku`.
2. **Deterministic Pre-Validation:** Run Python arithmetic check ($\sum \text{line items} == \text{total}$).
3. **Tier 2 (Escalation):** If confidence is low or fields fail validation after 2 retries, escalate the specific document to `gpt-4o` or `claude-3-5-sonnet`.
4. **Cache Guard:** Cache all extraction outputs keyed by `SHA256(raw_pdf_bytes + prompt_version)` so re-scans cost $0.
