"""Validated, data-only compliance rule import. No stored value is ever executed."""
from datetime import date
import hashlib
import json
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from ..models import ComplianceRule

VALIDATORS = {"required", "regex", "numeric", "date", "comparison", "conditional_required"}
FIELDS = {"product_name", "brand_name", "manufacturer_or_packer", "manufacturer_address", "importer",
          "country_of_origin", "net_quantity", "mrp", "manufacturing_or_packing_date", "best_before_or_use_by",
          "consumer_care_phone", "consumer_care_email", "unit_sale_price"}
SIDES = {"front", "back", "left", "right", "top", "bottom"}
COMMON_CONFIG = {"min_confidence", "min_ocr_confidence", "absence_is_failure", "required_sides", "alternative_fields"}
SPECIFIC_CONFIG = {"required": set(), "regex": {"pattern_key"}, "numeric": {"min", "max"}, "date": set(),
                   "comparison": {"other_field", "operator"}, "conditional_required": {"when_field"}}


class RuleDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_code: str = Field(min_length=2, max_length=80, pattern=r"^[A-Z0-9][A-Z0-9._-]+$")
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=3, max_length=2000)
    product_category: str | None = Field(default=None, max_length=120)
    field_name: str
    validator_type: Literal["required", "regex", "numeric", "date", "comparison", "conditional_required"]
    validator_config: dict[str, Any]
    severity: Literal["info", "warning", "critical"]
    source_document: str = Field(min_length=3, max_length=500)
    source_reference: str | None = Field(default=None, max_length=200)
    effective_from: date
    effective_to: date | None = None
    version: int = Field(ge=1, le=10000)
    is_active: bool
    verification_status: Literal["DEMO", "PROVISIONAL", "VERIFIED"]

    @model_validator(mode="after")
    def validate_semantics(self):
        if self.field_name not in FIELDS:
            raise ValueError("field_name is not supported by the extraction pipeline")
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to cannot be earlier than effective_from")
        allowed = COMMON_CONFIG | SPECIFIC_CONFIG[self.validator_type]
        unknown = set(self.validator_config) - allowed
        if unknown:
            raise ValueError(f"unsupported validator_config keys: {', '.join(sorted(unknown))}")
        config = self.validator_config
        for key in ("min_confidence", "min_ocr_confidence"):
            if key in config and (not isinstance(config[key], (int, float)) or isinstance(config[key], bool) or not 0 <= config[key] <= 1):
                raise ValueError(f"{key} must be a number from 0 to 1")
        if "absence_is_failure" in config and not isinstance(config["absence_is_failure"], bool):
            raise ValueError("absence_is_failure must be true or false")
        if "required_sides" in config and (not isinstance(config["required_sides"], list) or
                not config["required_sides"] or not set(config["required_sides"]) <= SIDES):
            raise ValueError("required_sides must contain supported package sides")
        if "alternative_fields" in config and (not isinstance(config["alternative_fields"], list) or
                not set(config["alternative_fields"]) <= FIELDS):
            raise ValueError("alternative_fields contains an unsupported field")
        if self.validator_type == "regex" and config.get("pattern_key") not in {"email", "phone"}:
            raise ValueError("regex rules must use the email or phone pattern_key")
        if self.validator_type == "numeric":
            for key in ("min", "max"):
                if key in config and (not isinstance(config[key], (int, float)) or isinstance(config[key], bool)):
                    raise ValueError(f"numeric {key} must be a number")
            if "min" in config and "max" in config and config["min"] > config["max"]:
                raise ValueError("numeric min cannot exceed max")
        if self.validator_type == "comparison":
            if config.get("other_field") not in FIELDS or config.get("operator") not in {"gte", "lte", "eq"}:
                raise ValueError("comparison requires a supported other_field and gte, lte, or eq operator")
        if self.validator_type == "conditional_required" and config.get("when_field") not in FIELDS:
            raise ValueError("conditional_required requires a supported when_field")
        return self


class RuleImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rules: list[RuleDefinition] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_versions(self):
        keys = [(rule.rule_code, rule.version) for rule in self.rules]
        if len(keys) != len(set(keys)):
            raise ValueError("The import contains duplicate rule_code and version pairs")
        return self


class RuleImportCommit(RuleImportRequest):
    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    verified_review_acknowledged: bool = False


def normalized(rule):
    return rule.model_dump(mode="json")


def import_digest(rules):
    payload = [normalized(rule) for rule in rules]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def preview_rules(db, rules):
    rows = []
    for rule in rules:
        existing = db.scalar(select(ComplianceRule).where(
            ComplianceRule.rule_code == rule.rule_code, ComplianceRule.version == rule.version))
        if existing is None:
            action = "CREATE"
        else:
            current = {key: getattr(existing, key) for key in normalized(rule)}
            current["effective_from"] = current["effective_from"].isoformat()
            current["effective_to"] = current["effective_to"].isoformat() if current["effective_to"] else None
            action = "UNCHANGED" if current == normalized(rule) else "CONFLICT"
        rows.append({"rule_code": rule.rule_code, "version": rule.version,
                     "verification_status": rule.verification_status, "action": action})
    return {"valid": not any(row["action"] == "CONFLICT" for row in rows),
            "preview_digest": import_digest(rules), "rules": rows,
            "warning": "VERIFIED is never assigned automatically and requires completed external official/legal review."}


def commit_rules(db, request):
    preview = preview_rules(db, request.rules)
    if request.preview_digest != preview["preview_digest"]:
        raise ValueError("Import content changed after preview. Validate it again.")
    if not preview["valid"]:
        raise ValueError("A rule_code and version conflicts with an existing rule.")
    if any(rule.verification_status == "VERIFIED" for rule in request.rules) and not request.verified_review_acknowledged:
        raise ValueError("VERIFIED imports require explicit acknowledgement of completed external review.")
    created = []
    for rule, row in zip(request.rules, preview["rules"]):
        if row["action"] == "UNCHANGED":
            continue
        values = rule.model_dump()
        values["is_demo_or_provisional"] = rule.verification_status != "VERIFIED"
        model = ComplianceRule(**values)
        db.add(model)
        created.append(model)
    db.flush()
    return created, preview
