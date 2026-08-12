"""Configuration loading: YAML defaults merged with environment overrides."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "default.yaml"


class LLMConfig(BaseModel):
    provider: str = "mock"
    claude_model: str = "claude-sonnet-4-20250514"
    openai_model: str = "gpt-4o"
    temperature: float = 0.0
    max_tokens: int = 2048
    timeout_seconds: int = 30


class RuntimeConfig(BaseModel):
    max_concurrency: int = 8
    enable_rerank: bool = True
    doclayout_weights: str = ""
    mineru_endpoint: str = ""
    trace_dir: str = "outputs/trace"


class CategoryConfig(BaseModel):
    description: str = ""
    context_budget: int = 1200
    requires: list[str] = Field(default_factory=list)


class RulesConfig(BaseModel):
    categories: dict[str, CategoryConfig] = Field(default_factory=dict)


class StandardsConfig(BaseModel):
    corpus_dir: str = "src/edr/standards/sample"
    build_index: bool = True


class ReportConfig(BaseModel):
    title: str = "电气图纸自动化审核报告"
    target_seconds: float = 3.0
    include_screenshots: bool = True


class Config(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    rules: RulesConfig = Field(default_factory=RulesConfig)
    standards: StandardsConfig = Field(default_factory=StandardsConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)


_ENV_MAP = {
    "EDR_LLM_PROVIDER": ("llm", "provider"),
    "EDR_CLAUDE_MODEL": ("llm", "claude_model"),
    "EDR_OPENAI_MODEL": ("llm", "openai_model"),
    "EDR_MAX_CONCURRENCY": ("runtime", "max_concurrency"),
    "EDR_ENABLE_RERANK": ("runtime", "enable_rerank"),
    "EDR_DOCLAYOUT_WEIGHTS": ("runtime", "doclayout_weights"),
    "EDR_MINERU_ENDPOINT": ("runtime", "mineru_endpoint"),
}


def _coerce(value: str, current: Any) -> Any:
    if isinstance(current, bool):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(current, int):
        return int(value)
    if isinstance(current, float):
        return float(value)
    return value


def load_config(path: str | os.PathLike | None = None) -> Config:
    """Load YAML config then overlay environment variables."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    data: dict[str, Any] = {}
    if cfg_path.exists():
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    cfg = Config(**data)

    for env_key, (section, field) in _ENV_MAP.items():
        if env_key in os.environ:
            section_obj = getattr(cfg, section)
            current = getattr(section_obj, field)
            setattr(section_obj, field, _coerce(os.environ[env_key], current))
    return cfg
