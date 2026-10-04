"""Provider-agnostic LLM access with a content-addressed on-disk cache.

Providers (env LLM_PROVIDER): gemini (default), anthropic, claude_cli.
Every call is cached at cache/llm/<sha256>.json so the corpus run is reproducible and the demo
can replay offline. The cache record keeps the full prompt and response: it is the audit log of
what the model was asked and what it answered.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "cache" / "llm"
DEFAULT_MODELS = {"gemini": "gemini-3.8-flash", "anthropic": "claude-sonnet-5", "claude_cli": "sonnet"}


class LLMUnavailable(RuntimeError):
    pass


@dataclass
class LLMResponse:
    text: str
    cached: bool
    provider: str
    model: str
    cache_key: str
    elapsed_ms: int = 0


def extract_json(text: str) -> Any:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON found in model output")


class LLM:
    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None, use_cache: Optional[bool] = None):
        self.provider = (provider or os.environ.get("LLM_PROVIDER") or "gemini").strip().lower()
        env_model = os.environ.get("LLM_MODEL", "").strip()
        self.model = model or env_model or DEFAULT_MODELS.get(self.provider, "gemini-3.8-flash")
        if use_cache is None:
            use_cache = os.environ.get("HOMERULE_CACHE", "1") not in ("0", "false", "no")
        self.use_cache = use_cache
        self.calls = 0
        self.cache_hits = 0
        self._client: Any = None
        self._lock = threading.Lock()

    def cache_key(self, prompt: str, system: str, temperature: float) -> str:
        h = hashlib.sha256()
        h.update(json.dumps([self.provider, self.model, system, prompt, temperature], ensure_ascii=False).encode())
        return h.hexdigest()

    def complete(self, prompt: str, *, system: str = "", temperature: float = 0.0, max_tokens: int = 16000,
                 json_mode: bool = True) -> LLMResponse:
        key = self.cache_key(prompt, system, temperature)
        path = CACHE_DIR / f"{key}.json"
        if self.use_cache and path.exists():
            data = json.loads(path.read_text())
            self.cache_hits += 1
            return LLMResponse(text=data["text"], cached=True, provider=data.get("provider", self.provider),
                               model=data.get("model", self.model), cache_key=key)
        t0 = time.time()
        text = self._call(prompt, system, temperature, max_tokens, json_mode)
        elapsed = int((time.time() - t0) * 1000)
        self.calls += 1
        if self.use_cache:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "provider": self.provider, "model": self.model, "temperature": temperature, "system": system,
                "prompt": prompt, "text": text, "elapsed_ms": elapsed,
                "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }, ensure_ascii=False, indent=1))
        return LLMResponse(text=text, cached=False, provider=self.provider, model=self.model, cache_key=key, elapsed_ms=elapsed)

    def complete_json(self, prompt: str, **kw) -> tuple[Any, LLMResponse]:
        resp = self.complete(prompt, **kw)
        try:
            return extract_json(resp.text), resp
        except ValueError:
            resp2 = self.complete(prompt + "\n\nYour previous answer was not valid JSON. Output ONLY one valid JSON value.", **kw)
            return extract_json(resp2.text), resp2

    # ------------------------------------------------------------------ providers
    def _call(self, prompt, system, temperature, max_tokens, json_mode) -> str:
        if self.provider == "gemini":
            return self._gemini(prompt, system, temperature, max_tokens, json_mode)
        if self.provider == "anthropic":
            return self._anthropic(prompt, system, temperature, max_tokens)
        if self.provider == "claude_cli":
            return self._claude_cli(prompt, system)
        raise LLMUnavailable(f"unknown LLM_PROVIDER {self.provider!r}")

    def _gemini(self, prompt, system, temperature, max_tokens, json_mode) -> str:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise LLMUnavailable("GEMINI_API_KEY is not set and no cached response exists for this call")
        from google import genai
        from google.genai import types

        with self._lock:
            if self._client is None:
                self._client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=240000))
        cfg: dict[str, Any] = {"temperature": temperature, "max_output_tokens": max_tokens,
                               "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True)}
        if self.model.startswith("gemini-3"):
            cfg["thinking_config"] = types.ThinkingConfig(thinking_level="low")
            cfg["max_output_tokens"] = max_tokens + 8000
        if system:
            cfg["system_instruction"] = system
        if json_mode:
            cfg["response_mime_type"] = "application/json"
        last: Optional[Exception] = None
        for attempt in range(3):
            try:
                resp = self._client.models.generate_content(model=self.model, contents=prompt,
                                                            config=types.GenerateContentConfig(**cfg))
                if not resp.text:
                    raise LLMUnavailable("Gemini returned no text")
                return resp.text
            except Exception as exc:  # retry on transient errors
                last = exc
                time.sleep(2 * (attempt + 1))
        raise LLMUnavailable(f"Gemini request failed: {type(last).__name__}: {str(last)[:200]}")

    def _anthropic(self, prompt, system, temperature, max_tokens) -> str:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMUnavailable("ANTHROPIC_API_KEY is not set and no cached response exists for this call")
        import anthropic

        if self._client is None:
            self._client = anthropic.Anthropic(api_key=key)
        kwargs: dict[str, Any] = dict(model=self.model, max_tokens=max_tokens, temperature=temperature,
                                      messages=[{"role": "user", "content": prompt}])
        if system:
            kwargs["system"] = system
        msg = self._client.messages.create(**kwargs)
        return "".join(getattr(b, "text", "") for b in msg.content)

    def _claude_cli(self, prompt, system) -> str:
        exe = shutil.which("claude")
        if not exe:
            raise LLMUnavailable("`claude` CLI not found on PATH")
        cmd = [exe, "-p", "--model", self.model, "--output-format", "json", "--no-session-persistence",
               "--tools", "", "--disallowedTools", "*", "--setting-sources", "", "--exclude-dynamic-system-prompt-sections",
               "--system-prompt", system or "Answer the user's request directly."]
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
        sandbox = Path(tempfile.gettempdir()) / "homerule-llm-sandbox"
        sandbox.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=600, env=env, cwd=str(sandbox))
        if proc.returncode != 0:
            raise LLMUnavailable(f"claude CLI failed ({proc.returncode}): {proc.stderr[-400:]}")
        try:
            data = json.loads(proc.stdout)
            return data.get("result", "") if isinstance(data, dict) else str(data)
        except json.JSONDecodeError:
            return proc.stdout


_default: Optional[LLM] = None


def get_llm() -> LLM:
    global _default
    if _default is None:
        _default = LLM()
    return _default
