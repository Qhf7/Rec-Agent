"""Run configured evaluators against immutable, shared trace-judging cases.

Credentials are resolved from the process environment only. A configured model
name and returned metadata describe the service response, not backend identity.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import re
import time
from typing import Any, Callable
import urllib.error
import urllib.request

from agent_benchmark.judges import fingerprint, parse_choices, percentile, questions
from jev_adapter import build_ssl_context
from scripts.strict_json_output import strict_json_loads

VERSION = "agent-provider-comparison-v1"
SYSTEM_INSTRUCTION = '你是Agent轨迹评审器。严格按输入questions逐题选择，只返回JSON：{"answers":{题目名:{"choice":允许选项,"confidence":0至1}}}。不输出解释。'
USAGE_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "reasoning_tokens")


@dataclass(frozen=True)
class EvaluatorConfig:
    name: str
    base_url: str
    api_key_env: str
    model: str
    protocol: str = "chat_completions"
    reasoning_effort: str | None = None
    max_output_tokens: int = 8192
    disable_thinking: bool = False
    temperature: float | None = None
    completion_token_field: str | None = None

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.name):
            raise ValueError("invalid evaluator name")
        if self.protocol not in {"chat_completions", "responses", "systemone"}:
            raise ValueError("unsupported evaluator protocol")
        from urllib.parse import urlsplit
        url = urlsplit(self.base_url)
        if url.scheme not in {"https", "http"} or not url.netloc or url.username or url.password or url.query or url.fragment or not self.model:
            raise ValueError("model and nonsecret API base URL are required")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.api_key_env):
            raise ValueError("credential must be an environment-variable reference")
        if type(self.max_output_tokens) is not int or self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        if self.completion_token_field not in (None, "max_tokens", "max_completion_tokens"):
            raise ValueError("invalid completion token parameter")
        if self.disable_thinking and self.reasoning_effort is not None:
            raise ValueError("reasoning effort conflicts with disabled thinking")

    def public(self) -> dict:
        return asdict(self)


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _endpoint(base: str, suffix: str) -> str:
    base = base.rstrip("/")
    return base if base.endswith("/" + suffix) else base + "/" + suffix


def build_request(config: EvaluatorConfig, state: dict) -> tuple[str, dict]:
    """Build the exact nonsecret request; all evaluators share the input state."""
    if state.get("questions") != questions():
        raise ValueError("frozen question definition mismatch")
    if config.protocol == "systemone":
        return _endpoint(config.base_url, "systemone"), {"model": config.model, "state": _dump(state), "questions": questions()}
    if config.protocol == "responses":
        payload = {"model": config.model, "instructions": SYSTEM_INSTRUCTION,
                   "input": [{"role": "user", "content": _dump(state)}],
                   "max_output_tokens": config.max_output_tokens, "text": {"format": {"type": "json_object"}}}
        if config.reasoning_effort is not None:
            payload["reasoning"] = {"effort": config.reasoning_effort}
        if config.temperature is not None:
            payload["temperature"] = config.temperature
        return _endpoint(config.base_url, "responses"), payload
    token_field = config.completion_token_field or ("max_completion_tokens" if config.reasoning_effort else "max_tokens")
    payload = {"model": config.model, token_field: config.max_output_tokens,
               "response_format": {"type": "json_object"},
               "messages": [{"role": "system", "content": SYSTEM_INSTRUCTION},
                            {"role": "user", "content": _dump(state)}]}
    if config.reasoning_effort is not None:
        payload["reasoning_effort"] = config.reasoning_effort
    if config.disable_thinking:
        payload["thinking"] = {"type": "disabled"}
    if config.temperature is not None:
        payload["temperature"] = config.temperature
    return _endpoint(config.base_url, "chat/completions"), payload


def _nonnegative(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def usage_of(envelope: dict) -> dict:
    source = envelope.get("usage")
    source = source if isinstance(source, dict) else {}
    result = {key: None for key in USAGE_FIELDS}
    for target, alias in (("prompt_tokens", "input_tokens"), ("completion_tokens", "output_tokens"), ("total_tokens", "total_tokens")):
        result[target] = _nonnegative(source.get(target, source.get(alias)))
    result["total_tokens_source"] = "reported" if result["total_tokens"] is not None else "unknown"
    if result["total_tokens"] is None and result["prompt_tokens"] is not None and result["completion_tokens"] is not None:
        result["total_tokens"] = result["prompt_tokens"] + result["completion_tokens"]
        result["total_tokens_source"] = "derived_input_plus_output"
    prompt_details = source.get("prompt_tokens_details", source.get("input_tokens_details")) or {}
    output_details = source.get("completion_tokens_details", source.get("output_tokens_details")) or {}
    if isinstance(prompt_details, dict):
        result["cached_tokens"] = _nonnegative(prompt_details.get("cached_tokens", source.get("prompt_cache_hit_tokens")))
    if isinstance(output_details, dict):
        result["reasoning_tokens"] = _nonnegative(output_details.get("reasoning_tokens", source.get("reasoning_tokens")))
    customer_usage = envelope.get("customer_usage", source.get("customer_usage"))
    if isinstance(customer_usage, dict):
        result["customer_usage"] = _redact_response(customer_usage)
        result["estimated"] = customer_usage.get("estimated") if type(customer_usage.get("estimated")) is bool else None
        result["measurement_source"] = customer_usage.get("source")
    else:
        result["customer_usage"] = None
        result["estimated"] = source.get("estimated") if type(source.get("estimated")) is bool else None
        result["measurement_source"] = source.get("source")
    return result


class AnswerError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def extract_answer(config: EvaluatorConfig, envelope: dict) -> dict:
    """Parse choices only after transport diagnostics have been persisted."""
    if envelope.get("error"):
        raise AnswerError("provider_error_envelope")
    if config.protocol == "systemone":
        parsed = envelope
    elif config.protocol == "responses":
        if envelope.get("status") in ("incomplete", "failed", "cancelled"):
            raise AnswerError("incomplete_response")
        chunks = []
        for output in envelope.get("output", []):
            if not isinstance(output, dict):
                continue
            for part in output.get("content", []):
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "refusal" or part.get("refusal"):
                    raise AnswerError("provider_refusal")
                if part.get("type") in ("output_text", "text") and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
        if not chunks and isinstance(envelope.get("output_text"), str):
            chunks.append(envelope["output_text"])
        if not chunks:
            raise AnswerError("missing_answer_text")
        parsed = strict_json_loads("".join(chunks))
    else:
        try:
            choice = envelope["choices"][0]
            if choice.get("finish_reason") in ("length", "content_filter"):
                raise AnswerError("output_truncated" if choice["finish_reason"] == "length" else "provider_refusal")
            message = choice["message"]
            if message.get("refusal"):
                raise AnswerError("provider_refusal")
            parsed = strict_json_loads(message["content"])
        except (KeyError, IndexError, TypeError):
            raise AnswerError("missing_answer_text") from None
    return parse_choices(parsed)


def _redact_response(value: Any, secret: str | None = None) -> Any:
    """Preserve diagnostics and usage without saving hidden reasoning strings."""
    if isinstance(value, dict):
        result = {}
        for key, part in value.items():
            if key in {"reasoning_content", "reasoning_text", "encrypted_content"}:
                continue
            if key == "reasoning" and isinstance(part, str):
                continue
            if value.get("type") == "reasoning" and key in {"summary", "content", "text"}:
                continue
            result[key] = _redact_response(part, secret)
        return result
    if isinstance(value, list):
        return [_redact_response(part, secret) for part in value]
    if isinstance(value, str) and secret:
        return value.replace(secret, "[REDACTED_CREDENTIAL]")
    return value


def _transport(config: EvaluatorConfig, endpoint: str, payload: dict, timeout: float) -> dict:
    """Return transport metadata and bytes, including non-2xx response bodies."""
    key = os.getenv(config.api_key_env, "")
    if not key:
        return {"status": None, "headers": {}, "body": "", "transport_error": "credential_missing"}
    request = urllib.request.Request(endpoint, data=_dump(payload).encode(),
              headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=build_ssl_context()))
    try:
        with opener.open(request, timeout=timeout) as response:
            return {"status": response.status, "headers": dict(response.headers), "body": response.read()}
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "headers": dict(exc.headers or {}), "body": exc.read()}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"status": None, "headers": {}, "body": "", "transport_error": "connection_error"}


def _response_metadata(config: EvaluatorConfig, envelope: dict, transport: dict) -> dict:
    headers = {str(k).lower(): v for k, v in (transport.get("headers") or {}).items()}
    reasoning = envelope.get("reasoning")
    returned_effort = reasoning.get("effort") if isinstance(reasoning, dict) else envelope.get("reasoning_effort")
    return {"requested_model": config.model, "requested_reasoning_effort": config.reasoning_effort,
            "requested_max_output_tokens": config.max_output_tokens, "protocol": config.protocol,
            "returned_model": envelope.get("model"), "response_id": envelope.get("id"),
            "request_id": headers.get("x-request-id", headers.get("request-id")),
            "system_fingerprint": envelope.get("system_fingerprint"),
            "reported_reasoning": ({k: reasoning[k] for k in ("effort", "budget_tokens") if k in reasoning} if isinstance(reasoning, dict) else None),
            "returned_reasoning": ({k: reasoning[k] for k in ("effort", "budget_tokens") if k in reasoning} if isinstance(reasoning, dict) else None),
            "returned_reasoning_effort": returned_effort,
            "reasoning_effort_mismatch": (returned_effort != config.reasoning_effort
                if returned_effort is not None and config.reasoning_effort is not None else None),
            "reported_reasoning_effort": envelope.get("reasoning_effort"),
            "status": envelope.get("status"), "incomplete_details": envelope.get("incomplete_details"),
            "finish_reasons": [part.get("finish_reason") for part in envelope.get("choices", []) if isinstance(part, dict)]}


def _validate_manifest(path: Path, case_limit: int | None) -> tuple[dict, list[dict]]:
    manifest = strict_json_loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("cases"), list) or not manifest["cases"]:
        raise ValueError("frozen manifest must contain cases")
    cases = manifest["cases"]
    if case_limit is not None:
        if case_limit < 1:
            raise ValueError("case_limit must be positive")
        cases = cases[:case_limit]
    identities = []
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("state"), dict):
            raise ValueError("invalid frozen case")
        if fingerprint(case["state"]) != case.get("input_sha256"):
            raise ValueError("frozen case fingerprint mismatch")
        if case["state"].get("questions") != questions():
            raise ValueError("frozen question definition mismatch")
        reference = case.get("reference")
        if not isinstance(reference, dict) or set(reference) != set(questions()) or any(reference[k] not in q["criteria"] for k, q in questions().items()):
            raise ValueError("invalid frozen reference")
        if not isinstance(case.get("case_id"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", case["case_id"]):
            raise ValueError("invalid frozen case identity")
        identities.append(case["case_id"])
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate frozen case identity")
    return manifest, deepcopy(cases)


def run_frozen_comparison(manifest_path: str | Path, configs: list[EvaluatorConfig], output: str | Path, *,
                          repeats: int = 1, workers: int = 2, timeout: float = 180,
                          case_limit: int | None = None,
                          transport: Callable[[EvaluatorConfig, str, dict, float], dict] | None = None) -> dict:
    manifest_path, output = Path(manifest_path), Path(output)
    if repeats < 1 or workers < 1 or timeout <= 0 or not configs:
        raise ValueError("positive repeats, workers, timeout and evaluators required")
    if len({config.name for config in configs}) != len(configs):
        raise ValueError("evaluator names must be unique")
    original_manifest, cases = _validate_manifest(manifest_path, case_limit)
    output.mkdir(parents=True, exist_ok=False)
    send = transport or _transport
    jobs = [{"case": case, "config": config, "repeat": repeat + 1}
            for case in cases for repeat in range(repeats) for config in configs]
    random.Random(20261120).shuffle(jobs)
    frozen = {"schema_version": VERSION, "source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
              "source_schema_version": original_manifest.get("schema_version"), "cases": cases,
              "case_count": len(cases), "repeats": repeats, "workers": workers, "timeout_seconds": timeout,
              "seed": 20261120, "automatic_retries": 0, "evaluators": [c.public() for c in configs],
              "reference_type": "programmatic_contract_checks_not_human_gold",
              "created_at": datetime.now(timezone.utc).isoformat()}
    _write(output / "manifest.json", frozen)

    def run(job: dict) -> dict:
        case, config, repeat = job["case"], job["config"], job["repeat"]
        directory = output / f"{case['case_id']}_{config.name}_{repeat}"
        endpoint, payload = build_request(config, case["state"])
        _write(directory / "request.json", {"endpoint": endpoint, "payload": payload, "config": config.public()})
        result = {"case_id": case["case_id"], "task_id": case.get("task_id"), "kind": config.name,
                  "repeat": repeat, "input_sha256": case["input_sha256"], "reference": case["reference"],
                  "calls": 1, "status": "error", "usage": usage_of({}), "http_status": None}
        started = time.monotonic()
        envelope = {}
        try:
            received = send(config, endpoint, payload, timeout)
            if not isinstance(received, dict):
                raise TypeError("invalid transport result")
        except Exception:
            received = {"status": None, "headers": {}, "body": "", "transport_error": "transport_exception"}
        body = received.get("body", "")
        raw_body = body if isinstance(body, bytes) else str(body).encode("utf-8")
        body = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
        result["http_status"] = received.get("status")
        secret = os.getenv(config.api_key_env, "")
        try:
            parsed = strict_json_loads(body)
            if isinstance(parsed, dict):
                envelope = _redact_response(parsed, secret)
        except (ValueError, TypeError):
            pass
        safe_headers = {k: v for k, v in (received.get("headers") or {}).items()
                        if str(k).lower() in {"x-request-id", "request-id", "content-type", "date", "openai-processing-ms", "retry-after"}}
        _write(directory / "http.json", {"status": received.get("status"), "headers": safe_headers,
               "transport_error": received.get("transport_error"), "body_bytes": len(raw_body),
               "raw_response_sha256": hashlib.sha256(raw_body).hexdigest()})
        if envelope:
            _write(directory / "response.json", _redact_response(envelope, secret))
        else:
            (directory / "response.txt").write_text(body.replace(secret, "[REDACTED_CREDENTIAL]") if secret else body, encoding="utf-8")
        # Diagnostics and token counts exist even when answer parsing fails.
        result["usage"] = usage_of(envelope)
        result["metadata"] = _redact_response(_response_metadata(config, envelope, received), secret)
        if received.get("transport_error") or not isinstance(received.get("status"), int) or not 200 <= received["status"] < 300:
            error_code = received.get("transport_error")
            result.update(failure_type="transport", error=(error_code if error_code in {"credential_missing", "connection_error", "transport_exception"} else "http_error"))
        else:
            try:
                result["choices"] = extract_answer(config, envelope)
                result["status"] = "ok"
            except Exception as exc:
                result.update(failure_type="parse", error=exc.code if isinstance(exc, AnswerError) else "invalid_answer")
        result["latency_seconds"] = round(time.monotonic() - started, 6)
        _write(directory / "result.json", result)
        return result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(run, jobs))
    rows.sort(key=lambda row: (row["case_id"], row["kind"], row["repeat"]))
    _write(output / "results.json", rows)
    summary = {"schema_version": VERSION, "case_count": len(cases), "repeats": repeats, "workers": workers,
               "reference_type": frozen["reference_type"], "evaluators": {}}
    for config in configs:
        group = [row for row in rows if row["kind"] == config.name]
        good = [row for row in group if row["status"] == "ok"]
        metric = {"config": config.public(), "requests": len(group), "valid_answers": len(good),
                  "answer_success_rate": len(good) / len(group),
                  "transport_failures": sum(r.get("failure_type") == "transport" for r in group),
                  "parse_failures": sum(r.get("failure_type") == "parse" for r in group),
                  "mean_latency_seconds": sum(r["latency_seconds"] for r in group) / len(group),
                  "p95_latency_seconds": percentile([r["latency_seconds"] for r in group]),
                  "agreement_all_attempts": {k: sum(r.get("choices", {}).get(k) == r["reference"][k] for r in group) / len(group) for k in questions()},
                  "agreement_valid_only": {k: sum(r["choices"][k] == r["reference"][k] for r in good) / len(good) if good else None for k in questions()},
                  "returned_models": sorted({str(r["metadata"]["returned_model"]) for r in group if r["metadata"].get("returned_model") is not None})}
        for field in USAGE_FIELDS:
            values = [r["usage"][field] for r in group if r["usage"][field] is not None]
            metric[field] = {"reported": len(values), "sum": sum(values) if values else None,
                             "mean_reported": sum(values) / len(values) if values else None}
        metric["estimated_usage_requests"] = sum(r["usage"].get("estimated") is True for r in group)
        metric["usage_measurement_sources"] = sorted({str(r["usage"].get("measurement_source")) for r in group if r["usage"].get("measurement_source") is not None})
        metric["returned_reasoning_efforts"] = sorted({str(r["metadata"].get("returned_reasoning_effort")) for r in group if r["metadata"].get("returned_reasoning_effort") is not None})
        metric["reasoning_effort_mismatches"] = sum(r["metadata"].get("reasoning_effort_mismatch") is True for r in group)
        metric["native_or_unmarked_total_tokens"] = {"requests": sum(r["usage"].get("estimated") is not True and r["usage"]["total_tokens"] is not None for r in group),
            "sum": sum(r["usage"]["total_tokens"] for r in group if r["usage"].get("estimated") is not True and r["usage"]["total_tokens"] is not None)
            if any(r["usage"].get("estimated") is not True and r["usage"]["total_tokens"] is not None for r in group) else None}
        metric["total_tokens_sources"] = {source: sum(r["usage"]["total_tokens_source"] == source for r in group)
                                           for source in ("reported", "derived_input_plus_output", "unknown")}
        metric["complete_repeat_cases"] = (sum(sum(r["case_id"] == c["case_id"] and r["status"] == "ok" for r in group) == repeats for c in cases)
                                           if repeats >= 2 else None)
        metric["repeat_unanimous"] = (sum(len({json.dumps(r.get("choices"), sort_keys=True) for r in group if r["case_id"] == c["case_id"] and r["status"] == "ok"}) == 1
            and sum(r["case_id"] == c["case_id"] and r["status"] == "ok" for r in group) == repeats for c in cases) if repeats >= 2 else None)
        summary["evaluators"][config.name] = metric
    _write(output / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--config-file", required=True, type=Path)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--case-limit", type=int)
    args = parser.parse_args()
    config_rows = strict_json_loads(args.config_file.read_text(encoding="utf-8"))
    if isinstance(config_rows, dict):
        config_rows = config_rows["evaluators"]
    configs = [EvaluatorConfig(**row) for row in config_rows]
    summary = run_frozen_comparison(args.manifest, configs, args.output, repeats=args.repeats, workers=args.workers,
                                    timeout=args.timeout, case_limit=args.case_limit)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
