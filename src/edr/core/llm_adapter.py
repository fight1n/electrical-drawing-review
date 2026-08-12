"""LLMAdapter abstraction layer.

Design goals
------------
* One uniform async interface (`complete`) for every provider.
* Hot-swappable models at runtime via :class:`LLMAdapterRouter`.
* Built-in full-chain Trace hooks on every call.
* Provider SDKs (anthropic / openai) are *optional* imports — the system runs
  end-to-end on the deterministic :class:`MockLLMAdapter`, which also supports a
  simulated Tool-Use loop so the Claude SDK Tool Use path can be exercised
  without network access.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from edr.core.trace import TraceCollector

# Approx. USD per 1K tokens (prompt / completion). Used only for Trace cost.
_PRICING = {
    "claude-sonnet-4-20250514": (0.003, 0.015),
    "claude-3-5-sonnet": (0.003, 0.015),
    "gpt-4o": (0.005, 0.015),
    "gpt-4o-mini": (0.00015, 0.0006),
}


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str
    model: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    raw: Any = None

    def json_content(self) -> Any:
        """Best-effort parse of `content` as JSON (strips code fences)."""
        text = self.content.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.lstrip().startswith("json"):
                text = text.lstrip()[4:]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None


def _estimate_tokens(text: str) -> int:
    # Rough 4-char/ token heuristic; good enough for cost tracing.
    return max(1, len(text) // 4)


class BaseLLMAdapter:
    """Async LLM interface. Subclasses implement :meth:`_complete`."""

    name = "base"
    model = "unknown"

    def __init__(self, trace: Optional[TraceCollector] = None, **kwargs: Any):
        self.trace = trace
        self.opts = kwargs

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        system: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        t0 = time.time()
        parent = kwargs.pop("trace_parent", None)
        resp = await self._complete(messages, tools, tool_choice, system, **kwargs)
        latency = (time.time() - t0) * 1000.0
        resp.latency_ms = latency
        price = _PRICING.get(self.model, (0.0, 0.0))
        resp.cost_usd = (resp.prompt_tokens * price[0] + resp.completion_tokens * price[1]) / 1000.0
        if self.trace:
            self.trace.event(
                node="llm",
                action=f"complete:{self.name}",
                parent=parent,
                model=self.model,
                prompt_tokens=resp.prompt_tokens,
                completion_tokens=resp.completion_tokens,
                latency_ms=latency,
                cost_usd=resp.cost_usd,
                meta={"tools": bool(tools), "tool_calls": len(resp.tool_calls)},
            )
        return resp

    async def _complete(self, messages, tools, tool_choice, system, **kwargs) -> LLMResponse:
        raise NotImplementedError


class MockLLMAdapter(BaseLLMAdapter):
    """Deterministic adapter for tests/demos/offline runs.

    * Without tools: emits a structured JSON review decision based on simple
      heuristics over the last user message (so the demo produces a realistic
      report).
    * With tools and no prior tool_result: emits one synthetic ToolCall to
      exercise the agentic Tool-Use loop; on the follow-up turn it emits the
      final decision.
    """

    name = "mock"
    model = "mock-1"

    def __init__(self, trace=None, fail_rate: float = 0.0, **kwargs):
        super().__init__(trace, **kwargs)
        self.fail_rate = fail_rate

    async def _complete(self, messages, tools, tool_choice, system, **kwargs):
        prompt_text = _last_user_text(messages)
        if tools and not _has_tool_result(messages):
            tool = tools[0]
            args = _sample_args(tool, prompt_text)
            tc = ToolCall(id="call_mock_1", name=tool["name"], arguments=args)
            return LLMResponse(
                content="", model=self.model, tool_calls=[tc],
                prompt_tokens=_estimate_tokens(prompt_text),
                completion_tokens=10,
            )
        decision = _mock_decision(prompt_text, system)
        content = json.dumps(decision, ensure_ascii=False)
        return LLMResponse(
            content=content, model=self.model,
            prompt_tokens=_estimate_tokens(prompt_text) + _estimate_tokens(system or ""),
            completion_tokens=_estimate_tokens(content),
        )


class ClaudeAdapter(BaseLLMAdapter):
    """Anthropic Claude via the `anthropic` SDK with Tool Use support."""

    name = "claude"

    def __init__(self, trace=None, api_key: str = "", model: str = "claude-sonnet-4-20250514",
                 temperature: float = 0.0, max_tokens: int = 2048, timeout: int = 30, **kwargs):
        super().__init__(trace, **kwargs)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        try:
            import anthropic  # noqa: F401
            self._anthropic = anthropic.AsyncAnthropic(api_key=api_key or None)
        except ImportError:
            raise RuntimeError(
                "anthropic SDK not installed. Run `pip install -r requirements-llm.txt` "
                "or set EDR_LLM_PROVIDER=mock."
            )

    async def _complete(self, messages, tools, tool_choice, system, **kwargs):
        sys = system or _extract_system(messages)
        convo = _strip_system(messages)
        kwargs_api: dict[str, Any] = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=sys or None,
            messages=convo,
            timeout=self.timeout,
        )
        if tools:
            kwargs_api["tools"] = [_to_anthropic_tool(t) for t in tools]
            if tool_choice == "auto":
                kwargs_api["tool_choice"] = {"type": "auto"}
        resp = await self._anthropic.messages.create(**kwargs_api)
        content_text, tool_calls = _parse_anthropic(resp)
        pt = resp.usage.input_tokens
        ct = resp.usage.output_tokens
        return LLMResponse(
            content=content_text, model=self.model, tool_calls=tool_calls,
            prompt_tokens=pt, completion_tokens=ct, raw=resp,
        )


class OpenAIAdapter(BaseLLMAdapter):
    """OpenAI Chat Completions via the `openai` SDK."""

    name = "openai"

    def __init__(self, trace=None, api_key: str = "", model: str = "gpt-4o",
                 temperature: float = 0.0, max_tokens: int = 2048, timeout: int = 30, **kwargs):
        super().__init__(trace, **kwargs)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        try:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=api_key or None, timeout=timeout)
        except ImportError:
            raise RuntimeError(
                "openai SDK not installed. Run `pip install -r requirements-llm.txt` "
                "or set EDR_LLM_PROVIDER=mock."
            )

    async def _complete(self, messages, tools, tool_choice, system, **kwargs):
        msgs = list(messages)
        if system:
            msgs = [{"role": "system", "content": system}] + msgs
        kwargs_api: dict[str, Any] = dict(
            model=self.model, messages=msgs,
            temperature=self.temperature, max_tokens=self.max_tokens,
        )
        if tools:
            kwargs_api["tools"] = [_to_openai_tool(t) for t in tools]
            kwargs_api["tool_choice"] = "auto" if tool_choice in (None, "auto") else tool_choice
        resp = await self._client.chat.completions.create(**kwargs_api)
        msg = resp.choices[0].message
        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=json.loads(tc.function.arguments or "{}"))
            for tc in (msg.tool_calls or [])
        ]
        content = msg.content or ""
        return LLMResponse(
            content=content, model=self.model, tool_calls=tool_calls,
            prompt_tokens=resp.usage.prompt_tokens,
            completion_tokens=resp.usage.completion_tokens,
            raw=resp,
        )


# --------------------------------------------------------------------------- #
# Provider registry + hot-swap router
# --------------------------------------------------------------------------- #
class LLMAdapterFactory:
    _registry: dict[str, Callable[..., BaseLLMAdapter]] = {
        "mock": MockLLMAdapter,
        "claude": ClaudeAdapter,
        "openai": OpenAIAdapter,
    }

    @classmethod
    def register(cls, name: str, ctor: Callable[..., BaseLLMAdapter]) -> None:
        cls._registry[name] = ctor

    @classmethod
    def create(cls, provider: str, **kwargs: Any) -> BaseLLMAdapter:
        if provider not in cls._registry:
            raise ValueError(f"Unknown LLM provider '{provider}'. Known: {list(cls._registry)}")
        return cls._registry[provider](**kwargs)


class LLMAdapterRouter:
    """Singleton-ish router enabling runtime hot-swapping of models."""

    def __init__(self, provider: str = "mock", trace: Optional[TraceCollector] = None, **defaults: Any):
        self._trace = trace
        self._defaults = defaults
        self._provider = provider
        self._instance: Optional[BaseLLMAdapter] = None
        self._lock = None
        self._build()

    def _build(self) -> None:
        self._instance = LLMAdapterFactory.create(self._provider, trace=self._trace, **self._defaults)

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def adapter(self) -> BaseLLMAdapter:
        return self._instance  # type: ignore[return-value]

    def set_provider(self, provider: str, **overrides: Any) -> None:
        """Hot-swap the underlying model without restarting the pipeline."""
        self._provider = provider
        merged = {**self._defaults, **overrides}
        self._instance = LLMAdapterFactory.create(provider, trace=self._trace, **merged)
        if self._trace:
            self._trace.event(node="llm", action="hot_swap", model=provider,
                              meta={"provider": provider})

    async def complete(self, *args: Any, **kwargs: Any) -> LLMResponse:
        return await self._instance.complete(*args, **kwargs)  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return ""


def _has_tool_result(messages: list[dict[str, Any]]) -> bool:
    for m in messages:
        if m.get("role") == "tool":
            return True
        c = m.get("content")
        if isinstance(c, str) and "tool_result" in c:
            return True
    return False


def _extract_system(messages: list[dict[str, Any]]) -> str:
    return " ".join(m.get("content", "") for m in messages if m.get("role") == "system")


def _strip_system(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m for m in messages if m.get("role") != "system"]


def _to_anthropic_tool(t: dict[str, Any]) -> dict[str, Any]:
    return {"name": t["name"], "description": t.get("description", ""),
            "input_schema": t.get("input_schema", {"type": "object", "properties": {}})}


def _to_openai_tool(t: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {
        "name": t["name"], "description": t.get("description", ""),
        "parameters": t.get("input_schema", {"type": "object", "properties": {}})}}


def _sample_args(tool: dict[str, Any], prompt: str) -> dict[str, Any]:
    props = tool.get("input_schema", {}).get("properties", {})
    args: dict[str, Any] = {}
    for pname in props:
        if "element" in pname.lower():
            args[pname] = "E1"
        elif "id" in pname.lower():
            args[pname] = "E1"
        else:
            args[pname] = ""
    return args


# Heuristic mock decision so the demo yields a realistic report.
# NOTE: the mock judges ONLY the drawing evidence (text after 【相关图元】),
# never the rule clause, so a benign clause mentioning "兼作/接地" does not
# produce a false positive. Each negative signal is evaluated independently.
def _mock_decision(prompt: str, system: Optional[str]) -> dict[str, Any]:
    p = (prompt or "").lower()
    # Isolate the actual drawing-element evidence from the rule clause block.
    evidence = p.split("【相关图元】")[-1] if "【相关图元】" in p else p
    # The rule category gates which heuristic applies (avoids cross-category noise).
    m = re.search(r"【规则类别】\s*([a-z_]+)", p)
    cat = m.group(1) if m else ""

    compliant, severity, triggered = True, "minor", False
    reason = "未发现明显违规，参数与标注符合标准要求。"
    suggestion = "维持现状。"

    # 1) Grounding / PE integrity (wiring_topology) — critical when broken.
    if cat in ("", "wiring_topology") and (
        ("pe" in evidence or "接地" in evidence or "保护" in evidence)
        and any(w in evidence for w in ["断开", "不连续", "混接", "兼作", "缺失", "无接地", "缺少"])
    ):
        compliant, severity, triggered = False, "critical", True
        reason = "保护接地(PE)存在断开/混接/缺失，违反强制性电气安全条款。"
        suggestion = "恢复保护接地导体连续性，严禁N线与PE线混接或利用N线兼作PE。"

    # 2) Missing annotation / label (symbol_annotation) — major.
    if not triggered and cat in ("", "symbol_annotation") and (
        "未标注" in evidence or "缺失" in evidence or "缺少" in evidence
    ):
        compliant, severity, triggered = False, "major", True
        reason = "检测到关键标注/参数缺失，不符合标准强制条款。"
        suggestion = "补充缺失的标注或额定参数后重新提交审核。"

    # 3) Conductor cross-section (parameter_threshold) — critical if < 2.5mm².
    if not triggered and cat in ("", "parameter_threshold") and "截面积" in evidence:
        sm = re.search(r"截面积[^\d]*(\d+(?:\.\d+)?)", evidence)
        if sm and float(sm.group(1)) < 2.5:
            compliant, severity, triggered = False, "critical", True
            reason = "导体截面积低于规范最小值，存在过热与短路风险。"
            suggestion = "将导体截面积提升至标准要求最小值以上并复核载流量。"

    # 4) Clearance / 电气间隙 (geometry_size) — major if < 10mm.
    if not triggered and cat in ("", "geometry_size") and (
        "电气间隙" in evidence or "间距" in evidence or "净距" in evidence
    ):
        cm = re.search(r"(?:电气间隙|间距|净距)[^\d]*(\d+(?:\.\d+)?)", evidence)
        if cm and float(cm.group(1)) < 10:
            compliant, severity, triggered = False, "major", True
            reason = "电气间隙/间距小于标准规定的最小值。"
            suggestion = "增大间距至标准规定的最小值或增设绝缘隔离。"

    return {
        "compliant": compliant,
        "severity": severity,
        "reason": reason,
        "suggestion": suggestion,
        "confidence": 0.82 if not compliant else 0.95,
    }
