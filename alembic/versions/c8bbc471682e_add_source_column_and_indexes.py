"""add_source_column_and_indexes

Revision ID: c8bbc471682e
Revises: 885449d573dc
Create Date: 2026-03-07 22:56:34.594205

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8bbc471682e'
down_revision: Union[str, Sequence[str], None] = '885449d573dc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('records', sa.Column('source', sa.String(), server_default='manual'))
    op.create_index('ix_records_date_type', 'records', ['date', 'type'])
    op.create_index('ix_records_user_type', 'records', ['user_id', 'type'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_records_user_type', table_name='records')
    op.drop_index('ix_records_date_type', table_name='records')
    op.drop_column('records', 'source')
