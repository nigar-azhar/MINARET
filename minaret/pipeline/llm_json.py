"""Reading the JSON object an LLM was asked to return.

Models asked for "only a JSON object" often wrap it anyway: local reasoning models emit a
<think>...</think> block first, and many models put the object in a ```json fence. The object
itself is what the prompts ask for, so it is taken from inside that wrapping. A reply that is
already a bare JSON object parses exactly as json.loads would.
"""
from __future__ import annotations

import json
import re

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n(.*?)\n?```$", re.DOTALL)


def parse_json_reply(raw: str):
    """json.loads(raw), after removing a <think> block and a surrounding code fence. If that still
    fails, the outermost {...} in the reply is tried; otherwise the original JSONDecodeError is
    raised, so callers keep treating an unusable reply as a failed attempt."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as first_error:
        text = _THINK.sub("", raw).strip()
        fenced = _FENCE.match(text)
        if fenced:
            text = fenced.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if 0 <= start < end:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    pass
        raise first_error
