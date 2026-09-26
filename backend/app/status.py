import tempfile
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from .config import settings
from .models import ComplianceRule
from .services.ocr import ocr_service


def component(status, detail, **values):
    return {"status": status, "detail": detail, **values}


def storage_status(path, label):
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, prefix=".health-", delete=True) as probe:
            probe.write(b"ok")
            probe.flush()
        return component("ONLINE", f"{label} is writable.")
    except OSError:
        return component("OFFLINE", f"{label} is not writable.")


def system_status(db):
    components = {"api": component("ONLINE", "FastAPI is accepting requests.")}
    try:
        db.execute(text("SELECT 1 FROM users LIMIT 1"))
        components["database"] = component("ONLINE", "Database query succeeded.")
    except SQLAlchemyError:
        db.rollback()
        components["database"] = component("OFFLINE", "Database query failed.")

    components["upload_storage"] = storage_status(settings.upload_dir, "Upload storage")
    components["report_storage"] = storage_status(settings.report_dir, "Report storage")
    components["ocr_worker"] = ocr_service.readiness()

    if components["database"]["status"] == "OFFLINE":
        components["rule_engine"] = component("OFFLINE", "Rule configuration cannot be read while the database is offline.")
    else:
        try:
            active = db.scalar(select(func.count()).select_from(ComplianceRule).where(ComplianceRule.is_active.is_(True))) or 0
            provisional = db.scalar(select(func.count()).select_from(ComplianceRule).where(
                ComplianceRule.is_active.is_(True), ComplianceRule.is_demo_or_provisional.is_(True))) or 0
            if active:
                components["rule_engine"] = component("ONLINE", "Deterministic rule engine has active structured rules.",
                                                       active_rules=active, provisional_rules=provisional)
            else:
                components["rule_engine"] = component("DEGRADED", "No active compliance rules are configured.",
                                                       active_rules=0, provisional_rules=0)
        except SQLAlchemyError:
            db.rollback()
            components["rule_engine"] = component("OFFLINE", "Rule configuration query failed.")

    statuses = [item["status"] for item in components.values()]
    overall = "OFFLINE" if any(value == "OFFLINE" for value in statuses) else "DEGRADED" if any(value == "DEGRADED" for value in statuses) else "ONLINE"
    return {"overall_status": overall, "components": components}
