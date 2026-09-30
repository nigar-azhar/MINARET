"""Replay: derive a sequence of reviewer actions that turns a session's V2/E1 into a known V3/E2.

For the paper's recordings the reviewed V3/E2 exist but the reviewer's individual actions were not
recorded, so this reconstructs a plausible path. The end state is exact (applying every action
reproduces V3 and E2); the path is an approximation, most visibly where the review restructured
segments heavily (e.g. restored omitted recitation, or resegmentation).

Transcript: V2 and V3 segments are walked in order and grouped by time overlap. Each group maps
to accept / correct / merge / split / insert / delete, with the target segment content carried
in the action, so the group's result is exactly its slice of V3.

Entities: E1 and E2 items are matched with the same identity keys RQ2 uses (surah/ayah or
reference, plus start time rounded to 0.1 s; topics and headings by rounded start/end). Matched
items are accepted or corrected; unmatched E1 items are rejected; unmatched E2 items are added.
`position` keeps each item at its place in E2's list order, which the KG relies on.
"""
from __future__ import annotations

from typing import Callable

EPS = 0.01


def _eff_end(s: dict) -> float:
    return max(s["start"], s["end"])  # tolerate a reviewed segment whose end precedes its start


def _fmt(t: float) -> str:
    t = max(0.0, float(t))
    return f"{int(t // 60)}:{t % 60:04.1f}"


def plan_segments(current: list[dict], target: list[dict]) -> list[dict]:
    """current: session segments [{uid, data}], target: V3 segment dicts."""
    actions: list[dict] = []
    i = j = 0
    n, m = len(current), len(target)
    last_uid = None  # uid of the last segment already in final position

    def emit(action, anchor):
        action["anchor"] = anchor
        actions.append(action)

    while i < n or j < m:
        if i < n and j < m:
            a, b = current[i]["data"], target[j]
            if _eff_end(b) <= a["start"] + EPS and b["start"] < a["start"]:
                emit({"op": "seg.insert", "after_uid": last_uid, "data": dict(b),
                      "describe": f"Insert omitted speech at {_fmt(b['start'])}"}, b["start"])
                last_uid = ("insert", len(actions) - 1)
                j += 1
                continue
            if _eff_end(a) <= b["start"] + EPS and a["start"] < b["start"]:
                emit({"op": "seg.delete", "uid": current[i]["uid"],
                      "describe": f"Remove segment at {_fmt(a['start'])} (duplicate or extraneous)"}, a["start"])
                i += 1
                continue
            g2, g3 = [i], [j]
            end = max(_eff_end(a), _eff_end(b))
            i, j = i + 1, j + 1
            grew = True
            while grew:
                grew = False
                if i < n and current[i]["data"]["start"] < end - EPS:
                    end = max(end, _eff_end(current[i]["data"])); g2.append(i); i += 1; grew = True
                if j < m and target[j]["start"] < end - EPS:
                    end = max(end, _eff_end(target[j])); g3.append(j); j += 1; grew = True
            uids = [current[k]["uid"] for k in g2]
            parts = [dict(target[k]) for k in g3]
            t0 = current[g2[0]]["data"]["start"]
            if len(uids) > 1:
                emit({"op": "seg.merge", "uids": uids,
                      "describe": f"Merge {len(uids)} segments at {_fmt(t0)} into one utterance"}, t0)
            head = uids[0]
            if len(parts) > 1:
                emit({"op": "seg.split", "uid": head, "parts": parts,
                      "describe": f"Split segment at {_fmt(t0)} into {len(parts)} utterances"}, t0)
            elif len(uids) > 1 or parts[0] != current[g2[0]]["data"]:
                emit({"op": "seg.edit", "uid": head, "data": parts[0],
                      "describe": f"Correct segment at {_fmt(t0)}"}, t0)
            else:
                emit({"op": "seg.accept", "uid": head, "describe": f"Accept segment at {_fmt(t0)}"}, t0)
            last_uid = ("group_tail", head, len(parts))
        elif i < n:
            a = current[i]["data"]
            emit({"op": "seg.delete", "uid": current[i]["uid"],
                  "describe": f"Remove segment at {_fmt(a['start'])} (duplicate or extraneous)"}, a["start"])
            i += 1
        else:
            b = target[j]
            emit({"op": "seg.insert", "after_uid": last_uid, "data": dict(b),
                  "describe": f"Insert omitted speech at {_fmt(b['start'])}"}, b["start"])
            last_uid = ("insert", len(actions) - 1)
            j += 1
    return actions


def _key(etype: str, item: dict):
    start = round(float(item.get("start", 0) or 0), 1)
    if etype == "ayat":
        return (str(item.get("surah_number")), str(item.get("ayah_number")), start)
    if etype in ("hadith", "dua"):
        return (str(item.get("reference")), start)
    if etype == "topics":
        return (start, round(float(item.get("end", 0) or 0), 1))
    return (start,)


def _label(etype: str, item: dict) -> str:
    if etype == "ayat":
        return f"ayah {item.get('surah_number')}:{item.get('ayah_number')}"
    if etype in ("hadith", "dua"):
        return f"{etype} {item.get('reference')}"
    if etype == "topics":
        return f"topic '{item.get('name_en') or item.get('name')}'"
    return f"heading '{item.get('title_en')}'"


def plan_entities(entities: list[dict], target: dict) -> list[dict]:
    """entities: session entities [{uid, type, fields, status}], target: E2 dict."""
    actions: list[dict] = []
    for etype, wanted in target.items():
        pool: dict = {}
        for e in entities:
            if e["type"] == etype and e["status"] != "rejected":
                pool.setdefault(_key(etype, e["fields"]), []).append(e)
        for pos, item in enumerate(wanted):
            k = _key(etype, item)
            anchor = float(item.get("start", 0) or 0)
            if pool.get(k):
                e = pool[k].pop(0)
                if e["fields"] == item:
                    actions.append({"op": "ent.accept", "uid": e["uid"], "position": pos, "anchor": anchor,
                                    "describe": f"Accept {_label(etype, item)}"})
                else:
                    actions.append({"op": "ent.edit", "uid": e["uid"], "fields": dict(item), "replace": True,
                                    "position": pos, "anchor": anchor,
                                    "describe": f"Correct {_label(etype, item)}"})
            else:
                actions.append({"op": "ent.add", "type": etype, "fields": dict(item), "position": pos,
                                "anchor": anchor, "describe": f"Add missing {_label(etype, item)}"})
        for leftovers in pool.values():
            for e in leftovers:
                actions.append({"op": "ent.reject", "uid": e["uid"], "anchor": float(e["fields"].get("start", 0) or 0),
                                "describe": f"Reject {_label(etype, e['fields'])} (not present)"})
    return actions


def plan(session_state: dict, v3: list[dict], e2: dict) -> list[dict]:
    """One pass through the recording: each segment action, followed by the actions on the entities
    that fall within it (as a reviewer handles a segment and its entities together). Segment
    actions keep their exact order, since inserts refer to earlier segment actions; entity actions
    carry explicit list positions, so their order of application does not affect the result."""
    seg_actions = plan_segments(session_state["segments"], v3)
    ent_actions = sorted(plan_entities(session_state["entities"], e2), key=lambda a: a["anchor"])
    merged, k = [], 0
    for n, a in enumerate(seg_actions):
        nxt = seg_actions[n + 1]["anchor"] if n + 1 < len(seg_actions) else float("inf")
        merged.append(a)
        while k < len(ent_actions) and ent_actions[k]["anchor"] < max(nxt, a["anchor"]):
            merged.append(ent_actions[k]); k += 1
    merged.extend(ent_actions[k:])
    return merged


def apply_all(session, actions: list[dict], role: str = "first_level",
              on_step: Callable[[int, dict], None] | None = None) -> None:
    """Apply a plan in order, resolving `after_uid` references to segments created earlier."""
    runner = ActionRunner(session)
    for n, a in enumerate(actions):
        runner.run(a, role, save=False)
        if on_step:
            on_step(n, a)
    session.save()


class ActionRunner:
    """Applies planned actions one at a time, resolving `after_uid` placeholders."""

    def __init__(self, session):
        self.session = session
        self.seg_results: list[dict] = []  # results of segment actions, in order (insert refs index this)
        self.group_tails: dict[str, str] = {}

    def resolve_after(self, ref):
        if ref is None or isinstance(ref, str):
            return ref
        if ref[0] == "insert":
            return self.seg_results[ref[1]]["uid"]
        _, head, nparts = ref
        return self.group_tails.get(head, head)

    def run(self, action: dict, role: str = "first_level", save: bool = True) -> dict:
        a = {k: v for k, v in action.items() if k not in ("describe", "anchor")}
        if a["op"] == "seg.insert":
            a["after_uid"] = self.resolve_after(a.get("after_uid"))
        result = self.session.apply(a, role, save=save)
        if a["op"] == "seg.split":
            self.group_tails[a["uid"]] = result["uids"][-1]
        if a["op"].startswith("seg."):
            self.seg_results.append(result)
        return result
