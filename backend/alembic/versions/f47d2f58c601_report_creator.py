"""store the user who generated each report

Revision ID: f47d2f58c601
Revises: ee57e063679e
"""
from alembic import op
import sqlalchemy as sa


revision = "f47d2f58c601"
down_revision = "ee57e063679e"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("reports") as batch_op:
        batch_op.add_column(sa.Column("created_by", sa.Uuid(as_uuid=False), nullable=True))
        batch_op.create_index("ix_reports_created_by", ["created_by"], unique=False)
        batch_op.create_foreign_key("fk_reports_created_by", "users", ["created_by"], ["id"], ondelete="SET NULL")


def downgrade():
    with op.batch_alter_table("reports") as batch_op:
        batch_op.drop_constraint("fk_reports_created_by", type_="foreignkey")
        batch_op.drop_index("ix_reports_created_by")
        batch_op.drop_column("created_by")
