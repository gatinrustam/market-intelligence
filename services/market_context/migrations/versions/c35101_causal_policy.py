"""Record lookup provenance and schedule new causal revisions without editing audit payloads.
Stop old resolver workers before upgrading: do not run old and causal workers together.
"""
from alembic import op
import sqlalchemy as sa
revision='c35101'
down_revision='c35001'
branch_labels=None
depends_on=None

def upgrade():
    for table in ('market_contexts','context_revisions'):
        op.add_column(table,sa.Column('lookup_policy',sa.String(32),nullable=False,server_default='legacy_nearest_v1'))
    # Token fencing prevents claims made before this migration from committing.
    op.execute("UPDATE context_jobs SET status='pending', next_attempt_at=UTC_TIMESTAMP(6), lease_token=NULL, lease_until=NULL, attempts=0, last_error=NULL")

def downgrade():
    for table in ('context_revisions','market_contexts'):op.drop_column(table,'lookup_policy')
