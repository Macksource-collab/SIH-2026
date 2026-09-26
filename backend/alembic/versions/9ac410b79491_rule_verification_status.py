"""add explicit legal-data verification status

Revision ID: 9ac410b79491
Revises: f47d2f58c601
"""
from alembic import op
import sqlalchemy as sa

revision = "9ac410b79491"
down_revision = "f47d2f58c601"
branch_labels = None
depends_on = None


def upgrade():
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        inspector = sa.inspect(op.get_bind())
        if "verification_status" not in {column["name"] for column in inspector.get_columns("compliance_rules")}:
            op.add_column("compliance_rules", sa.Column("verification_status", sa.String(20), nullable=False,
                                                         server_default="DEMO"))
        op.execute("UPDATE compliance_rules SET verification_status = CASE WHEN is_demo_or_provisional THEN 'DEMO' ELSE 'VERIFIED' END")
        if "ix_compliance_rules_verification_status" not in {index["name"] for index in inspector.get_indexes("compliance_rules")}:
            op.create_index("ix_compliance_rules_verification_status", "compliance_rules", ["verification_status"], unique=False)
    else:
        op.add_column("compliance_rules", sa.Column("verification_status", sa.String(20), nullable=True))
        op.execute("UPDATE compliance_rules SET verification_status = CASE WHEN is_demo_or_provisional THEN 'DEMO' ELSE 'VERIFIED' END")
        op.alter_column("compliance_rules", "verification_status", nullable=False)
        op.create_index("ix_compliance_rules_verification_status", "compliance_rules", ["verification_status"], unique=False)
        op.create_check_constraint("ck_rule_verification_status", "compliance_rules",
                                   "verification_status IN ('DEMO','PROVISIONAL','VERIFIED')")


def downgrade():
    if op.get_bind().dialect.name == "sqlite":
        op.drop_index("ix_compliance_rules_verification_status", table_name="compliance_rules")
        op.execute("ALTER TABLE compliance_rules DROP COLUMN verification_status")
    else:
        op.drop_constraint("ck_rule_verification_status", "compliance_rules", type_="check")
        op.drop_index("ix_compliance_rules_verification_status", table_name="compliance_rules")
        op.drop_column("compliance_rules", "verification_status")
