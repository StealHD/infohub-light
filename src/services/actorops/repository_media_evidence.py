"""Private per-source capability observations, separate from run health."""

import hashlib

from ...storage.actor_media_evidence_schema import ready
from .capability_evidence import MEDIA_EVIDENCE_VERSION

RANK = {'observed_multi': 0, 'unknown': 1, 'mapping_gap': 1, 'upstream_incomplete': 2}
REASONS = {'no_gallery_sample', 'multiple_media_observed', 'unmapped_media_items',
           'gallery_cover_only', 'gallery_items_missing'}


class MediaEvidenceRepository:
    def __init__(self, repository):
        self.repository = repository

    def record(self, *, attempt_id, binding, candidate, evidence):
        if evidence is None or not ready(self.repository.connection):
            return
        if (evidence.status not in RANK or evidence.reason not in REASONS
                or evidence.parser_version != MEDIA_EVIDENCE_VERSION):
            return
        attempt = self.repository.get_attempt(attempt_id)
        if (attempt['status'] != 'succeeded' or not attempt['cost_final']
                or attempt['source_id'] != binding.source_id
                or attempt['binding_version'] != binding.binding_version
                or attempt['target_fingerprint'] != binding.target_fingerprint
                or attempt['candidate_id'] != candidate.candidate_id):
            return
        with self.repository.transaction():
            self.repository.connection.execute(
                '''INSERT INTO actor_media_evidence_v2
                   (workspace_id,attempt_id,source_id,binding_version,candidate_id,build_id,
                    schema_hash,manifest_hash,parser_version,status,reason,sample_count,media_count,observed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(workspace_id,attempt_id,parser_version) DO NOTHING''',
                (self.repository.workspace_id, attempt_id, binding.source_id, binding.binding_version,
                 candidate.candidate_id, candidate.build_id, _schema_key(candidate),
                 candidate.manifest_hash or '', evidence.parser_version, evidence.status, evidence.reason,
                 evidence.sample_count, evidence.media_count, attempt['created_at']))

    def summary(self, binding, candidate):
        result = {'status': 'unknown', 'reason': 'no_gallery_sample', 'sample_count': 0,
                  'media_count': 0, 'observed_at': None}
        if not ready(self.repository.connection):
            return result
        row = self.repository.connection.execute(
            '''SELECT status,reason,sample_count,media_count,observed_at
               FROM actor_media_evidence_v2
               WHERE workspace_id=? AND source_id=? AND binding_version=? AND candidate_id=?
                 AND build_id=? AND schema_hash=? AND manifest_hash=? AND parser_version=?
                 AND status!='unknown'
               ORDER BY observed_at DESC,attempt_id DESC LIMIT 1''',
            (self.repository.workspace_id, binding.source_id, binding.binding_version,
             candidate.candidate_id, candidate.build_id, _schema_key(candidate),
             candidate.manifest_hash or '', MEDIA_EVIDENCE_VERSION)).fetchone()
        if row and row['status'] in RANK and row['reason'] in REASONS:
            result.update({key: row[key] for key in result})
        return result

    def rank(self, binding, candidate):
        return RANK[self.summary(binding, candidate)['status']]

    def record_schema_origin(self, candidate, origin):
        if origin not in {'declared_fields', 'dataset_view', 'observed_dataset', 'unknown'}:
            return
        if not ready(self.repository.connection):
            return
        self.repository._require_transaction()
        self.repository.connection.execute(
            """INSERT INTO actor_output_schema_provenance_v2(workspace_id,candidate_id,origin)
               VALUES(?,?,?) ON CONFLICT(workspace_id,candidate_id) DO NOTHING""",
            (self.repository.workspace_id, candidate.candidate_id, origin))

    def schema_origin(self, candidate):
        if not ready(self.repository.connection):
            return 'unknown'
        row = self.repository.connection.execute(
            'SELECT origin FROM actor_output_schema_provenance_v2 WHERE workspace_id=? AND candidate_id=?',
            (self.repository.workspace_id, candidate.candidate_id)).fetchone()
        return row['origin'] if row else 'unknown'


def _schema_key(candidate):
    raw = f'{candidate.input_schema_hash or ""}:{candidate.output_schema_hash or ""}'
    return hashlib.sha256(raw.encode()).hexdigest()
