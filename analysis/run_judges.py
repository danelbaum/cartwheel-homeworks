"""HW5 input preparation, fixed splits, and explicit development/test runners.

Importing this module makes no provider calls. Run development/test functions
only for authorized batches. Original inputs and splits are immutable.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from analysis.helpers import split_labels, register_judge, run_judge, judge_alignment
from analysis.helpers.normalization import normalize_trace

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "analysis/state"
MODE = "unnecessary_detail_or_repetition"
INPUTS = STATE / "hw5_trace_inputs.json"


def read(path):
    return json.loads(path.read_text())


def save_once(path, value):
    if path.exists():
        if read(path) != value:
            raise ValueError(f"Refusing to replace different saved data: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def labels(mode=MODE):
    rows = [json.loads(line) for line in
            (STATE / f"hw5_labels/{mode}.jsonl").read_text().splitlines() if line]
    live = {r["trace_id"]: r for r in rows if not r.get("superseded_by")}
    return {k: v for k, v in live.items() if v.get("eligible_for_split")}


def clean(messages):
    """Allow only observed message text and tool evidence, never review metadata."""
    result = []
    for message in messages:
        role = message["role"]
        if role == "system":
            continue
        for part in message.get("parts", []):
            kind = part["type"]
            if kind == "text":
                if part.get("content", "").strip():
                    result.append({"role": role, "text": part["content"]})
            elif kind == "tool_call":
                result.append({"role": "tool_call", "name": part["name"],
                               "arguments": {"name": part["name"],
                                             "arguments": part["arguments"]}})
            elif kind == "tool_call_response":
                result.append({"role": "tool_result", "content": part["response"]})
            else:
                raise ValueError(f"Unsupported evidence part: {kind}")
    return result


def turn(record):
    generations = sorted((o for o in record["observations"]
                          if o.get("type") == "GENERATION"),
                         key=lambda o: o["startTime"])
    if not generations:
        raise ValueError(f"Missing model evidence for {record['id']}")
    last = generations[-1]
    messages = last["input"]["messages"]
    requested = clean(record["input"])
    # The last model request contains all tool exchanges in the current turn.
    # Find its current user request without treating prior turns as fresh output.
    positions = [i for i, m in enumerate(messages)
                 if m.get("role") == "user" and clean([m]) == requested]
    if not positions:
        raise ValueError("Current user message not present in model input")
    start = positions[-1]
    current = clean(messages[start:]) + clean(last["output"])
    expected = clean(record["output"])
    if current[-len(expected):] != expected:
        raise ValueError("Final model output differs from recorded response")
    # Ensure every generation's actual tool calls survived the final input.
    calls = [m for g in generations for m in clean(g.get("output") or [])
             if m["role"] == "tool_call"]
    if [m for m in current if m["role"] == "tool_call"] != calls:
        raise ValueError("Incomplete tool-call history")
    if sum(m["role"] == "tool_result" for m in current) != len(calls):
        raise ValueError("Incomplete tool results")
    return clean(messages[:start]), current, messages


def prepare_inputs(mode=MODE):
    selected = labels(mode)
    raw = read(ROOT / "traces/support_traces.json")["traces"]
    index = {r["id"]: r for r in raw}
    sessions = defaultdict(list)
    for r in raw:
        sessions[r["metadata"]["attributes"]["cartwheel.session_id"]].append(r)
    assert len({r["session_id"] for r in selected.values()}) == len(selected)
    assert len({r["dedup_group"] for r in selected.values()}) == len(selected)
    records = []
    history_records = 0
    for tid in sorted(selected):
        target = index[tid]
        session = sorted(sessions[selected[tid]["session_id"]], key=lambda r: r["timestamp"])
        conversation = []
        for r in session:
            prior, current, model_messages = turn(r)
            if not conversation:
                # Keep authenticated role context, not the agent's full prompt.
                system_text = "\n".join(p.get("content", "") for m in model_messages
                                        if m["role"] == "system" for p in m.get("parts", []))
                context = [line for line in system_text.splitlines()
                           if line.startswith(("- User role:", "- User id:", "- Store id:"))]
                if context:
                    conversation.append({"role": "system", "text": "Authenticated session context:\n" + "\n".join(context)})
                conversation.extend(prior)
            conversation.extend(current)
            if r["id"] == tid:
                break
        assert conversation[-1]["role"] == "assistant"
        assert conversation[-1] == clean(target["output"])[-1]
        history_records += sum(m["role"] == "user" for m in conversation) > 1
        record = {"trace_id": tid, "trace": conversation}
        # Verify the downstream judge sees the message content, not empty parts.
        normalized = normalize_trace(record)
        assert conversation[-1]["text"] in normalized["text"]
        records.append(record)
    assert {r["trace_id"] for r in records} == set(selected)
    save_once(INPUTS, records)
    os.environ["CARTWHEEL_JUDGE_TRACE_SOURCE"] = str(INPUTS)
    manifest = {"mode": mode, "input_count": len(records),
                "conversations_with_history": history_records,
                "input_sha256": hashlib.sha256(INPUTS.read_bytes()).hexdigest(),
                "label_counts": dict(Counter(r["verdict"] for r in selected.values())),
                "label_encoding": "Pass=1, Fail=0", "network_calls": 0,
                "evidence_policy": "Observed user/assistant text, tool arguments/results, retrieved policies, authenticated session context. No labels, annotations, scenario metadata or reviewer notes."}
    save_once(STATE / "hw5_input_manifest.json", manifest)
    return records


def split_data(mode=MODE):
    records = read(INPUTS)
    eligible = [r["trace_id"] for r in records]
    os.environ["CARTWHEEL_ANALYSIS_STATE"] = str(STATE)
    existing = read(STATE / "splits.json") if (STATE / "splits.json").exists() else {}
    if mode in existing:
        saved = existing[mode]
        assignment = {k: saved[k] for k in ("train", "dev", "test")}
        if saved["seed"] != 7 or saved["fractions"] != [0.2, 0.4, 0.4]:
            raise ValueError("Existing split has different parameters")
    else:
        assignment = split_labels(mode, fractions=(0.2, 0.4, 0.4), seed=7,
                                  min_per_class=10, eligible_trace_ids=eligible)
    combined = [tid for ids in assignment.values() for tid in ids]
    assert len(combined) == len(set(combined)) and set(combined) == set(eligible)
    saved_all = read(STATE / "splits.json")
    assert all(saved_all[k] == v for k, v in existing.items() if k != mode)
    by_id = labels(mode)
    counts = {name: dict(Counter(by_id[tid]["verdict"] for tid in ids))
              for name, ids in assignment.items()}
    save_once(STATE / "hw5_split_summary.json",
              {"mode": mode, "seed": 7, "fractions": [0.2, 0.4, 0.4], "counts": counts})
    return assignment


def run_development(mode, prompt_path):
    """Run an authorized development batch; reuse the registered version on resume."""
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    os.environ["DOCETL_HOME_DIR"] = str(ROOT / "work/hw5-docetl")
    os.environ["CARTWHEEL_ANALYSIS_STATE"] = str(STATE)
    os.environ["CARTWHEEL_JUDGE_TRACE_SOURCE"] = str(INPUTS)
    manifest = read(STATE / "hw5_input_manifest.json")
    if hashlib.sha256(INPUTS.read_bytes()).hexdigest() != manifest["input_sha256"]:
        raise ValueError("Judge inputs changed since preparation")
    prompt_text = Path(prompt_path).read_text()
    history_path = STATE / f"judges/_history_{mode}.json"
    history = read(history_path) if history_path.exists() else {"versions": []}
    matching = []
    for version in history["versions"]:
        judge = read(STATE / f"judges/{version['judge_id']}.json")
        if judge["prompt_text"] == prompt_text and judge["model"] == "gpt-4o-mini":
            matching.append(judge["judge_id"])
    judge_id = matching[-1] if matching else register_judge(
        mode=mode, prompt_text=prompt_text, judge_model="gpt-4o-mini")["judge_id"]
    run_judge(judge_id, split="dev", batch_size=10)
    metrics = judge_alignment(judge_id, split="dev")
    report = ROOT / f"analysis/report/dev-{judge_id}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(metrics, indent=2) + "\n")
    return {"judge_id": judge_id, "metrics": metrics}


def run_test(judge_id):
    """Freeze the selected judge once, then run or resume its authorized test batch."""
    from dotenv import load_dotenv
    from analysis.helpers import freeze_judge

    load_dotenv(ROOT / ".env")
    os.environ["DOCETL_HOME_DIR"] = str(ROOT / "work/hw5-docetl")
    os.environ["CARTWHEEL_ANALYSIS_STATE"] = str(STATE)
    os.environ["CARTWHEEL_JUDGE_TRACE_SOURCE"] = str(INPUTS)
    manifest = read(STATE / "hw5_input_manifest.json")
    if hashlib.sha256(INPUTS.read_bytes()).hexdigest() != manifest["input_sha256"]:
        raise ValueError("Judge inputs changed since preparation")
    judge = read(STATE / f"judges/{judge_id}.json")
    if judge["status"] != "frozen":
        freeze_judge(judge_id)
    run_judge(judge_id, split="test", batch_size=10)
    metrics = judge_alignment(judge_id, split="test")
    report = ROOT / f"analysis/report/test-{judge_id}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(metrics, indent=2) + "\n")
    return {"judge_id": judge_id, "metrics": metrics}


if __name__ == "__main__":
    prepare_inputs()
    split_data()
    print(json.dumps(read(STATE / "hw5_input_manifest.json"), indent=2))
    print(json.dumps(read(STATE / "hw5_split_summary.json"), indent=2))
