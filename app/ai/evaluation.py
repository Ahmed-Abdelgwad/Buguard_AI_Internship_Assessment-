"""Output evaluation harness (bonus).

Two independent checks:
1. Grounding check — every asset ID referenced in the output must exist in the DB.
2. Completeness check — LLM-as-judge scores whether the output actually answers the input.

Grounding coverage by chain type:
  nl_query    → assets[].id
  risk        → findings[].asset_id
  enrichment  → asset_id (top-level)
  report      → no IDs in prose; grounding returns 1.0 (completeness judge handles quality)
  agent       → no structured IDs in prose answer; grounding returns 1.0
"""
import json
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.llm import get_llm
from app.schemas.analysis import EvaluationRequest, EvaluationResponse
from app.services.asset_service import get_asset


# ── Completeness judge ────────────────────────────────────────────────────────

class _JudgeResult(BaseModel):
    score: float
    explanation: str


_JUDGE_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are an output quality judge for a security analysis system. "
        "Rate how well the output answers the input on a scale 0.0 to 1.0. "
        "0.0 = completely wrong or irrelevant. 1.0 = complete and accurate. "
        "Return JSON: {{\"score\": float, \"explanation\": str}}",
    ),
    (
        "human",
        "Chain type: {chain_type}\n\nInput:\n{input}\n\nOutput:\n{output}",
    ),
])


# ── Grounding check ───────────────────────────────────────────────────────────

def _grounding_check(db: Session, output: dict[str, Any]) -> tuple[float, list[str]]:
    """Return (score 0-1, list of hallucinated asset IDs).

    Extracts asset IDs from all structured output schemas and verifies each
    exists in the database. Chain types whose outputs contain no structured IDs
    (report, agent) always return 1.0 — quality is assessed by the completeness judge.
    """
    candidate_ids: list[str] = []

    # risk scoring: findings[].asset_id
    for f in output.get("findings", []):
        if isinstance(f, dict) and "asset_id" in f:
            candidate_ids.append(f["asset_id"])

    # nl_query: assets[].id
    for a in output.get("assets", []):
        if isinstance(a, dict) and "id" in a:
            candidate_ids.append(a["id"])

    # enrichment: top-level asset_id
    top_level_id = output.get("asset_id")
    if isinstance(top_level_id, str) and top_level_id:
        candidate_ids.append(top_level_id)

    if not candidate_ids:
        # report / agent outputs contain prose, not structured IDs — not groundable here
        return 1.0, []

    hallucinated = [aid for aid in candidate_ids if not get_asset(db, aid)]
    score = 1.0 - (len(hallucinated) / len(candidate_ids))
    return round(score, 3), hallucinated


# ── Main entry point ──────────────────────────────────────────────────────────

def run_evaluation(db: Session, req: EvaluationRequest) -> EvaluationResponse:
    grounding_score, hallucinated = _grounding_check(db, req.output)

    llm = get_llm()
    judge_chain = _JUDGE_PROMPT | llm.with_structured_output(_JudgeResult)

    try:
        judge: _JudgeResult = judge_chain.invoke({
            "chain_type": req.chain_type,
            "input": json.dumps(req.input, default=str),
            "output": json.dumps(req.output, default=str),
        })
        completeness_score = judge.score
        explanation = judge.explanation
    except Exception as exc:
        completeness_score = 0.0
        explanation = f"Judge failed: {exc}"

    return EvaluationResponse(
        grounding_score=grounding_score,
        completeness_score=completeness_score,
        hallucinated_assets=hallucinated,
        explanation=explanation,
    )
