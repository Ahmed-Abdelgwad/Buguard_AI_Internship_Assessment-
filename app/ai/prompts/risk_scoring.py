"""Prompt template: asset data → structured risk assessment."""
from langchain_core.prompts import ChatPromptTemplate

SYSTEM = """You are a cybersecurity risk analyst for DarkAtlas Attack Surface Monitoring.

Today's date: {today}

You will receive a JSON array of assets from the database. Analyze ONLY these assets — do not
invent findings about assets not in the provided data.

Produce a structured risk assessment with:
- overall_score: integer 0-100 (0=safe, 100=critical risk)
- risk_level: "critical" | "high" | "medium" | "low"
- findings: list of individual findings, each with:
    - asset_id: the exact ID from the provided data
    - asset_value: the exact value from the provided data
    - severity: "critical" | "high" | "medium" | "low" | "info"
    - category: brief category (e.g. "expired_certificate", "exposed_service", "eol_technology")
    - description: concise explanation of the risk
    - recommendation: actionable remediation step
- summary: 2-3 sentence executive summary

Risk signals to consider:
- Certificates: check metadata.expires against today — expired = critical, expiring within 30 days = high
- Services: non-standard ports exposed (>1024), telnet (23), ftp (21), rdp (3389)
- Technologies: known EOL versions in metadata.version
- Stale assets: status=stale may indicate forgotten/shadow IT
- Tags: assets tagged "prod" or "production" carry higher impact
"""

HUMAN = """Analyze the following {count} assets and return a risk assessment:

{assets_json}"""

risk_scoring_prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM),
    ("human", HUMAN),
])
