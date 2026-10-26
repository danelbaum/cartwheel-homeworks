# Cartwheel human review interface

Run from the repository root:

```sh
.venv/bin/python -m analysis.review_app.server --port 8021
```

Open http://127.0.0.1:8021. Existing `.env` Langfuse credentials stay on the server.
The server binds only to loopback. POSTs require a per-process request token.

## Review

The live Langfuse project is the source. The HW3 export identifies the student's
scenario cohort; it is not used as a silent offline substitute. Refresh fetches
complete live traces. Sessions are grouped by `cartwheel.session_id`, ordered
chronologically, and preserve every distinct trace ID and turn boundary.

Select a phrase in a user/assistant message or tool arguments/results to open the
note editor. The highlight remains visible while entering the note. Save, edit,
or delete notes; deletion is a tombstone with preserved local revision history.
Overlapping highlights are supported. Browser drafts are backed up locally;
explicit Save commits the human observation. Use “no failure observed” only after
reviewing that particular trace. It does not label every taxonomy mode absent.

The evidence pane uses recorded tool results, never today's order database.
Missing names remain missing. Merchant store IDs may be recovered from the
recorded system context. Raw trace data, prompts, and policy results remain
available. Specification search uses a hash-versioned snapshot of the current
SPEC.md, explicitly not a verified historical specification.

## Storage and synchronization

- `analysis/state/annotations.json`: existing records preserved; each note has its
  trace, block, UTF-16 text offsets, exact quote, human note, revision, and spec hash.
- `analysis/state/review_app/history.jsonl`: append-only local revision history.
- Langfuse: notes are categorical `hw4_review_note` scores with the full anchor
  and note in the comment. Stable score IDs update rather than duplicate records.
  Deletions set the categorical value to `withdrawn`.
- `analysis/state/review_app/labels.json`: latest human binary judgments.
- `analysis/state/labels/<mode>.jsonl`: per-mode versioned records. For analysis,
  use the highest revision per record ID. Retries do not duplicate a revision.
- Final-mode judgments are numeric Langfuse scores named after the mode:
  1 = failure present, 0 = absent. Candidate modes cannot be labeled as final.
- Failed remote writes leave durable local `sync: pending` records. Use the
  Progress retry control. “Synced” means the Langfuse create-score API accepted
  the record; its query view can have a short ingestion delay.
- `analysis/state/review_app/specs/<sha256>.md`: reviewed specification snapshots.
- `analysis/state/review_app/live_traces.json`: untracked last live fetch cache;
  the app still requires a live fetch on restart.
- `analysis/state/review_app/annotation-events.jsonl`: a two-second polling log
  for the coding agent to inspect on subsequent turns. The server logs changes;
  it does not autonomously invent categories or act as a background AI reviewer.

Taxonomy is read from `analysis/state/patterns.json` (`{"modes": [...]}` with name,
definition, status, supporting annotations, boundaries, requirement source, etc.).
Modes with `status: final` enable the structured labeling form. Suggestions from
`analysis/state/suggestions.json` are separate from human notes; acceptance opens
an anchored note for human confirmation, rejection preserves the decision.
These views poll every five seconds. No model is called by the interface.

## Current scope and next work

This is the working review interface, not a completed homework submission.
The 259-trace cohort is available for browsing, but it has not been assigned to
HW4's four disjoint sampling batches. The progress page reads the sample manifest
when created. Sample selection/cluster map, taxonomy construction, report counts,
and the student's 100-trace review remain future work. The Workshop part is optional.
The policy pane lists retrieval calls; it does not infer which policy titles were
actually cited. The specification pane is searchable, without AI relevance ranking.

Validation:

```sh
.venv/bin/python -m pytest analysis/review_app/test_server.py tests/test_normalization_metadata.py tests/test_langfuse_export.py -q
node --check analysis/review_app/app.js
```
