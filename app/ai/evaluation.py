"""Output evaluation harness (bonus).

Two independent checks:
1. Grounding check — every asset ID/value mentioned in the output must exist in the DB.
2. Completeness check — LLM-as-judge scores whether the output actually answers the input.
"""
import json
import re
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.llm import get_llm
from app.schemas.analysis import EvaluationRequest, EvaluationResponse
from app.services.asset_service import get_asset, list_assets
from app.schemas.asset import AssetListParams


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

def _extract_candidate_ids(data: Any) -> set[str]:
    """Extract all string values from a nested dict/list that could be asset IDs or values."""
    candidates: set[str] = set()
    _walk(data, candidates)
    return candidates


def _walk(node: Any, acc: set[str]) -> None:
    if isinstance(node, str):
        acc.add(node)
    elif isinstance(node, dict):
        for v in node.values():
            _walk(v, acc)
    elif isinstance(node, list):
        for item in node:
            _walk(item, acc)


def _grounding_check(db: Session, output: dict[str, Any]) -> tuple[float, list[str]]:
    """Return (score 0-1, list of hallucinated references)."""
    candidate_ids: list[str] = []

    findings = output.get("findings", [])
    for f in findings:
        if isinstance(f, dict) and "asset_id" in f:
            candidate_ids.append(f["asset_id"])

    asset_list = output.get("assets", [])
    for a in asset_list:
        if isinstance(a, dict) and "id" in a:
            candidate_ids.append(a["id"])

    if not candidate_ids:
        return 1.0, []

    hallucinated = []
    for aid in candidate_ids:
        if not get_asset(db, aid):
            hallucinated.append(aid)

    score = 1.0 - (len(hallucinated) / len(candidate_ids)) if candidate_ids else 1.0
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
