"""Persistent OCR and analysis orchestration with per-inspection database leases."""
from contextlib import contextmanager
from datetime import timedelta, date
import hashlib
import logging
import time
from uuid import uuid4
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, or_, select, update
from ..config import settings
from ..models import AnalysisRun, ComplianceRule, ExtractedField, ImageProcessing, Inspection, InspectionImage, OCRResult, Report, RuleEvaluation, now
from ..audit import audit
from ..inspections import inspection_data
from .image_processing import ImageError, PIPELINE_VERSION, prepare_image
from .ocr import OCRUnavailable, ocr_service
from .extraction import extract_fields, FIELD_NAMES
from .compliance import evaluate_rules, rule_signature

logger = logging.getLogger("packsure.analysis")


def field_data(field):
    machine = field.machine_value or field.normalized_value
    return {"id":field.id,"field_name":field.field_name,"raw_value":field.raw_value,
            "machine_value":machine,"corrected_value":field.corrected_value,
            "normalized_value":field.corrected_value or machine,"human_reviewed":field.is_human_reviewed,
            "corrected_by":field.corrected_by,"corrected_at":field.corrected_at,
            "confidence":field.confidence,"image_id":field.image_id,"image_side":field.image_side,
            "bounding_box":field.bounding_box,"source_text":field.source_text,
            "extraction_method":field.extraction_method}


@contextmanager
def inspection_lease(db, inspection_id):
    token = str(uuid4())
    acquired = db.execute(update(Inspection).where(Inspection.id == inspection_id,
        or_(Inspection.processing_token.is_(None), Inspection.processing_started_at < now() - timedelta(minutes=45)))
        .values(processing_token=token, processing_started_at=now()))
    if acquired.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "This inspection is already being processed. Please wait.")
    db.commit()
    try:
        yield
    finally:
        db.rollback()
        db.execute(update(Inspection).where(Inspection.id == inspection_id, Inspection.processing_token == token)
                   .values(processing_token=None, processing_started_at=None))
        db.commit()


def derived_directory(image):
    return settings.upload_dir / image.inspection_id / ".derived" / image.id


def ocr_images(db, inspection, actor, force=False):
    images = db.scalars(select(InspectionImage).where(InspectionImage.inspection_id == inspection.id).order_by(InspectionImage.created_at)).all()
    if not images:
        raise HTTPException(422, "Upload at least one package image before processing.")
    start = time.monotonic()
    logger.info("OCR started inspection=%s image_count=%d", inspection.id, len(images))
    audit(db, "ocr.started", actor.id, "inspection", inspection.id, {"image_count":len(images)})
    db.commit()
    output = []
    for image in images:
        state = db.scalar(select(ImageProcessing).where(ImageProcessing.image_id == image.id))
        path = settings.upload_dir / image.inspection_id / image.stored_filename
        cached = False
        try:
            source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            cached = bool(not force and state and state.status == "success" and state.source_hash == source_hash and
                          state.pipeline_version == PIPELINE_VERSION and (derived_directory(image)/"evidence.png").is_file())
            if not cached:
                prepared = prepare_image(path, derived_directory(image))
                texts = ocr_service.recognize(prepared["ocr_path"], prepared["metrics"]["width"], prepared["metrics"]["height"])
                # Replacement is intentional and transactional, not appended on every rerun.
                db.execute(delete(OCRResult).where(OCRResult.image_id == image.id))
                db.add_all([OCRResult(inspection_id=inspection.id, image_id=image.id, **text) for text in texts])
                if state is None:
                    state = ImageProcessing(inspection_id=inspection.id, image_id=image.id)
                    db.add(state)
                state.status, state.quality = "success", prepared["quality"]
                state.metrics, state.source_hash = prepared["metrics"], source_hash
                state.error, state.pipeline_version, state.processed_at = None, PIPELINE_VERSION, now()
                db.commit()
        except (ImageError, OCRUnavailable, OSError) as error:
            db.rollback()
            state = db.scalar(select(ImageProcessing).where(ImageProcessing.image_id == image.id))
            if state is None:
                state = ImageProcessing(inspection_id=inspection.id, image_id=image.id)
                db.add(state)
            state.status, state.quality = "failed", "UNREADABLE"
            state.metrics, state.error = {}, str(error) if isinstance(error,(ImageError,OCRUnavailable)) else "Image file unavailable."
            state.pipeline_version, state.processed_at = PIPELINE_VERSION, now()
            audit(db, "ocr.image.failed", actor.id, "inspection", inspection.id, {"image_id":image.id,"error_type":type(error).__name__})
            db.commit()
            logger.warning("OCR image failed inspection=%s image=%s type=%s", inspection.id, image.id, type(error).__name__)
        texts = db.scalars(select(OCRResult).where(OCRResult.image_id == image.id).order_by(OCRResult.created_at)).all() if state.status == "success" else []
        output.append({"image_id":image.id,"image_side":image.image_side,"quality":state.quality,"status":state.status,
                       "metrics":state.metrics,"error":state.error,"cached":cached,
                       "texts":[{"text":row.text,"confidence":row.confidence,"bounding_box":row.bounding_box} for row in texts]})
    successful = sum(image["status"] == "success" for image in output)
    duration = round(time.monotonic()-start,2)
    audit(db,"ocr.completed",actor.id,"inspection",inspection.id,{"image_count":len(images),"successful":successful,"duration_seconds":duration})
    db.commit()
    logger.info("OCR completed inspection=%s successful=%d image_count=%d duration=%.2f",inspection.id,successful,len(images),duration)
    return {"inspection_id":inspection.id,"images":output,"successful_images":successful,
            "failed_images":len(images)-successful,"partial_success":0<successful<len(images),"duration_seconds":duration}


def processing_signature(db, inspection_id):
    states=db.scalars(select(ImageProcessing).where(ImageProcessing.inspection_id==inspection_id).order_by(ImageProcessing.image_id)).all()
    return [(row.image_id,row.status,row.processed_at.replace(tzinfo=None).isoformat()) for row in states]


def latest_analysis(db, inspection_id):
    return db.scalar(select(AnalysisRun).where(AnalysisRun.inspection_id==inspection_id).order_by(AnalysisRun.created_at.desc()))


def is_stale(db, run):
    ids = sorted(db.scalars(select(InspectionImage.id).where(InspectionImage.inspection_id==run.inspection_id)).all())
    rules = db.scalars(select(ComplianceRule)).all()
    return (ids != sorted(run.snapshot["image_ids"]) or rule_signature(rules) != run.snapshot["rule_signature"] or
            jsonable_encoder(processing_signature(db,run.inspection_id)) != run.snapshot["ocr_signature"] or
            run.snapshot["rule_date"] != date.today().isoformat())


def analyze(db, inspection, actor, force=False):
    analysis_started = time.monotonic()
    ocr = ocr_images(db,inspection,actor,force)
    run=AnalysisRun(inspection_id=inspection.id,overall_status="REVIEW_REQUIRED",snapshot={})
    db.add(run); db.flush()
    extracted=extract_fields(ocr["images"])
    fields=[]
    for field in extracted:
        model=ExtractedField(inspection_id=inspection.id,analysis_id=run.id,machine_value=field["normalized_value"],**field)
        db.add(model); db.flush()
        fields.append(field_data(model))
    rules=db.scalars(select(ComplianceRule)).all()
    evaluations, overall = evaluate_rules(rules,fields,ocr["images"],inspection.product_category)
    for evaluation in evaluations:
        db.add(RuleEvaluation(inspection_id=inspection.id,analysis_id=run.id,rule_id=evaluation["rule_id"],
                             status=evaluation["status"],reason=evaluation["reason"],field_name=evaluation["field_name"],
                             evidence_field_id=evaluation["evidence_field_id"],rule_snapshot=evaluation))
    availability_message = None
    if ocr["failed_images"]:
        availability_message = ("OCR could not read any package images. Existing saved inspections remain available; check OCR readiness or retry later."
                                if not ocr["successful_images"] else
                                "Some package images could not be read. Successful sides were retained; review failed sides and retry if needed.")
    snapshot={"analysis_id":run.id,"inspection":inspection_data(db,inspection),"overall_status":overall,
              "images":ocr["images"],"ocr_summary":{key:value for key,value in ocr.items() if key!="images"},
              "declarations":fields,"declaration_names":FIELD_NAMES,"rule_evaluations":evaluations,
              "is_demo_or_provisional":any(rule["is_demo_or_provisional"] for rule in evaluations),
              "notice":"DEMO / PROVISIONAL checks require official-source verification. This is not legal certification.",
              "image_ids":[image["image_id"] for image in ocr["images"]],"rule_signature":rule_signature(rules),
              "ocr_signature":processing_signature(db,inspection.id),"rule_date":date.today().isoformat(),
              "analysis_duration_seconds":round(time.monotonic()-analysis_started,2),
              "availability_message":availability_message,"created_at":now().isoformat()}
    run.overall_status=overall
    run.snapshot=jsonable_encoder(snapshot)
    audit(db,"analysis.completed",actor.id,"inspection",inspection.id,{"analysis_id":run.id,"overall_status":overall})
    db.commit()
    return {**run.snapshot,"stale":False,"reused_analysis":False}


def correct_and_reevaluate(db, inspection, run, field, corrected_value, actor):
    """Persist one correction and rerun rules from stored fields; OCR is untouched."""
    field.corrected_value = corrected_value
    field.normalized_value = corrected_value
    field.corrected_by = actor.id
    field.corrected_at = now()
    field.is_human_reviewed = True
    db.flush()
    models = db.scalars(select(ExtractedField).where(ExtractedField.analysis_id == run.id)
                        .order_by(ExtractedField.created_at, ExtractedField.id)).all()
    fields = [field_data(item) for item in models]
    rules = db.scalars(select(ComplianceRule)).all()
    evaluations, overall = evaluate_rules(rules, fields, run.snapshot["images"], inspection.product_category)
    db.execute(delete(RuleEvaluation).where(RuleEvaluation.analysis_id == run.id))
    for evaluation in evaluations:
        db.add(RuleEvaluation(inspection_id=inspection.id,analysis_id=run.id,rule_id=evaluation["rule_id"],
                              status=evaluation["status"],reason=evaluation["reason"],field_name=evaluation["field_name"],
                              evidence_field_id=evaluation["evidence_field_id"],rule_snapshot=evaluation))
    snapshot = dict(run.snapshot)
    snapshot.update(declarations=fields,rule_evaluations=evaluations,overall_status=overall,
                    revised_at=now().isoformat(),revision=int(snapshot.get("revision",0))+1)
    run.overall_status = overall
    run.snapshot = jsonable_encoder(snapshot)
    superseded = db.scalars(select(Report).where(Report.analysis_id == run.id, Report.status == "ready")).all()
    for report in superseded:
        report.status = "superseded"
    audit(db,"field.corrected",actor.id,"inspection",inspection.id,
          {"field_id":field.id,"field_name":field.field_name,"analysis_id":run.id,
           "revision":snapshot["revision"],"rules_reevaluated":len(evaluations)})
    db.commit()
    return {**run.snapshot,"stale":False,"report_ready":False}
