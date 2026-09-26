"""Idempotent seed of clearly provisional demonstration checks, never official law."""
from datetime import date
from sqlalchemy import select
from app.database import SessionLocal
from app.models import ComplianceRule

DEMO_RULES=[
    ("DEMO-MRP","MRP detected and positive","mrp","numeric",{"min":0.01}),
    ("DEMO-QUANTITY","Net quantity detected and positive","net_quantity","numeric",{"min":0.0001}),
    ("DEMO-MANUFACTURER","Manufacturer or packer detected","manufacturer_or_packer","required",{}),
    ("DEMO-CARE","Consumer-care declaration detected","consumer_care_phone","required",{"alternative_fields":["consumer_care_email"]}),
    ("DEMO-ORIGIN","Origin when an importer is detected","country_of_origin","conditional_required",{"when_field":"importer"}),
]


def seed_rules(db):
    added=0
    for code,title,field,validator,config in DEMO_RULES:
        if db.scalar(select(ComplianceRule).where(ComplianceRule.rule_code==code,ComplianceRule.version==1)):
            continue
        db.add(ComplianceRule(rule_code=code,title=title,description="DEMO / PROVISIONAL. Illustrates configured validation only. Official legal source and applicability must be verified.",
            field_name=field,validator_type=validator,validator_config={"min_confidence":0.8,"absence_is_failure":False,**config},
            severity="warning",source_document="PackSure demonstration specification - NOT official law",source_reference=None,
            effective_from=date(2026,1,1),version=1,is_active=True,is_demo_or_provisional=True,verification_status="DEMO"))
        added+=1
    db.commit()
    return added


if __name__=="__main__":
    with SessionLocal() as db:
        print(f"Created {seed_rules(db)} provisional demonstration rules.")
