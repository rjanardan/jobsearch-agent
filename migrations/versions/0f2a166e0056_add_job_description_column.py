"""add job.description column

Revision ID: 0f2a166e0056
Revises: 9b6cb6ba60ef
Create Date: 2026-09-09 11:29:53.987059

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0f2a166e0056'
down_revision: Union[str, Sequence[str], None] = '9b6cb6ba60ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('job', sa.Column('description', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('job', 'description')
