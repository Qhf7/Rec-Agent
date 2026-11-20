"""USD list-price equivalents for measured provider token usage.

Rates are supplied by the caller with their source and verification date. These
calculations estimate official list-price equivalents, never reseller invoices.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
import math
from typing import Any, Iterable, Mapping

BILLING_BASIS = "official_list_price_equivalent_estimate_not_reseller_invoice"
MILLION = Decimal(1000000)
RATE_FIELDS = ("input_per_million", "cached_input_per_million", "output_per_million",
               "cache_write_per_million", "cache_write_5m_per_million", "cache_write_1h_per_million",
               "cache_write_30m_per_million", "cache_write_12h_per_million")
WRITE_TTLS = ("5m", "1h", "30m", "12h")


@dataclass(frozen=True)
class Price:
    input_per_million: float
    output_per_million: float
    cached_input_per_million: float | None = None
    cache_write_5m_per_million: float | None = None
    cache_write_1h_per_million: float | None = None
    cache_write_per_million: float | None = None
    cache_write_30m_per_million: float | None = None
    cache_write_12h_per_million: float | None = None
    source_url: str = ""
    verified_date: str = ""
    currency: str = "USD"
    input_token_semantics: str = "includes_cache"
    variants: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self):
        if self.currency != "USD":
            raise ValueError("prices must be denominated in USD")
        if self.input_token_semantics not in {"includes_cache", "uncached_only"}:
            raise ValueError("unknown input token semantics")
        for key in RATE_FIELDS:
            value = getattr(self, key)
            if value is None and key not in {"input_per_million", "output_per_million"}:
                continue
            if type(value) not in (int, float, Decimal) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{key} must be finite and nonnegative")
        if not isinstance(self.variants, dict):
            raise ValueError("variants must be a mapping")
        for name, override in self.variants.items():
            if not isinstance(name, str) or not isinstance(override, dict) or set(override) - set(RATE_FIELDS):
                raise ValueError("variants may override rate fields only")
            replace(self, variants={}, **override)

    def for_variant(self, name: str | None = None) -> "Price":
        if name is None:
            return self
        if name not in self.variants:
            raise ValueError("unknown price variant")
        return replace(self, variants={}, **self.variants[name])

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Price":
        return cls(**dict(value))


def _number(value: Decimal | int | float) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _token(usage: Mapping, *names: str) -> tuple[int | None, str | None]:
    for name in names:
        if name in usage and usage[name] is not None:
            value = usage[name]
            if type(value) is not int or value < 0:
                return None, "invalid_" + name
            return value, None
    return None, None


def _usage_estimation(usage: Mapping) -> tuple[bool | None, str | None]:
    customer = usage.get("customer_usage") or {}
    customer = customer if isinstance(customer, Mapping) else {}
    value = usage.get("estimated", customer.get("estimated"))
    return (value if type(value) is bool else None, usage.get("measurement_source", customer.get("source")))


def _range(tokens: int, rate: float | None) -> tuple[Decimal, Decimal | None]:
    if not tokens:
        return Decimal(0), Decimal(0)
    if rate is None:
        return Decimal(0), None
    amount = Decimal(tokens) * _number(rate) / MILLION
    return amount, amount


def _float(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def calculate_cost(usage: Mapping[str, Any], price: Price | Mapping, cache_policy: str = "observed", *,
                   variant: str | None = None) -> dict:
    """Price one request without converting unavailable measurements to zero.

    Standard OpenAI input counts include cached reads and any reported writes.
    ``uncached_only`` supports APIs where input_tokens excludes cache reads and
    writes. ``cold`` prices the same logical input as all cache misses and drops
    cache creation charges, an explicitly hypothetical normalization. Unknown
    cache reads produce intervals; unpublished cache prices are not assumed free.
    Reasoning tokens are already included in output_tokens and are never added.
    """
    if cache_policy not in {"observed", "cold"}:
        raise ValueError("cache_policy must be observed or cold")
    price = price if isinstance(price, Price) else Price.from_dict(price)
    selected = price.for_variant(variant)
    usage = usage if isinstance(usage, Mapping) else {}
    estimated, measurement_source = _usage_estimation(usage)
    result = {"billing_basis": BILLING_BASIS, "currency": "USD", "cache_policy": cache_policy,
              "source_url": selected.source_url, "verified_date": selected.verified_date, "variant": variant,
              "rates": {key: getattr(selected, key) for key in RATE_FIELDS},
              "input_token_semantics": selected.input_token_semantics,
              "usage_estimated": estimated, "measurement_source": measurement_source,
              "measured": False, "cost_usd": None, "cost_lower_usd": None, "cost_upper_usd": None,
              "cache_status": "not_reported", "cache_write_status": "not_reported",
              "reasoning_charged_separately": False, "reasons": [], "components": {}}
    input_tokens, input_error = _token(usage, "prompt_tokens", "input_tokens")
    output_tokens, output_error = _token(usage, "completion_tokens", "output_tokens")
    result.update(input_tokens=input_tokens, output_tokens=output_tokens)
    for error in (input_error, output_error):
        if error:
            result["reasons"].append(error)
    if input_tokens is None:
        result["reasons"].append("input_tokens_not_reported" if not input_error else "input_tokens_invalid")
    if output_tokens is None:
        result["reasons"].append("output_tokens_not_reported" if not output_error else "output_tokens_invalid")
    if input_tokens is None or output_tokens is None:
        return result
    result["measured"] = True
    details = usage.get("prompt_tokens_details", usage.get("input_tokens_details")) or {}
    details = details if isinstance(details, Mapping) else {}
    cache_usage = dict(details)
    cache_usage.update({k: v for k, v in usage.items() if v is not None})
    cached, cache_error = _token(cache_usage, "cached_tokens", "cache_read_input_tokens", "prompt_cache_hit_tokens")
    creation = usage.get("cache_creation") or {}
    creation = creation if isinstance(creation, Mapping) else {}
    write_fields = dict(details)
    write_fields.update(creation)
    write_fields.update({k: v for k, v in usage.items() if v is not None})
    write_total, write_error = _token(write_fields, "cache_creation_input_tokens", "cache_write_tokens")
    writes_by_ttl, write_errors = {}, []
    for ttl in WRITE_TTLS:
        count, error = _token(write_fields, f"cache_creation_{ttl}_input_tokens",
                              f"cache_write_{ttl}_tokens", f"ephemeral_{ttl}_input_tokens")
        writes_by_ttl[ttl] = count
        if error:
            write_errors.append(error)
    for error in (cache_error, write_error, *write_errors):
        if error:
            result["reasons"].append(error)
    if result["reasons"]:
        return result
    ttl_counts_reported = any(count is not None for count in writes_by_ttl.values())
    known_write_tokens = sum(count for count in writes_by_ttl.values() if count is not None)
    relevant_ttls = [ttl for ttl, count in writes_by_ttl.items()
                     if count is not None or getattr(selected, f"cache_write_{ttl}_per_million") is not None]
    ttl_counts_complete = bool(relevant_ttls) and all(writes_by_ttl[ttl] is not None for ttl in relevant_ttls)
    if write_total is not None and known_write_tokens > write_total:
        result["reasons"].append("cache_write_total_mismatch")
        return result
    if write_total is None and ttl_counts_complete:
        write_total = known_write_tokens
    result.update(cached_input_tokens=cached, cache_write_tokens=write_total,
                  cache_write_tokens_known_min=known_write_tokens,
                  **{f"cache_write_{ttl}_tokens": count for ttl, count in writes_by_ttl.items()})
    result["cache_status"] = "observed" if cached is not None else "not_reported"
    result["cache_write_status"] = ("observed" if write_total is not None
                                      else "partial" if ttl_counts_reported else "not_reported")
    writes = write_total if write_total is not None else known_write_tokens
    if selected.input_token_semantics == "includes_cache":
        if writes > input_tokens or (cached is not None and cached + writes > input_tokens):
            result["reasons"].append("cache_tokens_exceed_input")
            return result
        logical_input = input_tokens
    else:
        writes_unknown = write_total is None and (ttl_counts_reported or any(
            getattr(selected, key) is not None for key in RATE_FIELDS if key.startswith("cache_write_")))
        logical_input = input_tokens + cached + writes if cached is not None and not writes_unknown else None
    result["logical_input_tokens"] = logical_input
    if cache_policy == "cold":
        if logical_input is None:
            result["reasons"].append("cold_normalization_requires_total_logical_input")
            return result
        lo, hi = _range(logical_input, selected.input_per_million)
        components = {"all_cache_miss_input": (lo, hi), "output": _range(output_tokens, selected.output_per_million)}
        result["assumption"] = "same_logical_input_all_cache_miss_no_cache_creation"
    else:
        components = {"output": _range(output_tokens, selected.output_per_million)}
        if selected.input_token_semantics == "uncached_only":
            components["uncached_input"] = _range(input_tokens, selected.input_per_million)
            if cached is None:
                components["cached_input"] = (Decimal(0), None)
                result["reasons"].append("cache_read_tokens_not_reported")
            else:
                components["cached_input"] = _range(cached, selected.cached_input_per_million)
        elif cached is not None:
            components["uncached_input"] = _range(input_tokens - cached - writes, selected.input_per_million)
            components["cached_input"] = _range(cached, selected.cached_input_per_million)
        else:
            remaining = input_tokens - writes
            if selected.cached_input_per_million is None and remaining:
                components["input_with_unknown_cache"] = (Decimal(0), None)
                result["reasons"].append("cache_tokens_and_rate_not_reported")
            else:
                rates = [selected.input_per_million, selected.cached_input_per_million or 0]
                components["input_with_unknown_cache"] = (_range(remaining, min(rates))[0], _range(remaining, max(rates))[1])
                if remaining:
                    result["reasons"].append("cache_read_tokens_not_reported")
        # APIs often omit cache-creation counters. If a write price applies,
        # omitted writes may form part of the reported input and affect the
        # upper bound. Never silently assume zero cache creation.
        if write_total is None and input_tokens and selected.input_token_semantics == "includes_cache":
            write_rates = [getattr(selected, key) for key in RATE_FIELDS if key.startswith("cache_write_") and getattr(selected, key) is not None]
            if write_rates:
                remaining = input_tokens - (cached or 0) - known_write_tokens
                base_key = "uncached_input" if cached is not None else "input_with_unknown_cache"
                current = components.get(base_key)
                if current is not None:
                    applicable = [selected.input_per_million, *write_rates]
                    if cached is None and selected.cached_input_per_million is not None:
                        applicable.append(selected.cached_input_per_million)
                    low = _range(remaining, min(applicable))[0]
                    high = _range(remaining, max(applicable))[1] if current[1] is not None else None
                    components[base_key] = (min(current[0], low), max(current[1], high) if high is not None and current[1] is not None else None)
                    result["reasons"].append("cache_write_tokens_not_reported")
        if cached and selected.cached_input_per_million is None:
            result["reasons"].append("cache_read_rate_not_configured")
        if ttl_counts_reported:
            for ttl, count in writes_by_ttl.items():
                if count is None:
                    continue
                rate = getattr(selected, f"cache_write_{ttl}_per_million")
                components[f"cache_write_{ttl}"] = _range(count, rate)
                if count and rate is None:
                    result["reasons"].append(f"cache_write_{ttl}_rate_not_configured")
        unspecified_writes = (write_total - known_write_tokens if write_total is not None
                              else 0)
        if unspecified_writes:
            write_rates = [getattr(selected, key) for key in RATE_FIELDS
                           if key.startswith("cache_write_") and getattr(selected, key) is not None]
            if write_rates:
                components["cache_write_unspecified_ttl"] = (_range(unspecified_writes, min(write_rates))[0],
                                                              _range(unspecified_writes, max(write_rates))[1])
                if min(write_rates) != max(write_rates):
                    result["reasons"].append("cache_write_duration_unknown_bounded_by_published_tiers")
                elif selected.cache_write_per_million is None:
                    result["reasons"].append("cache_write_duration_unknown_single_published_rate")
            else:
                components["cache_write_unspecified_ttl"] = (Decimal(0), None)
                result["reasons"].append("cache_write_duration_or_rate_unknown")
        if write_total is None and ttl_counts_reported and not ttl_counts_complete:
            result["reasons"].append("cache_write_ttl_counters_partially_reported")
            if selected.input_token_semantics == "uncached_only":
                components["additional_unreported_cache_writes"] = (Decimal(0), None)
    lower = sum(value[0] for value in components.values())
    upper = sum(value[1] for value in components.values()) if all(value[1] is not None for value in components.values()) else None
    result.update(cost_lower_usd=_float(lower), cost_upper_usd=_float(upper),
                  cost_usd=_float(lower) if upper is not None and lower == upper else None)
    result["components"] = {key: {"lower_usd": _float(lo), "upper_usd": _float(hi)} for key, (lo, hi) in components.items()}
    return result


def aggregate_costs(rows: Iterable[Mapping], price: Price | Mapping, cache_policy: str = "observed", *,
                    variant: str | None = None) -> dict:
    """Aggregate measured success and failure usage with explicit denominators.

    Missing request usage never contributes an invented zero. Per-thousand
    estimates normalize measured requests only; the complete-run upper bound is
    unknown whenever any request has unavailable or unbounded cost.
    """
    rows = list(rows)
    costs = [calculate_cost(row.get("usage", row), price, cache_policy, variant=variant) for row in rows]
    measured = [cost for cost in costs if cost["measured"]]
    exact = [cost for cost in costs if cost["cost_usd"] is not None]
    bounded = [cost for cost in costs if cost["cost_upper_usd"] is not None]
    exact_sum = sum(_number(cost["cost_usd"]) for cost in exact) if exact else None
    lower = sum(_number(cost["cost_lower_usd"]) for cost in costs if cost["cost_lower_usd"] is not None)
    upper = sum(_number(cost["cost_upper_usd"]) for cost in costs) if costs and len(bounded) == len(costs) else None
    measured_lower = (sum(_number(cost["cost_lower_usd"]) for cost in measured)
                      if measured and all(cost["cost_lower_usd"] is not None for cost in measured) else None)
    measured_upper = sum(_number(cost["cost_upper_usd"]) for cost in measured) if measured and all(cost["cost_upper_usd"] is not None for cost in measured) else None
    mean = exact_sum / len(measured) if measured and len(exact) == len(measured) else None
    mean_lower = measured_lower / len(measured) if measured_lower is not None else None
    mean_upper = measured_upper / len(measured) if measured_upper is not None else None
    return {"billing_basis": BILLING_BASIS, "currency": "USD", "cache_policy": cache_policy, "variant": variant,
            "requests": len(rows), "measured": len(measured), "unknown": len(rows) - len(measured),
            "measured_requests": len(measured), "unmeasured_requests": len(rows) - len(measured),
            "exact_cost_requests": len(exact), "bounded_cost_requests": len(bounded),
            "unknown_cost_requests": len(rows) - len(bounded),
            "estimated_count": sum(cost["usage_estimated"] is True for cost in costs),
            "known_cost_usd": _float(exact_sum), "total_cost_lower_usd": _float(lower) if rows else None,
            "total_cost_upper_usd": _float(upper),
            "total_cost_usd": _float(exact_sum) if len(exact) == len(rows) and rows else None,
            "mean_measured_cost_usd": _float(mean), "per_1000_measured_usd": _float(mean * 1000) if mean is not None else None,
            "mean_measured_lower_usd": _float(mean_lower), "mean_measured_upper_usd": _float(mean_upper),
            "per_1000_measured_lower_usd": _float(mean_lower * 1000) if mean_lower is not None else None,
            "per_1000_measured_upper_usd": _float(mean_upper * 1000) if mean_upper is not None else None,
            "normalization_denominator": "measured_requests_only", "request_costs": costs}


def compare_cache_policies(rows: Iterable[Mapping], price: Price | Mapping, *, variant: str | None = None) -> dict:
    rows = list(rows)
    return {policy: aggregate_costs(rows, price, policy, variant=variant) for policy in ("observed", "cold")}
