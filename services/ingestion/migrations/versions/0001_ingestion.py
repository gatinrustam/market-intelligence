"""Initial ingestion tables. Immutable migration; do not import runtime models."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGBLOB

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('raw_payloads',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('source_id', sa.String(64), nullable=False),
        sa.Column('received_at', sa.DateTime(), nullable=False),
        sa.Column('body', sa.LargeBinary().with_variant(LONGBLOB(), 'mysql', 'mariadb'), nullable=False),
        sa.Column('content_type', sa.String(200), nullable=False))
    op.create_index('ix_raw_payloads_source_id', 'raw_payloads', ['source_id'])
    op.create_table('news_items',
        sa.Column('message_id', sa.String(36), primary_key=True),
        sa.Column('source_id', sa.String(64), nullable=False),
        sa.Column('external_id_hash', sa.String(64)),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('raw_payload_id', sa.String(36), sa.ForeignKey('raw_payloads.id'), nullable=False),
        sa.Column('item_index', sa.Integer(), nullable=False),
        sa.Column('event', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('source_id', 'external_id_hash', name='uq_news_external'),
        sa.UniqueConstraint('source_id', 'content_hash', name='uq_news_content'))
    op.create_table('outbox_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('message_id', sa.String(36), sa.ForeignKey('news_items.message_id'), nullable=False, unique=True),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt_at', sa.DateTime(), nullable=False),
        sa.Column('lease_until', sa.DateTime()),
        sa.Column('lease_token', sa.String(36)),
        sa.Column('last_error', sa.String(100)),
        sa.Column('published_at', sa.DateTime()))
    op.create_index('ix_outbox_due', 'outbox_events', ['status', 'next_attempt_at', 'lease_until'])
    op.create_table('failed_items',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('source_id', sa.String(64), nullable=False),
        sa.Column('raw_payload_id', sa.String(36), sa.ForeignKey('raw_payloads.id'), nullable=False),
        sa.Column('item_index', sa.Integer()),
        sa.Column('error_type', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_index('ix_failed_items_source_id', 'failed_items', ['source_id'])


def downgrade():
    for table in ('failed_items', 'outbox_events', 'news_items', 'raw_payloads'):
        op.drop_table(table)
