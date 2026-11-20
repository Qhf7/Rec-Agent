import math

import pytest

from agent_benchmark.costs import Price, aggregate_costs, calculate_cost, compare_cache_policies


def price(**overrides):
    return Price(**{"input_per_million": 2, "cached_input_per_million": .1, "output_per_million": 10,
                    "source_url": "https://official.example/pricing", "verified_date": "2026-11-20", **overrides})


def test_cached_inputs_are_subtracted_once_and_reasoning_is_not_double_charged():
    usage = {"prompt_tokens": 1000, "completion_tokens": 100, "cached_tokens": 600, "reasoning_tokens": 80}
    result = calculate_cost(usage, price())
    assert result["cost_usd"] == pytest.approx((400 * 2 + 600 * .1 + 100 * 10) / 1e6)
    assert result["reasoning_charged_separately"] is False
    assert result["billing_basis"] == "official_list_price_equivalent_estimate_not_reseller_invoice"


def test_cold_normalized_prices_same_logical_input_as_all_misses():
    usage = {"input_tokens": 1000, "output_tokens": 100, "cached_tokens": 600}
    result = calculate_cost(usage, price(), "cold")
    assert result["cost_usd"] == pytest.approx(.003)
    assert result["assumption"] == "same_logical_input_all_cache_miss_no_cache_creation"


def test_conflicting_cache_breakdown_keeps_cold_total_and_bounds_observed():
    usage = {"input_tokens": 1000, "output_tokens": 100, "cached_tokens": 900, "cache_creation_input_tokens": 900}
    rates = price(cache_write_5m_per_million=2.5, cache_write_1h_per_million=4)
    observed = calculate_cost(usage, rates)
    assert observed["cost_usd"] is None
    assert "cache_tokens_exceed_input" in observed["reasons"]
    assert observed["cost_lower_usd"] == pytest.approx(.0011)
    assert observed["cost_upper_usd"] == pytest.approx(.005)
    assert calculate_cost(usage, rates, "cold")["cost_usd"] == pytest.approx(.003)


def test_unknown_cache_has_interval_but_no_invented_point_estimate():
    result = calculate_cost({"prompt_tokens": 1000, "completion_tokens": 100}, price())
    assert result["cache_status"] == "not_reported"
    assert result["cost_usd"] is None
    assert result["cost_lower_usd"] == pytest.approx(.0011)
    assert result["cost_upper_usd"] == pytest.approx(.003)
    assert calculate_cost({"prompt_tokens": 1000, "completion_tokens": 100}, price(), "cold")["cost_usd"] == pytest.approx(.003)


def test_unknown_cache_rate_does_not_assume_cache_is_free():
    result = calculate_cost({"prompt_tokens": 1000, "completion_tokens": 100, "cached_tokens": 600}, price(cached_input_per_million=None))
    assert result["cost_usd"] is None
    assert result["cost_upper_usd"] is None
    assert result["cost_lower_usd"] == pytest.approx(.0018)
    assert "cache_read_rate_not_configured" in result["reasons"]


def test_no_cached_tokens_does_not_require_cached_rate():
    result = calculate_cost({"input_tokens": 1000, "output_tokens": 100, "cached_tokens": 0}, price(cached_input_per_million=None))
    assert result["cost_usd"] == pytest.approx(.003)


@pytest.mark.parametrize("usage", [{"input_tokens": 100, "output_tokens": 10, "cached_tokens": 101},
                                   {"input_tokens": -1, "output_tokens": 10},
                                   {"input_tokens": float('nan'), "output_tokens": 10},
                                   {"input_tokens": 100, "output_tokens": float('inf')},
                                   {"input_tokens": True, "output_tokens": 10}])
def test_invalid_or_impossible_token_usage_is_not_priced(usage):
    result = calculate_cost(usage, price())
    assert result["cost_usd"] is None
    assert result["reasons"]


@pytest.mark.parametrize("rates", [{"input_per_million": -1}, {"output_per_million": math.inf}, {"cached_input_per_million": math.nan}])
def test_invalid_rates_raise(rates):
    with pytest.raises(ValueError):
        price(**rates)


def test_missing_input_or_output_is_unknown_and_estimation_flag_survives():
    result = calculate_cost({"input_tokens": 100, "estimated": True, "measurement_source": "client_request"}, price())
    assert result["measured"] is False
    assert result["cost_usd"] is None
    assert result["usage_estimated"] is True
    assert result["measurement_source"] == "client_request"
    assert "output_tokens_not_reported" in result["reasons"]


def test_success_and_failure_usage_count_and_unreported_failures_are_not_zero():
    usage = {"input_tokens": 1000, "output_tokens": 100, "cached_tokens": 0}
    result = aggregate_costs([{"status": "ok", "usage": usage},
                              {"status": "error", "usage": {**usage, "estimated": True}},
                              {"status": "error", "usage": {}}], price())
    assert result["requests"] == 3
    assert result["measured"] == 2
    assert result["unknown"] == 1
    assert result["estimated_count"] == 1
    assert result["known_cost_usd"] == pytest.approx(.006)
    assert result["total_cost_usd"] is None
    assert result["total_cost_upper_usd"] is None
    assert result["mean_measured_cost_usd"] == pytest.approx(.003)
    assert result["per_1000_measured_usd"] == pytest.approx(3)


def test_aggregate_unknown_cache_bounds_and_cold_column():
    result = compare_cache_policies([{"usage": {"input_tokens": 1000, "output_tokens": 100}}] * 2, price())
    assert result["observed"]["mean_measured_cost_usd"] is None
    assert result["observed"]["total_cost_lower_usd"] == pytest.approx(.0022)
    assert result["observed"]["total_cost_upper_usd"] == pytest.approx(.006)
    assert result["observed"]["per_1000_measured_lower_usd"] == pytest.approx(1.1)
    assert result["cold"]["per_1000_measured_usd"] == pytest.approx(3)


def test_cache_writes_are_charged_at_their_reported_ttl_without_double_input():
    usage = {"input_tokens": 1000, "output_tokens": 100, "cached_tokens": 200,
             "cache_creation_input_tokens": 300, "cache_creation": {"ephemeral_5m_input_tokens": 100, "ephemeral_1h_input_tokens": 200}}
    rates = price(cache_write_5m_per_million=2.5, cache_write_1h_per_million=4)
    result = calculate_cost(usage, rates)
    assert result["cost_usd"] == pytest.approx((500*2 + 200*.1 + 100*2.5 + 200*4 + 100*10) / 1e6)
    assert result["cache_write_status"] == "observed"
    assert calculate_cost(usage, rates, "cold")["cost_usd"] == pytest.approx(.003)


def test_unknown_cache_write_ttl_is_bounded_by_all_published_write_rates():
    usage = {"input_tokens": 1000, "output_tokens": 100, "cached_tokens": 0, "cache_creation_input_tokens": 300}
    result = calculate_cost(usage, price(cache_write_5m_per_million=2, cache_write_1h_per_million=4, cache_write_per_million=2))
    assert result["cost_usd"] is None
    assert result["cost_lower_usd"] == pytest.approx(.003)
    assert result["cost_upper_usd"] == pytest.approx(.0036)
    assert "cache_write_duration_unknown_bounded_by_published_tiers" in result["reasons"]


def test_uncached_only_input_semantics_preserve_full_logical_input():
    usage = {"input_tokens": 500, "output_tokens": 100, "cache_read_input_tokens": 200, "cache_creation_input_tokens": 300}
    rates = price(input_token_semantics="uncached_only", cache_write_per_million=2.5)
    result = calculate_cost(usage, rates)
    assert result["cost_usd"] == pytest.approx((500*2 + 200*.1 + 300*2.5 + 100*10) / 1e6)
    assert result["logical_input_tokens"] == 1000
    assert calculate_cost(usage, rates, "cold")["cost_usd"] == pytest.approx(.003)


def test_named_peak_offpeak_variants_are_explicit_and_auditable():
    rates = price(variants={"offpeak": {"input_per_million": 1, "cached_input_per_million": .05, "output_per_million": 5}})
    usage = {"input_tokens": 1000, "output_tokens": 100, "cached_tokens": 0}
    result = calculate_cost(usage, rates, variant="offpeak")
    assert result["cost_usd"] == pytest.approx(.0015)
    assert result["source_url"] == rates.source_url
    assert result["verified_date"] == rates.verified_date
    with pytest.raises(ValueError):
        calculate_cost(usage, rates, variant="unknown")


def test_all_unknown_requests_remain_unknown_in_mean_and_per_thousand():
    result = aggregate_costs([{"usage": {}}], price(), "cold")
    assert result["known_cost_usd"] is None
    assert result["mean_measured_cost_usd"] is None
    assert result["per_1000_measured_usd"] is None
    assert result["unknown"] == 1


def test_unreported_cache_writes_with_configured_rate_extend_observed_interval():
    usage = {"input_tokens": 1000, "output_tokens": 100, "cached_tokens": 0}
    result = calculate_cost(usage, price(cache_write_5m_per_million=2.5))
    assert result["cost_usd"] is None
    assert result["cost_lower_usd"] == pytest.approx(.003)
    assert result["cost_upper_usd"] == pytest.approx(.0035)
    assert result["cache_write_status"] == "not_reported"
    assert "cache_write_tokens_not_reported" in result["reasons"]
    assert calculate_cost(usage, price(cache_write_5m_per_million=2.5), "cold")["cost_usd"] == pytest.approx(.003)


def test_nested_explicit_zero_cache_writes_are_observed_without_extra_charges():
    usage = {"prompt_tokens": 1000, "completion_tokens": 100,
             "prompt_tokens_details": {"cache_write_tokens": 0}}
    result = calculate_cost(usage, price(cached_input_per_million=.2, cache_write_5m_per_million=2, cache_write_1h_per_million=4))
    assert result["cache_write_status"] == "observed"
    assert result["cache_write_tokens"] == 0
    assert result["cache_status"] == "not_reported"
    assert result["cost_lower_usd"] == pytest.approx(.0012)
    assert result["cost_upper_usd"] == pytest.approx(.003)
    assert "cache_write_tokens_not_reported" not in result["reasons"]


def test_thirty_minute_and_twelve_hour_cache_write_tiers_use_exact_observations():
    usage = {"input_tokens": 1000, "output_tokens": 100, "cached_tokens": 100,
             "input_tokens_details": {"cache_write_30m_tokens": 200, "cache_write_12h_tokens": 100}}
    rates = price(cache_write_30m_per_million=2.5, cache_write_12h_per_million=5)
    result = calculate_cost(usage, rates)
    assert result["cost_usd"] == pytest.approx((600*2 + 100*.1 + 200*2.5 + 100*5 + 100*10) / 1e6)
    assert result["cache_write_30m_tokens"] == 200
    assert result["cache_write_12h_tokens"] == 100


def test_unknown_thirty_minute_or_twelve_hour_writes_have_honest_bounds():
    usage = {"input_tokens": 1000, "output_tokens": 100, "cached_tokens": 0}
    rates = price(cache_write_30m_per_million=2.5, cache_write_12h_per_million=5)
    result = calculate_cost(usage, rates)
    assert result["cost_usd"] is None
    assert result["cost_lower_usd"] == pytest.approx(.003)
    assert result["cost_upper_usd"] == pytest.approx(.006)
    assert result["cache_write_status"] == "not_reported"


def test_flat_input_price_has_point_cost_even_when_cache_counter_is_absent():
    flat = Price(input_per_million=.042, cached_input_per_million=.042, output_per_million=0)
    result = calculate_cost({"input_tokens": 7000, "output_tokens": 80}, flat)
    assert result["cost_usd"] == pytest.approx(.000294)
    assert result["cache_status"] == "not_reported"
    assert calculate_cost({"input_tokens": 7000, "output_tokens": 80}, flat, "cold")["cost_usd"] == pytest.approx(.000294)


def test_partial_write_ttl_with_total_prices_remainder_as_unknown_ttl():
    usage = {"input_tokens": 1000, "output_tokens": 100, "cached_tokens": 0,
             "cache_write_tokens": 300, "cache_write_5m_tokens": 100}
    result = calculate_cost(usage, price(cache_write_5m_per_million=2, cache_write_1h_per_million=4))
    assert result["cache_write_tokens"] == 300
    assert result["cache_write_1h_tokens"] is None
    assert result["cost_usd"] is None
    assert result["cost_lower_usd"] == pytest.approx((700*2 + 100*2 + 200*2 + 100*10) / 1e6)
    assert result["cost_upper_usd"] == pytest.approx((700*2 + 100*2 + 200*4 + 100*10) / 1e6)


def test_partial_write_ttl_without_total_keeps_unknown_writes_to_input_limit():
    usage = {"input_tokens": 1000, "output_tokens": 100, "cached_tokens": 0, "cache_write_5m_tokens": 100}
    result = calculate_cost(usage, price(cache_write_5m_per_million=2, cache_write_1h_per_million=4))
    assert result["cache_write_tokens"] is None
    assert result["cache_write_status"] == "partial"
    assert result["cache_write_1h_tokens"] is None
    assert result["cost_usd"] is None
    assert result["cost_lower_usd"] == pytest.approx(.003)
    assert result["cost_upper_usd"] == pytest.approx(.0048)
    assert "cache_write_ttl_counters_partially_reported" in result["reasons"]


def test_partial_uncached_only_writes_keep_logical_total_unknown():
    usage = {"input_tokens": 500, "output_tokens": 100, "cached_tokens": 100, "cache_write_5m_tokens": 100}
    rates = price(input_token_semantics="uncached_only", cache_write_5m_per_million=2, cache_write_1h_per_million=4)
    result = calculate_cost(usage, rates)
    assert result["logical_input_tokens"] is None
    assert result["cost_upper_usd"] is None
    assert calculate_cost(usage, rates, "cold")["cost_usd"] is None
