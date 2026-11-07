Homework 5: unnecessary detail or repetition

Final judge: unnecessary_detail_or_repetition-v2, gpt-4o-mini, frozen.
Original test: 25 conversations (13 Pass, 12 Fail); TP 6, FN 7, TN 9, FP 3.
TPR 46.15% (95% Wilson CI 23.21–70.86%); TNR 75% (46.77–91.11%).
Agreement 60%. Student decision: not sufficiently reliable for production use.

Recalculate original test metrics offline, with no API calls:
  python3 analysis/report/recalculate-test-metrics.py
This reads hw5-v2-test-results.json beside the script, with the original labels.

Prompts: analysis/prompts/unnecessary_detail_or_repetition-v{0,1,2}.txt
Labels and review history: analysis/state/hw5_labels/
Fixed inputs: analysis/state/hw5_trace_inputs.json
Fixed split: analysis/state/splits.json
Judge prompts, predictions, critiques: analysis/state/judges/
Metric reports: analysis/report/dev-* and test-*

Workflow qualifications:
- The original 61-conversation split is unchanged: 12 train, 24 development,
  25 test. Development adjudication changed the class counts.
- Six supplemental Pass labels were collected after development began.
  Total eligible labels before post-test correction: 30 Pass, 37 Fail.
  Supplemental labels were not added to the immutable input export or splits.
  Thus the label-collection minimum is met, but the final split does not
  incorporate every eligible label. This is a deviation to disclose.
- v1 was registered but not evaluated; v0 and v2 were evaluated on development.
- The critical-context clarification was documented after v2 evaluation,
  and was not silently inserted into the frozen prompt.
- One post-test correction (082 Fail to Pass) is recorded separately.
  The original test report is preserved for reproduction.
- The optional gpt-4o comparison reused the same prompt and 25 test traces,
  with 082 corrected for BOTH models. It is a post-test exploratory comparison,
  not an independent untouched holdout evaluation or the homework final judge.
  Comparison records: analysis/state/post_test_gpt4o_comparison/.
  The isolated comparison's local version id v0 uses the exact main v2 prompt.
  Results: analysis/report/hw5-gpt4o-model-comparison.json.
- Video recording/submission remains the student's responsibility.

Read-only reproduction is preferred. Do not rerun input preparation or splitting
on the expanded labels: these functions deliberately reject replacing the
original saved inputs. Use the saved export and split for evaluated versions.
