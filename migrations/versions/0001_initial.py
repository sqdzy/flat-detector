"""Initial database schema for an empty deployment.

Revision ID: 0001
Revises:
"""
from alembic import op
from flat_detector.models import Base
revision="0001"
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    # This is initial schema creation only; later revisions require explicit alterations.
    Base.metadata.create_all(bind=op.get_bind(),checkfirst=False)

def downgrade():
    # Destroys all flat-detector data. Never run on production without approved backup.
    Base.metadata.drop_all(bind=op.get_bind())
