"""Database-owned inspections; legacy JSON files are left untouched."""
import logging
from uuid import UUID, uuid4
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from .audit import audit
from .config import settings
from .database import get_db
from .models import AnalysisRun, Inspection, InspectionImage, Report, User, now
from .schemas import InspectionCreate
from .security import current_user

router = APIRouter(prefix="/inspections", tags=["Inspections"])
logger = logging.getLogger("packsure.uploads")
UPLOAD_DIR = settings.upload_dir
MAX_FILE_SIZE = settings.max_upload_size_mb * 1024 * 1024
ALLOWED_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
VALID_SIDES = {"front", "back", "left", "right", "top", "bottom"}


def image_data(image):
    return {"success": True, "message": "Product image uploaded successfully", "file_id": image.id,
            "filename": image.stored_filename, "inspection_id": image.inspection_id,
            "image_side": image.image_side, "content_type": image.content_type, "size": image.file_size}


def inspection_data(db, inspection):
    images = db.scalars(select(InspectionImage).where(InspectionImage.inspection_id == inspection.id)
                        .order_by(InspectionImage.created_at)).all()
    latest = db.scalar(select(AnalysisRun).where(AnalysisRun.inspection_id == inspection.id).order_by(AnalysisRun.created_at.desc()))
    inspector = db.get(User, inspection.inspector_id)
    report_count = db.scalar(select(func.count()).select_from(Report).where(
        Report.inspection_id == inspection.id, Report.status.in_(("ready", "superseded"))))
    return {"overall_status": latest.overall_status if latest else None, "inspection_id": inspection.id, "inspector_id": inspection.inspector_id,
            "inspector_name": inspector.name if inspector else "Unknown user", "inspector_email": inspector.email if inspector else None,
            "status": inspection.status, "reports_generated": report_count,
            "product_name": inspection.product_name, "product_category": inspection.product_category,
            "created_at": inspection.created_at, "updated_at": inspection.updated_at,
            "images": [image_data(image) for image in images]}


def owned_inspection(db, inspection_id, user):
    inspection = db.get(Inspection, str(inspection_id))
    if not inspection:
        raise HTTPException(404, "Inspection not found.")
    if inspection.inspector_id != user.id and user.role != "admin":
        raise HTTPException(403, "You cannot access another inspector's inspection.")
    return inspection


@router.post("", status_code=201)
def create_inspection(data: InspectionCreate | None = Body(default=None), db=Depends(get_db), user=Depends(current_user)):
    inspection = Inspection(inspector_id=user.id, **(data.model_dump() if data else {}))
    db.add(inspection)
    db.flush()
    audit(db, "inspection.created", user.id, "inspection", inspection.id)
    db.commit()
    return inspection_data(db, inspection)


@router.get("")
def list_inspections(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                     db=Depends(get_db), user=Depends(current_user)):
    query = select(Inspection).order_by(Inspection.created_at.desc()).limit(limit).offset(offset)
    if user.role != "admin":
        query = query.where(Inspection.inspector_id == user.id)
    return [inspection_data(db, item) for item in db.scalars(query)]


def store_upload(db, user, file, image_side, inspection_id=None):
    destination = None
    # Capture actor before rollback can expire ORM attributes.
    actor_id = user.id
    resource_id = str(inspection_id) if inspection_id else None
    try:
        inspection = owned_inspection(db, inspection_id, user) if inspection_id else None
        if image_side not in VALID_SIDES:
            raise HTTPException(422, "Choose a valid side: front, back, left, right, top, or bottom.")
        if file is None:
            raise HTTPException(422, "Choose a product image to upload.")
        if file.content_type not in ALLOWED_TYPES:
            raise HTTPException(415, "Only PNG, JPG, JPEG, and WEBP images are allowed.")
        contents = file.file.read(MAX_FILE_SIZE + 1)
        if not contents:
            raise HTTPException(400, "The image file is empty.")
        if len(contents) > MAX_FILE_SIZE:
            raise HTTPException(413, f"Each image must be {settings.max_upload_size_mb} MB or smaller.")
        if inspection is None:
            inspection = Inspection(inspector_id=actor_id)
            db.add(inspection)
            db.flush()
            audit(db, "inspection.created", actor_id, "inspection", inspection.id)
        acquired = db.execute(update(Inspection).where(Inspection.id == inspection.id, Inspection.processing_token.is_(None)).values(updated_at=now()))
        if acquired.rowcount != 1:
            raise HTTPException(409, "Wait for the current analysis to finish before uploading more images.")
        resource_id = inspection.id
        if db.scalar(select(InspectionImage.id).where(InspectionImage.inspection_id == inspection.id,
                                                     InspectionImage.image_side == image_side)):
            raise HTTPException(409, "This side already has an uploaded image. Choose another side.")
        file_id = str(uuid4())
        filename = file_id + ALLOWED_TYPES[file.content_type]
        directory = UPLOAD_DIR / inspection.id
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / filename
        with destination.open("xb") as output:
            output.write(contents)
        image = InspectionImage(id=file_id, inspection_id=inspection.id, image_side=image_side,
                                stored_filename=filename, content_type=file.content_type, file_size=len(contents))
        db.add(image)
        inspection.status = "images_uploaded"
        inspection.updated_at = now()
        audit(db, "image.uploaded", actor_id, "inspection", inspection.id,
              {"file_id": file_id, "image_side": image_side, "size": len(contents)})
        db.commit()
        logger.info("Image uploaded inspection=%s file=%s side=%s", inspection.id, file_id, image_side)
        return image_data(image)
    except Exception as error:
        db.rollback()
        if destination is not None:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                logger.error("Failed to clean up an unsuccessful upload")
        if isinstance(error, IntegrityError):
            error = HTTPException(409, "This side already has an uploaded image. Choose another side.")
        elif isinstance(error, OSError):
            error = HTTPException(503, "Image storage is unavailable. Please try again.")
        if isinstance(error, HTTPException):
            audit(db, "image.upload.rejected", actor_id, "inspection", resource_id,
                  {"status_code": error.status_code})
            db.commit()
            logger.warning("Upload rejected status=%s", error.status_code)
        raise error
    finally:
        if file is not None:
            file.file.close()


@router.post("/upload", status_code=201)
def upload_image(file: UploadFile | None = File(default=None), db=Depends(get_db), user=Depends(current_user)):
    """Compatible single-image upload: creates an owned inspection with a Front image."""
    return store_upload(db, user, file, "front")


@router.get("/summary")
def inspection_summary(db=Depends(get_db), user=Depends(current_user)):
    owned = select(Inspection.id)
    if user.role != "admin":
        owned = owned.where(Inspection.inspector_id == user.id)
    ranked = select(AnalysisRun.overall_status, func.row_number().over(
        partition_by=AnalysisRun.inspection_id, order_by=AnalysisRun.created_at.desc()).label("position")
    ).where(AnalysisRun.inspection_id.in_(owned)).subquery()
    counts = dict(db.execute(select(ranked.c.overall_status, func.count()).where(
        ranked.c.position == 1).group_by(ranked.c.overall_status)).all())
    recent = db.scalars(select(Inspection).where(Inspection.id.in_(owned)).order_by(
        Inspection.created_at.desc()).limit(5)).all()
    return {"total": db.scalar(select(func.count()).select_from(owned.subquery())),
            "compliant": counts.get("COMPLIANT", 0), "non_compliant": counts.get("NON_COMPLIANT", 0),
            "review": counts.get("REVIEW_REQUIRED", 0),
            "reports_generated": db.scalar(select(func.count()).select_from(Report).where(
                Report.inspection_id.in_(owned), Report.status.in_(("ready", "superseded")))),
            "recent": [inspection_data(db, row) for row in recent]}


def report_data(db, report):
    inspection = db.get(Inspection, report.inspection_id)
    creator = db.get(User, report.created_by) if report.created_by else None
    inspector = db.get(User, inspection.inspector_id) if inspection else None
    return {"report_id": report.id, "inspection_id": report.inspection_id, "analysis_id": report.analysis_id,
            "status": report.status, "created_at": report.created_at,
            "creator_id": report.created_by, "creator_name": creator.name if creator else "Unknown / legacy",
            "inspector_name": inspector.name if inspector else "Unknown user",
            "product_name": inspection.product_name if inspection else None}


@router.get("/reports")
def list_reports(limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0),
                 db=Depends(get_db), user=Depends(current_user)):
    query = select(Report).join(Inspection).where(Report.status == "ready").order_by(Report.created_at.desc())
    if user.role != "admin":
        query = query.where(Inspection.inspector_id == user.id)
    return [report_data(db, item) for item in db.scalars(query.limit(limit).offset(offset))]


@router.get("/{inspection_id}")
def get_inspection(inspection_id: UUID, db=Depends(get_db), user=Depends(current_user)):
    return inspection_data(db, owned_inspection(db, inspection_id, user))


@router.post("/{inspection_id}/images", status_code=201)
def upload_inspection_image(inspection_id: UUID, file: UploadFile | None = File(default=None),
                            image_side: str = Form(default=""), db=Depends(get_db), user=Depends(current_user)):
    return store_upload(db, user, file, image_side, inspection_id)
