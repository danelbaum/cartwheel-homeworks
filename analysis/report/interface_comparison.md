# Review interface comparison

## Retained from the reference

Retained free-form open coding, durable local annotation state, and the distinction
between AI suggestions and human observations. Notes retain exact text anchors,
and structured binary labeling is a separate later workflow.

## Changed after inspecting our traces

In the live Langfuse trace for scenario `final-hw3-20261023-246`
(`583fe5f9c948275d0a4cd23f8b13a29d`), opening `get_order` replaced the visible
conversation, and the authenticated support role was buried in metadata.
The custom design keeps the chronological conversation dominant, promotes the
recorded caller context to a header, and puts tool evidence, searchable
specification, and phrase-specific observations in a side pane. It groups
multi-turn conversations by session while preserving distinct trace IDs.
The user requested exact-phrase highlighting and approved this design in the
interactive sketch before implementation.

## Remaining limitations

The specification is a snapshot of the current SPEC.md, not a verified match to
the historical trace's specification. This is labeled explicitly, and each saved
note records the snapshot hash. Policy retrieval remains fully inspectable, but
there is no automatic matching between retrieved documents and reply citations.
The app currently browses the HW3 cohort; the required four disjoint HW4 sampling
batches and cluster visualization have not yet been prepared.

## Sources and review status

Live Langfuse was available. No offline substitution was used. 259 live traces
were fetched for the student's 250-scenario HW3 cohort. One trace has been jointly
inspected for interface design; that discussion has not been silently converted
into saved human labels. A broader 5–10-trace usability review is still pending.
Workshop instrumentation and review were not performed (optional Part C).
