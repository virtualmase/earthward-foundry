"""
Earthward Rescue Task Force — live Claude agent loop.

Loads the rescue-coordinator system prompt from agents/rescue/rescue-coordinator.md,
wires it to the rescue tool layer via agent_tools.py, and runs a full
Claude tool-use conversation loop against the live incident log.

This module is framework-agnostic at the tool layer — the same agent_tools.dispatch()
function works for any model. Claude is used here because the system prompts
in this repo are written in that style, but swapping to OpenAI is one line.

Usage (from code):
    from live_agent import RescueAgent
    agent = RescueAgent()
    response = agent.run("Open a new urban SAR incident at 412 Alderton Ave.")
    print(response)

Usage (interactive):
    python live_demo.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import anthropic

import agent_tools
import incident_log as log

_SYSTEM_PROMPT_PATH = (
    Path(__file__).parent.parent.parent
    / "agents" / "rescue" / "rescue-coordinator.md"
)

_MODEL = "claude-opus-4-5"
_MAX_TOKENS = 4096


class RescueAgent:
    """
    A stateful Claude agent wired to the rescue tool layer.

    Each instance maintains its own conversation history so a session
    can span multiple turns (open incident → field updates → resume →
    closure) without losing context.

    The agent loop:
      1. Send messages + tools to Claude
      2. If Claude returns tool_use blocks, dispatch each one via
         agent_tools.dispatch() and feed results back
      3. Repeat until Claude returns a text-only response (stop_reason=end_turn)
      4. Return the final text response

    Tool errors are returned as tool_result content — the model sees
    exactly what failed and must report it faithfully per the system prompt.
    """

    def __init__(
        self,
        model: str = _MODEL,
        system_prompt_path: Path = _SYSTEM_PROMPT_PATH,
        verbose: bool = False,
    ):
        self.client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )
        self.model = model
        self.verbose = verbose
        self.messages: list[dict] = []
        self.tools = agent_tools.as_anthropic_tools()

        if not system_prompt_path.exists():
            raise FileNotFoundError(
                f"System prompt not found: {system_prompt_path}\n"
                "Run from the services/rescue directory or check the path."
            )
        self.system_prompt = system_prompt_path.read_text(encoding="utf-8")

        # Init the DB (no-op if already exists).
        log.init_db(reset=False)

    def run(self, user_message: str) -> str:
        """
        Send a user message and run the tool loop until the agent
        produces a final text response. Returns that text.
        """
        self.messages.append({"role": "user", "content": user_message})
        return self._loop()

    def reset(self) -> None:
        """Clear conversation history. Does NOT reset the incident DB."""
        self.messages = []

    # -----------------------------------------------------------------------
    # Internal loop
    # -----------------------------------------------------------------------

    def _loop(self) -> str:
        while True:
            if self.verbose:
                print(f"\n[agent] Calling {self.model} with {len(self.messages)} messages...")

            response = self.client.messages.create(
                model=self.model,
                max_tokens=_MAX_TOKENS,
                system=self.system_prompt,
                tools=self.tools,
                messages=self.messages,
            )

            # Append assistant turn to history.
            self.messages.append({"role": "assistant", "content": response.content})

            if self.verbose:
                print(f"[agent] stop_reason={response.stop_reason}")

            # If no tool calls, we're done — return the text response.
            if response.stop_reason == "end_turn":
                text_blocks = [b for b in response.content if b.type == "text"]
                return text_blocks[0].text if text_blocks else ""

            # Process tool calls.
            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    if self.verbose:
                        print(f"[tool]  {block.name}({json.dumps(block.input, indent=2)[:200]}...)")

                    result = agent_tools.dispatch(block.name, block.input)

                    if self.verbose:
                        result_preview = json.dumps(result)[:300]
                        print(f"[tool]  -> {result_preview}")

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })

                # Feed all results back in one user turn.
                self.messages.append({"role": "user", "content": tool_results})
                continue

            # Unexpected stop reason — surface it, don't swallow it.
            return f"[Unexpected stop_reason: {response.stop_reason}]"

    def get_usage(self) -> dict:
        """Rough token count from the last response (for monitoring)."""
        # Not tracked per-response in this impl; returns message count.
        return {"message_turns": len(self.messages)}
