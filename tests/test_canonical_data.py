import pytest

from canonical_data import (
    CANONICAL_SCHEMA_VERSION,
    CanonicalDataError,
    load_canonical_items,
    load_canonical_promos,
    load_canonical_users,
    normalize_item_id,
    validate_canonical_item,
)
from mcp_server import get_item


def test_canonical_loaders_use_data_raw_and_publish_one_version():
    users = load_canonical_users()
    items = load_canonical_items()
    promos = load_canonical_promos()

    assert CANONICAL_SCHEMA_VERSION == "canonical-2026-06-15-v1"
    assert users["u_0001"]["city"] == "广州"
    assert items["i_0001"]["price_cents"] == 5790
    assert promos[0]["rule_id"].startswith("P")
    assert all(item_id.startswith("i_") for item_id in items)


def test_legacy_item_id_is_normalized_only_with_matching_identity():
    item = load_canonical_items()["i_0001"]

    assert normalize_item_id("i_0001") == "i_0001"
    assert normalize_item_id("item_0001", legacy_item=item) == "i_0001"

    with pytest.raises(CanonicalDataError, match="title"):
        normalize_item_id(
            "item_0001",
            legacy_item={"title": "另一个商品", "brand": item["brand"]},
        )


def test_unknown_or_malformed_item_id_is_rejected():
    with pytest.raises(CanonicalDataError, match="item_id"):
        normalize_item_id("item_9999")

    with pytest.raises(CanonicalDataError, match="item_id"):
        normalize_item_id("item_bad")


def test_canonical_item_validation_requires_integer_cents_and_canonical_id():
    item = dict(load_canonical_items()["i_0001"])
    assert validate_canonical_item(item)["item_id"] == "i_0001"

    item["price_cents"] = "57.90"
    with pytest.raises(CanonicalDataError, match="price_cents"):
        validate_canonical_item(item)


def test_mcp_item_reads_the_same_canonical_snapshot():
    item = get_item("i_0001")
    canonical = load_canonical_items()["i_0001"]

    assert item["found"] is True
    assert item["item_id"] == canonical["item_id"]
    assert item["title"] == canonical["title"]
    assert item["price_cents"] == canonical["price_cents"]
