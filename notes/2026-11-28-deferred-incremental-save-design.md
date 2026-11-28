# Deferred incremental Save and sequence hooks

Design for Stoner Measurement, 28 November 2026.

A scan or sweep collects its row after its children run. The hook queues let
incremental Save wait for collection of the current point, then copy only the
rows it will write. See the [earlier incremental Save specification](incremental_save.md)
and the current [Save command](../src/stoner_measurement/plugins/command/save.py).

## Hook ownership and routing

A hook request consists of a callback and a boundary. Requests bubble up
through the active sequence invocations via the common `SequencePlugin`
interface. A scope that owns the requested boundary queues the callback.
Otherwise it forwards the request to its enclosing scope. The first scope
that can handle the request owns it. Queues live for the scope's invocation,
so a reused container or a later run gets fresh queues.

| Request | Owner | When it drains |
| --- | --- | --- |
| End of iteration | The nearest enclosing scan or sweep, or the root when there is no enclosing loop | After point collection and before advancing or exiting the loop. At the root, after the root body completes. |
| End of sequence | The nearest enclosing sequence container that owns this boundary | After the container finishes, before its cleanup |

A scan or sweep can own both boundaries. Its iteration queue is renewed for each
accepted point and its sequence queue lives for the entire invocation. An
ordinary container forwards an iteration request through its enclosing scopes
and can own its own sequence queue. At the root, both boundary names refer to
the same queue, which drains once after the root body completes and before
generated cleanup.

**Run Parallel** forwards both kinds of request to the surrounding scope.
Each worker receives the same hook routing it would have at the position of
the Run Parallel step. A scan or sweep started inside a worker still owns its
own iteration queue. Registration into a shared parent queue is thread-safe.
The parent can drain its queue after Run Parallel has joined its workers.
Actions run in registration order, so serial steps within one branch retain
their ordering. Cross-branch ordering depends on which registration arrives
first. Keep dependent actions in one serial branch. See
[sequence containers](../src/stoner_measurement/plugins/sequence/base.py) and
[Run Parallel](../src/stoner_measurement/plugins/sequence/containers.py).

## Finishing a scan or sweep point

When a loop accepts a point, the generator supplies the initial value of the
loop's `meas_flag`. The loop opens a fresh iteration queue and registers
automatic collection first if collection is enabled. The collection callback
reads the loop's **live `meas_flag` when it runs**, after the child actions
that executed for the point. The callback then applies `collect_filter` and
uses the configured outputs. It makes the committed row index, or the absence
of a committed row, available to the remaining actions. The loop drains the
point queue while its point state is still current.

| How the point body exits | Collection and queued actions | Loop flow |
| --- | --- | --- |
| Reaches the end | Finish the point | Advance normally |
| Break If fires | Finish the point and run actions already queued | Exit the nearest loop |
| Continue If fires | Finish the point and run actions already queued | Advance to the next point |
| Exception or cancellation | Discard the unfinished point's pending actions | Propagate the failure or cancellation through normal cleanup |

Break If and Continue If affect which child steps execute. A child skipped by
either command has had no opportunity to queue an action.

A shared point context can recognise fall-through, Python `break` and Python
`continue` as normal exits and distinguish them from an exception. The scan
and sweep paths should use the same point-completion rules in generated
scripts and direct execution. See [state collection](../src/stoner_measurement/plugins/state/base.py)
and [loop-control commands](../src/stoner_measurement/plugins/command/loop_control.py).

### Rejecting a point from a child step

A child that decides to exclude the current point should clear the owning
scan or sweep's `meas_flag` before the collection phase. The next point gets
its own flag from the scan or sweep generator. Any later child that tests
`meas_flag` also sees the updated value for the current point.

The scan and sweep **Data** tab already offers a **Collect filter** expression
for conditions evaluated at collection time. **Skip Collection** clears the
current flag on the innermost enclosing scan or sweep. Put it inside an `If`
that tests whether to reject the point. The command acts immediately, so the
queue's collection callback sees the decision. The separate Save condition
controls when the committed rows are written. See the
[scan](../src/stoner_measurement/plugins/state_scan/base.py)
and [sweep](../src/stoner_measurement/plugins/state_sweep/base.py) point loops.

## Deferred Save and row copying

1. When an incremental Save selects a collection table of an enclosing scan
   or sweep, register an end-of-iteration action with the **innermost enclosing
   loop**. The Save step's position in the sequence tree determines the
   boundary. Resolve the trace selection, path expression and effective
   overwrite setting at the Save step, while its evaluation context is
   available. Carry the request and source identifiers through the queue.
2. For a Save of the owning loop's table, use the table's committed row count
   after collection as the available range. Use the current point's committed
   row, when present, to align its point-local readings. A filtered point adds
   no row, and a Save on that point can still write rows from earlier points.
   A table belonging to an outer loop is visible up to its latest committed
   point. To save the outer loop's current point after its collection, place
   the Save in the outer loop body, outside the inner loop. Keep the ordinary
   longest-table row count for incremental exports independent of loop collection.
3. Each execution writes every available row from the destination's per-run
   saved-row cursor to the end of the available range. This applies to both
   immediate and deferred Save. Obtain row counts from the live sources
   before converting arrays. Slice each source to the part needed for that
   range, then convert and copy those cells into the payload. Pass the slice
   and its destination offset to the writer so it can place the rows accurately.
   The first write can include the available initial rows and metadata. Move
   the cursor forward after a successful write.
4. Where a point-local trace must reflect the exact Save position and a later
   child may replace it, snapshot just that point-local result when queuing
   the request. The growing collection table is still read by slice after
   collection. Pair supplemental readings with their point. For earlier rows
   in the batch, use their recorded readings or an explicit missing value
   where a point-local reading is unavailable.

A conditional Save batches writes. Every committed row remains eligible while
the condition is false. For example, if six rows have been saved and nine are
available when the condition next passes, Save writes rows seven to nine.
Collection settings decide which rows enter the table. The Save condition
decides when the accumulated rows are written.

For example, a Save inside an inner scan runs when the inner point finishes.
A sibling Save after the inner scan, still inside the outer sweep, runs when
the outer point finishes. Selecting tables from both loops leaves the hook
boundary fixed by that placement. Row alignment for tables collected by
different loops remains a design decision.

## Behaviour to verify during implementation

- Scan and sweep collection occurs once on a normal point, a Break If point
  and a Continue If point, subject to the same collection settings.
- Break If exits the loop and Continue If reaches the next point. Both skip
  the remaining children on the current point and run its queued actions.
  A child exception discards the unfinished point's actions and runs cleanup.
- Nested serial and parallel containers route both boundaries correctly,
  including a root queue that drains once. A Save inside an inner loop runs at
  the inner boundary, and a Save placed in the outer body runs at the outer
  boundary.
- Deferred TDI and NeXus writes pair the short acquisition with the current
  committed row, include the last eligible point and copy only the new slice
  when the accumulated table is already large.
- Immediate and deferred conditional saves catch up every unsaved committed
  row on the next execution. A deferred Save can flush a backlog even when
  collection rejects its current point.
- Clearing `meas_flag` in a child excludes the current point from collection.
  The next point starts with the flag supplied by its generator.
