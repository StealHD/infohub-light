"""Vendor-neutral, bounded declarations for collections and relationships."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .apify_actor_row_extraction import validate_extraction_pointer


class ContractModel(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)


class ValueMapping(ContractModel):
    pointers: tuple[str, ...] = Field(min_length=1, max_length=6)

    @field_validator('pointers')
    @classmethod
    def paths(cls, values):
        for value in values:
            if value != '':
                validate_extraction_pointer(value, allow_wildcard=False)
        if len(set(values)) != len(values):
            raise ValueError('duplicate paths')
        return values


class CollectionMapping(ContractModel):
    pointers: tuple[str, ...] = Field(min_length=1, max_length=6)
    shape: Literal['array', 'single', 'array_or_single'] = 'array'

    @field_validator('pointers')
    @classmethod
    def paths(cls, values):
        for value in values:
            if value != '':
                validate_extraction_pointer(value)
        if len(set(values)) != len(values):
            raise ValueError('duplicate paths')
        return values


class ImageProjection(ContractModel):
    url: ValueMapping
    width: ValueMapping | None = None
    height: ValueMapping | None = None


class VariantMapping(ImageProjection):
    collection: CollectionMapping


class MediaMapping(ContractModel):
    collection: CollectionMapping
    url: ValueMapping | None = None
    preview_url: ValueMapping | None = None
    native_id: ValueMapping | None = None
    kind: ValueMapping | None = None
    kind_values: dict[str, Literal['image', 'video']] = Field(default_factory=dict, max_length=12)
    default_kind: Literal['image', 'video'] = 'image'
    variants: VariantMapping | None = None


class ContributorMapping(ContractModel):
    collection: CollectionMapping
    handle: ValueMapping
    name: ValueMapping | None = None
    avatar_url: ValueMapping | None = None
    # This relation is a statement about confirmed participation, never tags/invitations.
    role: Literal['coauthor'] = 'coauthor'


class StructuredOutput(ContractModel):
    media: MediaMapping | None = None
    contributors: ContributorMapping | None = None
    media_count: ValueMapping | None = None
