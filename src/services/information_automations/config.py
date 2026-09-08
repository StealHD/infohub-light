"""One natural-language requirement and explicit, versioned execution settings."""
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Term = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]


class Trigger(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    kind: Literal['each', 'count', 'interval', 'calendar'] = 'each'
    count: int = Field(default=5, ge=2, le=10000)
    max_wait_seconds: int | None = Field(default=3600, ge=60, le=604800)
    interval_seconds: int = Field(default=3600, ge=60, le=604800)
    time: str = Field(default='08:00', pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    weekdays: list[Annotated[int, Field(ge=0, le=6)]] = Field(default_factory=list, max_length=7)
    timezone: str = 'Asia/Shanghai'

    @model_validator(mode='after')
    def valid_zone(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError('Unknown timezone') from error
        if len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError('Duplicate weekday')
        return self


class ModelSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: Term
    thinking: Term | None = None


class LegacyConditions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    all: list[Term] = Field(default_factory=list, max_length=30)
    any: list[Term] = Field(default_factory=list, max_length=30)
    exclude: list[Term] = Field(default_factory=list, max_length=30)


def upgrade_config(value):
    """Legacy input is converted only to a draft, never to a literal executor."""
    if not isinstance(value, dict) or not ({'mode', 'conditions'} & value.keys()):
        return value
    value = dict(value)
    mode = value.pop('mode', 'keyword')
    if mode not in {'keyword', 'semantic'}:
        raise ValueError('Unknown legacy mode')
    conditions = LegacyConditions.model_validate(value.pop('conditions', {})).model_dump()
    if mode == 'keyword':
        clauses = [label + '：' + '、'.join(conditions.get(key, []))
                   for key, label in [('all', '必须包含全部词语'), ('any', '至少包含一个词语'), ('exclude', '排除包含这些词语的内容')]
                   if conditions.get(key)]
        value['requirement'] = '；'.join(clauses)
    value.setdefault('trigger', {'kind': 'interval', 'interval_seconds': 60})
    value['schema_version'] = 2
    return value


class RuleConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal[2] = 2
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    source_ids: list[Term] = Field(default_factory=list, max_length=50)
    target_id: Term | None = None
    requirement: str = Field(default='', max_length=24000)
    trigger: Trigger = Field(default_factory=Trigger)
    model: ModelSelection | None = None

    @model_validator(mode='before')
    @classmethod
    def legacy_draft(cls, value):
        return upgrade_config(value)
