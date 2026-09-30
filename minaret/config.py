"""User configuration: `minaret.yaml` (models, endpoints, prompts, paths) + `.env` (API keys).

Every LLM-backed stage reads its endpoint from one `llm.<stage>` block:

    llm:
      correction:
        base_url: http://127.0.0.1:1234/v1
        model: qwen3.5-9b-mlx
        api_key_env: MINARET_CORRECTION_API_KEY   # the NAME of an env var, never the key
        prompt: minaret/prompts/correction_v1.txt

Keys live only in the environment (or a gitignored `.env` next to minaret.yaml), so the yaml
file can be committed and shared. CLI flags override whatever the yaml says.

Lookup order for the config file: explicit --config path, $MINARET_CONFIG, ./minaret.yaml,
then the minaret.yaml shipped at the repository root. Relative paths inside the file resolve
against the file's own directory, not the caller's cwd.

Local settings go in a gitignored `minaret.local.yaml` next to the config file (the reviewer
panel's Settings tab writes it). Its values are merged over the config file key by key, so it
only needs the settings that differ, and the shared minaret.yaml stays unchanged.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
LLM_STAGES = ("correction", "extraction", "rag_answer")


@dataclass
class LLMEndpoint:
    stage: str
    base_url: str
    model: str
    api_key: str
    prompt: Optional[Path]
    temperature: float = 0.0
    max_tokens: Optional[int] = None


class Config:
    def __init__(self, data: dict[str, Any], base_dir: Path, file: Optional[Path] = None):
        self.data = data
        self.base_dir = base_dir
        self.file = file  # the config file this was loaded from (None if no file was found)

    def path(self, key: str, default: Optional[str] = None) -> Optional[Path]:
        value = self.get(key, default)
        if value is None:
            return None
        p = Path(value).expanduser()
        return p if p.is_absolute() else (self.base_dir / p).resolve()

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def llm(self, stage: str, *, base_url: Optional[str] = None, model: Optional[str] = None,
            api_key: Optional[str] = None, prompt: Optional[str] = None) -> LLMEndpoint:
        """Resolve one stage's endpoint; explicit arguments (CLI flags) win over the yaml."""
        if stage not in LLM_STAGES:
            raise KeyError(f"Unknown LLM stage {stage!r}; expected one of {LLM_STAGES}")
        block = self.get(f"llm.{stage}", {}) or {}
        if api_key is None:
            env_name = block.get("api_key_env")
            api_key = os.environ.get(env_name, "") if env_name else ""
        prompt_value = prompt or block.get("prompt")
        prompt_path = None
        if prompt_value:
            p = Path(prompt_value).expanduser()
            prompt_path = p if p.is_absolute() else (self.base_dir / p).resolve()
        resolved = LLMEndpoint(
            stage=stage,
            base_url=base_url or block.get("base_url") or "",
            model=model or block.get("model") or "",
            api_key=api_key,
            prompt=prompt_path,
            temperature=float(block.get("temperature", 0.0)),
            max_tokens=block.get("max_tokens"),
        )
        if not resolved.base_url or not resolved.model:
            raise ValueError(f"llm.{stage} needs base_url and model (set them in minaret.yaml or "
                             f"pass --{stage.replace('_', '-')}-base-url/--{stage.replace('_', '-')}-model)")
        return resolved


LOCAL_CONFIG_NAME = "minaret.local.yaml"


def merge(base: dict, override: dict) -> dict:
    """`override` merged over `base`: nested mappings key by key, any other value replaced."""
    out = dict(base)
    for key, value in override.items():
        out[key] = merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def _candidate_paths(explicit: Optional[Path]) -> list[Path]:
    paths = []
    if explicit:
        paths.append(Path(explicit))
    if os.environ.get("MINARET_CONFIG"):
        paths.append(Path(os.environ["MINARET_CONFIG"]))
    paths += [Path.cwd() / "minaret.yaml", REPO_ROOT / "minaret.yaml"]
    return paths


def load(explicit: Optional[Path] = None) -> Config:
    for candidate in _candidate_paths(explicit):
        if candidate.is_file():
            env_file = candidate.parent / ".env"
            if env_file.is_file():
                try:
                    from dotenv import load_dotenv
                    load_dotenv(env_file, override=False)
                except ImportError:  # python-dotenv is optional; plain env vars still work
                    pass
            data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            local = candidate.parent / LOCAL_CONFIG_NAME
            if local.is_file():
                data = merge(data, yaml.safe_load(local.read_text(encoding="utf-8")) or {})
            return Config(data, candidate.resolve().parent, candidate.resolve())
        if explicit and candidate == Path(explicit):
            raise FileNotFoundError(f"Config file not found: {candidate}")
    return Config({}, Path.cwd())
