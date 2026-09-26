"""Portable SQLAlchemy types map to native PostgreSQL UUID and JSON."""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Date, Float, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, Uuid
from .database import Base


def now():
    return datetime.now(timezone.utc)


def uuid_string():
    return str(uuid4())


class User(Base):
    __tablename__ = "users"
    id = Column(Uuid(as_uuid=False), primary_key=True, default=uuid_string)
    name = Column(String(120), nullable=False)
    email = Column(String(254), nullable=False, unique=True)
    password_hash = Column(String(128), nullable=False)
    role = Column(String(20), nullable=False, default="inspector")
    is_active = Column(Boolean, nullable=False, default=True)
    token_version = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    __table_args__ = (CheckConstraint("role IN ('admin','inspector')", name="ck_user_role"),
                     Index("ix_users_role_active", "role", "is_active"))


class Inspection(Base):
    __tablename__ = "inspections"
    id = Column(Uuid(as_uuid=False), primary_key=True, default=uuid_string)
    inspector_id = Column(Uuid(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="draft", index=True)
    processing_token = Column(String(36))
    processing_started_at = Column(DateTime(timezone=True))
    product_name = Column(String(200))
    product_category = Column(String(120))
    created_at = Column(DateTime(timezone=True), nullable=False, default=now, index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=now, onupdate=now)
    __table_args__ = (CheckConstraint("status IN ('draft','images_uploaded')", name="ck_inspection_status"),)


class InspectionImage(Base):
    __tablename__ = "inspection_images"
    id = Column(Uuid(as_uuid=False), primary_key=True, default=uuid_string)
    inspection_id = Column(Uuid(as_uuid=False), ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False, index=True)
    image_side = Column(String(10), nullable=False)
    stored_filename = Column(String(50), nullable=False, unique=True)
    content_type = Column(String(30), nullable=False)
    file_size = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    __table_args__ = (
        UniqueConstraint("inspection_id", "image_side", name="uq_inspection_side"),
        CheckConstraint("image_side IN ('front','back','left','right','top','bottom')", name="ck_image_side"),
        CheckConstraint("file_size > 0", name="ck_image_size"),
        CheckConstraint("content_type IN ('image/png','image/jpeg','image/webp')", name="ck_image_type"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Uuid(as_uuid=False), primary_key=True, default=uuid_string)
    user_id = Column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action = Column(String(80), nullable=False, index=True)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(String(100), index=True)
    # 'metadata' is reserved by SQLAlchemy, so use a different Python attribute.
    details = Column("metadata", JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now, index=True)


class Report(Base):
    __tablename__ = "reports"
    id = Column(Uuid(as_uuid=False), primary_key=True, default=uuid_string)
    inspection_id = Column(Uuid(as_uuid=False), ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by = Column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    status = Column(String(20), nullable=False, default="pending")
    analysis_id = Column(Uuid(as_uuid=False), ForeignKey("analysis_runs.id"), index=True)
    stored_filename = Column(String(100))
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    __table_args__ = (CheckConstraint("status IN ('pending','ready','failed','superseded')", name="ck_report_status"),)


class ImageProcessing(Base):
    __tablename__ = "image_processing"
    id = Column(Uuid(as_uuid=False), primary_key=True, default=uuid_string)
    inspection_id = Column(Uuid(as_uuid=False), ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False, index=True)
    image_id = Column(Uuid(as_uuid=False), ForeignKey("inspection_images.id", ondelete="CASCADE"), nullable=False, unique=True)
    status = Column(String(20), nullable=False)
    quality = Column(String(20), nullable=False)
    metrics = Column(JSON, nullable=False, default=dict)
    error = Column(String(300))
    source_hash = Column(String(64))
    pipeline_version = Column(String(30), nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=False, default=now)
    __table_args__ = (CheckConstraint("status IN ('success','failed')", name="ck_processing_status"),
                     CheckConstraint("quality IN ('GOOD','LOW_QUALITY','UNREADABLE')", name="ck_processing_quality"))


class OCRResult(Base):
    __tablename__ = "ocr_results"
    id = Column(Uuid(as_uuid=False), primary_key=True, default=uuid_string)
    inspection_id = Column(Uuid(as_uuid=False), ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False, index=True)
    image_id = Column(Uuid(as_uuid=False), ForeignKey("inspection_images.id", ondelete="CASCADE"), nullable=False, index=True)
    text = Column(String(4000), nullable=False)
    confidence = Column(Float, nullable=False)
    bounding_box = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    __table_args__ = (CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_ocr_confidence"),)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id = Column(Uuid(as_uuid=False), primary_key=True, default=uuid_string)
    inspection_id = Column(Uuid(as_uuid=False), ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False, index=True)
    overall_status = Column(String(30), nullable=False, index=True)
    snapshot = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now, index=True)
    __table_args__ = (CheckConstraint("overall_status IN ('COMPLIANT','NON_COMPLIANT','REVIEW_REQUIRED')", name="ck_analysis_overall"),)


class ExtractedField(Base):
    __tablename__ = "extracted_fields"
    id = Column(Uuid(as_uuid=False), primary_key=True, default=uuid_string)
    inspection_id = Column(Uuid(as_uuid=False), ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False, index=True)
    analysis_id = Column(Uuid(as_uuid=False), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    image_id = Column(Uuid(as_uuid=False), ForeignKey("inspection_images.id", ondelete="CASCADE"), nullable=False)
    image_side = Column(String(10), nullable=False)
    field_name = Column(String(60), nullable=False, index=True)
    raw_value = Column(String(4000), nullable=False)
    machine_value = Column(JSON, nullable=False)
    normalized_value = Column(JSON, nullable=False)
    corrected_value = Column(JSON)
    corrected_by = Column(Uuid(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), index=True)
    corrected_at = Column(DateTime(timezone=True))
    is_human_reviewed = Column(Boolean, nullable=False, default=False)
    confidence = Column(Float, nullable=False)
    bounding_box = Column(JSON, nullable=False)
    source_text = Column(String(4000), nullable=False)
    extraction_method = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)


class ComplianceRule(Base):
    __tablename__ = "compliance_rules"
    id = Column(Uuid(as_uuid=False), primary_key=True, default=uuid_string)
    rule_code = Column(String(80), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(String(2000), nullable=False)
    product_category = Column(String(120))
    field_name = Column(String(60), nullable=False)
    validator_type = Column(String(30), nullable=False)
    validator_config = Column(JSON, nullable=False)
    severity = Column(String(20), nullable=False)
    source_document = Column(String(500), nullable=False)
    source_reference = Column(String(200))
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    version = Column(Integer, nullable=False, default=1)
    is_active = Column(Boolean, nullable=False, default=True)
    is_demo_or_provisional = Column(Boolean, nullable=False, default=True)
    verification_status = Column(String(20), nullable=False, default="DEMO", index=True)
    __table_args__ = (UniqueConstraint("rule_code", "version", name="uq_rule_version"),
                     CheckConstraint("validator_type IN ('required','regex','numeric','date','comparison','conditional_required')", name="ck_rule_validator"),
                     CheckConstraint("verification_status IN ('DEMO','PROVISIONAL','VERIFIED')", name="ck_rule_verification_status"),)


class RuleEvaluation(Base):
    __tablename__ = "rule_evaluations"
    id = Column(Uuid(as_uuid=False), primary_key=True, default=uuid_string)
    inspection_id = Column(Uuid(as_uuid=False), ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False, index=True)
    analysis_id = Column(Uuid(as_uuid=False), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_id = Column(Uuid(as_uuid=False), ForeignKey("compliance_rules.id"), nullable=False)
    status = Column(String(10), nullable=False)
    reason = Column(String(2000), nullable=False)
    field_name = Column(String(60), nullable=False)
    evidence_field_id = Column(Uuid(as_uuid=False), ForeignKey("extracted_fields.id", ondelete="SET NULL"))
    rule_snapshot = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=now)
    __table_args__ = (CheckConstraint("status IN ('PASS','FAIL','REVIEW')", name="ck_rule_evaluation_status"),)
