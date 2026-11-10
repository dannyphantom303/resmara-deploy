"""The engine's own record of what a campaign cost, and answers that arrive in odd places.

Two failures this pins down, both seen on a real campaign:

  * the model answered, but put the whole JSON in `reasoning_content` while `content` was "",
    so a good plan was thrown away and the build failed with "It answered: ''";
  * nothing recorded token usage, so "what does one campaign cost" could only be guessed.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import llm, photos  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILS.append(name)


# --- a reply whose text is in the reasoning field still counts --------------------------
data = {"choices": [{"message": {"content": "  ", "reasoning_content": '{"days": [{"day": 1}]}',
                                 "role": "assistant"}, "finish_reason": "stop"}]}
check("the answer is found when content is blank", llm._reply_text(data) == '{"days": [{"day": 1}]}')
check("a plain answer is untouched", llm._reply_text(
    {"choices": [{"message": {"content": "hello"}}]}) == "hello")
check("no choices means no text and no crash", llm._reply_text({"error": "boom"}) is None)

# --- usage is recorded per call, and taken per campaign ---------------------------------
llm.take_usage()
llm._record_usage({"usage": {"prompt_tokens": 900, "completion_tokens": 1200,
                             "total_tokens": 2100}}, "deepseek-v4.1-flash")
llm._record_usage({"usage": {"prompt_tokens": 100, "completion_tokens": 50,
                             "total_tokens": 150}}, "glm-5.3")
spoken = llm.take_usage()
check("two calls add up", spoken["total_tokens"] == 2250, str(spoken["total_tokens"]))
check("the breakdown names each model",
      [c["model"] for c in spoken["calls"]] == ["deepseek-v4.1-flash", "glm-5.3"],
      str([c["model"] for c in spoken["calls"]]))
check("taking it empties the ledger", llm.take_usage()["total_tokens"] == 0)
check("a response with no usage block records nothing",
      (llm._record_usage({"choices": []}, "x"), llm.take_usage()["total_tokens"])[1] == 0)

# --- a campaign that hits the importer gets a full gallery, not ten photos --------------
check("the importer keeps a whole gallery", photos.DEFAULT_LIMIT >= 14, str(photos.DEFAULT_LIMIT))

print()
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
    raise SystemExit(1)
print("ALL LLM USAGE TESTS PASSED")
