"""Independent enrichment database; no FK or reads into Stage 1."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGBLOB, DATETIME

revision = 'e0001'
down_revision = None
branch_labels = None
depends_on = None
DT = sa.DateTime().with_variant(DATETIME(fsp=6), 'mysql', 'mariadb')
BLOB = sa.LargeBinary().with_variant(LONGBLOB(), 'mysql', 'mariadb')


def col(name, type_, nullable=False, **kwargs):
    return sa.Column(name, type_, nullable=nullable, **kwargs)


def upgrade():
    op.create_table('enrichment_inputs',
        col('source_message_id', sa.String(36), primary_key=True), col('source_id', sa.String(64)),
        col('exact_payload', BLOB), col('payload', sa.JSON()), col('payload_hash', sa.String(64)),
        col('stream_sequence', sa.Integer()), col('accepted_at', DT))
    op.create_index('ix_enrichment_inputs_source_id', 'enrichment_inputs', ['source_id'])
    op.create_table('invalid_inputs', col('payload_hash', sa.String(64), primary_key=True),
        col('exact_payload', BLOB), col('stream_sequence', sa.Integer()), col('reason', sa.String(100)), col('created_at', DT))
    op.create_table('enrichment_jobs', col('id', sa.String(36), primary_key=True),
        sa.Column('source_message_id', sa.String(36), sa.ForeignKey('enrichment_inputs.source_message_id'), nullable=False, unique=True),
        col('status', sa.String(16)), col('attempt_count', sa.Integer()), col('next_retry_at', DT),
        col('lease_token', sa.String(36), True), col('lease_until', DT, True),
        col('last_error_type', sa.String(100), True), col('last_error_message', sa.String(200), True),
        col('failed_at', DT, True), col('created_at', DT), col('completed_at', DT, True))
    op.create_index('ix_enrichment_jobs_due', 'enrichment_jobs', ['status', 'next_retry_at', 'lease_until'])
    op.create_table('fetch_snapshots', col('id', sa.String(36), primary_key=True),
        sa.Column('job_id', sa.String(36), sa.ForeignKey('enrichment_jobs.id'), nullable=False, unique=True),
        col('requested_url', sa.Text()), col('final_url', sa.Text()), col('fetched_at', DT),
        col('http_status', sa.Integer()), col('content_type', sa.String(200)), col('content_length', sa.Integer()),
        col('response_hash', sa.String(64)), col('raw_body', BLOB), col('redirect_count', sa.Integer()), col('safe_headers', sa.JSON()))
    op.create_table('enriched_documents', col('id', sa.String(36), primary_key=True),
        sa.Column('source_message_id', sa.String(36), sa.ForeignKey('enrichment_inputs.source_message_id'), nullable=False, unique=True),
        sa.Column('job_id', sa.String(36), sa.ForeignKey('enrichment_jobs.id'), nullable=False, unique=True),
        col('status', sa.String(16)), col('payload', sa.JSON()), col('created_at', DT))
    op.create_index('ix_enriched_documents_status', 'enriched_documents', ['status'])
    op.create_table('outbox_events', col('id', sa.String(36), primary_key=True),
        col('message_id', sa.String(36), unique=True),
        sa.Column('document_id', sa.String(36), sa.ForeignKey('enriched_documents.id'), nullable=False, unique=True),
        col('payload', sa.JSON()), col('status', sa.String(16)), col('attempts', sa.Integer()), col('next_attempt_at', DT),
        col('lease_until', DT, True), col('lease_token', sa.String(36), True), col('last_error', sa.String(100), True), col('published_at', DT, True))
    op.create_index('ix_outbox_due', 'outbox_events', ['status', 'next_attempt_at', 'lease_until'])
    op.create_table('fetch_host_slots', col('hostname', sa.String(253), primary_key=True), col('next_allowed_at', DT))


def downgrade():
    for table in ('fetch_host_slots', 'outbox_events', 'enriched_documents', 'fetch_snapshots', 'enrichment_jobs', 'invalid_inputs', 'enrichment_inputs'):
        op.drop_table(table)
