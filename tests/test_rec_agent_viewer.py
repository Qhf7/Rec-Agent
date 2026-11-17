from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIEWER = ROOT / "rec-agent-viewer.html"


def test_viewer_has_independent_pretty_result_panel():
    html = VIEWER.read_text(encoding="utf-8")

    assert 'id="formatted-result"' in html
    assert 'id="copy-formatted"' in html
    assert "JSON.stringify(payload, null, 2)" in html
    assert "white-space: pre-wrap" in html
    assert "tab-size: 2" in html

