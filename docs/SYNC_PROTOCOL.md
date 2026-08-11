# Sync Protocol

Design document for `manabu-server` offline-first sync. Written before
implementation (Phase 3); Phase 4 implements exactly this.

---

## 1. Principles

1. **The client owns content; the server owns ordering.** Devices write
   offline against their own clocks. The server assigns every accepted row a
   monotonically increasing `server_seq` from a per-user counter, and devices
   pull "everything after the last seq I saw." Sync never orders by client
   timestamps — clocks drift.
2. **Prefer merges that need no arbitration.** Append-only logs union.
   Per-device rollups union. Tombstones are monotonic. Only the LWW tables
   need a winner, and `updated_at` picks it.
3. **Never reject a row for business reasons during sync.** Caps and limits
   are enforced at creation time on the client, not at merge time. A sync
   endpoint that rejects rows creates permanent divergence.
4. **Everything is idempotent.** Pushing the same batch twice must be a no-op.
   Pulling the same range twice must produce the same local state.

---

## 2. Server-side row shape

Every synced table mirrors its SQLite counterpart plus four server columns:

| Column | Type | Purpose |
|---|---|---|
| `user_id` | UUID | Tenant key. Indexed on every table; every query filters on it. |
| `server_seq` | BIGINT | Pull cursor. Assigned per-user on accept. Indexed with `user_id`. |
| `server_updated_at` | TIMESTAMPTZ | Server receipt time. Authoritative for auditing, never for merging. |
| `last_device_id` | TEXT | Which device last wrote this row. Used only as an LWW tie-break. |

The client's own `updated_at` (integer ms) travels with the row unchanged and
is the **only** field consulted for conflict resolution.

Primary key is always `(user_id, <natural pk>)`. Natural PKs:

| Table | Natural PK |
|---|---|
| `favorites` | `(item_type, item_id)` |
| `study_sets` | `id` |
| `study_set_words` | `(set_id, word_id)` |
| `settings` | `key` |
| `srs_item` | `(category, item_id, card_type)` |
| `srs_item_tombstone` | `(category, item_id, card_type)` |
| `srs_blacklist` | `(category, item_id)` |
| `srs_review_log` | `id` |
| `srs_daily_counter` | `(category, day, device_id)` |
| `study_activity` | `(day, device_id)` |

**Never synced:** `search_history`, `local_meta`, `srs_session`,
`srs_session_queue`. Sessions are device-local by design.

**Excluded from sync entirely:** the legacy SM-2 `cards` / `reviews` tables.
FSRS is the only synced scheduler. Syncing two schedulers doubles every
decision below for a system that is being retired.

---

## 3. Sequence assignment

A single row per user:

```
user_sync_state (user_id UUID PK, seq_high BIGINT NOT NULL DEFAULT 0)
```

Every push transaction:

1. `SELECT seq_high FROM user_sync_state WHERE user_id = ? FOR UPDATE`
2. Reserve a block of `N` sequence numbers, where `N` is the number of rows in
   the batch. Assign them positionally.
3. Upsert the rows with their assigned seqs (conditionally — see §5).
4. `UPDATE user_sync_state SET seq_high = seq_high + N`
5. Commit, releasing the lock.

### Why the lock is held for the whole transaction

This is the subtle part and the reason `FOR UPDATE` is not optional.

Suppose two pushes for the same user overlap. Push A reserves seqs 100–105,
push B reserves 106–110, and **B commits first**. A pull arriving in that
window sees rows up to 110, advances its cursor to 110, and returns. Push A
then commits — and rows 100–105 become visible *below* the client's cursor.
They are never pulled. Silent, permanent data loss.

Holding the row lock until commit makes sequence order identical to commit
order, so a row can never become visible below an already-issued cursor. Every
push for one user serializes; pushes for different users never contend.

### Gaps are expected and harmless

Reserved sequences for rows that lose LWW are simply never used. `server_seq`
is required to be monotonic, not dense. The pull cursor is a `>` comparison,
so gaps cost nothing.

---

## 4. Endpoints

### `POST /sync/push`

```jsonc
{
  "device_id": "uuid-of-this-device",
  "changes": {
    "srs_item":  [ { "id": "...", "updated_at": 1736899200000, ... } ],
    "favorites": [ { "item_type": "kana", "item_id": "\u3042", "updated_at": ..., "deleted_at": null } ]
  }
}
```

Response:

```jsonc
{
  "accepted":        { "srs_item": ["id1", "id2"], "favorites": [] },
  "server_seq_high": 1147
}
```

- `accepted` lists the natural PKs actually written. A row absent from
  `accepted` lost LWW — this is a **success**, not an error, and the client
  advances its watermark regardless.
- The entire push is **one transaction**. Partial success is not a state the
  client has to reason about: either the whole batch applied or nothing did
  and the client retries.
- Batch size cap: **500 rows total** across all tables. Larger payloads get
  `413`. The client chunks.
- Rows are validated with Pydantic before any write. A malformed row fails the
  whole batch with `422` — this is a client bug, not a merge conflict, and
  should be loud.

**Rollup tables are device-scoped.** For `srs_daily_counter` and
`study_activity`, any row whose `device_id` differs from the envelope's
`device_id` is rejected with `422`. A device may only write its own rollups;
peers' rows are read-only replicas.

**Device-local settings keys are not synced.** `settings` holds some
session-scoped, device-local state — observed in the wild:
`session_undo_boundary_<session-uuid>`. Syncing it would push one device's undo
boundary onto another mid-study. The client filters these out of its push
query, and the server drops any key matching the denylist rather than storing
it. Keep the denylist in one place per half and keep them identical:

```
session_undo_boundary_*
```

### `GET /sync/pull?since=<seq>&limit=500`

```jsonc
{
  "rows": [
    { "table": "srs_item", "server_seq": 1101, "row": { ... } },
    { "table": "favorites", "server_seq": 1102, "row": { ... } }
  ],
  "next_since": 1102,
  "has_more": true
}
```

- One query per table (`WHERE user_id = ? AND server_seq > ?
  ORDER BY server_seq LIMIT ?`), merge-sorted by seq, truncated at `limit`.
- `next_since` is the highest seq in `rows`. If `rows` is empty, `next_since`
  echoes the request's `since`.
- Client pages until `has_more` is false, then writes `last_pull_seq`.
- Sequences are unique per user, so a page boundary can never split a seq —
  paging is safe with a strict `>` cursor and needs no tie-breaking.
- **Bootstrap is `since=0`.** A fresh device pulls the user's entire history
  through the same code path. There is no separate "initial sync" endpoint.
- Rows written by the requesting device are **not** filtered out in v1.
  Re-applying your own row is a no-op under LWW, and the filter costs a column
  comparison plus a whole class of bugs. Revisit only if bandwidth measurably
  matters.

---

## 5. Merge rules

### The one statement that does most of the work

```sql
INSERT INTO srs_item (user_id, id, ..., updated_at, server_seq, last_device_id)
VALUES (...)
ON CONFLICT (user_id, id) DO UPDATE SET
  ...,
  updated_at     = EXCLUDED.updated_at,
  server_seq     = EXCLUDED.server_seq,
  last_device_id = EXCLUDED.last_device_id
WHERE EXCLUDED.updated_at > srs_item.updated_at
   OR (EXCLUDED.updated_at = srs_item.updated_at
       AND EXCLUDED.last_device_id > srs_item.last_device_id)
RETURNING id;
```

Postgres's conditional upsert *is* the LWW merge. `RETURNING` tells you which
rows were accepted. The strict `>` is what makes re-pushing an identical batch
a no-op.

### Tie-break

Equal `updated_at` from two devices is rare but must resolve **identically on
every device**, or they diverge permanently. The tie-break is lexicographic
comparison of `last_device_id`. Any deterministic rule works; both halves must
implement the same one.

> **Open decision.** `srs_item` has no `device_id` column in the client
> schema. Either (a) the server stores `last_device_id` from the push envelope
> and the client stores the same on pull, or (b) the tie-break uses a
> content-derived value both sides can compute. (a) is simpler and is assumed
> above, but it means the v17 client migration adds `last_device_id` to the
> LWW tables. Confirm before implementing.

### Per table

| Table | Strategy |
|---|---|
| `srs_review_log` | Append-only union. Insert-if-absent; never update. No conflict is possible because rows are immutable except `is_undone`, which is monotonic 0→1 and so merges by LWW trivially. |
| `srs_daily_counter`, `study_activity` | Union across devices. Each device writes only its own `device_id` rows. Reads SUM across devices. |
| `srs_item` | LWW on `updated_at`, tie-break on `last_device_id`. |
| `favorites`, `study_sets`, `study_set_words`, `srs_blacklist` | LWW + `deleted_at` tombstone column (already the row shape). A delete is a normal LWW write that sets `deleted_at`. |
| `settings` | LWW per key. The PK is `(user_id, key)`, so keys never contend. |
| `srs_item_tombstone` | Separate table, monotonic. See below. |

### Tombstones vs. items

`srs_item` deletion uses a side table rather than a `deleted_at` column, so the
ordering rule is explicit:

- A tombstone **wins** if `tombstone.deleted_at > item.updated_at` → the item
  row is deleted locally on apply.
- Otherwise the item **wins** — this is the "recreated after delete" case, and
  the item survives.
- Both rows continue to exist server-side and continue to sync. The server
  never resolves this; it stores both and lets every device apply the same
  deterministic rule.

**Orphaned reviews persist.** Deleting an `srs_item` on device A does not
delete its `srs_review_log` rows anywhere. History outlives its parent. This
is deliberate: the log is the auditable record and the input to any future
server-side FSRS replay.

### Invariant worth stating

> No sync operation ever deletes a row that the local device has not seen a
> newer tombstone for. Hard deletes do not propagate. This is why synced
> tables cannot use `DELETE`.

---

## 6. Client bookkeeping

### Migration v17 (client, guarded ALTERs — same pattern as v16)

Verified against a live v16 database. `updated_at` is already present on
`favorites`, `settings`, `study_sets`, `study_set_words`, `srs_item`,
`srs_blacklist`, and `study_activity`; `device_id` is already in the PK of both
rollup tables; `local_meta.device_id` and `srs_item_tombstone` both exist.
v17 therefore adds only:

- `srs_review_log.updated_at` — stamped at insert, bumped on the `is_undone`
  flip.
- `srs_daily_counter.updated_at` — bumped on every counter write.
- `last_device_id` on the LWW tables, pending the §5 open decision.

After v17, every synced table pushes by `updated_at` **except
`srs_item_tombstone`**, which has only `deleted_at`. Its watermark is
`deleted_at` and its rows are insert-only, so the push query needs one special
case. Do not add `updated_at` to it purely for uniformity — a tombstone has no
meaningful modification time, and a second timestamp would be one more thing to
keep consistent.

### `local_meta` keys

| Key | Meaning |
|---|---|
| `last_pull_seq` | Server cursor. Advanced only after a full page run completes. |
| `push_watermark:<table>` | Max `updated_at` successfully pushed for that table. |

Push selects `WHERE updated_at > watermark`. Advance the watermark to the
batch's max `updated_at` on any 2xx — including rows that lost LWW, since a
loss means the server already holds something newer.

> **Known limitation, v1.** Watermarks are wall-clock values. If a device's
> clock jumps backwards, rows written during the gap have `updated_at` below
> the watermark and are never pushed. The upgrade path is an **outbox table**
> written in the same transaction as each repo write, so pending changes are
> tracked by insertion rather than by timestamp. The repo layer plus
> `runSerialized` being the single write choke point is what makes that a
> contained change rather than a rewrite.

---

## 7. Ordering and triggers

- Push before pull. Pushing first means a conflict resolves against the
  server's current state rather than against state you're about to overwrite.
- Apply each pull page inside one `runSerialized(withTransactionAsync(...))`.
  A partially applied page must never be observable.
- Advance `last_pull_seq` only after the page's transaction commits.
- Triggers: app foreground, after `closeSession`, after sign-in, on network
  reconnect. Debounced. Never mid-card.

### First sign-in on a device with existing local data

Watermarks start at 0, so the device pushes everything, then pulls. LWW makes
the merge order-independent — the result is the same whichever device pushed
first.

### Signing in as a *different* account

Prompt, then wipe local data and pull fresh. Never merge two people's data.
Detected by comparing the incoming `user_id` against the one in `local_meta`.

---

## 8. Test scenarios (Phase 4, before any client work)

1. Push from device A, pull from device B, assert row equality.
2. LWW: A pushes an older row after B pushed a newer one → B's survives, and
   A's row appears in neither `accepted` nor any subsequent pull.
3. Tombstone beats an older item; a recreated item beats an older tombstone.
4. Idempotency: send the same batch twice → second push accepts nothing and
   allocates no sequences.
5. Two devices' `study_activity` rows for the same date both survive.
6. Pull paging: write 1200 rows, pull with `limit=500`, assert three pages and
   no duplicates or gaps.
7. Tenant isolation: user X's push is invisible to user Y's pull.
8. A device pushing rollup rows for a `device_id` that is not its own → 422.

---

## 9. Deferred

- Filtering the pusher's own rows out of its pulls.
- Hybrid logical clocks instead of wall-clock LWW.
- WebSocket change notifications instead of poll-on-foreground.
- Server-side FSRS replay to heal `srs_item` from the review log union.
- Tombstone pruning after 90 days (server and client).
