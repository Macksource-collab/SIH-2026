"""Whitelisted validators only. Demo rules are never legal certification."""
from datetime import date
import hashlib
import json
import re

PATTERNS = {"email": r"[^\s@]+@[^\s@]+\.[^\s@]+", "phone": r"\d{8,15}"}


def rule_data(rule):
    keys = ("id", "rule_code", "title", "description", "product_category", "field_name", "validator_type", "validator_config",
            "severity", "source_document", "source_reference", "effective_from", "effective_to", "version", "is_active", "is_demo_or_provisional")
    result = {key: getattr(rule, key).isoformat() if isinstance(getattr(rule, key), date) else getattr(rule, key) for key in keys}
    result["verification_status"] = getattr(rule, "verification_status",
        "DEMO" if result["is_demo_or_provisional"] else "VERIFIED")
    return result


def rule_signature(rules):
    return hashlib.sha256(json.dumps([rule_data(rule) for rule in sorted(rules,key=lambda r:r.rule_code)], sort_keys=True).encode()).hexdigest()


def evaluate_rules(rules, fields, images, category=None, today=None):
    today = today or date.today()
    by_name = {}
    for field in fields:
        by_name.setdefault(field["field_name"], []).append(field)
    evaluations = []
    for rule in rules:
        if not rule.is_active or rule.effective_from > today or (rule.effective_to and rule.effective_to < today):
            continue
        if rule.product_category and category and rule.product_category != category:
            continue
        snapshot = rule_data(rule)
        cfg = rule.validator_config
        candidates = list(by_name.get(rule.field_name, []))
        # Consumer-care demo accepts either a supported phone or email declaration.
        for alternative in cfg.get("alternative_fields", []):
            candidates += by_name.get(alternative, [])
        selected = max(candidates, key=lambda item:(item.get("human_reviewed",False), item["confidence"]), default=None)
        status, reason = "REVIEW", "No reliable evidence detected. Manual inspection recommended."
        quality_good = bool(images) and all(img["status"] == "success" and img["quality"] == "GOOD" and
                         img["texts"] and min(row["confidence"] for row in img["texts"]) >= cfg.get("min_ocr_confidence",0.75) for img in images)
        human_selected = bool(selected and selected.get("human_reviewed"))
        ambiguity = (not human_selected and
                     len({json.dumps(item["normalized_value"],sort_keys=True) for item in by_name.get(rule.field_name,[]) if item["confidence"] >= 0.5}) > 1)
        unsupported = category not in (None,"general","demo_general") or (rule.product_category and category is None)
        if unsupported:
            reason = "Product category applicability has not been verified."
        elif not quality_good and not human_selected:
            reason = "Image quality, missing text, failed OCR, or low OCR confidence requires human review."
        elif ambiguity:
            reason = "Conflicting extracted values require human review."
        elif selected and selected["confidence"] < cfg.get("min_confidence",0.8) and not human_selected:
            reason = "Declaration confidence is below the configured review threshold."
        else:
            try:
                validator = rule.validator_type
                conditional = validator == "conditional_required"
                condition = by_name.get(cfg.get("when_field"),[]) if conditional else []
                if conditional and (not condition or max(item["confidence"] for item in condition) < 0.8):
                    reason = "Condition cannot be confidently established from OCR; verify applicability manually."
                elif not selected:
                    required_sides = set(cfg.get("required_sides", ["front","back"]))
                    if cfg.get("absence_is_failure",False) and required_sides <= {img["image_side"] for img in images}:
                        status, reason = "FAIL", "Declaration not detected across the configured sides with usable OCR; confirm by manual inspection."
                    else:
                        reason = "Declaration not confidently detected; absence alone is not proof of non-compliance."
                else:
                    value = selected["normalized_value"].get("value")
                    passed = None
                    if validator in ("required","conditional_required"):
                        passed = value is not None and str(value).strip() != ""
                    elif validator == "numeric":
                        number = float(value)
                        passed = cfg.get("min",float('-inf')) <= number <= cfg.get("max",float('inf'))
                    elif validator == "regex":
                        passed = bool(re.fullmatch(PATTERNS[cfg["pattern_key"]], str(value)[:256]))
                    elif validator == "date":
                        if selected["normalized_value"].get("precision") == "day":
                            date.fromisoformat(str(value))
                            passed = True
                    elif validator == "comparison":
                        other = by_name.get(cfg["other_field"],[])
                        if len(other) == 1 and other[0]["confidence"] >= 0.8:
                            left, right = float(value), float(other[0]["normalized_value"]["value"])
                            passed = {"gte": left >= right, "lte": left <= right, "eq": left == right}[cfg["operator"]]
                    if passed is not None:
                        status = "PASS" if passed else "FAIL"
                        prefix = "Human-corrected" if human_selected else "Detected"
                        reason = (f"{prefix} declaration meets the configured check." if passed else
                                  f"{prefix} declaration does not meet the configured check; human verification required.")
                    else:
                        reason = "Validator cannot resolve this value or comparison confidently."
            except (ValueError, TypeError, KeyError):
                reason = "Rule configuration or extracted value is unsupported; manual review required."
        evaluations.append({**snapshot, "rule_id": rule.id, "status": status, "reason": reason,
                            "evidence_field_id": selected.get("id") if selected else None})
    # Provisional rules can demonstrate PASS/FAIL but never certify a commodity.
    if not evaluations or any(e["verification_status"] != "VERIFIED" or e["status"] == "REVIEW" for e in evaluations):
        overall = "REVIEW_REQUIRED"
    else:
        overall = "NON_COMPLIANT" if any(e["status"] == "FAIL" for e in evaluations) else "COMPLIANT"
    return evaluations, overall
