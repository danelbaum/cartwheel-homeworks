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

This is the working HW4 review interface. The sample manifest contains four disjoint batches: initial (30), quantity (30), depth (25), and final uniform (15). Human review progress is derived from saved annotations; selected traces and AI assessments are not counted as human reviews. Open `/?batch=final_uniform` for the final batch. Its selection audit preserves the taxonomy at selection time.

The taxonomy has accepted definitions and separate AI assessments; acceptance of definitions does not confirm every AI label. Structured human judgments and assignment completion should be checked against saved state rather than assumed complete. Workshop instrumentation and verification are recorded separately.

Validation:

```sh
.venv/bin/python -m pytest analysis/review_app/test_server.py tests/test_normalization_metadata.py tests/test_langfuse_export.py -q
node --check analysis/review_app/app.js
```

### Contextual specification
The Specification tab defaults to verbatim requirement excerpts selected from the pinned snapshot using conversation requests, caller roles, and recorded tools. Each excerpt explains its selection. General response requirements remain available alongside topic-specific requirements and recorded tool contracts. Selection is heuristic, not an exhaustive applicability determination or a failure judgment. Use Show full specification for omitted rules; search operates within the selected view. Selection refreshes when the conversation changes. No model calls or review labels are used.

Offline selection checks: `node analysis/review_app/test_spec.cjs`.

### Maps & groups
Open `/?view=explore`. Cluster coordinates are a PCA projection of the standardized features in initial_sampling_audit.json, retaining 30.5% of variance. Colors retain original cluster assignments; positions are not failure predictions. Select dots or use the scenario picker to handle overlaps. The taxonomy tree uses the accepted definitions and source-separated AI assessments described below. Notes and original traces are accessible from tiles.

## Accepted taxonomy and AI assessments

Open `/?view=explore&map=taxonomy` for the taxonomy tree. It reads the accepted definitions and subtypes from `analysis/state/patterns.json`, rather than guessing categories from annotation keywords. Filter by traces with or without human observations, then present, absent, uncertain, or all assessments. Select a tile or subtype for explanations, exact supporting quotes, original human observations, and conversation links. The Notes panel and Taxonomy view also show source-separated AI assessments.

`python -m analysis.review_app.assess_taxonomy` applies the rubric using the configured OpenAI account (API charges apply). It sends only synthetic conversation blocks and caller role/IDs, with prior session turns through the target; it does not send environment/location metadata, raw telemetry, or system prompts. It saves resumable, atomic output in `analysis/state/review_app/ai_assessments.json`. The runner requires explicit authorization to send the trace data to OpenAI.

These assessments are not validated judges or human labels. They do not change annotations, human label files, Langfuse scores, review completion counts, or homework sampling. A null label means uncertain, not absent. Internal-operation disclosure uses the accepted customer-purpose refinement; the old specification is retained. All categories can overlap when distinct defects support them. Counts are model findings, not prevalence estimates.
