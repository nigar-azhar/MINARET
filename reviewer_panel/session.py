"""Review session: the working state of one recording under review, and every reviewer action.

A session starts from a recording's V2 transcript and E1 entity set and ends, once every flag has
a final decision, in V3 and E2 written in the pipeline's established format through
`minaret.pipeline.ingest_reviewed.ingest` (the same hand-off any external review process uses).

Actions follow the paper's human-review description:
  segments  accept, correct (text/timestamps), insert, delete, split, merge
  entities  accept, correct (text/type/reference/fields), add, reject; topic scope
  flags     raise on a segment or entity (span + issue type), resolve, escalate ("Need Review")
  super     resolve an escalated flag (only the super reviewer can)
  finalize  refused while any flag is open or escalated
"""
from __future__ import annotations

import json
import shutil
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ENTITY_TYPES = ("ayat", "hadith", "dua", "topics", "headings")
FLAG_ISSUES = ("missing text", "incorrect text", "missing diacritics", "incorrect Quranic quotation",
               "incorrect Hadith quotation", "incorrect Dua quotation", "missing reference",
               "extraneous content")
ROLES = ("first_level", "super")


class ReviewError(ValueError):
    """A reviewer action that cannot be applied in the current state."""


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _load(path: Path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(data, dict) and "segments" in data:
        data = data["segments"]
    return data


@dataclass
class SessionKey:
    source: str  # "artifacts" | "runs"
    series: str
    recording: str

    def as_tuple(self):
        return (self.source, self.series, self.recording)


class Session:
    def __init__(self, state: dict, path: Path):
        self.state = state
        self.path = path

    # ------------------------------------------------------------------ creation / persistence
    @classmethod
    def start(cls, key: SessionKey, recording_dir: Path, path: Path) -> "Session":
        v2 = _load(recording_dir / "v2.json")
        e1 = json.loads((recording_dir / "e1.json").read_text(encoding="utf-8"))
        segments = [{"uid": _uid("s"), "data": dict(s), "status": "unreviewed"} for s in v2]
        entities = []
        for etype in ENTITY_TYPES:
            for i, item in enumerate(e1.get(etype, [])):
                entities.append({"uid": _uid("e"), "type": etype, "fields": dict(item), "status": "pending",
                                 "order": float(i), "e1": dict(item)})
        state = {"key": key.__dict__, "recording_dir": str(recording_dir), "segments": segments,
                 "entities": entities, "flags": [], "finalized": None}
        s = cls(state, path)
        s.save()
        return s

    @classmethod
    def load(cls, path: Path) -> "Session":
        return cls(json.loads(path.read_text(encoding="utf-8")), path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    # ------------------------------------------------------------------ lookups
    def _seg_index(self, uid: str) -> int:
        for i, s in enumerate(self.state["segments"]):
            if s["uid"] == uid:
                return i
        raise ReviewError(f"No segment {uid}")

    def _entity(self, uid: str) -> dict:
        for e in self.state["entities"]:
            if e["uid"] == uid:
                return e
        raise ReviewError(f"No entity {uid}")

    def _flag(self, fid: str) -> dict:
        for f in self.state["flags"]:
            if f["id"] == fid:
                return f
        raise ReviewError(f"No flag {fid}")

    def recording_end(self) -> float:
        segs = self.state["segments"]
        return max((max(s["data"]["start"], s["data"]["end"]) for s in segs), default=0.0)

    # ------------------------------------------------------------------ actions
    def apply(self, action: dict, role: str = "first_level", save: bool = True) -> dict:
        if role not in ROLES:
            raise ReviewError(f"Unknown role {role!r}")
        if self.state.get("finalized"):
            raise ReviewError("This review is finalized; reopen it to make further changes.")
        op = action.get("op")
        handler = getattr(self, "_op_" + (op or "").replace(".", "_"), None)
        if handler is None:
            raise ReviewError(f"Unknown action {op!r}")
        result = handler(action, role) or {}
        if save:
            self.save()
        return result

    # segments
    def _op_seg_accept(self, a, role):
        seg = self.state["segments"][self._seg_index(a["uid"])]
        if seg["status"] == "unreviewed":
            seg["status"] = "accepted"

    def _op_seg_edit(self, a, role):
        seg = self.state["segments"][self._seg_index(a["uid"])]
        if "data" in a:  # full replacement (replay)
            seg["data"] = dict(a["data"])
        else:
            for k in ("text", "start", "end"):
                if k in a:
                    seg["data"][k] = a[k] if k == "text" else float(a[k])
        seg["status"] = "edited" if seg["status"] != "inserted" else "inserted"

    def _op_seg_insert(self, a, role):
        data = dict(a["data"]) if "data" in a else {"start": float(a["start"]), "end": float(a["end"]),
                                                     "text": a.get("text", "")}
        new = {"uid": _uid("s"), "data": data, "status": "inserted"}
        segs = self.state["segments"]
        pos = 0 if a.get("after_uid") is None else self._seg_index(a["after_uid"]) + 1
        segs.insert(pos, new)
        return {"uid": new["uid"]}

    def _op_seg_delete(self, a, role):
        segs = self.state["segments"]
        uid = a["uid"]
        segs.pop(self._seg_index(uid))
        for f in self.state["flags"]:
            if f["target"] == {"kind": "segment", "uid": uid} and f["status"] != "resolved":
                f["status"] = "resolved"
                f["resolution"] = {"role": role, "note": "segment removed"}

    def _op_seg_split(self, a, role):
        segs = self.state["segments"]
        i = self._seg_index(a["uid"])
        seg = segs[i]
        if "parts" in a:  # replay: exact target segments
            parts = [dict(p) for p in a["parts"]]
        else:
            text, at = seg["data"]["text"], int(a["at"])
            if not 0 < at < len(text):
                raise ReviewError("Split position must fall inside the segment text")
            start, end = seg["data"]["start"], seg["data"]["end"]
            cut = round(start + (end - start) * at / len(text), 2)
            first = {**seg["data"], "text": text[:at].rstrip(), "end": cut}
            second = {k: v for k, v in seg["data"].items() if k != "id"}
            second.update(text=text[at:].lstrip(), start=cut, end=end)
            parts = [first, second]
        new = [{"uid": seg["uid"] if n == 0 else _uid("s"), "data": p, "status": "edited"} for n, p in enumerate(parts)]
        segs[i:i + 1] = new
        return {"uids": [s["uid"] for s in new]}

    def _op_seg_merge(self, a, role):
        segs = self.state["segments"]
        idx = sorted(self._seg_index(u) for u in a["uids"])
        if len(idx) < 2 or idx != list(range(idx[0], idx[-1] + 1)):
            raise ReviewError("Merge needs two or more adjacent segments")
        group = segs[idx[0]:idx[-1] + 1]
        data = {**group[0]["data"], "end": group[-1]["data"]["end"],
                "text": " ".join(s["data"]["text"].strip() for s in group)}
        merged = {"uid": group[0]["uid"], "data": data, "status": "edited"}
        segs[idx[0]:idx[-1] + 1] = [merged]
        return {"uid": merged["uid"]}

    # entities
    def _op_ent_accept(self, a, role):
        e = self._entity(a["uid"])
        if "position" in a:
            e["order"] = float(a["position"])
        if e["status"] == "pending":
            e["status"] = "accepted"

    def _op_ent_edit(self, a, role):
        e = self._entity(a["uid"])
        if a.get("replace"):
            e["fields"] = dict(a["fields"])
        else:
            e["fields"].update(a["fields"])
        if "position" in a:
            e["order"] = float(a["position"])
        e["status"] = "added" if e["status"] == "added" else "edited"

    def _op_ent_retype(self, a, role):
        if a["type"] not in ENTITY_TYPES:
            raise ReviewError(f"Unknown entity type {a['type']!r}")
        e = self._entity(a["uid"])
        e["type"] = a["type"]
        e["status"] = "added" if e["status"] == "added" else "edited"

    def _op_ent_add(self, a, role):
        if a["type"] not in ENTITY_TYPES:
            raise ReviewError(f"Unknown entity type {a['type']!r}")
        if "position" in a:
            order = float(a["position"])
        else:  # place among same-type entities by start time
            same = sorted((e for e in self.state["entities"] if e["type"] == a["type"]), key=lambda e: e["order"])
            start = float(a["fields"].get("start", 0))
            after = [e["order"] for e in same if float(e["fields"].get("start", 0)) <= start]
            later = [e["order"] for e in same if e["order"] > (after[-1] if after else -1)]
            lo = after[-1] if after else (later[0] - 1 if later else 0.0)
            hi = later[0] if later else lo + 2
            order = (lo + hi) / 2
        new = {"uid": _uid("e"), "type": a["type"], "fields": dict(a["fields"]), "status": "added",
               "order": order, "e1": None}
        self.state["entities"].append(new)
        return {"uid": new["uid"]}

    def _op_ent_reject(self, a, role):
        self._entity(a["uid"])["status"] = "rejected"

    def _op_ent_scope(self, a, role):
        """Topics: lecture-level (whole recording) or tied to a segment group [start, end]."""
        e = self._entity(a["uid"])
        if e["type"] != "topics":
            raise ReviewError("Scope applies to topics only")
        if a["scope"] == "lecture":
            e["fields"]["start"], e["fields"]["end"] = 0.0, self.recording_end()
        else:
            e["fields"]["start"], e["fields"]["end"] = float(a["start"]), float(a["end"])
        e["status"] = "added" if e["status"] == "added" else "edited"

    # flags / escalation
    def _op_flag_add(self, a, role):
        target = a["target"]
        if target.get("kind") == "segment":
            self._seg_index(target["uid"])
        elif target.get("kind") == "entity":
            self._entity(target["uid"])
        else:
            raise ReviewError("Flag target must be a segment or an entity")
        if a["issue"] not in FLAG_ISSUES:
            raise ReviewError(f"Issue must be one of {FLAG_ISSUES}")
        flag = {"id": _uid("f"), "target": {"kind": target["kind"], "uid": target["uid"]}, "issue": a["issue"],
                "span": a.get("span"), "note": a.get("note", ""), "status": "open", "raised_by": role,
                "resolution": None}
        self.state["flags"].append(flag)
        return {"id": flag["id"]}

    def _op_flag_resolve(self, a, role):
        f = self._flag(a["id"])
        if f["status"] == "resolved":
            raise ReviewError("Flag already resolved")
        if f["status"] == "escalated" and role != "super":
            raise ReviewError("This flag was escalated; only the super reviewer can resolve it")
        f["status"] = "resolved"
        f["resolution"] = {"role": role, "note": a.get("note", "")}

    def _op_flag_escalate(self, a, role):
        f = self._flag(a["id"])
        if f["status"] != "open":
            raise ReviewError("Only an open flag can be escalated")
        f["status"] = "escalated"
        f["escalation_note"] = a.get("note", "")

    # ------------------------------------------------------------------ completion
    def blockers(self) -> list[str]:
        out = []
        for f in self.state["flags"]:
            if f["status"] == "open":
                out.append(f"Open flag ({f['issue']}) on a {f['target']['kind']}")
            elif f["status"] == "escalated":
                out.append(f"Escalated flag ({f['issue']}) awaiting the super reviewer")
        return out

    def build_outputs(self) -> tuple[list[dict], dict]:
        v3 = [dict(s["data"]) for s in self.state["segments"]]
        e2 = {t: [] for t in ENTITY_TYPES}
        for e in sorted(self.state["entities"], key=lambda e: e["order"]):
            if e["status"] != "rejected":
                e2[e["type"]].append(dict(e["fields"]))
        return v3, e2

    def finalize(self, runs_recordings: Path) -> dict:
        from minaret.pipeline.ingest_reviewed import ingest, validate

        blockers = self.blockers()
        if blockers:
            return {"ok": False, "blockers": blockers}
        v3, e2 = self.build_outputs()
        try:
            warnings = validate(v3, e2)
        except ValueError as exc:
            return {"ok": False, "blockers": [f"Output fails the V3/E2 format check: {exc}"]}

        key = self.state["key"]
        src_dir = Path(self.state["recording_dir"])
        out_dir = Path(runs_recordings) / key["series"] / key["recording"]
        out_dir.mkdir(parents=True, exist_ok=True)
        # Carry the reviewer's inputs alongside, so the recording is complete for evaluation.
        if src_dir.resolve() != out_dir.resolve():
            for name in ("v0.json", "v1.json", "v2.json", "e1.json", "source.json"):
                if (src_dir / name).exists():
                    shutil.copyfile(src_dir / name, out_dir / name)
        staging = self.path.parent / f"{key['recording']}.export"
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "v3.json").write_text(json.dumps(v3, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (staging / "e2.json").write_text(json.dumps(e2, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = ingest(out_dir, v3_path=staging / "v3.json", e2_path=staging / "e2.json",
                        recording_id=key["recording"], series_id=key["series"])
        shutil.rmtree(staging, ignore_errors=True)
        self.state["finalized"] = {"v3": str(result.v3_path), "e2": str(result.e2_path)}
        self.save()
        return {"ok": True, "v3": str(result.v3_path), "e2": str(result.e2_path), "warnings": warnings}

    def reopen(self) -> None:
        self.state["finalized"] = None
        self.save()


class SessionStore:
    """One Session per (source, series, recording), persisted under <runs>/review_panel/sessions/."""

    def __init__(self, runs_dir: Path, recordings_roots: dict[str, Path]):
        self.root = Path(runs_dir) / "review_panel" / "sessions"
        self.recordings_roots = recordings_roots
        self.lock = threading.RLock()

    def path_for(self, key: SessionKey) -> Path:
        return self.root / key.source / key.series / f"{key.recording}.json"

    def recording_dir(self, key: SessionKey) -> Path:
        if key.source not in self.recordings_roots:
            raise ReviewError(f"Unknown source {key.source!r}")
        d = self.recordings_roots[key.source] / key.series / key.recording
        if not (d / "v2.json").exists() or not (d / "e1.json").exists():
            raise ReviewError(f"{key.series}/{key.recording} has no v2.json + e1.json to review yet")
        return d

    def open(self, key: SessionKey, reset: bool = False) -> Session:
        with self.lock:
            p = self.path_for(key)
            if p.exists() and not reset:
                return Session.load(p)
            return Session.start(key, self.recording_dir(key), p)

    def get(self, key: SessionKey) -> Optional[Session]:
        p = self.path_for(key)
        return Session.load(p) if p.exists() else None
