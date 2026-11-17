from pathlib import Path


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
    assert "不能只是「人群/用途 + 类目 + 规格」的事实罗列" in patch_text
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
    assert "exposure_reason" in readme_text


def test_profile_links_to_main_workspace_preset():
    profile = Path.home() / ".dsh/profiles/desktop/package.json"
    text = profile.read_text(encoding="utf-8")

    assert "Jev曝光审核/rec-agent-preset" in text
    assert "Jev曝光审核_副本/rec-agent-preset" not in text
