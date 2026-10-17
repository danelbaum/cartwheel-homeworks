# Homework 1 evidence

## Part C example: current-status relevance

The student expected “What’s the status of my order #4127?” to return only the latest event and date in prose. The original response included purchase/shipment history and a refund invitation. The student identified missing specificity in the specification and prompt. SPEC.md RESP-6 formalizes the chosen behavior; the active prompt's current-status section implements it.

`hw1-session.jsonl` preserves the actual original response. `before-prompt.txt` reconstructs the original Part B template and matches its captured hash b955415137f0. `baseline-repeat-trace.txt` is a fresh repeat with that template; `after-trace.txt` uses the saved `tested-after-prompt.txt` (f707675255e1). Both used GPT-4o mini, shopper 1, identical current tool code, and an isolated deterministic dev seed. Both called get_order and received the same order evidence. The repeat baseline included history and a closing invitation; the revised answer was “Your order was delivered on June 19, 2026.”

`prompt-changes.diff` preserves exact changes, including other accumulated revisions. This is a consolidated intervention and one observed comparison, not an isolated causal test of one sentence or a guarantee of reliability. The rejected alternate prompt is not active. Separate Juniper experiments did not establish the intended relevance improvement.

## Other evidence

- Original merchant-denial trace demonstrates a real tool-enforced cross-store denial. Fresh rehearsal replies that skipped tools are not presented as enforcement evidence.
- Original large-refund trace shows queued approval, not completed payment.
- Northwind before/after traces demonstrate deterministic resolution of 45-day store policy instead of 30-day platform default. Remaining deadline/citation/unknown-requirement errors are documented in the checkpoint summary; the tool improvement did not make the entire answer correct.

The original ten records retain the student's assessments. Some presentation expectations were formalized after their runs; these are annotated rather than represented as original specification requirements. Cases 8–10 were proposed by the assistant and reviewed by the student; final selection as the student's additional case designs remains pending. Video recording/upload is also pending.
