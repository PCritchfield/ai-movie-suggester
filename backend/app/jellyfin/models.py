"""Pydantic models and dataclass DTOs for Jellyfin API responses.

Uses Field aliases to map Jellyfin's PascalCase JSON to snake_case Python.
Includes plain dataclass DTOs for lightweight internal transfer objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class WatchHistoryEntry:
    """User-scoped activity data for a single watched/favorited item.

    Slim DTO for the history-aware ranking service — contains only the
    activity fields needed for scoring.  Does NOT extend LibraryItem:
    catalog metadata lives in library_items from sync; this is a
    different domain with a different lifecycle.
    """

    jellyfin_id: str
    last_played_date: datetime | None
    play_count: int
    is_favorite: bool


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
    run_time_ticks: int | None = Field(default=None, alias="RunTimeTicks")
    people: list[dict[str, Any]] = Field(default_factory=list, alias="People")
    official_rating: str | None = Field(default=None, alias="OfficialRating")

    @property
    def runtime_minutes(self) -> int | None:
        """Convert RunTimeTicks to minutes, or None if not set."""
        if self.run_time_ticks is None:
            return None
        return self.run_time_ticks // 600_000_000

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
