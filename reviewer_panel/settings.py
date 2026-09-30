"""The Settings tab: read and change the pipeline configuration from the panel.

Changes are written to `minaret.local.yaml` next to the loaded config file (gitignored, merged over
it by `minaret.config.load`), so the shared minaret.yaml is never modified and "Restore defaults"
simply removes the local file. API keys are written to the gitignored `.env` beside it, under the
variable each stage names in `api_key_env`; they are never sent back to the browser.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml

from minaret import config as config_mod
from minaret.config import LLM_STAGES, REPO_ROOT

LANGUAGES = [None, "ur", "en", "ar"]  # faster-whisper language codes; None = auto-detect

# dotted key -> (kind, extra). Only these can be changed from the panel.
FIELDS: dict[str, tuple[str, Any]] = {}
for _stage in LLM_STAGES:
    FIELDS[f"llm.{_stage}.base_url"] = ("url", None)
    FIELDS[f"llm.{_stage}.model"] = ("text", None)
    FIELDS[f"llm.{_stage}.prompt"] = ("path", None)
FIELDS["llm.rag_answer.max_tokens"] = ("int", (1, 100000))
FIELDS["asr.language"] = ("choice", LANGUAGES)
FIELDS["validation.alpha"] = ("float", (0.0, 1.0))
FIELDS["validation.tau"] = ("float", (0.0, 1.0))
FIELDS["validation.delta"] = ("float", (0.0, 1.0))
FIELDS["rag.target_seconds"] = ("int", (5, 600))
FIELDS["rag.top_k_initial"] = ("int", (1, 100))
FIELDS["rag.top_k_final"] = ("int", (1, 100))
for _key in ("quran_db", "dua_db", "quran_csv", "duas_csv", "semantic_hadith_dump"):
    FIELDS[f"corpora.{_key}"] = ("path", None)

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _get(data: dict, dotted: str) -> Any:
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _set(data: dict, dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    node = data
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def _coerce(dotted: str, value: Any) -> Any:
    kind, extra = FIELDS[dotted]
    if kind == "choice":
        value = value or None
        if value not in extra:
            raise ValueError(f"{dotted}: choose one of {', '.join(str(x) for x in extra)}")
        return value
    if kind in ("int", "float"):
        try:
            num = int(value) if kind == "int" else float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{dotted}: expected a number, got {value!r}") from None
        lo, hi = extra
        if not lo <= num <= hi:
            raise ValueError(f"{dotted}: must be between {lo} and {hi}")
        return num
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{dotted} cannot be empty")
    if kind == "url" and not re.match(r"^https?://", value):
        raise ValueError(f"{dotted}: must start with http:// or https://")
    return value


class Settings:
    def __init__(self, cfg: config_mod.Config):
        self.cfg = cfg

    @property
    def config_file(self) -> Path:
        return self.cfg.file or (REPO_ROOT / "minaret.yaml")

    @property
    def local_file(self) -> Path:
        return self.config_file.parent / config_mod.LOCAL_CONFIG_NAME

    @property
    def env_file(self) -> Path:
        return self.config_file.parent / ".env"

    def _shared(self) -> dict:
        f = self.config_file
        return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f.is_file() else {}

    def _local(self) -> dict:
        f = self.local_file
        return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f.is_file() else {}

    # ------------------------------------------------------------------ read
    def view(self) -> dict:
        shared, local = self._shared(), self._local()
        fields = {}
        for dotted, (kind, extra) in FIELDS.items():
            value = _get(self.cfg.data, dotted)
            entry = {"value": value, "default": _get(shared, dotted), "kind": kind,
                     "local": _get(local, dotted) is not None}
            if kind == "choice":
                entry["choices"] = extra
            if kind == "path" and value:
                entry["exists"] = bool(self.cfg.path(dotted) and self.cfg.path(dotted).exists())
            fields[dotted] = entry
        keys = {}
        for stage in LLM_STAGES:
            name = _get(self.cfg.data, f"llm.{stage}.api_key_env")
            keys[stage] = {"env": name, "set": bool(name and os.environ.get(name))}
        prompts = sorted(str(p.relative_to(REPO_ROOT)) for p in (REPO_ROOT / "minaret" / "prompts").glob("*.txt"))
        return {"fields": fields, "keys": keys, "prompts": prompts, "config_file": str(self.config_file),
                "local_file": str(self.local_file), "local_exists": self.local_file.is_file(),
                "env_file": str(self.env_file)}

    # ------------------------------------------------------------------ write
    def save(self, values: dict, keys: Optional[dict] = None) -> None:
        """Validate `values` (dotted key -> value) and write every setting that differs from the
        shared config to minaret.local.yaml; write any non-empty `keys` (stage -> key) to .env."""
        unknown = [k for k in values if k not in FIELDS]
        if unknown:
            raise ValueError(f"Not a setting the panel can change: {', '.join(unknown)}")
        shared = self._shared()
        local = self._local()
        for dotted, raw in values.items():
            value = _coerce(dotted, raw)
            if value == _get(shared, dotted):
                _drop(local, dotted)
            else:
                _set(local, dotted, value)
        if local:
            self.local_file.write_text(
                "# Local settings written by the reviewer panel; merged over minaret.yaml.\n"
                "# Gitignored. Delete this file (or use Settings > Restore defaults) to go back.\n"
                + yaml.safe_dump(local, allow_unicode=True, sort_keys=False), encoding="utf-8")
        elif self.local_file.exists():
            self.local_file.unlink()
        for stage, key in (keys or {}).items():
            if stage not in LLM_STAGES:
                raise ValueError(f"Unknown stage {stage!r}")
            if key is None:
                continue
            name = _get(self.cfg.data, f"llm.{stage}.api_key_env")
            if not name or not _ENV_NAME.match(name):
                raise ValueError(f"llm.{stage}.api_key_env is not set to a valid variable name")
            self._write_env(name, key.strip())

    def restore_defaults(self) -> None:
        if self.local_file.exists():
            self.local_file.unlink()

    def _write_env(self, name: str, value: str) -> None:
        if "\n" in value or "\r" in value:
            raise ValueError("An API key cannot contain a line break")
        lines = self.env_file.read_text(encoding="utf-8").splitlines() if self.env_file.exists() else []
        lines = [ln for ln in lines if not re.match(rf"^\s*(export\s+)?{re.escape(name)}\s*=", ln)]
        if value:
            lines.append(f"{name}={value}")
            os.environ[name] = value
        else:
            os.environ.pop(name, None)
        self.env_file.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _drop(data: dict, dotted: str) -> None:
    """Remove a dotted key and any mappings it leaves empty."""
    parts = dotted.split(".")
    trail = [data]
    for part in parts[:-1]:
        nxt = trail[-1].get(part)
        if not isinstance(nxt, dict):
            return
        trail.append(nxt)
    trail[-1].pop(parts[-1], None)
    for i in range(len(parts) - 1, 0, -1):
        if not trail[i]:
            trail[i - 1].pop(parts[i - 1], None)
