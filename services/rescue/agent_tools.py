"""
Earthward Rescue Task Force — generic agent tool definitions.

NOT framework-specific. This module exports:

  TOOLS         — list of tool definitions in a neutral schema
  dispatch      — call any tool by name with a dict of arguments
  OPENAI_TOOLS  — same tools formatted for OpenAI function calling
  ANTHROPIC_TOOLS — same tools formatted for Anthropic tool use
  as_langchain_tools() — returns LangChain StructuredTool list

Any agent framework that can call a Python function or an HTTP endpoint
can use this module. The enforcement rules live in incident_log.py —
this module only provides the schema and dispatch layer.

Framework wiring examples at the bottom of this file.
"""

from __future__ import annotations

import json
from typing import Any

import incident_log as log
from models import (
    ActionSource,
    ActionType,
    IncidentPriority,
    IncidentType,
    RescueError,
)


# ---------------------------------------------------------------------------
# Neutral tool definitions
# Each tool has: name, description, parameters (JSON Schema)
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "open_incident",
        "description": (
            "Open a new rescue incident and run the pipeline through the "
            "operational plan draft (phases 1-5). Returns the incident_id "
            "and pipeline result including any escalations and the awaiting_human "
            "gate if plan approval is needed. "
            "The pipeline halts automatically at human gates — do not attempt "
            "to approve the plan yourself."
        ),
        "parameters": {
            "type": "object",
            "required": ["incident_type", "priority", "location", "description", "source"],
            "properties": {
                "incident_type": {
                    "type": "string",
                    "enum": [t.value for t in IncidentType],
                    "description": "Type of rescue incident.",
                },
                "priority": {
                    "type": "string",
                    "enum": [p.value for p in IncidentPriority],
                },
                "location": {
                    "type": "string",
                    "description": "Address or location description.",
                },
                "description": {
                    "type": "string",
                    "description": "Initial incident description.",
                },
                "source": {
                    "type": "object",
                    "required": ["type", "id"],
                    "description": "Who is reporting this incident.",
                    "properties": {
                        "type": {"type": "string", "enum": ["human", "agent"]},
                        "id": {"type": "string"},
                    },
                },
            },
        },
    },
    {
        "name": "get_incident",
        "description": (
            "Read the full record for an incident — all actions, hazards, "
            "victims, escalations, and derived current_status. Read-only."
        ),
        "parameters": {
            "type": "object",
            "required": ["incident_id"],
            "properties": {
                "incident_id": {"type": "string"},
            },
        },
    },
    {
        "name": "list_open_incidents",
        "description": "Return a summary list of all open (non-closed) incidents.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "log_action",
        "description": (
            "Append an action to an incident's log. Append-only — never edits "
            "history. Sequence rules and human-only gates are enforced by the "
            "service. Returns an error dict if the action is rejected — never "
            "silently drops a rejection. "
            "Human-only action_types (source.type must be 'human'): "
            "operational_plan_approved, victim_transferred, hazard_mitigated, "
            "hazard_cleared, incident_closed."
        ),
        "parameters": {
            "type": "object",
            "required": ["incident_id", "action_type", "source", "reference"],
            "properties": {
                "incident_id": {"type": "string"},
                "action_type": {
                    "type": "string",
                    "enum": [a.value for a in ActionType],
                },
                "source": {
                    "type": "object",
                    "required": ["type", "id"],
                    "properties": {
                        "type": {"type": "string", "enum": ["human", "agent"]},
                        "id": {"type": "string"},
                    },
                },
                "reference": {
                    "type": "string",
                    "description": (
                        "Pointer to supporting data — radio log ID, report number, "
                        "order reference. Free text alone is rejected."
                    ),
                },
                "data": {
                    "type": "object",
                    "description": "Action-type-specific payload.",
                },
                "corrects_action_id": {
                    "type": "string",
                    "description": "Set only for correction actions.",
                },
            },
        },
    },
    {
        "name": "open_hazard",
        "description": (
            "Log a new hazard against an incident. Critical and high hazards "
            "block operations until cleared by a human. "
            "This tool does NOT clear hazards — only a human can do that."
        ),
        "parameters": {
            "type": "object",
            "required": ["incident_id", "description", "severity", "source"],
            "properties": {
                "incident_id": {"type": "string"},
                "description": {"type": "string"},
                "severity": {
                    "type": "string",
                    "enum": ["critical", "high", "moderate", "low"],
                },
                "source": {
                    "type": "object",
                    "required": ["type", "id"],
                    "properties": {
                        "type": {"type": "string", "enum": ["human", "agent"]},
                        "id": {"type": "string"},
                    },
                },
                "notes": {"type": "string"},
            },
        },
    },
    {
        "name": "add_victim",
        "description": (
            "Register a victim against an incident. Logs a victim_located "
            "action to the incident timeline."
        ),
        "parameters": {
            "type": "object",
            "required": ["incident_id", "description", "location_description",
                         "triage_category", "source"],
            "properties": {
                "incident_id": {"type": "string"},
                "description": {
                    "type": "string",
                    "description": "General description — avoid PII.",
                },
                "location_description": {"type": "string"},
                "triage_category": {
                    "type": "string",
                    "enum": ["immediate", "delayed", "minimal", "expectant"],
                },
                "source": {
                    "type": "object",
                    "required": ["type", "id"],
                    "properties": {
                        "type": {"type": "string", "enum": ["human", "agent"]},
                        "id": {"type": "string"},
                    },
                },
            },
        },
    },
    {
        "name": "raise_escalation",
        "description": (
            "Raise an escalation for human attention. "
            "escalate_to MUST name a specific role or person — 'Incident Commander', "
            "'Safety Officer', 'Logistics Section Chief', etc. "
            "Vague values like 'a human' are rejected."
        ),
        "parameters": {
            "type": "object",
            "required": ["incident_id", "raised_by", "escalate_to",
                         "reason", "action_required"],
            "properties": {
                "incident_id": {"type": "string"},
                "raised_by": {"type": "string"},
                "escalate_to": {
                    "type": "string",
                    "description": "Named role or person. Never vague.",
                },
                "reason": {"type": "string"},
                "action_required": {"type": "string"},
            },
        },
    },
    {
        "name": "draft_plan",
        "description": (
            "Draft an operational plan — always status='draft'. "
            "Agents may draft; only a human can approve. "
            "Assumptions must be listed explicitly — never fold them in silently. "
            "Open questions must be listed rather than assumed away."
        ),
        "parameters": {
            "type": "object",
            "required": ["incident_id", "drafted_by", "objectives"],
            "properties": {
                "incident_id": {"type": "string"},
                "drafted_by": {"type": "string"},
                "objectives": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "team_assignments": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
                "resource_assignments": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
                "assumptions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Always explicit — never omit assumptions.",
                },
                "open_questions": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
    },
    {
        "name": "resume_pipeline",
        "description": (
            "Resume the pipeline from a named phase after a human gate is cleared. "
            "authorized_by must be a human source. "
            "Use after plan approval ('operations-agent') or extraction "
            "confirmation ('verification-agent')."
        ),
        "parameters": {
            "type": "object",
            "required": ["incident_id", "from_phase", "authorized_by"],
            "properties": {
                "incident_id": {"type": "string"},
                "from_phase": {
                    "type": "string",
                    "enum": [
                        "incident-log-agent", "safety-agent", "assessment-agent",
                        "resource-agent", "planning-agent", "operations-agent",
                        "integration-agent", "verification-agent", "command-agent",
                    ],
                },
                "authorized_by": {
                    "type": "object",
                    "required": ["type", "id"],
                    "properties": {
                        "type": {"type": "string", "enum": ["human"]},
                        "id": {"type": "string"},
                    },
                },
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Dispatch — call any tool by name with a plain dict
# Returns a JSON-serializable dict; never raises past this boundary.
# ---------------------------------------------------------------------------

def dispatch(name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    """
    Execute a tool call. Returns either the result or a structured error
    dict — never raises, so any calling agent loop can feed the rejection
    back to the model as a tool result.

    This is the single integration point: wire your framework's tool-use
    output into this function and you're done.
    """
    from runner import TaskForceRunner
    _runner = TaskForceRunner()

    try:
        if name == "open_incident":
            src = tool_input["source"]
            result = _runner.intake(
                incident_type=IncidentType(tool_input["incident_type"]),
                priority=IncidentPriority(tool_input["priority"]),
                location=tool_input["location"],
                description=tool_input["description"],
                reported_by=ActionSource(type=src["type"], id=src["id"]),
            )
            return result

        if name == "get_incident":
            return log.get_incident(tool_input["incident_id"])

        if name == "list_open_incidents":
            return {"incidents": log.list_open_incidents()}

        if name == "log_action":
            src = tool_input["source"]
            return log.log_action(
                incident_id=tool_input["incident_id"],
                action_type=ActionType(tool_input["action_type"]),
                source=ActionSource(type=src["type"], id=src["id"]),
                reference=tool_input["reference"],
                data=tool_input.get("data"),
                corrects_action_id=tool_input.get("corrects_action_id"),
            )

        if name == "open_hazard":
            src = tool_input["source"]
            hazard_id = log.open_hazard(
                incident_id=tool_input["incident_id"],
                description=tool_input["description"],
                severity=tool_input["severity"],
                source=ActionSource(type=src["type"], id=src["id"]),
                notes=tool_input.get("notes", ""),
            )
            return {"hazard_id": hazard_id}

        if name == "add_victim":
            src = tool_input["source"]
            victim_id = log.add_victim(
                incident_id=tool_input["incident_id"],
                description=tool_input["description"],
                location_description=tool_input["location_description"],
                triage_category=tool_input["triage_category"],
                source=ActionSource(type=src["type"], id=src["id"]),
            )
            return {"victim_id": victim_id}

        if name == "raise_escalation":
            esc_id = log.raise_escalation(
                incident_id=tool_input["incident_id"],
                raised_by=tool_input["raised_by"],
                escalate_to=tool_input["escalate_to"],
                reason=tool_input["reason"],
                action_required=tool_input["action_required"],
            )
            return {"escalation_id": esc_id}

        if name == "draft_plan":
            plan_id = log.draft_plan(
                incident_id=tool_input["incident_id"],
                drafted_by=tool_input["drafted_by"],
                objectives=tool_input["objectives"],
                team_assignments=tool_input.get("team_assignments", {}),
                resource_assignments=tool_input.get("resource_assignments", {}),
                assumptions=tool_input.get("assumptions", []),
                open_questions=tool_input.get("open_questions", []),
            )
            return {"plan_id": plan_id, "status": "draft"}

        if name == "resume_pipeline":
            src = tool_input["authorized_by"]
            result = _runner.resume(
                incident_id=tool_input["incident_id"],
                from_phase=tool_input["from_phase"],
                authorized_by=ActionSource(type=src["type"], id=src["id"]),
            )
            return result

        return {"error": "UnknownTool", "message": f"No such tool: {name!r}"}

    except RescueError as e:
        # Rejections are returned as data, not raised — the agent sees
        # exactly why the call failed and must report it faithfully.
        return {"error": type(e).__name__, "message": str(e)}
    except (KeyError, ValueError) as e:
        return {"error": "BadInput", "message": str(e)}


# ---------------------------------------------------------------------------
# Framework-specific formatters
# ---------------------------------------------------------------------------

def as_openai_tools() -> list[dict[str, Any]]:
    """
    Format TOOLS for OpenAI function calling (Chat Completions API).
    Compatible with GPT-4o, GPT-4-turbo, GPT-3.5-turbo, and any
    OpenAI-compatible endpoint (Groq, Together, Mistral, etc.).

    Usage:
        from agent_tools import as_openai_tools, dispatch
        from openai import OpenAI

        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o",
            tools=as_openai_tools(),
            messages=[{"role": "user", "content": "..."}],
        )
        for tool_call in response.choices[0].message.tool_calls or []:
            result = dispatch(
                tool_call.function.name,
                json.loads(tool_call.function.arguments),
            )
            # append as tool message and continue the loop
    """
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in TOOLS
    ]


def as_anthropic_tools() -> list[dict[str, Any]]:
    """
    Format TOOLS for Anthropic Claude tool use.

    Usage:
        from agent_tools import as_anthropic_tools, dispatch
        from anthropic import Anthropic

        client = Anthropic()
        response = client.messages.create(
            model="claude-opus-4-5",
            tools=as_anthropic_tools(),
            messages=[{"role": "user", "content": "..."}],
        )
        for block in response.content:
            if block.type == "tool_use":
                result = dispatch(block.name, block.input)
                # append as tool_result and continue
    """
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"],
        }
        for t in TOOLS
    ]


def as_langchain_tools():
    """
    Return a list of LangChain StructuredTool objects.
    Requires: pip install langchain-core

    Usage:
        from agent_tools import as_langchain_tools
        tools = as_langchain_tools()
        # pass to AgentExecutor or bind_tools()
    """
    try:
        from langchain_core.tools import StructuredTool
        from pydantic import create_model, Field
    except ImportError:
        raise ImportError(
            "langchain-core is required: pip install langchain-core pydantic"
        )

    lc_tools = []
    for t in TOOLS:
        # Build a minimal pydantic model from the JSON schema properties.
        props = t["parameters"].get("properties", {})
        required = set(t["parameters"].get("required", []))
        fields = {}
        for field_name, field_schema in props.items():
            annotation = str  # default; JSON Schema -> Python type is best-effort
            if field_schema.get("type") == "array":
                annotation = list
            elif field_schema.get("type") == "object":
                annotation = dict
            elif field_schema.get("type") == "boolean":
                annotation = bool
            elif field_schema.get("type") == "integer":
                annotation = int

            default = ... if field_name in required else None
            fields[field_name] = (annotation, Field(default, description=field_schema.get("description", "")))

        InputModel = create_model(f"{t['name']}_input", **fields)

        tool_name = t["name"]  # capture for closure

        def make_func(n):
            def fn(**kwargs):
                return dispatch(n, kwargs)
            fn.__name__ = n
            fn.__doc__ = next(x["description"] for x in TOOLS if x["name"] == n)
            return fn

        lc_tools.append(
            StructuredTool(
                name=t["name"],
                description=t["description"],
                args_schema=InputModel,
                func=make_func(tool_name),
            )
        )
    return lc_tools


def as_crewai_tools():
    """
    Return a list of CrewAI-compatible tool wrappers.
    Requires: pip install crewai

    Usage:
        from agent_tools import as_crewai_tools
        from crewai import Agent
        tools = as_crewai_tools()
        agent = Agent(role="...", tools=tools, ...)
    """
    try:
        from crewai.tools import BaseTool
    except ImportError:
        raise ImportError("crewai is required: pip install crewai")

    crew_tools = []
    for t in TOOLS:
        tool_name = t["name"]
        tool_desc = t["description"]

        class _Tool(BaseTool):
            name: str = tool_name
            description: str = tool_desc

            def _run(self, **kwargs):
                return json.dumps(dispatch(tool_name, kwargs), indent=2)

        crew_tools.append(_Tool())
    return crew_tools


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"Rescue task force tools: {len(TOOLS)} tools defined")
    for t in TOOLS:
        required = t["parameters"].get("required", [])
        print(f"  {t['name']:<25} required={required}")

    print()
    print("OpenAI format  : as_openai_tools()    -> list of {type, function}")
    print("Anthropic format: as_anthropic_tools() -> list of {name, description, input_schema}")
    print("LangChain format: as_langchain_tools() -> list of StructuredTool")
    print("CrewAI format  : as_crewai_tools()    -> list of BaseTool")
    print("Direct dispatch: dispatch(name, args) -> dict (never raises)")
