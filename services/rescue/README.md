# Earthward Rescue Task Force — Runner Service

Built on the same foundation as `services/traceability/` — the same four
rules that govern every foundry agent apply here without exception:

1. No agent self-certifies its own output.
2. No agent hides a failure to look complete.
3. No agent invents a standard or authorization.
4. Every escalation names who it goes to.

## What this is

A pipeline runner that routes rescue incidents through the foundry agent
fleet, remapped to rescue functions. The foundry's physical workflow
(design → make → measure → accept) becomes the incident workflow
(assess → plan → deploy → extract → verify → close).

The same enforcement that prevents a CMM agent from marking a part
"accepted" prevents an operations agent from closing an incident before
objectives are verified. Same code, same pattern, different domain.

## Quick start

```bash
cd services/rescue
pip install -r requirements.txt

# Run the demo (no server needed)
python3 demo.py

# Regression tests
python3 tests/test_models.py tests/test_incident_log.py tests/test_runner.py tests/test_api_auth.py
python3 tests/test_api.py   # HTTP smoke test, uses Flask's test client

# Start the HTTP API (requires an API key — see Authentication below)
RESCUE_API_KEY=$(openssl rand -hex 32) python3 api.py
# -> http://127.0.0.1:5001
# -> http://127.0.0.1:5001/openapi.yaml
```

Or with Docker: `docker build -t earthward-rescue .` then
`docker run -p 5001:5001 -e RESCUE_API_KEY=... earthward-rescue` — or
`docker compose up rescue` from the repo root.

### Authentication

Every request except `GET /health` and `GET /openapi.yaml` requires
`Authorization: Bearer <RESCUE_API_KEY>`. Unset the key and the API
refuses all non-exempt requests with `500 ServerMisconfigured` rather than
silently allowing them through — the only opt-out is
`ALLOW_UNAUTHENTICATED=true`, for local demos only. Requests are also
rate-limited (`RATE_LIMIT_PER_MINUTE`, default 120/min, 0 disables). See
the repo-root `SECURITY.md` for the full model and `.env.example` for
every variable. **The `source` field in request bodies below is
provenance for the ledger, not authentication** — it never substitutes
for the bearer token.

## Files

```
services/rescue/
├── models.py           data structures, enums, errors
├── incident_log.py     append-only SQLite incident store (zero external deps)
├── runner.py           TaskForceRunner — 9-phase pipeline
├── api.py              Flask HTTP API — model-agnostic, any client can call this
├── api_auth.py         bearer-token auth + rate limiting, shared pattern with traceability
├── logging_config.py   structured request/response/error logging for the API
├── openapi.yaml        machine-readable spec for tool/LLM discovery
├── agent_tools.py      tool definitions + formatters for every major framework
├── demo.py             narrated end-to-end walkthrough
├── Dockerfile
├── tests/              test_models.py, test_incident_log.py, test_runner.py, test_api.py, test_api_auth.py
└── requirements.txt
```

---

## HTTP API

All enforcement lives in `incident_log.py`. The API only translates HTTP
to function calls. Any language, any LLM, any tool can use it.

```
POST   /incidents                            open incident + run pipeline 1-5
GET    /incidents                            list open incidents
GET    /incidents/<id>                       full incident record
POST   /incidents/<id>/actions               log an action
POST   /incidents/<id>/hazards               open a hazard
DELETE /incidents/<id>/hazards/<hid>         clear a hazard (human-only → 403 if agent)
POST   /incidents/<id>/victims               add a victim
POST   /incidents/<id>/escalations           raise an escalation
PATCH  /escalations/<eid>/resolve            resolve an escalation
POST   /incidents/<id>/plans                 draft an operational plan
PATCH  /incidents/<id>/plans/<pid>/approve   approve plan (human-only → 403 if agent)
POST   /incidents/<id>/resume                resume pipeline from named phase
GET    /openapi.yaml                         OpenAPI 3.1 spec
GET    /health                               liveness check
```

### Example — open an incident

```bash
curl -s -X POST http://127.0.0.1:5001/incidents \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $RESCUE_API_KEY" \
  -d '{
    "incident_type": "urban_sar",
    "priority": "life_threat",
    "location": "412 Alderton Ave — apartment collapse",
    "description": "Partial collapse, 2 confirmed trapped, gas leak",
    "source": {"type": "human", "id": "Dispatcher-IC1"}
  }' | python -m json.tool
```

### Example — log a field action

```bash
curl -s -X POST http://127.0.0.1:5001/incidents/<id>/actions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $RESCUE_API_KEY" \
  -d '{
    "action_type": "extraction_started",
    "source": {"type": "human", "id": "Team-Alpha-Lead"},
    "reference": "radio-log-0412-1347",
    "data": {"entry_point": "East stairwell"}
  }'
```

### Example — agent tries to close incident (rejected)

```bash
curl -s -X POST http://127.0.0.1:5001/incidents/<id>/actions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $RESCUE_API_KEY" \
  -d '{
    "action_type": "incident_closed",
    "source": {"type": "agent", "id": "command-agent"},
    "reference": "auto-close-attempt"
  }'
# -> 403 UnauthorizedSourceError (note: a request with no/invalid API key
#    would instead get 401 before ever reaching this check)
```

---

## Wiring to any LLM framework

`agent_tools.py` exports tool definitions and a single `dispatch()` function.
Pick your framework:

### OpenAI / OpenAI-compatible (Groq, Together, Mistral, etc.)

```python
from openai import OpenAI
from agent_tools import as_openai_tools, dispatch
import json

client = OpenAI()
tools = as_openai_tools()
messages = [{"role": "user", "content": "Open a new urban SAR incident at 412 Alderton Ave."}]

while True:
    response = client.chat.completions.create(
        model="gpt-4o",
        tools=tools,
        messages=messages,
    )
    msg = response.choices[0].message
    messages.append(msg)

    if not msg.tool_calls:
        print(msg.content)
        break

    for tc in msg.tool_calls:
        result = dispatch(tc.function.name, json.loads(tc.function.arguments))
        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": json.dumps(result),
        })
```

### Anthropic Claude

```python
from anthropic import Anthropic
from agent_tools import as_anthropic_tools, dispatch
import json

client = Anthropic()
tools = as_anthropic_tools()
messages = [{"role": "user", "content": "Open a new urban SAR incident at 412 Alderton Ave."}]

while True:
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        tools=tools,
        messages=messages,
    )
    messages.append({"role": "assistant", "content": response.content})

    tool_uses = [b for b in response.content if b.type == "tool_use"]
    if not tool_uses:
        print(next(b.text for b in response.content if b.type == "text"))
        break

    tool_results = []
    for block in tool_uses:
        result = dispatch(block.name, block.input)
        tool_results.append({
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": json.dumps(result),
        })
    messages.append({"role": "user", "content": tool_results})
```

### LangChain

```python
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from agent_tools import as_langchain_tools

llm = ChatOpenAI(model="gpt-4o")
tools = as_langchain_tools()

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a rescue coordination assistant. Use tools to manage incidents."),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent = create_tool_calling_agent(llm, tools, prompt)
executor = AgentExecutor(agent=agent, tools=tools, verbose=True)
executor.invoke({"input": "Open a new urban SAR incident at 412 Alderton Ave."})
```

### CrewAI

```python
from crewai import Agent, Task, Crew
from agent_tools import as_crewai_tools

tools = as_crewai_tools()

coordinator = Agent(
    role="Rescue Coordinator",
    goal="Manage and coordinate rescue incidents",
    backstory="Expert in ICS and rescue operations",
    tools=tools,
    verbose=True,
)

task = Task(
    description="Open a new urban SAR incident at 412 Alderton Ave and report the pipeline result.",
    agent=coordinator,
    expected_output="Incident ID and list of phases completed.",
)

Crew(agents=[coordinator], tasks=[task]).kickoff()
```

### HTTP (any language, no SDK)

```python
import requests, json

BASE = "http://127.0.0.1:5001"

# Open incident
r = requests.post(f"{BASE}/incidents", json={
    "incident_type": "urban_sar",
    "priority": "life_threat",
    "location": "412 Alderton Ave",
    "description": "Partial collapse",
    "source": {"type": "human", "id": "Dispatcher-1"},
})
incident_id = r.json()["incident_id"]

# Get full record
record = requests.get(f"{BASE}/incidents/{incident_id}").json()
```

---

## Foundry → Rescue mapping

| Foundry house / agent       | Rescue equivalent         |
|-----------------------------|---------------------------|
| Records / Traceability      | Incident Log Agent        |
| Metrology / Quality Eng.    | Assessment Agent          |
| Engineering / Mfg. Engineer | Planning Agent            |
| Materials / Materials Eng.  | Resource Agent            |
| Forge / Fabrication Seq.    | Operations Agent          |
| Assembly / Integration Eng. | Integration Agent         |
| Validation / Test & Val.    | Verification Agent        |
| EHS / Safety                | Safety Agent              |
| Leadership / GM             | Command Agent             |

## The pipeline

```
intake()
  Phase 1  Incident Log Agent   — open incident, activate log
  Phase 2  Safety Agent         — hazard sweep, escalate to Safety Officer
  Phase 3  Assessment Agent     — situational picture, surface gaps
  Phase 4  Resource Agent       — identify requirements, escalate to Logistics
  Phase 5  Planning Agent       — draft operational plan
  *** HALT — Incident Commander plan approval required ***

resume(from_phase="operations-agent", authorized_by=<human IC>)
  Phase 6  Operations Agent     — deploy teams against approved plan
  Phase 7  Integration Agent    — check team-to-objective coverage
  *** HALT — extraction_complete must be logged by field team ***

resume(from_phase="verification-agent", authorized_by=<human IC>)
  Phase 8  Verification Agent   — confirm objectives met
  Phase 9  Command Agent        — cross-team status roll-up

Human logs: INCIDENT_CLOSED → AFTER_ACTION_FILED
```

## Human-only actions

Returns 403 if source.type is "agent":

| Action                       | Who must log it           |
|------------------------------|---------------------------|
| `operational_plan_approved`  | Incident Commander        |
| `victim_transferred`         | Incident Commander        |
| `hazard_mitigated`           | Safety Officer            |
| `hazard_cleared`             | Safety Officer            |
| `incident_closed`            | Incident Commander        |

## Sequence rules (enforced in code, not prompts)

| Action                     | Requires                        |
|----------------------------|---------------------------------|
| `operational_plan_approved`| `operational_plan_drafted`      |
| `team_deployed`            | `operational_plan_approved`     |
| `extraction_started`       | `victim_located`                |
| `extraction_complete`      | `extraction_started`            |
| `victim_stabilized`        | `victim_assessed`               |
| `victim_transferred`       | `victim_stabilized`             |
| `objective_verified`       | `team_deployed`                 |
| `incident_closed`          | `objective_verified`            |
| `after_action_filed`       | `incident_closed`               |

`team_deployed`, `extraction_started`, `victim_transferred`, and
`incident_closed` are also blocked while any critical or high hazard is open.

## Escalation rules

`escalate_to` must name a specific role or callsign. Values like "a human"
or "someone" are rejected with a 400 error. This is enforced in code.
