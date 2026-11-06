#!/usr/bin/env python3
"""What the engine sends to a non-OpenAI endpoint (ollama.com, OpenRouter, a local box).

The 14-day plan asks for a 40k-token completion. A hosted reasoning model spends that budget
on its trace and returns content="" with finish_reason="length" when the cap is too low, which
surfaced as "Content engine failed: chat_json: the model did not return valid JSON" on a real
deployment. These checks pin the translation rules so that cannot come back quietly.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global FAILS
    print(("ok   " if ok else "FAIL ") + label + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS += 1


def send(base: str, payload: dict, cap: str | None = None) -> dict:
    """Run one payload through llm._for_provider as that endpoint would see it."""
    for mod in [m for m in list(sys.modules) if m.startswith("app.services.llm")]:
        del sys.modules[mod]
    os.environ["RESMARA_ENGINE_BASE_URL"] = base
    os.environ.pop("RESMARA_ENGINE_MAX_TOKENS", None)
    if cap is not None:
        os.environ["RESMARA_ENGINE_MAX_TOKENS"] = cap
    from app.services import llm

    return llm._for_provider(dict(payload))


def main() -> int:
    plan = {"model": "glm-5.3", "max_completion_tokens": 40000, "reasoning_effort": "medium"}

    sent = send("https://ollama.com/v1", plan)
    check("compatible endpoint: max_completion_tokens becomes max_tokens", "max_tokens" in sent and "max_completion_tokens" not in sent, str(sent))
    check("compatible endpoint: the 40k plan request keeps a 32k budget", sent.get("max_tokens") == 32000, str(sent.get("max_tokens")))
    check("compatible endpoint: OpenAI-only options are dropped", "options" not in sent and "reasoning_effort" not in sent, str(sent))

    sent = send("https://ollama.com/v1", plan, cap="12000")
    check("an explicit RESMARA_ENGINE_MAX_TOKENS still wins", sent.get("max_tokens") == 12000, str(sent.get("max_tokens")))

    plain = {"model": "glm-5.3", "max_completion_tokens": 4000}
    sent = send("http://127.0.0.1:11434/v1", plain)
    check("local endpoint keeps the small 8k cap", sent.get("max_tokens") == 4000, str(sent.get("max_tokens")))
    check("local endpoint raises num_ctx", (sent.get("options") or {}).get("num_ctx") == 32768, str(sent.get("options")))
    check("local endpoint that was not asked to think gets reasoning_effort none",
          sent.get("reasoning_effort") == "none", str(sent.get("reasoning_effort")))

    sent = send("https://api.openai.com/v1", plan)
    check("OpenAI itself is untouched", sent == plan, str(sent))

    os.environ.pop("RESMARA_ENGINE_BASE_URL", None)
    os.environ.pop("RESMARA_ENGINE_MAX_TOKENS", None)
    print(f"{'FAILED' if FAILS else 'ok'} — llm provider translation")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
