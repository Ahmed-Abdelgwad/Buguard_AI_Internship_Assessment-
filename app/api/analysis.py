"""AI analysis endpoints — all four LangChain capabilities plus agent, evaluation,
and the unified /ask endpoint that auto-routes and auto-evaluates every response.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_reader
from app.database import get_db
from app.schemas.analysis import (
    AgentRequest,
    AgentResponse,
    AskRequest,
    AskResponse,
    EnrichRequest,
    EnrichResponse,
    EvaluationRequest,
    EvaluationResponse,
    NLQueryRequest,
    NLQueryResponse,
    ReportRequest,
    ReportResponse,
    RiskRequest,
    RiskResponse,
)

router = APIRouter(
    prefix="/analysis",
    tags=["Analysis (AI)"],
    dependencies=[Depends(require_reader)],  # all analysis endpoints require at least reader role
)


# ── 1. Natural-language asset query ──────────────────────────────────────────

@router.post(
    "/query",
    response_model=NLQueryResponse,
    summary="Natural-language asset query — grounded in DB results",
)
def nl_query(req: NLQueryRequest, db: Session = Depends(get_db)):
    from app.ai.chains.nl_query import run_nl_query
    try:
        return run_nl_query(db, req.question)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Query failed: {exc}")


# ── 2. Risk scoring & summarization ──────────────────────────────────────────

@router.post(
    "/risk",
    response_model=RiskResponse,
    summary="Risk scoring and summarization for a set of assets",
)
def risk_score(req: RiskRequest, db: Session = Depends(get_db)):
    from app.ai.chains.risk_scoring import run_risk_scoring
    try:
        return run_risk_scoring(db, req)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Risk scoring failed: {exc}")


# ── 3. Automated enrichment & categorization ─────────────────────────────────

@router.post(
    "/enrich",
    response_model=EnrichResponse,
    summary="Classify and enrich an asset with environment, category, and criticality",
)
def enrich(req: EnrichRequest, db: Session = Depends(get_db)):
    from app.ai.chains.enrichment import run_enrichment
    try:
        return run_enrichment(db, req)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Enrichment failed: {exc}")


# ── 4. Natural-language report generation ────────────────────────────────────

@router.post(
    "/report",
    response_model=ReportResponse,
    summary="Generate a readable inventory and risk report",
)
def generate_report(req: ReportRequest, db: Session = Depends(get_db)):
    from app.ai.chains.report import run_report
    try:
        return run_report(db, req)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}")


# ── 5. Agentic mode ───────────────────────────────────────────────────────────

@router.post(
    "/agent",
    response_model=AgentResponse,
    summary="Agentic multi-step analysis — LLM calls asset and chain tools autonomously",
)
def agent_query(req: AgentRequest):
    from app.ai.agent import run_agent

    try:
        return run_agent(req)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent failed: {exc}")


# ── 6. Evaluation harness ─────────────────────────────────────────────────────

@router.post(
    "/evaluate",
    response_model=EvaluationResponse,
    summary="Score an analysis output for grounding and completeness",
)
def evaluate_output(req: EvaluationRequest, db: Session = Depends(get_db)):
    from app.ai.evaluation import run_evaluation
    try:
        return run_evaluation(db, req)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {exc}")


# ── 7. Unified ask — auto-routes and auto-evaluates ──────────────────────────

@router.post(
    "/ask",
    response_model=AskResponse,
    summary="Unified AI ask — auto-routes to the right chain or agent, then auto-evaluates",
)
def unified_ask(req: AskRequest, db: Session = Depends(get_db)):
    """Single entry point for any question about your assets.

    Internally:
    1. The router classifies the question as nl_query / risk_scoring / report / agent.
    2. The appropriate chain runs (fast path) or the full agent executes (complex path).
    3. The evaluation harness scores the answer for grounding and completeness.
    4. Everything is returned together so the caller always knows what ran and how reliable it is.
    """
    from app.ai.agent import run_agent
    from app.ai.chains.nl_query import run_nl_query
    from app.ai.chains.report import run_report
    from app.ai.chains.risk_scoring import run_risk_scoring
    from app.ai.evaluation import run_evaluation
    from app.ai.router import classify_question

    # ── Step 1: Route ─────────────────────────────────────────────────────────
    try:
        decision = classify_question(req.question)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Routing failed: {exc}")

    mode = decision.mode

    # ── Step 2: Execute ───────────────────────────────────────────────────────
    try:
        if mode == "nl_query":
            chain_result = run_nl_query(db, req.question)
            answer_dict = chain_result.model_dump()

        elif mode == "risk_scoring":
            # No specific filters from free text — score all assets.
            # The agent path handles filtered risk questions via score_asset_risk tool.
            chain_result = run_risk_scoring(db, RiskRequest())
            answer_dict = chain_result.model_dump()

        elif mode == "report":
            title = req.question[:80].strip().rstrip("?")
            chain_result = run_report(db, ReportRequest(title=title))
            answer_dict = chain_result.model_dump()

        else:  # agent — handles enrichment, complex multi-step, and ambiguous questions
            agent_result = run_agent(
                AgentRequest(question=req.question, max_iterations=req.max_agent_iterations)
            )
            answer_dict = agent_result.model_dump()

    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Analysis failed ({mode}): {exc}")

    # ── Step 3: Auto-evaluate ─────────────────────────────────────────────────
    grounding_score = None
    completeness_score = None
    hallucinated_assets = None
    evaluation_note = None

    if req.evaluate:
        # Map router modes → EvaluationRequest.chain_type literals
        _mode_to_chain_type = {
            "nl_query": "nl_query",
            "risk_scoring": "risk",
            "report": "report",
            "agent": "agent",
        }
        eval_chain_type = _mode_to_chain_type.get(mode, "nl_query")
        try:
            eval_result = run_evaluation(
                db,
                EvaluationRequest(
                    chain_type=eval_chain_type,
                    input={"question": req.question},
                    output=answer_dict,
                ),
            )
            grounding_score = eval_result.grounding_score
            completeness_score = eval_result.completeness_score
            hallucinated_assets = eval_result.hallucinated_assets or []
            if grounding_score < 0.8:
                evaluation_note = (
                    f"Low grounding score ({grounding_score:.2f}): "
                    "some asset IDs in the response could not be verified in the database."
                )
            elif completeness_score < 0.6:
                evaluation_note = (
                    f"Low completeness score ({completeness_score:.2f}): "
                    "the answer may not fully address your question."
                )
        except Exception:
            evaluation_note = "Evaluation could not run for this response."

    return AskResponse(
        question=req.question,
        mode_used=mode,
        routing_reason=decision.reasoning,
        answer=answer_dict,
        grounding_score=grounding_score,
        completeness_score=completeness_score,
        hallucinated_assets=hallucinated_assets,
        evaluation_note=evaluation_note,
    )
