"""
RateGuard AI — Top-10 Carrier Ultra-Stable Regex Fallback Parser (Phase 7.2)
Zero-cost, high-reliability fallback extraction engine for Top-10 US LTL carriers.

Supported Carriers:
1. ABF Freight (ArcBest)
2. XPO Logistics
3. Roadrunner Transportation
4. Estes Express Lines
5. Saia LTL Freight
6. TForce Freight (UPS Freight)
7. Old Dominion Freight Line (ODFL)
8. R+L Carriers
9. Yellow / YRC Freight
10. Southeastern Freight Lines (SEFL)
"""

import re
from typing import Any, Dict, List, Optional
from packages.schemas.models import RegexFallbackExtractionResult

# Top-10 Carrier Regex Compiled Rule Patterns
CARRIER_REGEX_PATTERNS = {
    "ABF Freight": {
        "pro": [r"042-\d{6,8}", r"PRO[#:\s]*([0-9\-]{7,12})", r"\b042\d{6}\b"],
        "invoice": [r"(?:INV-)?ABF-[0-9]{4,8}", r"INVOICE[#:\s]*([A-Z0-9\-]{5,15})"],
        "weight": [r"(\d{1,6})\s*(?:LBS|LB|WEIGHT)", r"TOTAL WEIGHT[#:\s]*(\d{1,6})"],
        "fsc": [r"FUEL\s*(?:SURCHARGE|FSC)[#:\s]*\$\s*([\d,]+\.\d{2})", r"FSC[#:\s]*\$\s*([\d,]+\.\d{2})"],
        "net_charge": [r"NET\s*(?:FREIGHT|CHARGE)[#:\s]*\$\s*([\d,]+\.\d{2})"],
        "total": [r"TOTAL[^\$\n]*\$\s*([\d,]+\.\d{2})", r"(?:AMOUNT|BALANCE)\s*DUE[^\$\n]*\$\s*([\d,]+\.\d{2})", r"\$\s*([\d,]+\.\d{2})\s*(?:TOTAL|DUE)"],
    },
    "XPO Logistics": {
        "pro": [r"065-\d{6,8}", r"PRO[#:\s]*([0-9\-]{7,12})", r"\b065\d{6}\b"],
        "invoice": [r"XPO-[0-9]{4,8}", r"INVOICE[#:\s]*([A-Z0-9\-]{5,15})"],

        "weight": [r"(\d{1,6})\s*(?:LBS|LB|WEIGHT)"],
        "fsc": [r"FUEL\s*SURCHARGE[#:\s]*\$\s*([\d,]+\.\d{2})"],
        "total": [r"TOTAL\s*DUE[#:\s]*\$\s*([\d,]+\.\d{2})", r"\$\s*([\d,]+\.\d{2})"],
    },
    "Roadrunner": {
        "pro": [r"RRTS-[0-9]{4,8}", r"PRO[#:\s]*([0-9]{7,10})"],
        "invoice": [r"RRTS-INV-[0-9]{4,8}", r"INV[#:\s]*(RRTS-[0-9]{4,8})"],
        "weight": [r"(\d{1,6})\s*(?:LBS|LB)"],
        "total": [r"TOTAL\s*AMOUNT[#:\s]*\$\s*([\d,]+\.\d{2})"],
    },
    "Estes Express": {
        "pro": [r"ESTES-[0-9]{6,10}", r"PRO[#:\s]*([0-9]{10})", r"\b\d{10}\b"],
        "invoice": [r"EST-[0-9]{6,8}"],
        "weight": [r"(\d{1,6})\s*(?:LBS|LB)"],
        "total": [r"TOTAL\s*CHARGES[#:\s]*\$\s*([\d,]+\.\d{2})"],
    },
    "Saia Freight": {
        "pro": [r"SAIA-[0-9]{6,10}", r"PRO[#:\s]*([0-9]{9,10})"],
        "invoice": [r"SAIA-INV-[0-9]{5,8}"],
        "weight": [r"(\d{1,6})\s*(?:LBS|LB)"],
        "total": [r"NET\s*AMOUNT[#:\s]*\$\s*([\d,]+\.\d{2})"],
    },
    "TForce Freight": {
        "pro": [r"TF-[0-9]{6,10}", r"PRO[#:\s]*([0-9]{9,10})"],
        "invoice": [r"TF-INV-[0-9]{5,8}"],
        "weight": [r"(\d{1,6})\s*(?:LBS|LB)"],
        "total": [r"TOTAL\s*DUE[#:\s]*\$\s*([\d,]+\.\d{2})"],
    },
    "Old Dominion": {
        "pro": [r"ODFL-[0-9]{6,10}", r"PRO[#:\s]*([0-9]{9,11})"],
        "invoice": [r"ODFL-INV-[0-9]{5,8}"],
        "weight": [r"(\d{1,6})\s*(?:LBS|LB)"],
        "total": [r"AMOUNT\s*DUE[#:\s]*\$\s*([\d,]+\.\d{2})"],
    },
    "R+L Carriers": {
        "pro": [r"RL-[0-9]{6,10}", r"PRO[#:\s]*([0-9]{9})"],
        "invoice": [r"RL-INV-[0-9]{5,8}"],
        "weight": [r"(\d{1,6})\s*(?:LBS|LB)"],
        "total": [r"TOTAL\s*DUE[#:\s]*\$\s*([\d,]+\.\d{2})"],
    },
    "Yellow / YRC": {
        "pro": [r"YRC-[0-9]{6,10}", r"PRO[#:\s]*([0-9]{9,10})"],
        "invoice": [r"YRC-INV-[0-9]{5,8}"],
        "weight": [r"(\d{1,6})\s*(?:LBS|LB)"],
        "total": [r"TOTAL\s*DUE[#:\s]*\$\s*([\d,]+\.\d{2})"],
    },
    "Southeastern Freight": {
        "pro": [r"SEFL-[0-9]{6,10}", r"PRO[#:\s]*([0-9]{9})"],
        "invoice": [r"SEFL-INV-[0-9]{5,8}"],
        "weight": [r"(\d{1,6})\s*(?:LBS|LB)"],
        "total": [r"TOTAL\s*DUE[#:\s]*\$\s*([\d,]+\.\d{2})"],
    },
}


class RegexFallbackParser:
    """Ultra-stable regex extraction engine for Top-10 US LTL carrier invoice formats."""

    @classmethod
    def parse_text(cls, raw_text: str, carrier_hint: str = "") -> RegexFallbackExtractionResult:
        """Extracts mandatory invoice fields from raw document text using carrier-tuned regex rules."""
        text_upper = raw_text.upper()
        matched_rules: List[str] = []

        # Identify carrier if not explicitly provided
        carrier = carrier_hint or "Unknown Carrier"
        if not carrier_hint or carrier_hint == "Unknown Carrier":
            if "ABF" in text_upper or "ARCBEST" in text_upper:
                carrier = "ABF Freight"
            elif "XPO" in text_upper:
                carrier = "XPO Logistics"
            elif "ROADRUNNER" in text_upper or "RRTS" in text_upper:
                carrier = "Roadrunner"
            elif "ESTES" in text_upper:
                carrier = "Estes Express"
            elif "SAIA" in text_upper:
                carrier = "Saia Freight"
            elif "TFORCE" in text_upper or "UPS FREIGHT" in text_upper:
                carrier = "TForce Freight"
            elif "OLD DOMINION" in text_upper or "ODFL" in text_upper:
                carrier = "Old Dominion"
            elif "R+L" in text_upper or "R & L" in text_upper:
                carrier = "R+L Carriers"
            elif "YRC" in text_upper or "YELLOW" in text_upper:
                carrier = "Yellow / YRC"
            elif "SOUTHEASTERN" in text_upper or "SEFL" in text_upper:
                carrier = "Southeastern Freight"

        patterns = CARRIER_REGEX_PATTERNS.get(carrier, CARRIER_REGEX_PATTERNS["ABF Freight"])

        # Extract PRO Number
        pro_number: Optional[str] = None
        for p in patterns.get("pro", []):
            m = re.search(p, raw_text, re.IGNORECASE)
            if m:
                pro_number = m.group(0) if m.lastindex is None else m.group(1)
                matched_rules.append(f"pro:{p}")
                break

        # Extract Invoice Number
        invoice_number: Optional[str] = None
        for p in patterns.get("invoice", []):
            m = re.search(p, raw_text, re.IGNORECASE)
            if m:
                invoice_number = m.group(0) if m.lastindex is None else m.group(1)
                matched_rules.append(f"invoice:{p}")
                break

        if not invoice_number and pro_number:
            invoice_number = f"INV-{pro_number}"

        # Extract Invoice Date
        date_match = re.search(r"(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})", raw_text)
        invoice_date = date_match.group(1) if date_match else None
        if invoice_date:
            matched_rules.append("date:standard")

        # Extract Total Weight
        weight_lbs: Optional[float] = None
        for p in patterns.get("weight", []):
            m = re.search(p, raw_text, re.IGNORECASE)
            if m:
                try:
                    weight_lbs = float(m.group(1).replace(",", ""))
                    matched_rules.append(f"weight:{p}")
                    break
                except ValueError:
                    pass

        # Extract FSC Amount
        fsc_cents: Optional[int] = None
        fsc_dollars: Optional[float] = None
        for p in patterns.get("fsc", []):
            m = re.search(p, raw_text, re.IGNORECASE)
            if m:
                try:
                    fsc_dollars = float(m.group(1).replace(",", ""))
                    fsc_cents = int(round(fsc_dollars * 100))
                    matched_rules.append(f"fsc:{p}")
                    break
                except ValueError:
                    pass

        # Extract Net Freight Charge
        net_cents: Optional[int] = None
        net_dollars: Optional[float] = None
        for p in patterns.get("net_charge", []):
            m = re.search(p, raw_text, re.IGNORECASE)
            if m:
                try:
                    net_dollars = float(m.group(1).replace(",", ""))
                    net_cents = int(round(net_dollars * 100))
                    matched_rules.append(f"net_charge:{p}")
                    break
                except ValueError:
                    pass

        # Extract Total Amount
        total_cents: Optional[int] = None
        total_dollars: Optional[float] = None
        for p in patterns.get("total", []):
            m = re.search(p, raw_text, re.IGNORECASE)
            if m:
                try:
                    total_dollars = float(m.group(1).replace(",", ""))
                    total_cents = int(round(total_dollars * 100))
                    matched_rules.append(f"total:{p}")
                    break
                except ValueError:
                    pass

        # Fallback total dollar extraction if not found by pattern
        if total_dollars is None:
            all_amounts = re.findall(r"\$\s*([\d,]+\.\d{2})", raw_text)
            if all_amounts:
                parsed_amts = [float(a.replace(",", "")) for a in all_amounts]
                total_dollars = max(parsed_amts)
                total_cents = int(round(total_dollars * 100))
                matched_rules.append("total:max_dollar_regex")

        confidence = 0.95 if (pro_number and total_dollars is not None) else 0.80

        return RegexFallbackExtractionResult(
            carrier=carrier,
            pro_number=pro_number,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            total_weight_lbs=weight_lbs,
            net_charge_cents=net_cents,
            net_charge_dollars=net_dollars,
            fuel_surcharge_cents=fsc_cents,
            fuel_surcharge_dollars=fsc_dollars,
            total_amount_cents=total_cents,
            total_amount_dollars=total_dollars,
            matched_rules=matched_rules,
            confidence_score=confidence,
            parser_used="regex_fallback",
        )
