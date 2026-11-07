"""Recalculate original HW5 test metrics offline from saved verdicts and labels."""
import json
import math
from pathlib import Path

data = json.loads(Path(__file__).with_name("hw5-v2-test-results.json").read_text())
rows = data["comparisons"]
assert len(rows) == 25 and len({r["trace_id"] for r in rows}) == 25
assert all(r[k] in {"Pass", "Fail"} for r in rows for k in ("human_verdict", "judge_verdict"))
tp = sum(r["human_verdict"] == r["judge_verdict"] == "Pass" for r in rows)
tn = sum(r["human_verdict"] == r["judge_verdict"] == "Fail" for r in rows)
fp = sum(r["human_verdict"] == "Fail" and r["judge_verdict"] == "Pass" for r in rows)
fn = sum(r["human_verdict"] == "Pass" and r["judge_verdict"] == "Fail" for r in rows)

def wilson(successes, total):
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z*z/total
    center = (p + z*z/(2*total)) / denominator
    radius = z*math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / denominator
    return center-radius, center+radius

print("Frozen v2 | gpt-4o-mini | original test labels")
print("Offline calculation from 25 saved predictions; no model calls.\n")
print(f"Human Pass: {tp+fn}; Human Fail: {tn+fp}")
print(f"TP={tp}, FN={fn}, TN={tn}, FP={fp}")
for title, successes, total in [("TPR (correct Passes)", tp, tp+fn), ("TNR (correct Fails)", tn, tn+fp)]:
    low, high = wilson(successes, total)
    print(f"{title}: {successes}/{total} = {successes/total:.1%}; 95% Wilson CI {low:.1%}–{high:.1%}")
print(f"Agreement: {tp+tn}/{len(rows)} = {(tp+tn)/len(rows):.1%}")
print("\nLater label corrections and model comparisons are separate analyses.")
