import pytest

from scripts.strict_json_output import extract_last_json, strict_json_loads


def test_extract_last_json_skips_non_strict_tool_preview_and_returns_final_object():
    text = '''工具预览：{found:true,history_status:"warm",events:[…]}
我会开始查询。
{"user_id":"u_0001","recommendations":[],"agent_version":"rec-agent-v2"}'''

    assert extract_last_json(text) == {
        "user_id": "u_0001",
        "recommendations": [],
        "agent_version": "rec-agent-v2",
    }


def test_extract_last_json_uses_the_last_complete_strict_object():
    text = '{"intermediate":true}\n{"user_id":"u_0199","recommendations":[]}'

    assert extract_last_json(text)["user_id"] == "u_0199"


@pytest.mark.parametrize("text", [
    '{"x": NaN}', '{"x": Infinity}', '{"x": -Infinity}', '{"x": 1e999}',
    '{"x": 1, "x": 2}', '{"x": {"a": 1, "a": 2}}',
    '{} {}', '说明 {}', '```json\n{}\n```',
])
def test_whole_document_parser_rejects_non_strict_values(text):
    with pytest.raises(ValueError):
        strict_json_loads(text)
