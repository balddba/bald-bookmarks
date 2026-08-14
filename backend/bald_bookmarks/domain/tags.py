"""Tag domain and API models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_tag_name(name: str) -> str:
    """Normalize a tag name for uniqueness comparisons.

    Args:
        name (str): Raw tag name.

    Returns:
        str: Trimmed, lowercased tag name.

    Raises:
        ValueError: If the normalized name is empty.
    """
    normalized = name.strip().lower()
    if not normalized:
        raise ValueError("Tag name cannot be empty")
    return normalized


class TagCreate(BaseModel):
    """Payload for creating a tag.

    Attributes:
        name (str): Tag name (stored normalized).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Normalize and validate tag name.

        Args:
            value (str): Raw tag name.

        Returns:
            str: Normalized tag name.
        """
        return normalize_tag_name(value)


class Tag(BaseModel):
    """Persisted tag entity.

    Attributes:
        id (int): Primary key.
        name (str): Normalized tag name.
        created_at (datetime): Creation timestamp.
    """

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    name: str
    created_at: datetime
