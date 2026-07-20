"""Strict, identity-free inputs for Remote MCP subscription tools."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ..services.source_schedule import SOURCE_ALLOWED_INTERVALS


class RemoteMCPInputModel(BaseModel):
    """Reject undeclared fields without echoing their values in errors."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ExistingSourceInput(RemoteMCPInputModel):
    mode: Literal["existing"]
    source_id: str = Field(min_length=1, max_length=128)


class PrivateSourceInput(RemoteMCPInputModel):
    mode: Literal["private"]
    type: Literal[
        "rss",
        "telegram",
        "github",
        "reddit",
        "twitter",
        "website",
        "youtube",
        "apify",
    ]
    display_name: str = Field(min_length=1, max_length=120)
    config: dict[str, Any] = Field(default_factory=dict)
    description: str = Field(default="", max_length=500)
    default_channel: str | None = Field(default=None, max_length=80)
    default_topics: list[str] = Field(default_factory=list, max_length=50)


SourceInput = Annotated[
    ExistingSourceInput | PrivateSourceInput,
    Field(discriminator="mode"),
]


class SubscriptionInput(RemoteMCPInputModel):
    enabled: bool = True
    override_channel: str | None = Field(default=None, max_length=80)
    override_topics: list[str] = Field(default_factory=list, max_length=50)
    personal_tags: list[str] = Field(default_factory=list, max_length=50)
    analysis_mode: Literal["full", "personal_only"] = "full"
    priority: StrictInt = Field(default=0, ge=0, le=100)


class ScheduleInput(RemoteMCPInputModel):
    enabled: bool | None = None
    interval_minutes: StrictInt | None = None

    @model_validator(mode="after")
    def validate_interval(self) -> "ScheduleInput":
        if (
            self.interval_minutes is not None
            and self.interval_minutes not in SOURCE_ALLOWED_INTERVALS
        ):
            raise ValueError(
                "interval_minutes must be one of "
                + ", ".join(str(value) for value in SOURCE_ALLOWED_INTERVALS)
            )
        return self


class SourceUpdatesInput(RemoteMCPInputModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    default_channel: str | None = Field(default=None, max_length=80)
    default_topics: list[str] | None = Field(default=None, max_length=50)
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class SubscriptionUpdatesInput(RemoteMCPInputModel):
    enabled: bool | None = None
    override_channel: str | None = Field(default=None, max_length=80)
    override_topics: list[str] | None = Field(default=None, max_length=50)
    personal_tags: list[str] | None = Field(default=None, max_length=50)
    analysis_mode: Literal["full", "personal_only"] | None = None
    priority: StrictInt | None = Field(default=None, ge=0, le=100)


class ScheduleUpdatesInput(ScheduleInput):
    pass


class PrepareCreateSubscriptionInput(RemoteMCPInputModel):
    source: SourceInput
    subscription: SubscriptionInput | None = None
    schedule: ScheduleInput | None = None


class PrepareUpdateSubscriptionInput(RemoteMCPInputModel):
    subscription_id: str = Field(min_length=1, max_length=128)
    source_updates: SourceUpdatesInput | None = None
    subscription_updates: SubscriptionUpdatesInput | None = None
    schedule_updates: ScheduleUpdatesInput | None = None


class PrepareDeleteSubscriptionInput(RemoteMCPInputModel):
    subscription_id: str = Field(min_length=1, max_length=128)
    source_disposition: Literal["keep", "disable_private"]


class ApplySubscriptionChangeInput(RemoteMCPInputModel):
    proposal_id: str = Field(min_length=1, max_length=128)
    confirmation_text: str = Field(min_length=1, max_length=160)
