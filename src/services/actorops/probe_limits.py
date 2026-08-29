"""Shared bounded evidence limits for paid Candidate probes."""

from __future__ import annotations


# A Probe still requests and bills at most one result, but some Actors ignore
# their input limit and emit related or foreign rows. Validate a small spillover
# sample so the one-row proof cannot certify a Candidate that production rejects.
PROBE_DATASET_VALIDATION_LIMIT = 4


__all__ = ["PROBE_DATASET_VALIDATION_LIMIT"]
