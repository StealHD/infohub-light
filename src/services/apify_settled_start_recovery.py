"""Evidence required to release a stale pool block without editing Run history."""


def settled_start_can_release(connection, state):
    # Include orphaned memberships: losing a key reference is not no-start proof.
    pending = connection.execute(
        """SELECT 1 FROM apify_actor_runs AS run
           LEFT JOIN apify_key_pool_members AS member
             ON member.workspace_id=run.workspace_id AND member.secret_id=run.secret_id
           WHERE run.workspace_id=?
             AND (run.purpose='acquisition' OR member.role='acquisition' OR member.secret_id IS NULL)
             AND run.status IN ('reserved','starting','running','aborting','start_outcome_unknown')
           LIMIT 1""", (state['workspace_id'],),
    ).fetchone()
    if pending:
        return False
    # Require settled proof for the blocked credential after this block began;
    # an unrelated old zero-cost Run cannot authorize clearing a newer barrier.
    return connection.execute(
        """SELECT 1 FROM apify_actor_runs AS run
           JOIN apify_key_pool_members AS member
             ON member.workspace_id=run.workspace_id AND member.secret_id=run.secret_id
           WHERE run.workspace_id=? AND member.role='acquisition'
             AND run.secret_id=coalesce(?, ?)
             AND run.pool_generation<=? AND julianday(run.updated_at)>=julianday(?)
             AND run.status='start_rejected' AND run.remote_run_id IS NULL AND run.dataset_id IS NULL
             AND run.charge_final=1 AND run.charge_actual_usd=0 AND run.charge_reserved_usd=0
             AND run.last_error_code IN ('actorops_v2_proven_no_start','apify_start_not_created')
           LIMIT 1""",
        (state['workspace_id'], state['active_secret_id'], state['draining_secret_id'],
         state['generation'], state['updated_at']),
    ).fetchone() is not None
