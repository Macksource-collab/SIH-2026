from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from .audit import audit
from .database import get_db
from .inspections import inspection_data, report_data
from .models import AuditLog, Inspection, InspectionImage, User
from .schemas import UserPatch
from .security import admin_user, user_data
from .status import system_status
from .services.ocr import OCRUnavailable, ocr_service

router = APIRouter(prefix="/admin", tags=["Administration"])


def record_read(db, user, action):
    audit(db, action, user.id)
    db.commit()


@router.get("/stats")
def stats(db=Depends(get_db), user=Depends(admin_user)):
    result = {"total_users": db.scalar(select(func.count()).select_from(User)),
              "active_inspectors": db.scalar(select(func.count()).select_from(User).where(User.role == "inspector", User.is_active.is_(True))),
              "total_inspections": db.scalar(select(func.count()).select_from(Inspection)),
              "total_uploaded_images": db.scalar(select(func.count()).select_from(InspectionImage)),
              "inspection_status_counts": dict(db.execute(select(Inspection.status, func.count()).group_by(Inspection.status)).all())}
    ranked = select(AnalysisRun.overall_status, func.row_number().over(partition_by=AnalysisRun.inspection_id, order_by=AnalysisRun.created_at.desc()).label("position")).subquery()
    counts = dict(db.execute(select(ranked.c.overall_status,func.count()).where(ranked.c.position==1).group_by(ranked.c.overall_status)).all())
    result.update(compliant_inspections=counts.get("COMPLIANT",0), non_compliant_inspections=counts.get("NON_COMPLIANT",0),
                  review_required=counts.get("REVIEW_REQUIRED",0),
                  ocr_processed_inspections=db.scalar(select(func.count(func.distinct(ImageProcessing.inspection_id))).where(ImageProcessing.status=="success")),
                  reports_generated=db.scalar(select(func.count()).select_from(Report).where(Report.status.in_(("ready", "superseded")))))
    record_read(db, user, "admin.stats.viewed")
    return result


@router.get("/users")
def users(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), db=Depends(get_db), user=Depends(admin_user)):
    result = [user_data(item) for item in db.scalars(select(User).order_by(User.created_at.desc()).limit(limit).offset(offset))]
    record_read(db, user, "admin.users.viewed")
    return result


@router.patch("/users/{user_id}")
def update_user(user_id: UUID, data: UserPatch, db=Depends(get_db), actor=Depends(admin_user)):
    user = db.get(User, str(user_id))
    if user is None:
        raise HTTPException(404, "User not found.")
    changes = data.model_dump(exclude_unset=True)
    if not changes or any(value is None for value in changes.values()):
        raise HTTPException(422, "Provide non-null user fields to update.")
    if user.id == actor.id and (changes.get("is_active") is False or changes.get("role", "admin") != "admin"):
        raise HTTPException(409, "You cannot deactivate or demote your own admin account.")
    previous_active = user.is_active
    for field, value in changes.items():
        setattr(user, field, value)
    if "role" in changes or "is_active" in changes:
        user.token_version += 1
    audit(db, "admin.user.updated", actor.id, "user", user.id, changes)
    if previous_active != user.is_active:
        audit(db, "user.activated" if user.is_active else "user.deactivated", actor.id, "user", user.id)
    db.commit()
    return user_data(user)


@router.get("/logs")
def logs(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), db=Depends(get_db), user=Depends(admin_user)):
    items = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)).all()
    actors = {item.user_id: db.get(User, item.user_id) for item in items if item.user_id}
    result = [{"id": item.id, "user_id": item.user_id,
               "actor_name": actors[item.user_id].name if item.user_id and actors.get(item.user_id) else "System / unknown",
               "actor_email": actors[item.user_id].email if item.user_id and actors.get(item.user_id) else None,
               "action": item.action,
               "resource_type": item.resource_type, "resource_id": item.resource_id,
               "metadata": item.details, "created_at": item.created_at}
              for item in items]
    record_read(db, user, "admin.logs.viewed")
    return result


@router.get("/inspections")
def inspections(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), db=Depends(get_db), user=Depends(admin_user)):
    result = [inspection_data(db, item) for item in db.scalars(select(Inspection).order_by(Inspection.created_at.desc()).limit(limit).offset(offset))]
    record_read(db, user, "admin.inspections.viewed")
    return result


@router.get("/reports")
def reports(limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0), db=Depends(get_db), user=Depends(admin_user)):
    result = [report_data(db, item) for item in db.scalars(
        select(Report).where(Report.status == "ready").order_by(Report.created_at.desc()).limit(limit).offset(offset))]
    record_read(db, user, "admin.reports.viewed")
    return result


@router.get("/status")
def status(db=Depends(get_db), user=Depends(admin_user)):
    result = system_status(db)
    if result["components"]["database"]["status"] == "ONLINE":
        record_read(db, user, "admin.status.viewed")
    return result


@router.post("/ocr/warmup")
def warmup_ocr(db=Depends(get_db), user=Depends(admin_user)):
    try:
        result = ocr_service.warmup()
        audit(db, "admin.ocr.warmed", user.id, "ocr_worker", None,
              {"initialization_duration_seconds": result.get("initialization_duration_seconds")})
        db.commit()
        return result
    except OCRUnavailable as error:
        audit(db, "admin.ocr.warmup.failed", user.id, "ocr_worker", None, {"state": "ERROR"})
        db.commit()
        raise HTTPException(503, str(error)) from None


from pydantic import BaseModel, ConfigDict, StrictBool
from .models import ComplianceRule, AnalysisRun, ImageProcessing, Report
from .services.compliance import rule_data
from .services.rule_import import RuleImportCommit, RuleImportRequest, commit_rules, preview_rules


class RuleToggle(BaseModel):
    model_config=ConfigDict(extra="forbid")
    is_active: StrictBool


@router.get("/rules")
def rules(db=Depends(get_db),user=Depends(admin_user)):
    result=[rule_data(rule) for rule in db.scalars(select(ComplianceRule).order_by(ComplianceRule.rule_code,ComplianceRule.version))]
    record_read(db,user,"admin.rules.viewed")
    return result


@router.post("/rules/import/validate")
def validate_rule_import(data:RuleImportRequest,db=Depends(get_db),user=Depends(admin_user)):
    return preview_rules(db,data.rules)


@router.post("/rules/import/commit",status_code=201)
def commit_rule_import(data:RuleImportCommit,db=Depends(get_db),user=Depends(admin_user)):
    try:
        created,preview=commit_rules(db,data)
        audit(db,"admin.rules.imported",user.id,"rule_import",preview["preview_digest"],
              {"created":len(created),"unchanged":len(data.rules)-len(created),
               "rule_codes":[rule.rule_code for rule in data.rules]})
        db.commit()
        return {**preview,"created":len(created),"unchanged":len(data.rules)-len(created)}
    except ValueError as error:
        db.rollback()
        raise HTTPException(409,str(error)) from None


@router.patch("/rules/{rule_id}")
def toggle_rule(rule_id:UUID,data:RuleToggle,db=Depends(get_db),user=Depends(admin_user)):
    rule=db.get(ComplianceRule,str(rule_id))
    if rule is None:
        raise HTTPException(404,"Rule not found.")
    rule.is_active=data.is_active
    audit(db,"admin.rule.toggled",user.id,"rule",rule.id,{"is_active":data.is_active})
    db.commit()
    return rule_data(rule)
