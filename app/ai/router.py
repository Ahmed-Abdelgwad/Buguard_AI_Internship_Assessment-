"""Question router — classifies a free-text question to the right chain or agent mode.

Decision logic:
  - nl_query     : simple search/filter (single intent, no analysis needed)
  - risk_scoring : risk / threat / vulnerability assessment questions
  - report       : explicit request for a written report or executive summary
  - agent        : everything else — multi-step, ambiguous, or cross-domain questions

Enrichment is intentionally excluded from the simple modes here because extracting
a reliable asset_id from free text is unreliable; the agent's search_assets tool
handles those flows more gracefully.
"""
from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from app.ai import cache
from app.ai.llm import get_llm


class RouteDecision(BaseModel):
    mode: Literal["nl_query", "risk_scoring", "report", "agent"]
    reasoning: str


_ROUTER_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        """You are a routing classifier for DarkAtlas, a security asset management system.

Classify the user's question into exactly one of these modes:

nl_query
  Simple lookup or filter questions — single intent, no deep analysis.
  Examples: "show all domains", "list active certs", "find assets tagged prod",
            "which subdomains are stale?", "how many IP addresses do we have?"

risk_scoring
  Any question about risk, threats, vulnerabilities, security scores, or exposure.
  Examples: "what's our risk level?", "assess threats on prod", "score these assets",
            "how vulnerable are we?", "which assets are most dangerous?"

report
  Explicit request for a written narrative report, inventory summary, or executive overview.
  Examples: "generate a security report", "write an inventory report", "summarize our attack surface",
            "give me a Q2 report", "create an executive summary"

agent
  Everything else — questions that require 2+ operations, mention enrichment/classification
  of specific assets, combine search with analysis, or are ambiguous/complex.
  Examples: "find expired certs AND score their risk", "show prod domains then enrich them",
            "which assets are most vulnerable and what services run on them?",
            "categorize api.example.com", "analyze the subdomain relationships"

When in doubt between a simple mode and agent, always choose agent.
""",
    ),
    ("human", "{question}"),
])


def classify_question(question: str) -> RouteDecision:
    cached = cache.get("router", {"question": question})
    if cached:
        return cached

    llm = get_llm()
    chain = _ROUTER_PROMPT | llm.with_structured_output(RouteDecision)
    try:
        result: RouteDecision = chain.invoke({"question": question})
    except Exception:
        result = RouteDecision(
            mode="agent",
            reasoning="Classification failed; defaulting to agent for maximum coverage.",
        )

    cache.set("router", {"question": question}, result)
    return result
