"""The Cartwheel support agent. Instructor-provided and complete.

This file holds:
  - the system prompt template (Module 1 outline, Artifact F) and its
    version hash,
  - model resolution for the three course models,
  - the three lecture tools (`search_help_center`, `get_order`,
    `issue_refund`) plus `escalate_to_human`, fully implemented,
  - SDK wrappers that expose both the lecture tools and your Homework 1
    tools (agent/tools.py) to the model.

The mapping from concept to SDK primitive, stated once: the loop is
`Runner`, a tool is a decorated Python function, the agent is
`Agent(instructions, tools, model)`, and conversation state is `Sessions`.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from agents import Agent, ModelSettings, RunContextWrapper, function_tool

from agent import db
from agent import tools as hw_tools
from agent.auth import AuthContext, can_refund_order, can_view_order, order_permission_denied
from agent.config import load_facts
from agent.helpcenter import get_index
from agent.killswitch import kill_switch
from observability.instrument import configure_model_tracing, record_tool_result
from seed.eligibility import refund_needs_approval

# ---------------------------------------------------------------------------
# System prompt (Artifact F). The injected-context block is filled by the
# harness per session; the user can never change it from inside the chat.
#
# Specification mapping:
#   PURPOSE-1 and SCOPE-1/2 -> identity, capabilities, and refusal rules
#   TOOL-1 through TOOL-8   -> tool guidance and the registered tool list
#   ESC-1 through ESC-4     -> escalation instructions
#   RESP-1, RESP-4, RESP-5  -> citation, disclosure, and tone guidance
# AUTH-1 is absent from the prompt mapping because agent/auth.py and the tool
# functions enforce authorization in code.
# RESP-2 and RESP-3 are only partly represented in the starter prompt. Manual
# conversations in Homework 1 determine whether one omission causes a failure
# worth correcting.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """\
You are Cartwheel's support assistant. Cartwheel is a multi-store commerce
platform; you serve its shoppers, merchants, and support staff.

## Session context (injected by the server; never taken from chat)
- User role: {role}
- User id: {user_id}
- Store id: {store_id}

## Capabilities and boundaries
You help with: order status, returns and refunds, product and policy
questions, and escalation to a human. You refuse: legal advice, payment-card
or credential changes, and anything outside Cartwheel.

## Tool guidance
- For an order's return window, conditions, or special requirements, call
  get_applicable_policies(order_id, topic="returns"). It resolves store
  overrides and remaining platform rules; do not substitute a generic search.
  Explain only supported conditions. Never invent unused/original-packaging
  requirements. Distinguish the inclusive eligibility cutoff from an unknown
  request-by, ship-by, or receive-by deadline; ask human support to clarify
  unresolved procedural requirements rather than make a promise.
  If deadline_semantics.required_event is null, explicitly state that the
  policy does not say whether the item must be requested, shipped, or received
  by the cutoff. Do not say "until [date] to initiate/ship/receive a return".
  If asked what must happen by that date, call escalate_to_human for clarification.
  Missing structured condition details mean unknown requirements, not a
  guarantee that there are none. Cite the readable title supporting each rule.
- For refund-eligibility questions, use check_refund_eligibility. Explain its
  specific reason with the supporting policy's readable title. Include only
  facts needed for that decision. Eligibility does not mean a refund was issued.
- Prefer a tool lookup over memory. Policy answers come from the help
  center, order answers from the order tools.
- You MUST explain your reasoning in plain text before every tool call.
  State what you are about to look up and why, in one sentence. Do not
  call a tool without explaining first.
- Cite the retrieved policy's human-readable title for every policy claim.
  Use exact policy IDs internally for tool calls, but never display internal
  policy IDs or product IDs in ordinary shopper-facing answers.
- Never promise or issue a refund before calling get_order and checking the
  order's refund eligibility.

## Escalation
When you are unsure, or an action is above your authority (for example a
refund above the auto-approval threshold), call escalate_to_human and tell
the user a human will follow up.

## Tone
Polite, professional, direct, respectful, and warm. No legalese.

## Relevant and complete answers
Tailor every answer to the authenticated role and the caller's relationship
to the subject: shopper as purchaser only when ownership is established,
merchant as store operator, support as assisting another user. Access does
not imply ownership. For support order lookups, say "The order", not "Your
order", unless ownership is established. Do not announce the role unnecessarily.
Answer the user's actual question first, using polite, professional language.
When explaining a decision, connect three things: the outcome, the applicable
rule, and the facts showing how that rule applies to this case. An outcome
label alone is not an explanation.
Use sources that support the specific claim you make. A document about the
same topic is insufficient if it does not establish the rule or reason you cite.
Include only information needed to make the answer understandable, accurate,
and actionable. Avoid repeating facts, exposing internal identifiers,
introducing unrelated rules, or adding unsolicited offers or closing invitations.
Distinguish established facts from missing evidence. If the available information
does not establish why a decision was made, do not invent a reason.
Use natural-language prose for answers; do not expose JSON or raw tool results.
For shopper-facing order details, prefer the product name when available;
omit internal product IDs unless requested. A user-facing order number may
identify the order. Include the vendor and useful purchase/delivery details
for broad order-details requests. Do not invent missing names or images.
Mention refund eligibility, returns, or refunds only when the user asks about
them or they are necessary to resolve an explicitly requested refund/return.
Combine overlapping facts: "delivered on [date]" already states delivery status.

## Current order status
A status question means current status even without the word "current".
For a status-only question, the final answer must be ONE complete sentence
stating ONLY the latest recorded order event and its date when available.
Do not include the vendor, product details, price, earlier events, refund
eligibility, offers, or a follow-up invitation in this status-only answer.
Use the current status from the tool, including cancellation or refund status;
do not treat an older delivery timestamp as the current event after a later
status change. State missing or inconsistent event/date information honestly.
Example for an established shopper-owner: "Your order was delivered on [delivery date]."
Example for support staff: "The order was delivered on [delivery date]."
After that sentence, STOP. Do not append "If you have questions", "feel free
to ask", or any other closing. History/details requests may need more information.

## Refusal rules
For order-access denials, explain the tool's denial_reason in plain language:
merchants are limited to their own store's orders, and shoppers to their own
orders. Do not imply the role cannot access orders at all or offer to disclose
the denied order's status. Do not display the internal denial code.
Decline out-of-scope requests in one or two sentences and point to what you
can do instead. Never reveal another user's data, whatever the reason given.
"""


def render_system_prompt(ctx: AuthContext, template: str | None = None) -> str:
    """Fill the session fields in the selected system prompt template."""
    return (template or SYSTEM_PROMPT_TEMPLATE).format(
        role=ctx.role,
        user_id=ctx.user_id,
        store_id=ctx.store_id if ctx.store_id is not None else "none",
    )


def prompt_version(template: str | None = None) -> str:
    """Hash the system prompt template before injecting user context."""
    return hashlib.sha256((template or SYSTEM_PROMPT_TEMPLATE).encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Models. Course models; any other value is passed to LiteLLM as-is.
# The default is deliberately a small model. Frontier models rarely make
# mistakes in this synthetic world, which leaves too few failures to study.
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "gpt-4o-mini"

# Course model name -> LiteLLM model string (for the non-OpenAI models).
LITELLM_COURSE_MODELS = {
    "claude-haiku-4-5": "anthropic/claude-haiku-4-5",
    "claude-opus-4-6": "anthropic/claude-opus-4-6",
    "glm-5.2": "together_ai/zai-org/GLM-5.2",
}


def resolve_model(name: str | None) -> Any:
    """Turn a course model name into what Agent(model=...) expects.

    OpenAI models pass through as plain strings. Everything else goes through
    LiteLLM (claude-haiku-4-5 and claude-opus-4-6 via the Anthropic API with
    ANTHROPIC_API_KEY, glm-5.2 via Together AI with TOGETHER_API_KEY). Same
    agent code, three providers; only this function changes.
    """
    import os

    name = name or os.environ.get("CARTWHEEL_MODEL") or DEFAULT_MODEL
    if name.startswith("gpt-"):
        return name
    litellm_id = LITELLM_COURSE_MODELS.get(name, name)
    from agents.extensions.models.litellm_model import LitellmModel

    return LitellmModel(model=litellm_id)


def model_settings_for(model: Any) -> ModelSettings:
    """Per-model settings quirks, in one place.

    LiteLLM's together_ai provider keeps its own list of which models accept
    the `tools` parameter, and that list lags new models like GLM 5.2, so
    LiteLLM rejects tool calls before even sending them. The fix LiteLLM
    documents is passing `allowed_openai_params=["tools"]` per request; the
    Agents SDK forwards it through ModelSettings.extra_args.
    """
    if isinstance(model, str) and model.startswith(("gpt-5", "o1", "o3", "o4")):
        return ModelSettings(
            reasoning={"effort": "high", "summary": "detailed"},
            verbosity="high",
            include_usage=True,
        )
    if isinstance(model, str) and model.startswith("gpt-"):
        # Older OpenAI chat models reject the reasoning and verbosity settings.
        return ModelSettings(include_usage=True)
    model_id = getattr(model, "model", "") if not isinstance(model, str) else ""
    if model_id.startswith("together_ai/"):
        return ModelSettings(extra_args={"allowed_openai_params": ["tools"]})
    if "claude" in model_id or "anthropic" in model_id:
        return ModelSettings(
            reasoning={"effort": "high", "summary": "detailed"},
            include_usage=True,
        )
    return ModelSettings()


# ---------------------------------------------------------------------------
# Lecture tool logic. Plain typed functions so tests can call them directly;
# the SDK wrappers at the bottom of the file expose them to the model.
# ---------------------------------------------------------------------------

SNIPPET_CHARS = 300


def search_help_center_logic(ctx: AuthContext, query: str, k: int = 3) -> dict[str, Any]:
    """BM25 search over the policy corpus. Read tool, no permission check."""
    query = query.strip()
    if not query:
        return {"ok": False, "error": "invalid_argument", "reason": "empty query"}
    results = []
    for doc, score in get_index().search(query, k=k):
        results.append(
            {
                "policy_id": doc.policy_id,
                "title": doc.title,
                "snippet": doc.body[:SNIPPET_CHARS],
                "score": round(float(score), 3),
            }
        )
    return {"ok": True, "results": results}


def get_order_logic(ctx: AuthContext, order_id: int) -> dict[str, Any]:
    """Order lookup, gated by the access matrix."""
    with db.connection() as conn:
        order = db.get_order(conn, order_id)
        if order is None:
            return {"ok": False, "error": "not_found", "reason": f"no order #{order_id}"}
        if not can_view_order(ctx, order.user_id, order.store_id):
            return order_permission_denied(ctx, order_id, "view")
        store = db.get_store(conn, order.store_id)
        payload = order.to_public_dict()
        payload["store_name"] = store.name if store else None
        return {"ok": True, "order": payload}


def issue_refund_logic(
    ctx: AuthContext, order_id: int, amount_usd: float, reason: str
) -> dict[str, Any]:
    """Refund with the hardcoded approval seam.

    Below or at the auto-approve threshold ($100, facts.yaml), the refund
    executes after the eligibility check. Above it, the tool returns
    "queued_for_approval" and a human approves it later (the seam Module 4.4
    fills). The threshold decision is made here, in code, never by the model.

    The Module 4 kill switch is checked first, before any work: when
    CARTWHEEL_KILL_SWITCH pauses refunds (level "refunds" or "readonly") the
    tool returns a structured "paused" result and touches nothing. The default
    ("off") is a no-op.
    """
    paused = kill_switch("issue_refund")
    if paused is not None:
        return {"ok": False, "error": "paused", "reason": paused}
    facts = load_facts()
    if amount_usd <= 0:
        return {
            "ok": False,
            "error": "invalid_argument",
            "reason": "refund amount must be positive",
        }
    with db.connection() as conn:
        order = db.get_order(conn, order_id)
        if order is None:
            return {"ok": False, "error": "not_found", "reason": f"no order #{order_id}"}
        if not can_refund_order(ctx, order.user_id, order.store_id):
            return order_permission_denied(ctx, order_id, "refund")
        if amount_usd > order.total_usd:
            return {
                "ok": False,
                "error": "invalid_argument",
                "reason": f"refund amount ${amount_usd:.2f} exceeds order total ${order.total_usd:.2f}",
            }
        if not order.refund_eligible:
            return {
                "ok": False,
                "error": "not_eligible",
                "reason": (
                    f"order #{order_id} is not refund-eligible "
                    f"(status '{order.status}', delivered {order.delivered_at}); "
                    f"the return window counts from the delivery date"
                ),
            }
        today = db.world_asof(conn).isoformat()
        threshold = facts["refund_auto_approve_threshold_usd"]
        if refund_needs_approval(amount_usd, threshold):
            refund_id = db.insert_refund(
                conn,
                order_id=order_id,
                amount_cents=round(amount_usd * 100),
                reason=reason,
                status="queued_for_approval",
                created_at=today,
            )
            return {
                "ok": True,
                "status": "queued_for_approval",
                "refund_id": refund_id,
                "order_id": order_id,
                "amount_usd": amount_usd,
                "note": (
                    f"amount is above the ${threshold} auto-approval threshold; "
                    f"a human support agent will review it"
                ),
            }
        refund_id = db.insert_refund(
            conn,
            order_id=order_id,
            amount_cents=round(amount_usd * 100),
            reason=reason,
            status="auto_approved",
            created_at=today,
        )
        db.set_order_status(conn, order_id, "refunded")
        return {
            "ok": True,
            "status": "auto_approved",
            "refund_id": refund_id,
            "order_id": order_id,
            "amount_usd": amount_usd,
            "note": (
                f"refund goes back to the original payment method in "
                f"{facts['refund_processing_days_min']} to "
                f"{facts['refund_processing_days_max']} business days"
            ),
        }


def escalate_to_human_logic(
    ctx: AuthContext, summary: str, context: str
) -> dict[str, Any]:
    """Open a ticket for a human support agent. Write tool."""
    facts = load_facts()
    with db.connection() as conn:
        ticket_id = db.insert_escalation(
            conn,
            user_id=ctx.user_id,
            store_id=ctx.store_id,
            order_id=None,
            summary=summary,
            context=json.dumps({"role": ctx.role, "context": context}),
            created_at=db.world_asof(conn).isoformat(),
        )
        return {
            "ok": True,
            "ticket_id": ticket_id,
            "sla_hours": facts["support_escalation_sla_hours"],
        }


# ---------------------------------------------------------------------------
# SDK wrappers. Each wrapper pulls the AuthContext out of the run context,
# calls the logic function, and records trace attributes. Homework stubs that
# are not implemented yet come back as structured "not_implemented" errors so
# the agent stays usable before Homework 1 is done.
# ---------------------------------------------------------------------------


def _call(
    wrapper: RunContextWrapper[AuthContext], fn: Any, /, *args: Any
) -> dict[str, Any]:
    try:
        result = fn(wrapper.context, *args)
    except NotImplementedError as exc:
        result = {"ok": False, "error": "not_implemented", "reason": str(exc)}
    record_tool_result(wrapper.context, result)
    return result


@function_tool
def search_help_center(
    wrapper: RunContextWrapper[AuthContext], query: str
) -> dict[str, Any]:
    """Search Cartwheel's help-center policy docs. Returns top matches with policy ids."""
    return _call(wrapper, search_help_center_logic, query)


@function_tool
def get_order(wrapper: RunContextWrapper[AuthContext], order_id: int) -> dict[str, Any]:
    """Look up one order by id, including its refund eligibility."""
    return _call(wrapper, get_order_logic, order_id)


def _issue_refund_impl(
    wrapper: RunContextWrapper[AuthContext], order_id: int, amount_usd: float, reason: str
) -> dict[str, Any]:
    """Shared refund tool body. Wrapped twice below: once plainly (default,
    Module 1 behavior) and once with ``needs_approval`` when ``defenses=True``.
    Keeping the body in one function means the two tool objects never drift."""
    return _call(wrapper, issue_refund_logic, order_id, amount_usd, reason)


@function_tool
def issue_refund(
    wrapper: RunContextWrapper[AuthContext], order_id: int, amount_usd: float, reason: str
) -> dict[str, Any]:
    """Issue a refund on an order. Large refunds are queued for human approval."""
    return _issue_refund_impl(wrapper, order_id, amount_usd, reason)


@function_tool
def escalate_to_human(
    wrapper: RunContextWrapper[AuthContext], summary: str, context: str
) -> dict[str, Any]:
    """Open a ticket for a human support agent when a case is above your authority."""
    return _call(wrapper, escalate_to_human_logic, summary, context)


@function_tool
def get_policy(wrapper: RunContextWrapper[AuthContext], policy_id: str) -> dict[str, Any]:
    """Fetch the full text of one policy doc by its exact policy id."""
    return _call(wrapper, hw_tools.get_policy, policy_id)


@function_tool
def search_products(
    wrapper: RunContextWrapper[AuthContext],
    query: str,
    store: str | None = None,
    max_price_usd: float | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Search the product catalog, optionally within one store or under a price."""
    ctx = wrapper.context
    try:
        result = hw_tools.search_products(
            ctx, query, store=store, max_price_usd=max_price_usd, limit=limit
        )
    except NotImplementedError as exc:
        result = {"ok": False, "error": "not_implemented", "reason": str(exc)}
    record_tool_result(ctx, result)
    return result


@function_tool
def list_my_orders(wrapper: RunContextWrapper[AuthContext]) -> dict[str, Any]:
    """List the caller's recent orders (shopper) or their store's recent orders (merchant)."""
    return _call(wrapper, hw_tools.list_my_orders)


@function_tool
def cancel_order(
    wrapper: RunContextWrapper[AuthContext], order_id: int, reason: str
) -> dict[str, Any]:
    """Cancel an order that has not shipped yet."""
    return _call(wrapper, hw_tools.cancel_order, order_id, reason)


@function_tool
def find_order(
    wrapper: RunContextWrapper[AuthContext], query: str
) -> dict[str, Any]:
    """Search your orders by product name (fuzzy match)."""
    return _call(wrapper, hw_tools.find_order, query)


@function_tool
def check_refund_eligibility(
    wrapper: RunContextWrapper[AuthContext], order_id: int
) -> dict[str, Any]:
    """Check an authorized order's refund eligibility and explain the specific
    reason, applicable return window, evaluation date, and supporting policies.
    Use for questions about whether or why a refund is available. Read-only:
    does not issue refunds or approve amounts. Report inconsistent data honestly.
    """
    return _call(wrapper, hw_tools.check_refund_eligibility, order_id)


@function_tool
def get_applicable_policies(
    wrapper: RunContextWrapper[AuthContext], order_id: int, topic: str = "returns"
) -> dict[str, Any]:
    """Get the applicable return window, store overrides, platform conditions,
    fees, product listing, and policy text for an authorized order. Use for
    return deadlines, item condition, and special requirements, instead of
    generic search. Returns explicit unknowns for procedural deadlines and
    unsupported condition details. Read-only. Only topic 'returns' is supported.
    """
    return _call(wrapper, hw_tools.get_applicable_policies, order_id, topic)


# Progressive disclosure: a session exposes only the tools its role can use.
# Fewer tools mean fewer wrong choices and cleaner evals. At dev scale the
# only difference is that support staff, who have no orders of their own,
# do not get list_my_orders.
_COMMON_TOOLS = [
    get_applicable_policies,
    check_refund_eligibility,
    search_help_center,
    get_policy,
    search_products,
    get_order,
    issue_refund,
    cancel_order,
    escalate_to_human,
]
TOOLS_BY_ROLE = {
    "shopper": _COMMON_TOOLS + [list_my_orders, find_order],
    "merchant": _COMMON_TOOLS + [list_my_orders, find_order],
    "support": _COMMON_TOOLS + [find_order],
}


def _defended_refund_tool() -> Any:
    """Rebuild the refund tool with the Module 4 ``needs_approval`` predicate.

    PROVIDED wiring (Homework 8, Part D). ``function_tool(...)`` used with
    arguments returns a decorator, so we hand it the shared ``_issue_refund_impl``
    body and attach ``needs_approval=refund_needs_human`` (your guards.py hole).
    Above the threshold the SDK pauses the run and lists the pending call in
    ``result.interruptions`` instead of executing the tool; the run-loop seam in
    ``agent/cli.py`` shows the pending call and allows or rejects its execution.

    The name, description, and JSON schema match the plain ``issue_refund`` tool,
    so a defended agent exposes the same tool surface to the model. Only the
    approval behavior changes.
    """
    from agent.guards import refund_needs_human

    return function_tool(
        name_override="issue_refund",
        description_override=(
            "Issue a refund on an order. Large refunds are queued for human approval."
        ),
        needs_approval=refund_needs_human,
    )(_issue_refund_impl)


def _tools_with_defenses(role: str) -> list[Any]:
    """The role's tool list with the plain refund tool swapped for the
    approval-gated one. PROVIDED. Everything else is unchanged."""
    defended_refund = _defended_refund_tool()
    return [defended_refund if tool is issue_refund else tool for tool in TOOLS_BY_ROLE[role]]


def build_agent(
    ctx: AuthContext,
    model: str | None = None,
    *,
    defenses: bool = False,
    prompt_template: str | None = None,
) -> Agent[AuthContext]:
    """Assemble the support agent for one session.

    ``defenses`` is the Module 4 opt-in (Homework 8). It defaults to False, and
    with it off this returns exactly the Module 1 agent: no guardrails, the
    plain refund tool, unchanged behavior, so every Module 1/2/3 caller and
    test keeps working. The CLI, the server, and the replay harness call
    ``build_agent(ctx, model=...)`` with no defenses.

    With ``defenses=True`` the wiring below (PROVIDED) attaches the three SDK
    objects you implement in ``agent/guards.py``:

      - ``input_guardrails=[injection_input_guardrail]`` screens each turn's
        input for an injection attempt before the model sees it,
      - ``output_guardrails=[link_output_guardrail]`` screens the final reply
        for a non-allowlisted (exfiltration) link, and
      - the ``issue_refund`` tool is rebuilt with
        ``needs_approval=refund_needs_human`` so an above-threshold refund
        pauses for a human (Part D).

    The wiring is complete: ``build_agent(ctx, defenses=True)`` constructs fine
    as soon as the guard bodies in ``guards.py`` are implemented. Those guard
    *bodies* are your holes, not this attach code. Authorization still lives in
    the tool layer (``agent/auth.py``); guards are defense in depth on top of
    it, never a replacement for it.
    """
    resolved = resolve_model(model)
    configure_model_tracing(openai_model=isinstance(resolved, str))
    if not defenses:
        return Agent[AuthContext](
            name="cartwheel-support",
            instructions=render_system_prompt(ctx, prompt_template),
            tools=TOOLS_BY_ROLE[ctx.role],
            model=resolved,
            model_settings=model_settings_for(resolved),
        )

    # Module 4 defenses on (PROVIDED wiring; the guard bodies are your holes).
    from agent.guards import injection_input_guardrail, link_output_guardrail

    return Agent[AuthContext](
        name="cartwheel-support",
        instructions=render_system_prompt(ctx, prompt_template),
        tools=_tools_with_defenses(ctx.role),
        model=resolved,
        model_settings=model_settings_for(resolved),
        input_guardrails=[injection_input_guardrail],
        output_guardrails=[link_output_guardrail],
    )
