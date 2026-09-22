"""Optional content capability observations; never an execution failure."""

from dataclasses import dataclass
from typing import Literal

MEDIA_EVIDENCE_VERSION = 2


@dataclass(frozen=True, slots=True)
class MediaCapabilityEvidence:
    status: Literal['unknown', 'observed_multi', 'mapping_gap', 'upstream_incomplete'] = 'unknown'
    reason: str = 'no_gallery_sample'
    sample_count: int = 0
    media_count: int = 0
    parser_version: int = MEDIA_EVIDENCE_VERSION
