# Homework 1 checkpoint

Implemented all five HW1 tools plus read-only refund-eligibility explanation and applicable return-policy resolution. Shared authorization denial explanations distinguish merchant store scope from shopper ownership scope without exposing inaccessible order fields. Existing permission predicates, refund thresholds, approval behavior, and kill switches are preserved.

`hw1-session.jsonl` preserves ten actual original conversations and the student's assessments. Original prompt versions and retrospective criteria are annotated. All three roles are represented. Three additional cases were assistant-proposed and remain subject to the student's design confirmation. Generated database, API keys, and session files are excluded from version control.

## Verification

- Full offline suite: 170 passed, 4 skipped, 19 expected failures, 8 unexpected passes. The 8 passes are implemented HW1 tests still marked xfail by the starter.
- Focused HW1 contracts with --runxfail: 8 passed.
- Validated all ten JSONL records, required fields, boolean assessments, and failure-source labels.

## Observed improvements and limitations

Eligibility evidence improved explanation of the expired return window. Policy resolution correctly retrieved Northwind's 45-day override, but the model still mishandled unknown procedural deadlines and omitted citations in live tests. The resolver supports only returns in the generated course corpus; it compares published bodies with configured templates and flags differences for review, rather than parsing arbitrary policy language.

An order's stored refunded state and its queued refund record were inconsistent in case 10; no automatic data correction was made. Product listing condition detail and verified Help Center links remain incomplete. Existing active prompt still lacks explicit account-change escalation wording, despite specification ESC-2. The proposed prompt containing that correction was not activated.

Two controlled exploratory comparisons used GPT-4o mini, shopper user 1, unchanged current tools, and fresh conversations for the question: “How long do I have to return an item bought from Juniper Home Goods?” The active prompt f707675255e1 incorrectly selected an unrelated order and used its 30-day window. Proposed prompt ea2e574719f8 correctly returned 14 days but repeated the unrequested 30-day comparison in both runs. Thus the proposal did not fix the target relevance failure. The historical correct-but-verbose baseline predates tool changes; compare it cautiously. No proposal was activated and no claim of full model compliance is made.

## Remaining deliverables

Finalize the student's choice of additional scenarios and final prompt, summarize before/after evidence, record the student's continuous video of no more than five minutes, and submit through the course channel. A commit is a checkpoint, not proof that those deliverables or all discovered failures are complete.
