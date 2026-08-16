"""user_avatar

Revision ID: c3f1a92e7b58
Revises: 43d9ea7a4d9a
Create Date: 2026-08-16 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f1a92e7b58'
down_revision: Union[str, Sequence[str], None] = '43d9ea7a4d9a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'user_avatar',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('content_type', sa.String(length=64), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('updated_at', sa.BigInteger(), nullable=False),
        sa.Column(
            'server_updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('user_avatar')
