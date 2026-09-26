"""human declaration corrections"""
from alembic import op
import sqlalchemy as sa

revision = 'ee57e063679e'
down_revision = '0cff59a89d4b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('extracted_fields', schema=None) as batch_op:
        batch_op.add_column(sa.Column('machine_value', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('corrected_value', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('corrected_by', sa.Uuid(as_uuid=False), nullable=True))
        batch_op.add_column(sa.Column('corrected_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('is_human_reviewed', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.create_index(batch_op.f('ix_extracted_fields_corrected_by'), ['corrected_by'], unique=False)
        batch_op.create_foreign_key('fk_extracted_fields_corrected_by', 'users', ['corrected_by'], ['id'], ondelete='SET NULL')

    # Preserve every pre-migration machine result before making the column required.
    op.execute(sa.text('UPDATE extracted_fields SET machine_value = normalized_value WHERE machine_value IS NULL'))
    with op.batch_alter_table('extracted_fields', schema=None) as batch_op:
        batch_op.alter_column('machine_value', existing_type=sa.JSON(), nullable=False)
        batch_op.alter_column('is_human_reviewed', existing_type=sa.Boolean(), server_default=None)

    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.drop_constraint('ck_report_status', type_='check')
        batch_op.create_check_constraint('ck_report_status', "status IN ('pending','ready','failed','superseded')")

    # ### end Alembic commands ###


def downgrade():
    # A superseded report is an old valid file; map it to failed for the older schema.
    op.execute(sa.text("UPDATE reports SET status = 'failed' WHERE status = 'superseded'"))
    with op.batch_alter_table('reports', schema=None) as batch_op:
        batch_op.drop_constraint('ck_report_status', type_='check')
        batch_op.create_check_constraint('ck_report_status', "status IN ('pending','ready','failed')")

    with op.batch_alter_table('extracted_fields', schema=None) as batch_op:
        batch_op.drop_constraint('fk_extracted_fields_corrected_by', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_extracted_fields_corrected_by'))
        batch_op.drop_column('is_human_reviewed')
        batch_op.drop_column('corrected_at')
        batch_op.drop_column('corrected_by')
        batch_op.drop_column('corrected_value')
        batch_op.drop_column('machine_value')
