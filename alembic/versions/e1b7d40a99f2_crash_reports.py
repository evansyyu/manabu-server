"""crash_reports

Revision ID: e1b7d40a99f2
Revises: c3f1a92e7b58
Create Date: 2026-08-19 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1b7d40a99f2'
down_revision: Union[str, Sequence[str], None] = 'c3f1a92e7b58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'crash_reports',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('install_id', sa.String(length=64), nullable=False),
        sa.Column('platform', sa.String(length=16), nullable=False),
        sa.Column('os_version', sa.String(length=32), nullable=False),
        sa.Column('app_version', sa.String(length=32), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('is_fatal', sa.Boolean(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('stack', sa.Text(), nullable=False),
        sa.Column('occurred_at', sa.BigInteger(), nullable=False),
        sa.Column(
            'received_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_crash_reports_received_at', 'crash_reports', ['received_at'])
    op.create_index('ix_crash_reports_install_id', 'crash_reports', ['install_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_crash_reports_install_id', table_name='crash_reports')
    op.drop_index('ix_crash_reports_received_at', table_name='crash_reports')
    op.drop_table('crash_reports')
