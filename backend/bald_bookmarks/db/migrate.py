"""Apply Alembic schema migrations for relational drivers."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from loguru import logger

from bald_bookmarks.config import Settings
from bald_bookmarks.domain.admin import SchemaRevision, SchemaStatus

# Driver names that persist schema with Alembic.
SCHEMA_MIGRATION_DRIVERS = frozenset({"oracle", "postgres", "mysql", "sqlite"})


def find_alembic_root() -> Path:
    """Locate the directory that contains alembic.ini.

    Returns:
        Path: Repository (or image) root containing alembic.ini.

    Raises:
        FileNotFoundError: If alembic.ini cannot be found.
    """
    candidates = [
        Path.cwd(),
        Path(__file__).resolve().parents[3],
    ]
    for root in candidates:
        if (root / "alembic.ini").is_file() and (root / "alembic").is_dir():
            return root
    raise FileNotFoundError(
        "alembic.ini not found; run the API from the repository root"
    )


def alembic_config(alembic_root: Path | None = None) -> Config:
    """Build an Alembic Config pointed at the local script directory.

    Args:
        alembic_root (Path | None): Optional directory containing alembic.ini.

    Returns:
        Config: Alembic config with script_location set.

    Raises:
        FileNotFoundError: If alembic.ini is missing.
    """
    root = alembic_root if alembic_root is not None else find_alembic_root()
    ini_path = root / "alembic.ini"
    if not ini_path.is_file():
        raise FileNotFoundError(f"alembic.ini not found at {ini_path}")
    config = Config(str(ini_path))
    config.set_main_option("script_location", str(root / "alembic"))
    return config


def _revision_parent(down_revision: object) -> str | None:
    """Normalize an Alembic down_revision value to a display string.

    Args:
        down_revision (object): Parent revision id, tuple of ids, or None.

    Returns:
        str | None: Comma-separated parent ids, or None.
    """
    if down_revision is None:
        return None
    if isinstance(down_revision, tuple):
        return ", ".join(str(item) for item in down_revision)
    return str(down_revision)


def describe_schema(
    settings: Settings,
    current_revision: str | None,
    *,
    current_error: str | None = None,
    alembic_root: Path | None = None,
) -> SchemaStatus:
    """Compare the deployed Alembic revision with local script heads.

    When current_revision is omitted, is_current stays unset.

    Args:
        settings (Settings): Application settings.
        current_revision (str | None): Revision read from the database.
        current_error (str | None): Error from reading the deployed revision.
        alembic_root (Path | None): Optional directory containing alembic.ini.

    Returns:
        SchemaStatus: Local heads, revision chain, and current match state.
    """
    applicable = settings.normalized_driver in SCHEMA_MIGRATION_DRIVERS
    try:
        script = ScriptDirectory.from_config(alembic_config(alembic_root))
    except FileNotFoundError as exc:
        return SchemaStatus(
            applicable=applicable,
            current_revision=current_revision,
            head_revisions=[],
            is_current=None,
            revisions=[],
            error=str(exc),
        )
    head_revisions = list(script.get_heads())
    revisions = [
        SchemaRevision(
            revision=rev.revision,
            down_revision=_revision_parent(rev.down_revision),
            doc=rev.doc,
        )
        for rev in script.walk_revisions()
    ]
    is_current: bool | None = None
    if applicable and current_revision is not None and head_revisions:
        is_current = current_revision in head_revisions
    return SchemaStatus(
        applicable=applicable,
        current_revision=current_revision,
        head_revisions=head_revisions,
        is_current=is_current,
        revisions=revisions,
        error=current_error,
    )


def upgrade_schema(
    settings: Settings,
    alembic_root: Path | None = None,
) -> None:
    """Apply Alembic migrations to head for relational drivers.

    The upgrade is idempotent when the schema is already current.

    Args:
        settings (Settings): Application settings.
        alembic_root (Path | None): Optional directory containing alembic.ini.

    Raises:
        FileNotFoundError: If alembic.ini is missing for a relational startup.
    """
    if settings.normalized_driver not in SCHEMA_MIGRATION_DRIVERS:
        return
    if settings.normalized_driver == "sqlite":
        settings.sqlite_db_path().parent.mkdir(parents=True, exist_ok=True)
    config = alembic_config(alembic_root)
    config.attributes["settings"] = settings
    logger.info("Applying Alembic migrations to head")
    command.upgrade(config, "head")
    logger.info("Alembic migrations applied")
