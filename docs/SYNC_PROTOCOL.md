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
| `last_device_id` | TEXT NULL | Provenance only — which device last wrote this row. Recorded from the push envelope, never consulted during merge. The client has no matching column. |

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

Tables are **top-level fields**, not a nested `changes` map. Each field name
matches a `SyncedTable.name` in the registry, which is what lets the route
resolve batches by attribute lookup and lets Pydantic type every row in a
single validation pass. All table fields default to `[]`, so a client sends
only what it has.

```jsonc
{
  "device_id": "46a054b2-2498-46a9-8f64-ff184227fbe8",
  "favorites": [
    { "item_type": "kana", "item_id": "あ", "created_at": 1786468000000,
      "updated_at": 1786468000000, "deleted_at": null }
  ],
  "srs_item": [ { "category": "kana", "item_id": "あ", "card_type": "default", ... } ]
}
```

Response:

```jsonc
{
  "accepted": {
    "favorites": [ ["kana", "あ"] ],
    "srs_item":  []
  },
  "highest_reserved_seq": 1147
}
```

- `accepted` maps each table to the natural PKs actually written, **each PK as
  an ordered list of its components** (favorites key on two columns, `srs_item`
  on three). A row absent from `accepted` lost LWW — this is a **success**, not
  an error, and the client advances its watermark regardless.
- `highest_reserved_seq` is **diagnostic only**. Sequences are reserved before
  LWW is evaluated, so the highest reserved number may belong to no row at all.
  It is *not* a pull cursor: using it as one would skip every row another device
  wrote below it. The cursor comes only from `/sync/pull`'s `next_since`.
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

### The table registry

Every per-table difference lives in one `SyncedTable` entry
(`app/sync/tables.py`), so push, pull, dedupe, and merge share a single code
path across all ten tables:

| Field | Purpose |
|---|---|
| `name` | Wire field name and `accepted` key. Must match the `PushRequest` attribute. |
| `model` | SQLAlchemy model, used for the upsert and the pull query. |
| `row_schema` | Pydantic row model. Its fields also define `wire_columns` — what pull returns — so push and pull cannot drift apart, and server-only columns stay off the wire. |
| `pk` | Natural PK columns, in order. Combined with `user_id` to form the `ON CONFLICT` target. |
| `device_owned` | Rollup tables only. Rejects rows whose `device_id` differs from the push envelope's, with `422`. |
| `watermark_field` | The column LWW compares. `updated_at` everywhere except `srs_item_tombstone`, which has only `deleted_at`. |

Adding a table is one registry entry, one row schema, one model, one
`PushRequest` field, and a migration. No merge code changes.

`srs_item_tombstone` carries a server-side `updated_at` derived from
`deleted_at` at push time, so the generic upsert works unchanged. That column
is not in the row schema, so clients never see it.

### The one statement that does most of the work

```sql
INSERT INTO srs_item (user_id, category, item_id, card_type, ...,
                      updated_at, server_seq, last_device_id)
VALUES (...)
ON CONFLICT (user_id, category, item_id, card_type) DO UPDATE SET
  ...,
  updated_at     = EXCLUDED.updated_at,
  server_seq     = EXCLUDED.server_seq,
  last_device_id = EXCLUDED.last_device_id
WHERE EXCLUDED.updated_at > srs_item.updated_at
RETURNING category, item_id, card_type;
```

Postgres's conditional upsert *is* the LWW merge. `RETURNING` tells you which
rows were accepted. The strict `>` is what makes re-pushing an identical batch
a no-op.

### Tie-break: the server wins

Two devices can write the same row at the same millisecond. Some rule must make
every replica pick the same winner, or they diverge permanently. The rule is
asymmetric:

- **Server accepts pushes with strictly `>`.** First arrival wins the tie; the
  second push is rejected as a no-op.
- **Clients apply pulled rows with `>=`.** The tie-losing device adopts what the
  server kept.

Walk the failure it prevents. A and B both write row R at time T. A pushes
first and the server stores A's version. B pushes; `>` fails against the equal
timestamp, so the server keeps A's. B then pulls A's row — and if B applied it
with `>` too, the equal timestamp would lose against B's own local copy and B
would keep its version forever. `>=` on the pull side is what closes that.

This needs no `last_device_id` on either half and no extra stamping at any
write site. It works because a single server is the serialization point: the
winner need not be deterministic *by content*, only deferred to by every
replica. It encodes the project's core principle — devices own content, the
server owns ordering.

One replica loses a true tie silently. That is true of every LWW scheme,
including a `(timestamp, device_id)` pair; this one just costs no schema.

> The server still records `last_device_id` from the push envelope as
> provenance, because it is free there and useful when debugging. It is
> **never** read during merge. Adding a matching client column later is a clean
> additive migration if provenance earns its keep.

### Per table

| Table | Strategy |
|---|---|
| `srs_review_log` | Append-only union. Insert-if-absent; never update. No conflict is possible because rows are immutable except `is_undone`, which is monotonic 0→1 and so merges by LWW trivially. |
| `srs_daily_counter`, `study_activity` | Union across devices. Each device writes only its own `device_id` rows. Reads SUM across devices. |
| `srs_item` | LWW on `updated_at`. Ties go to whichever push arrived first; see above. |
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

**Advance watermarks on pull as well.** Applying a pulled row copies its
`updated_at` into the local row. If that value exceeds the table's push
watermark, the next push ships the row straight back, where the server rejects
it under `>` — wasted bandwidth for no effect. In steady state that is a few
rows; on bootstrap it is the entire account history making a return trip, since
watermarks start at 0. So: in the same transaction that applies a pull batch,
raise each affected table's watermark to at least the max `updated_at` applied.

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

## 8. Test coverage

Implemented in `tests/test_sync_push.py`, `tests/test_sync_pull.py`,
`tests/test_sync_special_tables.py`, and `tests/test_seq.py` (53 tests total
across the server).

| Property | Test |
|---|---|
| Concurrent pushes never share sequence numbers | `test_concurrent_reservations_do_not_overlap` — five real transactions, genuine lock contention |
| Re-pushing a batch is a no-op | `test_push_is_idempotent` |
| Newer wins, older loses | `test_newer_row_wins`, `test_older_row_loses` |
| Equal timestamps go to first arrival | `test_equal_timestamp_loses` |
| Duplicate PKs in one batch collapse to the newest | `test_duplicate_pks_in_one_batch` |
| Device-local settings keys never stored | `test_denied_settings_key_dropped` |
| Batch cap returns 413 | `test_batch_cap_enforced` |
| A device cannot write another device's rollups | `test_foreign_device_rollup_rejected` |
| Two devices' rollups for one day coexist | `test_two_devices_rollups_coexist` |
| Tombstones merge on `deleted_at` | `test_tombstone_merges_on_deleted_at` |
| Pull pages cover everything exactly once | `test_paging_covers_everything_once` — 12 rows, limit 5, asserts 3 pages and no duplicates |
| Server-only columns never reach the wire | `test_server_columns_not_exposed`, `test_tombstone_pull_shape` |
| One user's rows are invisible to another | `test_tenant_isolation` |
| Cross-table sequencing in one push | `test_all_tables_in_one_push` |

Still untested, deliberately: bootstrap at realistic scale (needs a seeded
database), and the client-side apply rules.

## 9. Deferred

- Filtering the pusher's own rows out of its pulls.
- Hybrid logical clocks instead of wall-clock LWW.
- WebSocket change notifications instead of poll-on-foreground.
- Server-side FSRS replay to heal `srs_item` from the review log union.
- Tombstone pruning after 90 days (server and client).
