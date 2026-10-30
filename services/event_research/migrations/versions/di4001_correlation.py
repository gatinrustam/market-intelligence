from alembic import op
from app.storage.models import (CorrelationPolicy, CorrelationCandidate, CorrelationEvent,
    CorrelationRevision, CorrelationDecision, CorrelationSuggestion, CorrelationProcessed)
revision = 'di4001'
down_revision = 'di3001'
branch_labels = depends_on = None

def upgrade():
    for model in (CorrelationPolicy, CorrelationCandidate, CorrelationEvent,
                  CorrelationRevision, CorrelationDecision, CorrelationSuggestion, CorrelationProcessed):
        model.__table__.create(op.get_bind(), checkfirst=True)

def downgrade():
    raise RuntimeError('Immutable correlation history cannot be dropped')
