"""Resolve the seeded world's explicit return-policy relationships.

The course corpus is generated from facts and store records. Check those
documents against their templates rather than infer applicability via search.
This is deliberately not a general natural-language policy parser.
"""
from agent.config import load_facts
from agent.helpcenter import load_policy_docs
from seed.eligibility import effective_return_window_days
from seed.policies import render_platform_policies, render_store_policy


def resolve_return_policy(store):
    facts = load_facts()
    expected = [p for p in render_platform_policies(facts)
                if p.policy_id in {"cw-returns", "cw-store-overrides", "cw-restocking-fees"}]
    store_doc = render_store_policy(facts, store.name, store.slug,
                                   store.return_window_days_override, store.restocking_fee_opt_in)
    if store_doc:
        expected.append(store_doc)
    docs = load_policy_docs()
    ids = [p.policy_id for p in docs]
    selected = []
    for template in expected:
        if ids.count(template.policy_id) != 1:
            return {"ok": False, "error": "data_inconsistent",
                    "reason": "An applicable policy is missing or has duplicate identifiers; human review is required."}
        doc = next(p for p in docs if p.policy_id == template.policy_id)
        expected_body = f"# {template.title}\n\n{template.body}"
        if " ".join(doc.body.split()) != " ".join(expected_body.split()):
            return {"ok": False, "error": "data_inconsistent",
                    "reason": "Published policy differs from the configured course rules; human review is required."}
        selected.append({"policy_id": doc.policy_id, "title": doc.title, "body": doc.body})
    if not store_doc and f"store-{store.slug}-policy" in ids:
        return {"ok": False, "error": "data_inconsistent",
                "reason": "A published store policy is not represented in the configured rules; human review is required."}
    return {
        "ok": True,
        "return_window_days": effective_return_window_days(facts["return_window_days"], store.return_window_days_override),
        "store_override_days": store.return_window_days_override,
        "window_source": store_doc.policy_id if store.return_window_days_override is not None else "cw-returns",
        "store_has_policy": store_doc is not None,
        "policy_references": selected,
        "condition_rule": "Items must be in the condition described by the store's listing.",
        "specific_condition_requirements": None,
        "condition_note": "No structured condition/packaging requirements are available; do not infer unused or original packaging.",
        "restocking_fee": {
            "store_opted_in": store.restocking_fee_opt_in,
            "max_percent": facts["restocking_fee_max_percent"] if store.restocking_fee_opt_in else 0,
            "applies_to": "Opened items only" if store.restocking_fee_opt_in else "No fee under the configured store policy",
        },
        "deadline_semantics": {
            "required_event": None,
            "note": "Policy does not specify whether requesting, shipping, or receipt must occur by the deadline.",
            "eligibility_day_boundary": "inclusive",
            "boundary_source": "Existing deterministic eligibility oracle: elapsed calendar days <= applicable window",
            "time_of_day": None, "timezone": None,
        },
    }
