import sys
import os

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from engine.thinking_detector import ThinkingDetector
from engine.quality_evaluator import QualityEvaluator
from engine.llm_router import UniversalGreedyJSONParser


def test_resilient_json_parser():
    print("--- Testing UniversalGreedyJSONParser ---")
    # Level 1: Clean JSON
    res1 = UniversalGreedyJSONParser.extract_json('{"scenes": [1, 2, 3]}')
    assert res1 == {"scenes": [1, 2, 3]}, f"Level 1 failed: {res1}"

    # Level 2: Markdown fence
    res2 = UniversalGreedyJSONParser.extract_json('```json\n{"scenes": [1, 2, 3]}\n```')
    assert res2 == {"scenes": [1, 2, 3]}, f"Level 2 failed: {res2}"

    # Level 3: Syntax repair (trailing commas & single quotes)
    malformed_json = "{'scenes': ['a', 'b', ], 'valid': True,}"
    res3 = UniversalGreedyJSONParser.extract_json(malformed_json)
    assert isinstance(res3, dict) and "scenes" in res3, f"Level 3 failed: {res3}"

    # Level 3b: Truncated JSON
    truncated_json = '{"scenes": [{"text": "Scene 1"}, {"text": "Scene 2"'
    res3b = UniversalGreedyJSONParser.extract_json(truncated_json)
    assert isinstance(res3b, dict) and "scenes" in res3b, f"Level 3b failed: {res3b}"

    # Level 4: Plain-Text Fallback Synthesis (Pure Prose)
    prose_script = """
    Scene 1: Turritopsis dohrnii is the only known creature capable of biological immortality.
    Scene 2: When starving or injured, it reverts its cells back to a juvenile polyp state.
    Scene 3: This transdifferentiation process completely resets its biological clock to zero.
    Scene 4: And that is why scientists are studying this tiny creature to unlock the secret of human longevity.
    """
    synth_script = UniversalGreedyJSONParser.extract_or_synthesize(prose_script, expected_type="script")
    assert "scenes" in synth_script and len(synth_script["scenes"]) == 4, f"Script synthesis failed: {synth_script}"
    print("✅ Resilient Parser Level 1-4 tests passed!")
    return synth_script, prose_script


def test_quality_evaluator(synth_script, prose_script):
    print("--- Testing QualityEvaluator ---")
    audit = QualityEvaluator.audit_script(synth_script, raw_text=prose_script)
    assert audit["score"] >= 6.0, f"Audit score too low: {audit}"
    assert audit["scene_count"] == 4, f"Scene count wrong: {audit}"
    print(f"✅ QualityEvaluator Script Audit: score={audit['score']}/10, feedback={audit['feedback']}")

    seo_prose = """
    Title: The Immortal Creature Science Cannot Explain #shorts
    Description: Discover the secret of Turritopsis dohrnii, the jellyfish that never dies.
    Tags: jellyfish, immortality, biology, science, nature, shorts, viral
    """
    synth_seo = UniversalGreedyJSONParser.extract_or_synthesize(seo_prose, expected_type="seo")
    seo_audit = QualityEvaluator.audit_seo(synth_seo, raw_text=seo_prose)
    assert seo_audit["score"] >= 6.0, f"SEO audit score too low: {seo_audit}"
    print(f"✅ QualityEvaluator SEO Audit: score={seo_audit['score']}/10, feedback={seo_audit['feedback']}")


def test_thinking_detector():
    print("--- Testing ThinkingDetector ---")
    # Test OpenAI reasoning_content
    mock_openai = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": '{"title": "Hi"}',
                "reasoning_content": "Thinking deeply about jellyfish cellular reversal..."
            }
        }],
        "usage": {"completion_tokens_details": {"reasoning_tokens": 45}}
    }
    t_op = ThinkingDetector.detect_openai_response(mock_openai)
    assert t_op["is_thinking"] is True, f"OpenAI thinking detection failed: {t_op}"
    assert t_op["thought_tokens"] == 45, f"OpenAI tokens count failed: {t_op}"
    print(f"✅ ThinkingDetector OpenAI: is_thinking={t_op['is_thinking']}, method={t_op['method']}, tokens={t_op['thought_tokens']}")

    # Test XML tags
    t_xml = ThinkingDetector.detect_openai_response(None, raw_text="<think>Internal reasoning step</think> Final answer")
    assert t_xml["is_thinking"] is True and t_xml["method"] == "xml_tags", f"XML thinking detection failed: {t_xml}"
    print("✅ ThinkingDetector XML tags test passed!")

    # Test Google Mock
    class MockPart:
        def __init__(self, text, thought=False):
            self.text = text
            self.thought = thought

    class MockContent:
        def __init__(self, parts):
            self.parts = parts

    class MockCandidate:
        def __init__(self, content):
            self.content = content

    class MockResponse:
        def __init__(self, candidates):
            self.candidates = candidates
            self.usage_metadata = None

    mock_google = MockResponse([
        MockCandidate(MockContent([
            MockPart("Let's analyze the life cycle of jellyfish...", thought=True),
            MockPart('{"scenes": []}', thought=False)
        ]))
    ])
    t_goog = ThinkingDetector.detect_google_response(mock_google)
    assert t_goog["is_thinking"] is True and t_goog["method"] == "native_part", f"Google thinking detection failed: {t_goog}"
    print(f"✅ ThinkingDetector Google: is_thinking={t_goog['is_thinking']}, method={t_goog['method']}, tokens={t_goog['thought_tokens']}")


if __name__ == "__main__":
    synth_script, prose_script = test_resilient_json_parser()
    test_quality_evaluator(synth_script, prose_script)
    test_thinking_detector()
    print("\n🎉 ALL 3 TEST SUITES PASSED WITH 100% SUCCESS!")
