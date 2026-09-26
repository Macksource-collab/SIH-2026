"""Evidence-backed deterministic extraction; no inferred brand/product names."""
import re
from datetime import datetime

FIELD_NAMES = ["product_name", "brand_name", "manufacturer_or_packer", "manufacturer_address", "importer",
               "country_of_origin", "net_quantity", "mrp", "manufacturing_or_packing_date",
               "best_before_or_use_by", "consumer_care_phone", "consumer_care_email", "unit_sale_price"]


def date_value(value):
    token = re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{4})\b", value)
    if token:
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%m/%Y", "%m-%Y"):
            try:
                parsed = datetime.strptime(token[1], fmt)
                month_only = fmt in ("%m/%Y", "%m-%Y")
                return {"value": parsed.strftime("%Y-%m" if month_only else "%Y-%m-%d"),
                        "precision": "month" if month_only else "day", "display": token[1]}
            except ValueError:
                continue
    return {"value": value.strip(), "precision": "unparsed", "display": value.strip()}


def normalize_correction(field_name, raw):
    """Normalize a reviewer-entered value with the same deterministic field rules."""
    value = raw.strip()
    if field_name in {"mrp", "unit_sale_price"}:
        match = re.search(r"(?:Rs\.?|INR|₹)?\s*([0-9]+(?:[,.][0-9]+)*)", value, re.I)
        if not match:
            raise ValueError("Enter a numeric INR value, for example 120 or INR 120.")
        number = float(match[1].replace(",", ""))
        result = {"value": number, "currency": "INR", "display": f"INR {number:g}"}
        if field_name == "unit_sale_price":
            unit = re.search(r"(?:per|/)\s*(kg|g|l|ml|piece|pcs)\b", value, re.I)
            if unit:
                result.update(unit=unit[1].lower(), display=f"INR {number:g} per {unit[1].lower()}")
        return result
    if field_name == "net_quantity":
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(kg|kilograms?|g|grams?|ml|millilitres?|l|litres?|pcs|pieces?)\s*", value, re.I)
        if not match:
            raise ValueError("Enter a quantity and supported unit, for example 500 g.")
        number, unit = float(match[1]), match[2].lower()
        unit = {"grams":"g","gram":"g","kilograms":"kg","kilogram":"kg","litres":"l","litre":"l",
                "millilitres":"ml","pieces":"pcs","piece":"pcs"}.get(unit, unit)
        return {"value": number, "unit": unit, "display": f"{number:g} {unit}"}
    if field_name in {"manufacturing_or_packing_date", "best_before_or_use_by"}:
        result = date_value(value)
        if result["precision"] == "unparsed":
            raise ValueError("Enter a date as DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD, or MM/YYYY.")
        return result
    if field_name == "consumer_care_email":
        if not re.fullmatch(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", value, re.I):
            raise ValueError("Enter a valid consumer-care email address.")
        value = value.lower()
    elif field_name == "consumer_care_phone":
        value = re.sub(r"\D", "", value)
        if not 8 <= len(value) <= 15:
            raise ValueError("Enter a phone number containing 8 to 15 digits.")
    return {"value": value, "display": value}


def union_box(lines):
    points = [point for line in lines for point in line["bounding_box"]]
    if not points:
        return []
    x, y = zip(*points)
    return [[min(x), min(y)], [max(x), min(y)], [max(x), max(y)], [min(x), max(y)]]


def extract_fields(images):
    fields = []
    def add(name, value, sources, image, factor=0.97):
        raw = "\n".join(line["text"] for line in sources)[:4000]
        fields.append({"field_name": name, "raw_value": raw, "source_text": raw,
                       "normalized_value": value, "confidence": round(min(line["confidence"] for line in sources) * factor, 4),
                       "image_id": image["image_id"], "image_side": image["image_side"],
                       "bounding_box": union_box(sources), "extraction_method": "keyword-regex-context-v1"})
    for image in images:
        if image.get("status") != "success":
            continue
        lines = sorted(image["texts"], key=lambda row: (min(p[1] for p in row["bounding_box"]), min(p[0] for p in row["bounding_box"])))
        for index, line in enumerate(lines):
            text = line["text"].strip()
            sources = [line]
            # Label-only regions can take the immediately adjacent line on the same image.
            if re.search(r"[:：]\s*$", text) and index + 1 < len(lines):
                next_line = lines[index + 1]
                if min(p[1] for p in next_line["bounding_box"]) - max(p[1] for p in line["bounding_box"]) < 0.10:
                    sources.append(next_line)
                    text += " " + next_line["text"]
            simple = {
                "product_name": r"^(?:product(?: name)?|commodity)\s*[:：]\s*(.+)",
                "brand_name": r"^brand(?: name)?\s*[:：]\s*(.+)",
                "manufacturer_or_packer": r"(?:manufactured|packed|mfd|mfg)\.?\s*(?:&\s*packed\s*)?by\s*[:：]?\s*(.+)",
                "manufacturer_address": r"^(?:manufacturer(?:'s)? address|address)\s*[:：]\s*(.+)",
                "importer": r"(?:imported by|importer)\s*[:：]?\s*(.+)",
                "country_of_origin": r"(?:country of origin|made in)\s*[:：]?\s*(.+)",
            }
            for name, pattern in simple.items():
                match = re.search(pattern, text, re.I)
                if match:
                    value = match[1].strip()
                    if name == "manufacturer_address" and not any(re.search(r"manufactur|pack|mfd|mfg", row["text"], re.I) for row in lines[max(0,index-2):index+1]):
                        continue
                    add(name, {"value": value, "display": value}, sources, image, 0.92 if name == "manufacturer_address" else 0.97)
            mrp = re.search(r"\b(?:MRP|M\.R\.P\.?|maximum retail price)\s*[:：]?\s*(?:Rs\.?|INR|₹)?\s*([0-9]+(?:[,.][0-9]+)*)", text, re.I)
            if mrp:
                try:
                    value = float(mrp[1].replace(",", ""))
                    add("mrp", {"value": value, "currency": "INR", "display": f"INR {value:g}"}, sources, image)
                except ValueError:
                    pass
            quantity = re.search(r"(?:net\s*(?:wt\.?|weight|quantity|qty\.?|vol(?:ume)?\.?)?)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(kg|kilograms?|g|grams?|ml|millilitres?|l|litres?|pcs|pieces?)\b", text, re.I)
            if quantity:
                value, unit = float(quantity[1]), quantity[2].lower()
                unit = {"grams":"g","gram":"g","kilograms":"kg","kilogram":"kg","litres":"l","litre":"l","millilitres":"ml","pieces":"pcs","piece":"pcs"}.get(unit,unit)
                add("net_quantity", {"value": value, "unit": unit, "display": f"{value:g} {unit}"}, sources, image)
            for name, pattern in [("manufacturing_or_packing_date", r"(?:mfg\.?\s*date|mfd\.?|manufactur(?:ing|ed)\s*(?:date|on)|pack(?:ing|ed)\s*(?:date|on))\s*[:：]?\s*(.+)"),
                                  ("best_before_or_use_by", r"(?:best before|use by|expiry(?: date)?|exp\.?\s*date)\s*[:：]?\s*(.+)")]:
                match = re.search(pattern, text, re.I)
                if match:
                    value = date_value(match[1])
                    add(name, value, sources, image, 0.95 if value["precision"] != "unparsed" else 0.55)
            context = text + " " + (lines[index-1]["text"] if index else "")
            if re.search(r"consumer|customer|care|helpline|toll.?free|email|e-mail", context, re.I):
                email = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, re.I)
                if email:
                    add("consumer_care_email", {"value": email[0].lower(), "display": email[0].lower()}, sources, image)
                if re.search(r"care|phone|helpline|toll.?free", context, re.I):
                    phone = re.search(r"(?<!\d)(\+?\d[\d ()-]{7,18}\d)(?!\d)", text)
                    if phone:
                        digits = re.sub(r"\D", "", phone[1])
                        if 8 <= len(digits) <= 15:
                            add("consumer_care_phone", {"value": digits, "display": digits}, sources, image, 0.94)
            unit_price = re.search(r"unit\s*(?:sale\s*)?price\s*[:：]?\s*(?:Rs\.?|INR|₹)?\s*(\d+(?:\.\d+)?)\s*(?:per|/)\s*(kg|g|l|ml|piece|pcs)\b", text, re.I)
            if unit_price:
                add("unit_sale_price", {"value": float(unit_price[1]), "currency": "INR", "unit": unit_price[2].lower(),
                                      "display": f"INR {unit_price[1]} per {unit_price[2]}"}, sources, image)
    return fields
