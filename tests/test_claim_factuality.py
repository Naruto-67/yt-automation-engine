"""
tests/test_claim_factuality.py — Isolated Unit Tests for Standalone Claim Inspector (v1.0)

Covers:
1. Empirical classification
2. Subjective opinion exemption
3. Metaphor/analogy non-literal handling
4. Mixed statement proposition extraction
5. Ambiguous statement handling
6. Relevant evidence directly supports claim
7. Relevant evidence directly contradicts claim
8. Irrelevant evidence yields unverifiable
9. Insufficient evidence yields unverifiable
10. Numerical scope/precision mismatch not supported
11. Multiple claims in one scene traceable to scene
12. Malformed model output handled safely
13. Verifier exception yields verification_unavailable, never supported
14. Missing source metadata is not fabricated
15. Empty inputs and missing optional evidence handled consistently
16. Zero side effects on disk, caches, or output files
17. Stage 1.2 Surgical evidence-selection corrections (token queries, index verification, fallback removal)
"""

import os
import pathlib
import pytest
from unittest.mock import MagicMock

from engine.managers.claim_inspector import (
    ClaimInspector,
    ClaimClassification,
    VerificationOutcome,
    RiskLevel,
    EvidenceReference,
    ClaimRecord,
    ClaimInspectionReport,
    assess_risk_level
)


# ─── 1. EMPIRICAL CLASSIFICATION ──────────────────────────────────────────────

def test_empirical_statement_classified_as_empirical():
    """A clearly empirical statement is classified as empirical."""
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "classification": "empirical",
        "rationale": "Objective anatomical and physical assertion about humming.",
        "propositions": [
            {
                "proposition": "You physically cannot hum while holding your nose shut.",
                "risk_level": "low"
            }
        ]
    }

    inspector = ClaimInspector(llm_manager=mock_llm)
    classification, props, rationale, err = inspector.classify_and_extract(
        "You physically cannot hum while holding your nose shut."
    )

    assert classification == ClaimClassification.EMPIRICAL.value
    assert len(props) == 1
    assert props[0]["proposition"] == "You physically cannot hum while holding your nose shut."
    assert err is None


# ─── 2. SUBJECTIVE OPINION EXEMPTION ─────────────────────────────────────────

def test_subjective_opinion_exempt_from_verification():
    """A subjective opinion is exempt from empirical verification with not_applicable outcome."""
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "classification": "subjective",
        "rationale": "Personal sensory and aesthetic judgment about popcorn smell.",
        "propositions": []
    }

    inspector = ClaimInspector(llm_manager=mock_llm)
    records = inspector.inspect_scene("Popcorn steam is the most nostalgic smell on Earth.", scene_id=1)

    assert len(records) == 1
    rec = records[0]
    assert rec.classification == ClaimClassification.SUBJECTIVE.value
    assert rec.outcome == VerificationOutcome.NOT_APPLICABLE.value
    assert rec.evidence == []
    assert rec.extracted_proposition == ""
    assert "exempt" in rec.rationale.lower() or "subjective" in rec.rationale.lower()


# ─── 3. METAPHOR / ANALOGY HANDLING ──────────────────────────────────────────

def test_metaphor_not_treated_as_literal_fact():
    """A figurative metaphor is classified as metaphorical and exempt from factual debunking."""
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "classification": "metaphorical",
        "rationale": "Poetic comparison between sleep and biological battery charging.",
        "propositions": []
    }

    inspector = ClaimInspector(llm_manager=mock_llm)
    records = inspector.inspect_scene("Sleeping is just charging your biological battery.", scene_id=2)

    assert len(records) == 1
    rec = records[0]
    assert rec.classification == ClaimClassification.METAPHORICAL.value
    assert rec.outcome == VerificationOutcome.NOT_APPLICABLE.value
    assert rec.evidence == []


# ─── 4. MIXED STATEMENT EXTRACTION ───────────────────────────────────────────

def test_mixed_statement_extracts_empirical_core():
    """A mixed statement preserves original text and extracts only the empirical proposition."""
    original_text = "Oxygen is the ultimate villain because it slowly damages our cells over decades."
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "classification": "mixed",
        "rationale": "Combines dramatic hyperbole with empirical observation of oxidative stress.",
        "propositions": [
            {
                "proposition": "Oxygen slowly damages human cells over decades.",
                "risk_level": "medium"
            }
        ]
    }

    inspector = ClaimInspector(llm_manager=mock_llm)
    records = inspector.inspect_scene(original_text, scene_id=3)

    assert len(records) == 1
    rec = records[0]
    assert rec.classification == ClaimClassification.MIXED.value
    assert rec.original_text == original_text
    assert rec.extracted_proposition == "Oxygen slowly damages human cells over decades."
    assert rec.risk_level == RiskLevel.MEDIUM.value


# ─── 5. AMBIGUOUS STATEMENT HANDLING ─────────────────────────────────────────

def test_ambiguous_statement_handled_as_ambiguous():
    """An ambiguous or grammatically fragmented statement receives ambiguous classification."""
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "classification": "ambiguous",
        "rationale": "Incomplete clause lacking clear proposition.",
        "propositions": []
    }

    inspector = ClaimInspector(llm_manager=mock_llm)
    records = inspector.inspect_scene("Which is why you should never...", scene_id=4)

    assert len(records) == 1
    rec = records[0]
    assert rec.classification == ClaimClassification.AMBIGUOUS.value
    assert rec.outcome == VerificationOutcome.AMBIGUOUS.value


# ─── 6. RELEVANT EVIDENCE SUPPORTS CLAIM ─────────────────────────────────────

def test_relevant_evidence_directly_supports_claim():
    """Relevant evidence directly corroborates proposition yielding supported outcome."""
    proposition = "You physically cannot hum while holding your nose shut."
    evidence_item = EvidenceReference(
        id="body_03",
        source="verified_science",
        text="You physically cannot hum while holding your nose shut.",
        pillar="human_body_and_perception",
        type="fact"
    )

    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "outcome": "supported",
        "supporting_indices": [1],
        "rationale": "Directly corroborated by respiratory mechanics evidence record body_03."
    }

    inspector = ClaimInspector(llm_manager=mock_llm)
    outcome, supporting_ev, rationale, err = inspector.verify_proposition(
        proposition, candidate_evidence=[evidence_item]
    )

    assert outcome == VerificationOutcome.SUPPORTED.value
    assert len(supporting_ev) == 1
    assert supporting_ev[0].id == "body_03"
    assert supporting_ev[0].source == "verified_science"
    assert err is None


# ─── 7. RELEVANT EVIDENCE CONTRADICTS CLAIM ──────────────────────────────────

def test_relevant_evidence_directly_contradicts_claim():
    """Relevant evidence directly refuting a claim yields contradicted outcome."""
    proposition = "Cracking your knuckles causes arthritis."
    conflicting_ev = EvidenceReference(
        id="med_01",
        source="Harvard Medical School",
        text="Cracking your knuckles does not cause arthritis or joint damage.",
        pillar="medicine",
        type="fact"
    )

    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "outcome": "contradicted",
        "supporting_indices": [1],
        "rationale": "Medical study explicitly disproves that knuckle cracking causes arthritis."
    }

    inspector = ClaimInspector(llm_manager=mock_llm)
    outcome, supporting_ev, rationale, err = inspector.verify_proposition(
        proposition, candidate_evidence=[conflicting_ev]
    )

    assert outcome == VerificationOutcome.CONTRADICTED.value
    assert len(supporting_ev) == 1
    assert supporting_ev[0].id == "med_01"


# ─── 8. IRRELEVANT EVIDENCE YIELDS UNVERIFIABLE ──────────────────────────────

def test_irrelevant_evidence_returns_unverifiable():
    """Topically unrelated evidence does not count as support and yields unverifiable."""
    proposition = "Every mirror you purchase is technically used since someone tested it."
    irrelevant_ev = EvidenceReference(
        id="ocean_01",
        source="Marine Biology",
        text="Octopuses have three hearts and blue copper-based blood.",
        pillar="animals",
        type="fact"
    )

    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "outcome": "unverifiable",
        "supporting_indices": [],
        "rationale": "Marine biology evidence is completely irrelevant to mirror manufacturing."
    }

    inspector = ClaimInspector(llm_manager=mock_llm)
    outcome, supporting_ev, rationale, err = inspector.verify_proposition(
        proposition, candidate_evidence=[irrelevant_ev]
    )

    assert outcome == VerificationOutcome.UNVERIFIABLE.value
    assert len(supporting_ev) == 0


# ─── 9. INSUFFICIENT EVIDENCE YIELDS UNVERIFIABLE ────────────────────────────

def test_insufficient_evidence_returns_unverifiable():
    """When candidate evidence is empty, verify_proposition returns unverifiable without inventing facts."""
    inspector = ClaimInspector(llm_manager=None)
    outcome, supporting_ev, rationale, err = inspector.verify_proposition(
        "Ancient Romans brushed their teeth with crushed seashells.",
        candidate_evidence=[]
    )

    assert outcome == VerificationOutcome.UNVERIFIABLE.value
    assert supporting_ev == []
    assert "no candidate evidence" in rationale.lower()


# ─── 10. NUMERICAL MISMATCH NOT SUPPORTED ────────────────────────────────────

def test_numerical_claim_mismatch_not_supported():
    """Evidence with materially different numbers/timeframes is not accepted as supported."""
    proposition = "Oxygen destroys 95% of human brain cells every year."
    general_ev = EvidenceReference(
        id="bio_02",
        source="verified_science",
        text="Oxygen causes oxidative stress in cells over decades.",
        pillar="human_body_and_perception",
        type="fact"
    )

    # Even if LLM mistakenly returns 'supported', our numerical safety check prevents it
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "outcome": "supported",
        "supporting_indices": [1],
        "rationale": "Evidence mentions oxygen and cells."
    }

    inspector = ClaimInspector(llm_manager=mock_llm)
    outcome, supporting_ev, rationale, err = inspector.verify_proposition(
        proposition, candidate_evidence=[general_ev]
    )

    assert outcome != VerificationOutcome.SUPPORTED.value
    assert outcome == VerificationOutcome.CONTRADICTED.value
    assert "numerical mismatch" in rationale.lower()


# ─── 11. MULTIPLE CLAIMS IN ONE SCENE ────────────────────────────────────────

def test_multiple_claims_in_one_scene_independent_and_traceable():
    """A scene with two factual assertions yields two distinct, traceable ClaimRecords."""
    scene_text = "Your brain uses 20% of your body's energy, and you cannot hum while holding your nose."
    mock_llm = MagicMock()

    def mock_gen_json(sys_p, usr_p, **kw):
        if "classify" in sys_p.lower():
            return {
                "classification": "empirical",
                "rationale": "Compound empirical observation.",
                "propositions": [
                    {
                        "proposition": "Your brain uses 20% of your body's energy.",
                        "risk_level": "medium"
                    },
                    {
                        "proposition": "You cannot hum while holding your nose shut.",
                        "risk_level": "low"
                    }
                ]
            }
        else:
            return {
                "outcome": "supported",
                "supporting_indices": [1],
                "rationale": "Corroborated by biological evidence."
            }

    mock_llm.generate_json.side_effect = mock_gen_json
    inspector = ClaimInspector(llm_manager=mock_llm)

    records = inspector.inspect_scene(scene_text, scene_id=7, chapter_id=2)

    assert len(records) == 2
    assert records[0].claim_id == "claim_7_1"
    assert records[0].scene_id == 7
    assert records[0].chapter_id == 2
    assert records[0].original_text == scene_text
    assert "20%" in records[0].extracted_proposition
    assert records[0].risk_level == RiskLevel.MEDIUM.value

    assert records[1].claim_id == "claim_7_2"
    assert records[1].scene_id == 7
    assert records[1].chapter_id == 2
    assert records[1].original_text == scene_text
    assert "hum" in records[1].extracted_proposition
    assert records[1].risk_level == RiskLevel.LOW.value


# ─── 12. MALFORMED MODEL OUTPUT ──────────────────────────────────────────────

def test_malformed_model_output_handled_safely():
    """Non-dictionary or invalid JSON response is handled safely without raising unhandled exceptions."""
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = "This is a raw text string, not a JSON dictionary"

    inspector = ClaimInspector(llm_manager=mock_llm)
    records = inspector.inspect_scene("A test claim.", scene_id=1)

    assert len(records) == 1
    assert records[0].outcome == VerificationOutcome.VERIFICATION_UNAVAILABLE.value
    assert records[0].error_reason is not None
    assert "non-dictionary" in records[0].error_reason.lower() or "malformed" in records[0].error_reason.lower()


# ─── 13. VERIFIER EXCEPTION YIELDS VERIFICATION_UNAVAILABLE ───────────────────

def test_verifier_exception_yields_verification_unavailable_never_supported():
    """Network or timeout exceptions yield verification_unavailable, never supported."""
    mock_llm = MagicMock()
    # First call classifies as empirical
    # Second call raises TimeoutError
    calls = [0]
    def mock_gen_json(sys_p, usr_p, **kw):
        calls[0] += 1
        if calls[0] == 1:
            return {
                "classification": "empirical",
                "rationale": "Objective observation.",
                "propositions": [{"proposition": "Water boils at 100 degrees Celsius.", "risk_level": "medium"}]
            }
        raise TimeoutError("LLM API gateway timeout after 10000ms")

    mock_llm.generate_json.side_effect = mock_gen_json
    inspector = ClaimInspector(llm_manager=mock_llm)

    test_ev = [EvidenceReference(id="chem_01", text="Water boiling point is 100C.")]
    records = inspector.inspect_scene("Water boils at 100 degrees Celsius.", scene_id=5, candidate_evidence=test_ev)

    assert len(records) == 1
    assert records[0].outcome == VerificationOutcome.VERIFICATION_UNAVAILABLE.value
    assert "timeout" in records[0].error_reason.lower()
    assert records[0].outcome != VerificationOutcome.SUPPORTED.value


# ─── 14. MISSING METADATA NOT FABRICATED ──────────────────────────────────────

def test_missing_source_metadata_not_fabricated():
    """Evidence with missing optional metadata preserves None without fabricating URLs or dates."""
    ev = EvidenceReference(
        id="body_01",
        text="The only part of your reflection you can actually lick is your tongue."
    )
    d = ev.to_dict()

    assert d["id"] == "body_01"
    assert d["text"] == "The only part of your reflection you can actually lick is your tongue."
    assert "url" not in d
    assert "timestamp" not in d
    assert "source" not in d


# ─── 15. EMPTY INPUTS & MISSING OPTIONAL EVIDENCE ────────────────────────────

def test_empty_inputs_and_missing_optional_evidence_handled_consistently():
    """Empty scene lists and whitespace-only inputs are handled cleanly."""
    inspector = ClaimInspector(llm_manager=None)

    # Empty script
    report = inspector.inspect_script([])
    assert report.status == "completed"
    assert len(report.claims) == 0
    assert report.summary["total_claims"] == 0

    # Whitespace-only scene
    records = inspector.inspect_scene("   \n\t  ")
    assert len(records) == 1
    assert records[0].classification == ClaimClassification.AMBIGUOUS.value


# ─── 16. ZERO SIDE EFFECTS ON DISK ───────────────────────────────────────────

def test_import_and_execution_zero_side_effects_on_disk():
    """Importing ClaimInspector and running inspection creates no files on disk."""
    import hashlib

    # Capture initial state of memory, config, output directories
    target_dirs = ["memory", "config", "output"]
    initial_files = {}

    for d in target_dirs:
        p = pathlib.Path(d)
        if p.exists():
            for f in p.glob("**/*"):
                if f.is_file():
                    initial_files[str(f)] = hashlib.sha256(f.read_bytes()).hexdigest()

    # Instantiate and run inspector on sample scenes
    inspector = ClaimInspector(llm_manager=None)
    scenes = [
        {"scene_id": 1, "spoken_text": "The only part of your reflection you can lick is your tongue."},
        {"scene_id": 2, "spoken_text": "Popcorn steam is the most nostalgic smell on Earth."},
        {"scene_id": 3, "spoken_text": "Sleeping is just charging your biological battery."}
    ]
    report = inspector.inspect_script(scenes)

    assert report.status == "completed"
    assert len(report.claims) == 3

    # Verify no files were created, deleted, or modified
    for d in target_dirs:
        p = pathlib.Path(d)
        if p.exists():
            for f in p.glob("**/*"):
                if f.is_file():
                    assert str(f) in initial_files, f"Unexpected new file created on disk: {f}"
                    current_hash = hashlib.sha256(f.read_bytes()).hexdigest()
                    assert current_hash == initial_files[str(f)], f"File mutated on disk: {f}"


# ─── 17. STAGE 1.2 EVIDENCE-SELECTION REGRESSION TESTS ────────────────────────

def test_empty_content_token_query_returns_empty_list():
    """Queries with no usable content tokens return empty list rather than top vault items."""
    inspector = ClaimInspector(llm_manager=None)

    # All stopwords
    results = inspector.find_candidate_evidence("what about this and that")
    assert results == []

    # Short tokens under 3 chars / punctuation
    results2 = inspector.find_candidate_evidence("is it on? !!")
    assert results2 == []

    # Blank query
    results3 = inspector.find_candidate_evidence("   ")
    assert results3 == []


def test_multiple_candidates_missing_supporting_indices_yields_unverifiable():
    """When multiple candidates exist and verifier asserts supported without indices, outcome is unverifiable."""
    cands = [
        EvidenceReference(id="ev_1", text="Human blood is red due to hemoglobin."),
        EvidenceReference(id="ev_2", text="Octopus blood is blue due to hemocyanin."),
        EvidenceReference(id="ev_3", text="Horseshoe crab blood is copper-based and blue.")
    ]

    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "outcome": "supported",
        "supporting_indices": [],  # Missing/empty
        "rationale": "I consider this supported but did not cite an index."
    }

    inspector = ClaimInspector(llm_manager=mock_llm)
    outcome, supporting_ev, rationale, err = inspector.verify_proposition(
        "Octopus blood contains hemocyanin.",
        candidate_evidence=cands
    )

    assert outcome == VerificationOutcome.UNVERIFIABLE.value
    assert supporting_ev == []
    assert "no valid supporting evidence reference" in rationale.lower()


def test_valid_explicit_index_selects_correct_record():
    """Explicit valid 1-based index correctly selects corresponding candidate record."""
    cands = [
        EvidenceReference(id="ev_1", text="Human blood is red due to hemoglobin."),
        EvidenceReference(id="ev_2", text="Octopus blood is blue due to hemocyanin."),
        EvidenceReference(id="ev_3", text="Horseshoe crab blood is copper-based and blue.")
    ]

    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "outcome": "supported",
        "supporting_indices": [2],
        "rationale": "Directly supported by candidate record #2."
    }

    inspector = ClaimInspector(llm_manager=mock_llm)
    outcome, supporting_ev, rationale, err = inspector.verify_proposition(
        "Octopus blood contains hemocyanin.",
        candidate_evidence=cands
    )

    assert outcome == VerificationOutcome.SUPPORTED.value
    assert len(supporting_ev) == 1
    assert supporting_ev[0].id == "ev_2"
    assert supporting_ev[0].text == "Octopus blood is blue due to hemocyanin."


def test_invalid_and_out_of_range_indices_handled_safely():
    """Malformed, non-integer, bool, or out-of-range indices do not cause crashes or spurious support."""
    cands = [
        EvidenceReference(id="ev_1", text="First piece of evidence."),
        EvidenceReference(id="ev_2", text="Second piece of evidence.")
    ]

    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "outcome": "supported",
        "supporting_indices": [0, 999, "two", None, True, -1],
        "rationale": "Attempting supported with bogus indices."
    }

    inspector = ClaimInspector(llm_manager=mock_llm)
    outcome, supporting_ev, rationale, err = inspector.verify_proposition(
        "A test proposition.",
        candidate_evidence=cands
    )

    assert outcome == VerificationOutcome.UNVERIFIABLE.value
    assert supporting_ev == []
    assert "no valid supporting evidence reference" in rationale.lower()


def test_supported_without_valid_reference_cannot_produce_supported():
    """Model judgment alone asserting supported with out-of-bounds index cannot produce SUPPORTED outcome."""
    cand = EvidenceReference(id="ev_1", text="Only one candidate available.")

    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "outcome": "supported",
        "supporting_indices": [999],
        "rationale": "Trust me, it is true."
    }

    inspector = ClaimInspector(llm_manager=mock_llm)
    outcome, supporting_ev, rationale, err = inspector.verify_proposition(
        "Some claim.",
        candidate_evidence=[cand]
    )

    assert outcome == VerificationOutcome.UNVERIFIABLE.value
    assert supporting_ev == []


def test_contradicted_without_valid_reference_attaches_no_evidence():
    """Contradicted outcome without valid supporting indices preserves contradicted outcome with empty evidence list."""
    cand = EvidenceReference(id="ev_1", text="General scientific observation.")

    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "outcome": "contradicted",
        "supporting_indices": [],
        "rationale": "Contradicted based on general physical principles."
    }

    inspector = ClaimInspector(llm_manager=mock_llm)
    outcome, supporting_ev, rationale, err = inspector.verify_proposition(
        "Perpetual motion machines generate infinite energy.",
        candidate_evidence=[cand]
    )

    assert outcome == VerificationOutcome.CONTRADICTED.value
    assert supporting_ev == []
    assert "no specific conflicting evidence record index identified" in rationale


# ─── 18. STAGE 3A POLICY EVALUATION TESTS ─────────────────────────────────────

def test_policy_evaluation_supported_claims_pass():
    """All supported empirical claims evaluate to FactualityPolicyStatus.PASSED."""
    from engine.managers.pipeline_runner import FactualityPolicyStatus, evaluate_shorts_factuality_policy

    report = ClaimInspectionReport(
        claims=[
            ClaimRecord(
                claim_id="claim_1_1",
                scene_id=1,
                original_text="The only part of your reflection you can lick is your tongue.",
                extracted_proposition="The only part of your reflection you can lick is your tongue.",
                classification=ClaimClassification.EMPIRICAL.value,
                outcome=VerificationOutcome.SUPPORTED.value,
                risk_level=RiskLevel.LOW.value,
                evidence=[EvidenceReference(id="ev_1", text="Reflection anatomy fact.")],
                rationale="Corroborated by optical anatomy."
            )
        ],
        status="completed"
    )

    status, reason, affected = evaluate_shorts_factuality_policy(report)
    assert status == FactualityPolicyStatus.PASSED
    assert len(affected) == 0
    assert "supported or exempt" in reason.lower()


def test_policy_evaluation_low_risk_unverifiable_yields_passed_with_unverified():
    """Unverifiable low-risk empirical claims evaluate to PASSED_WITH_UNVERIFIED under policy allowance."""
    from engine.managers.pipeline_runner import FactualityPolicyStatus, evaluate_shorts_factuality_policy

    report = ClaimInspectionReport(
        claims=[
            ClaimRecord(
                claim_id="claim_1_1",
                scene_id=1,
                original_text="You physically cannot hum while holding your nose shut.",
                extracted_proposition="You physically cannot hum while holding your nose shut.",
                classification=ClaimClassification.EMPIRICAL.value,
                outcome=VerificationOutcome.UNVERIFIABLE.value,
                risk_level=RiskLevel.LOW.value,
                evidence=[],
                rationale="No candidate evidence in curated vault."
            )
        ],
        status="completed"
    )

    status, reason, affected = evaluate_shorts_factuality_policy(report)
    assert status == FactualityPolicyStatus.PASSED_WITH_UNVERIFIED
    assert len(affected) == 0
    assert "low-risk policy" in reason.lower()


def test_policy_evaluation_contradiction_evidence_backed_vs_model_assessed():
    """Contradicted outcomes distinguish between evidence-backed and model-assessed contradictions."""
    from engine.managers.pipeline_runner import FactualityPolicyStatus, evaluate_shorts_factuality_policy

    # Case A: Evidence-backed contradiction (evidence list non-empty)
    report_ev_backed = ClaimInspectionReport(
        claims=[
            ClaimRecord(
                claim_id="claim_1_1",
                scene_id=1,
                original_text="Cracking your knuckles causes arthritis.",
                extracted_proposition="Cracking your knuckles causes arthritis.",
                classification=ClaimClassification.EMPIRICAL.value,
                outcome=VerificationOutcome.CONTRADICTED.value,
                risk_level=RiskLevel.LOW.value,
                evidence=[EvidenceReference(id="med_01", text="Knuckle cracking does not cause joint damage.")],
                rationale="Evidence disproves arthritis assertion."
            )
        ],
        status="failed"
    )
    status_a, reason_a, affected_a = evaluate_shorts_factuality_policy(report_ev_backed)
    assert status_a == FactualityPolicyStatus.REJECTED_CONTRADICTION
    assert "Evidence-backed contradiction in Scene 1" in reason_a
    assert len(affected_a) == 1
    assert affected_a[0][0] == 1

    # Case B: Model-assessed contradiction (evidence list empty)
    report_model_assessed = ClaimInspectionReport(
        claims=[
            ClaimRecord(
                claim_id="claim_1_1",
                scene_id=1,
                original_text="Perpetual motion machines generate infinite energy.",
                extracted_proposition="Perpetual motion machines generate infinite energy.",
                classification=ClaimClassification.EMPIRICAL.value,
                outcome=VerificationOutcome.CONTRADICTED.value,
                risk_level=RiskLevel.LOW.value,
                evidence=[],
                rationale="Thermodynamic contradiction according to model reasoning."
            )
        ],
        status="failed"
    )
    status_b, reason_b, affected_b = evaluate_shorts_factuality_policy(report_model_assessed)
    assert status_b == FactualityPolicyStatus.REJECTED_CONTRADICTION
    assert "Model-assessed contradiction in Scene 1" in reason_b
    assert len(affected_b) == 1
    assert affected_b[0][0] == 1


def test_policy_evaluation_high_and_medium_risk_unverified_fail_closed():
    """High-risk and medium-risk unverified claims fail closed under policy."""
    from engine.managers.pipeline_runner import FactualityPolicyStatus, evaluate_shorts_factuality_policy

    # High-risk unverifiable
    report_high = ClaimInspectionReport(
        claims=[
            ClaimRecord(
                claim_id="claim_1_1",
                scene_id=2,
                original_text="Drinking snake poison cures all cellular cancer.",
                extracted_proposition="Drinking snake poison cures cancer.",
                classification=ClaimClassification.EMPIRICAL.value,
                outcome=VerificationOutcome.UNVERIFIABLE.value,
                risk_level=RiskLevel.HIGH.value,
                evidence=[],
                rationale="No medical evidence."
            )
        ],
        status="completed"
    )
    status_h, reason_h, affected_h = evaluate_shorts_factuality_policy(report_high)
    assert status_h == FactualityPolicyStatus.REJECTED_HIGH_RISK_UNVERIFIED
    assert len(affected_h) == 1
    assert affected_h[0][0] == 2

    # Medium-risk unverifiable (specific percentage)
    report_med = ClaimInspectionReport(
        claims=[
            ClaimRecord(
                claim_id="claim_1_1",
                scene_id=3,
                original_text="Exactly 94.6% of human skin cells regenerate every four hours.",
                extracted_proposition="94.6% of human skin cells regenerate every four hours.",
                classification=ClaimClassification.EMPIRICAL.value,
                outcome=VerificationOutcome.UNVERIFIABLE.value,
                risk_level=RiskLevel.MEDIUM.value,
                evidence=[],
                rationale="Quantitative stat lacks citation."
            )
        ],
        status="completed"
    )
    status_m, reason_m, affected_m = evaluate_shorts_factuality_policy(report_med)
    assert status_m == FactualityPolicyStatus.REJECTED_MEDIUM_RISK_UNVERIFIED
    assert len(affected_m) == 1
    assert affected_m[0][0] == 3


def test_policy_evaluation_service_unavailable_high_risk_fails_closed():
    """Service unavailability on a high-risk claim yields VERIFICATION_UNAVAILABLE."""
    from engine.managers.pipeline_runner import FactualityPolicyStatus, evaluate_shorts_factuality_policy

    report_unavail = ClaimInspectionReport(
        claims=[
            ClaimRecord(
                claim_id="claim_1_1",
                scene_id=1,
                original_text="This synthetic chemical antidote neutralizes lethal nerve poison.",
                extracted_proposition="Antidote neutralizes lethal poison.",
                classification=ClaimClassification.EMPIRICAL.value,
                outcome=VerificationOutcome.VERIFICATION_UNAVAILABLE.value,
                risk_level=RiskLevel.HIGH.value,
                evidence=[],
                error_reason="LLM provider timed out after 30 seconds"
            )
        ],
        status="failed"
    )
    status, reason, affected = evaluate_shorts_factuality_policy(report_unavail)
    assert status == FactualityPolicyStatus.VERIFICATION_UNAVAILABLE
    assert "Verification service unavailable for high-risk claim" in reason
    assert len(affected) == 1


def test_policy_evaluation_subjective_and_metaphorical_exempt():
    """Subjective and metaphorical statements with not_applicable outcome pass policy without evidence."""
    from engine.managers.pipeline_runner import FactualityPolicyStatus, evaluate_shorts_factuality_policy

    report = ClaimInspectionReport(
        claims=[
            ClaimRecord(
                claim_id="claim_1_1",
                scene_id=1,
                original_text="Popcorn steam is the most nostalgic smell on Earth.",
                extracted_proposition="",
                classification=ClaimClassification.SUBJECTIVE.value,
                outcome=VerificationOutcome.NOT_APPLICABLE.value,
                risk_level=RiskLevel.LOW.value,
                evidence=[],
                rationale="Subjective statement exempt from empirical verification."
            ),
            ClaimRecord(
                claim_id="claim_2_1",
                scene_id=2,
                original_text="Sleeping is just charging your biological battery.",
                extracted_proposition="",
                classification=ClaimClassification.METAPHORICAL.value,
                outcome=VerificationOutcome.NOT_APPLICABLE.value,
                risk_level=RiskLevel.LOW.value,
                evidence=[],
                rationale="Metaphorical statement exempt from empirical verification."
            )
        ],
        status="completed"
    )

    status, reason, affected = evaluate_shorts_factuality_policy(report)
    assert status == FactualityPolicyStatus.PASSED
    assert len(affected) == 0
