"""Authenticated intelligence endpoints; existing owner/admin checks remain authoritative."""
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from ..audit import audit
from ..config import settings
from ..database import get_db
from ..inspections import owned_inspection
from ..models import AnalysisRun, ExtractedField, InspectionImage, Report, User, now
from ..schemas import FieldCorrection
from ..security import current_user
from .pipeline import analyze, correct_and_reevaluate, derived_directory, inspection_lease, is_stale, latest_analysis, ocr_images
from .extraction import normalize_correction
from .reporting import generate_pdf

router=APIRouter(prefix="/inspections",tags=["Intelligence"])


@router.post("/{inspection_id}/ocr")
def run_ocr(inspection_id:UUID,force:bool=False,db=Depends(get_db),user=Depends(current_user)):
    inspection=owned_inspection(db,inspection_id,user)
    with inspection_lease(db,inspection.id):
        return ocr_images(db,inspection,user,force)


@router.post("/{inspection_id}/analyze")
def run_analysis(inspection_id:UUID,force:bool=False,db=Depends(get_db),user=Depends(current_user)):
    inspection=owned_inspection(db,inspection_id,user)
    previous=latest_analysis(db,inspection.id)
    if (not force and previous is not None and not is_stale(db,previous)
            and not previous.snapshot.get("ocr_summary",{}).get("failed_images",0)):
        report = db.scalar(select(Report).where(Report.analysis_id == previous.id, Report.status == "ready")
                           .order_by(Report.created_at.desc()))
        return {**previous.snapshot,"stale":False,"reused_analysis":True,
                "report_ready":bool(report and (settings.report_dir/report.stored_filename).is_file())}
    with inspection_lease(db,inspection.id):
        try:
            return analyze(db,inspection,user,force)
        except HTTPException:
            raise
        except Exception as error:
            db.rollback()
            audit(db,"analysis.failed",user.id,"inspection",inspection.id,{"error_type":type(error).__name__})
            db.commit()
            raise HTTPException(503,"Analysis could not be completed. Successfully processed sides are retained; please retry.") from None


@router.get("/{inspection_id}/result")
def result(inspection_id:UUID,db=Depends(get_db),user=Depends(current_user)):
    inspection=owned_inspection(db,inspection_id,user)
    run=latest_analysis(db,inspection.id)
    if not run:
        raise HTTPException(404,"No analysis yet. Run Analysis first.")
    report = db.scalar(select(Report).where(Report.analysis_id == run.id, Report.status == "ready").order_by(Report.created_at.desc()))
    return {**run.snapshot, "stale": is_stale(db, run),
            "report_ready": bool(report and (settings.report_dir / report.stored_filename).is_file())}


@router.get("/{inspection_id}/images/{image_id}/evidence")
def evidence_image(inspection_id:UUID,image_id:UUID,db=Depends(get_db),user=Depends(current_user)):
    inspection=owned_inspection(db,inspection_id,user)
    image=db.get(InspectionImage,str(image_id))
    if image is None or image.inspection_id!=inspection.id:
        raise HTTPException(404,"Image not found.")
    path=derived_directory(image)/"evidence.png"
    if not path.is_file():
        raise HTTPException(404,"No safely decoded evidence image is available. Run analysis first.")
    return FileResponse(path,media_type="image/png",headers={"Cache-Control":"private, no-store"})


@router.patch("/{inspection_id}/fields/{field_id}")
def correct_field(inspection_id:UUID,field_id:UUID,data:FieldCorrection,
                  db=Depends(get_db),user=Depends(current_user)):
    inspection=owned_inspection(db,inspection_id,user)
    with inspection_lease(db,inspection.id):
        run=latest_analysis(db,inspection.id)
        if run is None:
            raise HTTPException(404,"No analysis yet. Run Analysis first.")
        if is_stale(db,run):
            raise HTTPException(409,"Run a current analysis before correcting declarations.")
        field=db.get(ExtractedField,str(field_id))
        if field is None or field.inspection_id!=inspection.id or field.analysis_id!=run.id:
            raise HTTPException(404,"Extracted declaration not found in the current analysis.")
        try:
            corrected=normalize_correction(field.field_name,data.corrected_value)
        except ValueError as error:
            raise HTTPException(422,str(error)) from None
        return correct_and_reevaluate(db,inspection,run,field,corrected,user)


@router.post("/{inspection_id}/report",status_code=201)
def create_report(inspection_id:UUID,db=Depends(get_db),user=Depends(current_user)):
    inspection=owned_inspection(db,inspection_id,user)
    with inspection_lease(db,inspection.id):
        run=latest_analysis(db,inspection.id)
        if run is None or is_stale(db,run):
            raise HTTPException(409,"Run a current analysis before generating a report.")
        report=Report(id=str(uuid4()),inspection_id=inspection.id,analysis_id=run.id,created_by=user.id,status="pending")
        db.add(report); db.commit()
        path=None
        try:
            settings.report_dir.mkdir(parents=True,exist_ok=True)
            filename=report.id+".pdf"
            path=settings.report_dir/filename
            inspector=db.get(User,inspection.inspector_id)
            generate_pdf(path,run.snapshot,inspector.name,now().isoformat())
            report.status,report.stored_filename="ready",filename
            audit(db,"report.created",user.id,"inspection",inspection.id,{"report_id":report.id,"analysis_id":run.id})
            db.commit()
        except Exception as error:
            db.rollback()
            if path and path.exists():
                path.unlink(missing_ok=True)
            report=db.get(Report,report.id)
            report.status="failed"
            audit(db,"report.failed",user.id,"inspection",inspection.id,{"error_type":type(error).__name__})
            db.commit()
            raise HTTPException(503,"Report generation failed. Please try again.") from None
        return {"report_id":report.id,"analysis_id":run.id,"status":"ready","url":f"/inspections/{inspection.id}/report"}


@router.get("/{inspection_id}/report")
def get_report(inspection_id:UUID,download:bool=False,db=Depends(get_db),user=Depends(current_user)):
    inspection=owned_inspection(db,inspection_id,user)
    run=latest_analysis(db,inspection.id)
    if run is None or is_stale(db,run):
        raise HTTPException(409,"Run a current analysis and generate a report first.")
    report=db.scalar(select(Report).where(Report.inspection_id==inspection.id,Report.analysis_id==run.id,Report.status=="ready")
                     .order_by(Report.created_at.desc()))
    if report is None or not (settings.report_dir/report.stored_filename).is_file():
        raise HTTPException(404,"Report not found. Generate a report first.")
    audit(db,"report.viewed",user.id,"inspection",inspection.id,{"report_id":report.id})
    db.commit()
    return FileResponse(settings.report_dir/report.stored_filename,media_type="application/pdf",filename=f"PackSure-{inspection.id}.pdf",
                        content_disposition_type="attachment" if download else "inline",headers={"Cache-Control":"private, no-store"})


@router.get("/{inspection_id}/reports/{report_id}")
def get_specific_report(inspection_id:UUID,report_id:UUID,download:bool=False,
                        db=Depends(get_db),user=Depends(current_user)):
    inspection=owned_inspection(db,inspection_id,user)
    report=db.get(Report,str(report_id))
    if report is None or report.inspection_id != inspection.id or report.status != "ready":
        raise HTTPException(404,"Report not found.")
    path=settings.report_dir/report.stored_filename
    if not path.is_file():
        raise HTTPException(404,"Report file is unavailable.")
    audit(db,"report.viewed",user.id,"inspection",inspection.id,{"report_id":report.id})
    db.commit()
    return FileResponse(path,media_type="application/pdf",filename=f"PackSure-{inspection.id}.pdf",
                        content_disposition_type="attachment" if download else "inline",headers={"Cache-Control":"private, no-store"})
