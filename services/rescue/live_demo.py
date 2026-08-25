"""
Earthward Rescue Task Force — live agent demo.

Runs a scripted incident through the live Claude agent so you can see
real tool calls, real DB writes, and real enforcement in action.

Two modes:
  python live_demo.py          scripted walkthrough (no user input needed)
  python live_demo.py --chat   interactive CLI — type your own messages

Requires:
  ANTHROPIC_API_KEY environment variable set

The scripted walkthrough covers:
  Turn 1  Report a structural collapse incident
  Turn 2  Log two victims found by first responders
  Turn 3  Log a critical gas hazard
  Turn 4  Ask the agent to approve the plan (should be refused)
  Turn 5  Human clears hazard and approves plan via the log directly,
          then ask agent to resume operations
  Turn 6  Log extraction complete, ask agent to run verification
  Turn 7  Ask for final incident status
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import incident_log as log
from models import ActionSource, ActionType
from live_agent import RescueAgent


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_WIDTH = 72

def _banner(title: str) -> None:
    print()
    print("=" * _WIDTH)
    print(f"  {title}")
    print("=" * _WIDTH)

def _turn(label: str) -> None:
    print()
    print(f"{'─' * _WIDTH}")
    print(f"  {label}")
    print(f"{'─' * _WIDTH}")

def _human(msg: str) -> None:
    print(f"\n  YOU: {msg}")

def _agent(msg: str) -> None:
    print()
    # Word-wrap at 70 chars for readability
    for line in msg.splitlines():
        if not line.strip():
            print()
            continue
        while len(line) > 70:
            cut = line[:70].rfind(" ")
            if cut == -1:
                cut = 70
            print(f"  {line[:cut]}")
            line = line[cut:].lstrip()
        if line:
            print(f"  {line}")

def _system(msg: str) -> None:
    print(f"\n  [SYSTEM] {msg}")


# ---------------------------------------------------------------------------
# Scripted demo
# ---------------------------------------------------------------------------

def run_scripted(agent: RescueAgent) -> None:
    _banner("EARTHWARD RESCUE TASK FORCE — LIVE AGENT DEMO")
    print("  Model: claude-opus-4-5")
    print("  Mode:  scripted walkthrough")
    print("  All incident data written to earthward_rescue.db")

    # Fresh DB for the demo.
    log.init_db(reset=True)
    agent.reset()

    # -----------------------------------------------------------------------
    _turn("TURN 1 — Report the incident")
    # -----------------------------------------------------------------------
    msg = (
        "We have a structural collapse at 55 Harbor Street, downtown. "
        "4-story mixed-use building, floors 2 and 3 partially collapsed. "
        "Multiple people reported trapped. Gas odor confirmed by first unit on scene. "
        "This is a life-threat priority urban SAR. "
        "Reporting source is Dispatcher-Chen. Open the incident."
    )
    _human(msg)
    response = agent.run(msg)
    _agent(response)

    # Extract incident_id from the DB for later use.
    open_incidents = log.list_open_incidents()
    if not open_incidents:
        print("\n  [ERROR] No incident created — check API key and retry.")
        return
    incident_id = open_incidents[0]["incident_id"]
    _system(f"Incident ID: {incident_id}")

    # -----------------------------------------------------------------------
    _turn("TURN 2 — Field team reports victims")
    # -----------------------------------------------------------------------
    msg = (
        "Team Bravo on scene. They've located two victims. "
        "Victim 1: adult female, floor 2 east corridor, trapped under debris, "
        "conscious and calling out — triage immediate. "
        "Victim 2: adult male, apartment 3B, voice contact, ambulatory but blocked — "
        "triage delayed. Source is TeamBravo-Lead. Log them both."
    )
    _human(msg)
    response = agent.run(msg)
    _agent(response)

    # -----------------------------------------------------------------------
    _turn("TURN 3 — Safety Officer confirms hazard")
    # -----------------------------------------------------------------------
    msg = (
        "Safety Officer Kim on scene. She's confirming an active gas leak, "
        "utility not yet isolated — this is critical. She also notes the "
        "floor 3 slab is unsupported on the east side, critical structural risk. "
        "Log both hazards with source SafetyOfficer-Kim."
    )
    _human(msg)
    response = agent.run(msg)
    _agent(response)

    # -----------------------------------------------------------------------
    _turn("TURN 4 — Ask agent to approve the plan (should be refused)")
    # -----------------------------------------------------------------------
    msg = (
        "The operational plan looks good. Go ahead and approve it so we "
        "can get teams moving."
    )
    _human(msg)
    response = agent.run(msg)
    _agent(response)

    # -----------------------------------------------------------------------
    _turn("TURN 5 — Human clears hazards and approves plan out-of-band, then resume")
    # -----------------------------------------------------------------------
    _system("Simulating human actions directly against the DB...")

    # Get the plan and hazard IDs from the record.
    record = log.get_incident(incident_id)
    plans = [p for p in record["operational_plans"] if p["status"] == "draft"]
    hazards = [h for h in record["hazards"] if h["is_open"]]

    ic = ActionSource(type="human", id="IncidentCommander-Vasquez")
    safety = ActionSource(type="human", id="SafetyOfficer-Kim")

    for h in hazards:
        log.clear_hazard(
            incident_id=incident_id,
            hazard_id=h["hazard_id"],
            source=safety,
            notes="Utility isolated and confirmed. Structural shoring in place.",
        )
        _system(f"Hazard {h['hazard_id'][:8]}... cleared by SafetyOfficer-Kim")

    if plans:
        log.approve_plan(
            plan_id=plans[0]["plan_id"],
            incident_id=incident_id,
            approved_by=ic,
        )
        _system(f"Plan {plans[0]['plan_id'][:8]}... approved by IncidentCommander-Vasquez")

    msg = (
        "Incident Commander Vasquez has approved the operational plan and "
        "Safety Officer Kim has cleared all hazards. Resume operations."
    )
    _human(msg)
    response = agent.run(msg)
    _agent(response)

    # -----------------------------------------------------------------------
    _turn("TURN 6 — Field team logs extraction, ask agent to verify")
    # -----------------------------------------------------------------------
    _system("Logging field actions directly (simulating radio reports)...")

    victims = record["victims"]
    team = ActionSource(type="human", id="TeamBravo-Lead")
    medic = ActionSource(type="human", id="Paramedic-Osei")

    log.log_action(incident_id, ActionType.EXTRACTION_STARTED, team,
                   "radio-log-55H-1401", {"entry": "east stairwell"})
    for v in victims:
        log.log_action(incident_id, ActionType.VICTIM_ASSESSED, medic,
                       f"triage-{v['victim_id'][:6]}", {"victim_id": v["victim_id"]})
    log.log_action(incident_id, ActionType.EXTRACTION_COMPLETE, team,
                   "radio-log-55H-1438", {"victims": [v["victim_id"] for v in victims]})
    for v in victims:
        log.log_action(incident_id, ActionType.VICTIM_STABILIZED, medic,
                       f"medical-{v['victim_id'][:6]}", {"victim_id": v["victim_id"]})

    _system("Extraction complete and victims stabilized logged.")

    msg = (
        "Both victims have been extracted and stabilized. "
        "Run the verification phase and tell me if we're clear to close."
    )
    _human(msg)
    response = agent.run(msg)
    _agent(response)

    # -----------------------------------------------------------------------
    _turn("TURN 7 — Close the incident")
    # -----------------------------------------------------------------------
    _system("Logging victim transfer and incident closure via human sources...")

    log.log_action(
        incident_id, ActionType.VICTIM_TRANSFERRED, ic,
        "hospital-transfer-55H-1445",
        {"receiving_facility": "Harbor General ER"},
    )

    msg = (
        "Victims have been transferred to Harbor General ER by Incident Commander Vasquez. "
        "Give me a final status on this incident."
    )
    _human(msg)
    response = agent.run(msg)
    _agent(response)

    # -----------------------------------------------------------------------
    _banner("DEMO COMPLETE")
    # -----------------------------------------------------------------------
    final = log.get_incident(incident_id)
    print(f"  Incident ID    : {incident_id}")
    print(f"  Final status   : {final['current_status']}")
    print(f"  Total actions  : {len(final['actions'])}")
    print(f"  Victims        : {len(final['victims'])}")
    print(f"  Open escalations: {final['open_escalations']}")
    print(f"  Agent turns    : {agent.get_usage()['message_turns']}")
    print()


# ---------------------------------------------------------------------------
# Interactive chat mode
# ---------------------------------------------------------------------------

def run_chat(agent: RescueAgent) -> None:
    _banner("EARTHWARD RESCUE TASK FORCE — INTERACTIVE MODE")
    print("  Model: claude-opus-4-5")
    print("  Type your messages. Commands: /reset  /status  /quit")
    print()

    log.init_db(reset=False)

    while True:
        try:
            user_input = input("  YOU: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Exiting.")
            break

        if not user_input:
            continue

        if user_input.lower() in ("/quit", "/exit", "quit", "exit"):
            print("  Exiting.")
            break

        if user_input.lower() == "/reset":
            agent.reset()
            print("  [Conversation history cleared. DB unchanged.]")
            continue

        if user_input.lower() == "/status":
            incidents = log.list_open_incidents()
            if not incidents:
                print("  [No open incidents.]")
            else:
                for inc in incidents:
                    print(
                        f"  [{inc['current_status'].upper()}] "
                        f"{inc['incident_id'][:8]}... "
                        f"{inc['incident_type']} — {inc['location']}"
                    )
            continue

        response = agent.run(user_input)
        _agent(response)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        print("Set it with: $env:ANTHROPIC_API_KEY = 'sk-ant-...'")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Earthward Rescue Task Force — live agent")
    parser.add_argument("--chat", action="store_true", help="Interactive chat mode")
    parser.add_argument("--verbose", action="store_true", help="Show tool calls")
    args = parser.parse_args()

    agent = RescueAgent(verbose=args.verbose)

    if args.chat:
        run_chat(agent)
    else:
        run_scripted(agent)
