"""Alembic migration script template."""

${imports}

from alembic import op


def upgrade() -> None:
    """Apply the migration."""
    ${upgrades}


def downgrade() -> None:
    """Revert the migration."""
    ${downgrades}
