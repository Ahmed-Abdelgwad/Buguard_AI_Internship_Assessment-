"""Agentic analysis mode — the LLM calls asset tools AND chain tools to answer questions.

The agent has two layers of tools:
  - asset_tools  : raw DB operations (search, get details, get relationships)
  - chain_tools  : full AI chains (nl_query, risk_scoring, enrichment, report)

This lets the agent compose multi-step answers — e.g. search for assets, enrich
the interesting ones, then score their risk — all in a single conversation turn.
"""
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, ToolMessage

from app.ai.llm import get_llm
from app.ai.tools.asset_tools import ALL_TOOLS as _ASSET_TOOLS
from app.ai.tools.chain_tools import CHAIN_TOOLS as _CHAIN_TOOLS
from app.schemas.analysis import AgentRequest, AgentResponse, AgentStep

ALL_TOOLS = _ASSET_TOOLS + _CHAIN_TOOLS

SYSTEM_PROMPT = """You are DarkAtlas AI, an expert security analyst for attack surface monitoring.

You have two categories of tools:

RAW DATABASE TOOLS (fast, no AI cost — use for discovery and lookup):
  - search_assets              : filter and list assets by type, status, tag, or value
  - get_asset_details          : full details of one asset by ID (includes metadata like cert expiry)
  - get_asset_relationships    : connected assets and relationship graph

AI CHAIN TOOLS (richer analysis — use when the user needs insights or scoring):
  - query_assets_natural_language : natural-language asset search with smart filtering
  - score_asset_risk              : AI risk scoring with severity findings and recommendations
  - enrich_asset                  : classify environment, category, criticality for one asset
  - generate_security_report      : write a narrative security report

Strategy:
1. Always use tools to fetch real data — never fabricate IDs, counts, or values.
2. For simple lookups, prefer the raw DB tools (cheaper and faster).
3. For analysis or insights, use the AI chain tools.
4. For multi-part questions, chain tools together: search → enrich → score → report.
5. To check certificate expiry, use get_asset_details and read the metadata.expires field.
6. If you cannot find relevant data, say so clearly.
7. Be concise and security-focused in your final answer.
"""


def run_agent(req: AgentRequest) -> AgentResponse:
    llm = get_llm()
    agent = create_agent(llm, ALL_TOOLS, system_prompt=SYSTEM_PROMPT)

    # recursion_limit caps tool-call rounds (each round = model + tool call ≈ 2 graph steps)
    config = {"recursion_limit": req.max_iterations * 3}

    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": req.question}]},
            config=config,
        )
    except Exception as exc:
        return AgentResponse(
            question=req.question,
            answer=f"Agent encountered an error: {exc}",
            steps=[],
        )

    messages = result.get("messages", [])

    # Extract tool call steps from the message history
    steps = []
    tool_inputs: dict[str, object] = {}
    for msg in messages:
        if isinstance(msg, AIMessage):
            for tc in getattr(msg, "tool_calls", []):
                tool_inputs[tc["id"]] = {"tool": tc["name"], "input": tc["args"]}
        elif isinstance(msg, ToolMessage):
            info = tool_inputs.get(msg.tool_call_id, {})
            steps.append(AgentStep(
                tool=info.get("tool", msg.name or "unknown"),
                input=info.get("input", {}),
                output=msg.content,
            ))

    # Final answer is the content of the last AIMessage
    answer = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            answer = msg.content if isinstance(msg.content, str) else str(msg.content)
            break

    return AgentResponse(
        question=req.question,
        answer=answer,
        steps=steps,
    )
