from bible_cc_plugin.daemon.detector import _format_turns, _parse_moments


def test_format_turns():
    turns = [
        {"role": "user", "content": "I want to build a web app."},
        {"role": "assistant", "content": "What framework?"},
        {"role": "user", "content": "Let's use Flask."},
    ]
    formatted = _format_turns(turns)
    assert "[1] user: I want to build a web app." in formatted
    assert "[3] user: Let's use Flask." in formatted


def test_parse_moments_valid_json():
    text = '[{"type": "decision", "title": "Chose Flask", "narrative": "User decided on Flask.", "turn_range": "2-3"}]'
    moments = _parse_moments(text)
    assert len(moments) == 1
    assert moments[0]["type"] == "decision"
    assert moments[0]["title"] == "Chose Flask"


def test_parse_moments_markdown_fenced():
    text = '```json\n[{"type": "accomplishment", "title": "Done", "narrative": "Feature complete.", "turn_range": "4-6"}]\n```'
    moments = _parse_moments(text)
    assert len(moments) == 1
    assert moments[0]["type"] == "accomplishment"


def test_parse_moments_empty():
    assert _parse_moments("[]") == []


def test_parse_moments_invalid():
    assert _parse_moments("not json") == []
    assert _parse_moments('{"not": "array"}') == []
