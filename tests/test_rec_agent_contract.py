from pathlib import Path
import json
import re

from canonical_data import load_canonical_items


ROOT = Path(__file__).resolve().parents[1]


def test_rec_agent_preset_exposes_user_facing_reason_contract():
    patch = ROOT / "rec-agent-preset" / "cordis.patch.yml"
    readme = ROOT / "rec-agent-preset" / "README.md"

    assert patch.is_file()
    assert readme.is_file()
    patch_text = patch.read_text(encoding="utf-8")
    readme_text = readme.read_text(encoding="utf-8")

    assert 'name: Rec-Agent' in patch_text
    assert '"exposure_reason": "string"' in patch_text
    assert '"generated_reason": "string"' in patch_text
    assert '"agent_version": "rec-agent-v2"' in patch_text
    assert '"user_profile": {' in patch_text
    assert "exposure_reason 不得出现优惠、折扣、满减、价格" in patch_text
    assert "由大模型围绕商品关键信息创作" in patch_text
    assert "在内部拟写 2–3 个不同开头的候选" in patch_text
    assert "使用通用场景，不断言收件人的个人或家庭状态" in patch_text
    assert "逐字段回指文案" in patch_text
    assert "只返回一个格式化 JSON 对象" in patch_text
    assert "禁止输出单行压缩 JSON" in patch_text
    assert "不得在 JSON 前后输出英文或中文过程说明" in patch_text
    assert "generated_reason 必须与 exposure_reason 完全相同" in patch_text
    assert "get_user_recommendation_history" in patch_text
    assert "cold_start" in patch_text
    assert "只能有一个 JSON 根对象" in patch_text
    assert "禁止输出未加引号的键" in patch_text
    assert "禁止输出省略号" in patch_text
    assert "工具回显" in patch_text
    assert "调用工具前不要输出任何文本" in patch_text
    assert "工具调用之间不要发送自然语言消息" in patch_text
    assert "exposure_reason" in readme_text


def test_ad_copy_examples_use_canonical_facts_and_fit_length_contract():
    patch_text = (ROOT / "rec-agent-preset/cordis.patch.yml").read_text(encoding="utf-8")
    items = load_canonical_items()
    examples = re.findall(r"参考（(i_\d{4})；([^）]+)）：「([^」]+)」", patch_text)

    assert len(examples) == 4
    for item_id, sources, reason in examples:
        item = items[item_id]
        for source in sources.split("；"):
            field, expected = source.removeprefix("items.").split("=", 1)
            actual = item[field]
            assert ("|".join(actual) if isinstance(actual, list) else actual) == expected
        assert 8 <= len(reason) <= 20
        assert re.search(r"[0-9０-９]|(?:一|二|三|四|五|六|七|八|九|十|两|百)+(?:(?:包|层|抽|厘米|毫升|克|公斤|键|粒|片))", reason) is None
        assert "\n" not in reason

    for text in (patch_text, (ROOT / "rec-agent-preset/README.md").read_text(encoding="utf-8")):
        assert "8–18" in text and "不超过 20 个" in text
        assert "数量、尺寸、容量" in text
        assert "一抹" in text and "三餐" in text


def test_profile_links_to_main_workspace_preset():
    profile = Path.home() / ".dsh/profiles/desktop/package.json"
    text = profile.read_text(encoding="utf-8")

    assert "Jev曝光审核/rec-agent-preset" in text
    assert "Jev曝光审核_副本/rec-agent-preset" not in text


def test_rec_agent_native_output_boundary_is_wired_into_preset():
    patch = (ROOT / "rec-agent-preset/cordis.patch.yml").read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "rec-agent-preset/package.json").read_text(encoding="utf-8"))
    assert "- id: strict-output\n            name: '@local/dsh-rec-agent-preset'" in patch
    assert manifest["exports"]["."] == "./strict-output.js"
    assert (ROOT / "rec-agent-preset/strict-output.js").is_file()
