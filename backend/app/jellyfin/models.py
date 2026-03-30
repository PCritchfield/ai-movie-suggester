"""Pydantic models for Jellyfin API responses.

Uses Field aliases to map Jellyfin's PascalCase JSON to snake_case Python.
"""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AuthResult(BaseModel):
    """Result of a successful authentication against Jellyfin."""

    access_token: str
    user_id: str
    user_name: str

    @classmethod
    def from_jellyfin(cls, data: dict[str, Any]) -> Self:
        """Parse from Jellyfin's AuthenticateByName response shape."""
        return cls(
            access_token=data["AccessToken"],
            user_id=data["User"]["Id"],
            user_name=data["User"]["Name"],
        )


class UserPolicy(BaseModel):
    """Jellyfin user policy (nested inside /Users/Me response)."""

    model_config = ConfigDict(populate_by_name=True)

    is_administrator: bool = Field(default=False, alias="IsAdministrator")


class UserInfo(BaseModel):
    """Jellyfin user info (from /Users/Me or /Users/{id})."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="Id")
    name: str = Field(alias="Name")
    server_id: str = Field(alias="ServerId")
    has_password: bool = Field(alias="HasPassword")
    policy: UserPolicy = Field(default_factory=UserPolicy, alias="Policy")


class LibraryItem(BaseModel):
    """A single item from a Jellyfin library."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="Id")
    name: str = Field(alias="Name")
    type: str = Field(alias="Type")
    overview: str | None = Field(default=None, alias="Overview")
    genres: list[str] = Field(default_factory=list, alias="Genres")
    production_year: int | None = Field(default=None, alias="ProductionYear")
    tags: list[str] = Field(default_factory=list, alias="Tags")
    studios: list[str] = Field(default_factory=list, alias="Studios")
    community_rating: float | None = Field(default=None, alias="CommunityRating")
    people: list[dict[str, Any]] = Field(default_factory=list, alias="People")

    @field_validator("studios", mode="before")
    @classmethod
    def _extract_studio_names(cls, v: Any) -> list[str]:
        """Extract Name from studio objects; pass through plain strings."""
        if not isinstance(v, list):
            return []
        result: list[str] = []
        for item in v:
            if isinstance(item, dict) and "Name" in item:
                result.append(item["Name"])
            elif isinstance(item, str):
                result.append(item)
        return result


class PaginatedItems(BaseModel):
    """Paginated response from Jellyfin's item listing endpoints."""

    model_config = ConfigDict(populate_by_name=True)

    items: list[LibraryItem] = Field(alias="Items")
    total_count: int = Field(alias="TotalRecordCount")
    start_index: int = Field(alias="StartIndex")
