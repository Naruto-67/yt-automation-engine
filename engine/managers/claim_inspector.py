"""
engine/managers/claim_inspector.py — Standalone Claim-Level Factuality & Provenance Inspector (v1.0)

Extracts factual claims from script scenes, classifies statements (empirical, subjective,
metaphorical, mixed, ambiguous), evaluates empirical propositions against candidate evidence,
and returns an in-memory auditable provenance report without mutating disk, caches, or pipeline schemas.
"""

from __future__ import annotations

import os
import re
import json
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple, Union, Set


# ─── ENUMS & DATA CONTRACTS ──────────────────────────────────────────────────

class ClaimClassification(str, Enum):
    """Classification of a statement or extracted proposition."""
    EMPIRICAL = "empirical"          # Proposition that can meaningfully be checked against evidence
    SUBJECTIVE = "subjective"        # Opinion, preference, aesthetic evaluation, or personal perspective
    METAPHORICAL = "metaphorical"    # Figurative, analogical, or philosophical framing not asserting literal truth
    MIXED = "mixed"                  # Statement combining figurative/subjective framing and empirical claim(s)
    AMBIGUOUS = "ambiguous"          # Insufficiently clear or structured to classify or verify reliably


class VerificationOutcome(str, Enum):
    """Outcome of verifying an empirical proposition against candidate evidence."""
    SUPPORTED = "supported"                                  # Available evidence directly corroborates the claim
    CONTRADICTED = "contradicted"                            # Relevant evidence directly conflicts with the claim
    UNVERIFIABLE = "unverifiable"                            # Evidence is insufficient or unavailable to establish truth/falsity
    AMBIGUOUS = "ambiguous"                                  # Proposition scope or precision is too unclear to assess
    VERIFICATION_UNAVAILABLE = "verification_unavailable"    # Verifier call failed, timed out, or returned malformed output
    NOT_APPLICABLE = "not_applicable"                        # Subjective or metaphorical statement exempt from verification


class RiskLevel(str, Enum):
    """
    Conservative risk classification for extracted empirical propositions.
    Explicit criteria:
    - HIGH: Claims concerning human disease, medical therapies/cures, toxicity, poison, or physical safety hazards.
    - MEDIUM: Claims asserting specific quantitative statistics, numerical percentages, historical dates, or constants.
    - LOW: Everyday sensory observations, perceptual curiosities, or low-stakes physical claims.
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Keywords used for rule-assisted conservative risk indicator
_HIGH_RISK_KEYWORDS = {
    "cancer", "disease", "cure", "deadly", "poison", "toxic", "toxicity",
    "treatment", "medicine", "arthritis", "vaccine", "fatal", "lethal",
    "stroke", "heart attack", "tumor", "overdose", "infection"
}

_NUMERICAL_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%?\b")


def assess_risk_level(proposition: str, classification: str = ClaimClassification.EMPIRICAL) -> RiskLevel:
    """Assigns conservative risk level based on explicit topical and precision criteria."""
    if classification in (ClaimClassification.SUBJECTIVE, ClaimClassification.METAPHORICAL):
        return RiskLevel.LOW

    text_lower = proposition.lower()
    words = set(re.findall(r"\b[a-z]+\b", text_lower))

    if words & _HIGH_RISK_KEYWORDS:
        return RiskLevel.HIGH

    # Check for specific numerical claims or percentages
    if _NUMERICAL_PATTERN.search(text_lower):
        return RiskLevel.MEDIUM

    return RiskLevel.LOW


# ─── PROVENANCE DATA STRUCTURES ──────────────────────────────────────────────

@dataclass
class EvidenceReference:
    """
    Grounded reference to a candidate or supporting evidence record.
    Preserves existing metadata from real records (e.g. data/curated_thoughts_and_facts.json)
    without fabricating URLs, timestamps, or artificial identifiers.
    """
    id: Optional[str] = None
    source: Optional[str] = None
    text: str = ""
    pillar: Optional[str] = None
    type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {"text": self.text}
        if self.id is not None:
            res["id"] = self.id
        if self.source is not None:
            res["source"] = self.source
        if self.pillar is not None:
            res["pillar"] = self.pillar
        if self.type is not None:
            res["type"] = self.type
        return res


@dataclass
class ClaimRecord:
    """Individual claim evaluation and provenance record."""
    claim_id: str
    scene_id: Optional[int] = None
    chapter_id: Optional[int] = None
    original_text: str = ""
    extracted_proposition: str = ""
    classification: str = ClaimClassification.EMPIRICAL.value
    outcome: str = VerificationOutcome.UNVERIFIABLE.value
    evidence: List[EvidenceReference] = field(default_factory=list)
    rationale: str = ""
    risk_level: str = RiskLevel.LOW.value
    error_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "scene_id": self.scene_id,
            "chapter_id": self.chapter_id,
            "original_text": self.original_text,
            "extracted_proposition": self.extracted_proposition,
            "classification": self.classification,
            "outcome": self.outcome,
            "evidence": [e.to_dict() for e in self.evidence],
            "rationale": self.rationale,
            "risk_level": self.risk_level,
            "error_reason": self.error_reason
        }


@dataclass
class ClaimInspectionReport:
    """Auditable in-memory report summarizing claim-level factuality inspection."""
    claims: List[ClaimRecord] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    status: str = "completed"
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "error": self.error,
            "summary": self.summary,
            "claims": [c.to_dict() for c in self.claims]
        }


# ─── STANDALONE CLAIM INSPECTOR ENGINE ────────────────────────────────────────

class ClaimInspector:
    """
    Standalone claim extractor, classifier, and evidence verifier.
    Performs inspection in memory without disk persistence, network requests, or pipeline mutations.
    """

    VAULT_FILE = os.path.join("data", "curated_thoughts_and_facts.json")

    def __init__(self, llm_manager: Optional[Any] = None, vault_path: Optional[str] = None):
        self.llm = llm_manager
        self.vault_path = vault_path or self.VAULT_FILE
        self._vault_cache: Optional[List[EvidenceReference]] = None

    def load_curated_evidence(self) -> List[EvidenceReference]:
        """Loads curated facts from data/curated_thoughts_and_facts.json without disk mutations."""
        if self._vault_cache is not None:
            return self._vault_cache

        evidence_list: List[EvidenceReference] = []
        if os.path.exists(self.vault_path):
            try:
                with open(self.vault_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                items = data.get("items", [])
                for it in items:
                    if isinstance(it, dict):
                        evidence_list.append(
                            EvidenceReference(
                                id=it.get("id"),
                                source=it.get("source"),
                                text=it.get("text", "") or it.get("fact", ""),
                                pillar=it.get("pillar"),
                                type=it.get("type")
                            )
                        )
            except Exception as e:
                # Read-only graceful fallback without crashing
                pass

        self._vault_cache = evidence_list
        return evidence_list

    @staticmethod
    def _normalize_evidence(
        raw_evidence: Optional[List[Union[Dict[str, Any], EvidenceReference, str]]]
    ) -> List[EvidenceReference]:
        """Normalizes external evidence items into clean EvidenceReference objects."""
        if not raw_evidence:
            return []
        normalized: List[EvidenceReference] = []
        for it in raw_evidence:
            if isinstance(it, EvidenceReference):
                normalized.append(it)
            elif isinstance(it, dict):
                normalized.append(
                    EvidenceReference(
                        id=it.get("id"),
                        source=it.get("source"),
                        text=it.get("text", "") or it.get("fact", ""),
                        pillar=it.get("pillar"),
                        type=it.get("type")
                    )
                )
            elif isinstance(it, str) and it.strip():
                normalized.append(EvidenceReference(text=it.strip()))
        return normalized

    def find_candidate_evidence(
        self,
        query: str,
        top_k: int = 5,
        additional_evidence: Optional[List[Union[Dict[str, Any], EvidenceReference, str]]] = None
    ) -> List[EvidenceReference]:
        """
        Finds candidate evidence records matching query tokens.
        Searches provided additional_evidence first, then falls back to local curated vault.
        """
        pool: List[EvidenceReference] = []
        if additional_evidence:
            pool.extend(self._normalize_evidence(additional_evidence))
        pool.extend(self.load_curated_evidence())

        if not query or not query.strip() or not pool:
            return []

        q_tokens = set(re.findall(r"\b[a-zA-Z]{3,}\b", query.lower()))
        if not q_tokens:
            return []

        stopwords = {
            "the", "and", "that", "this", "with", "from", "for", "your",
            "you", "have", "are", "was", "were", "been", "they", "their",
            "just", "about", "into", "because", "what", "which", "when"
        }
        content_tokens = q_tokens - stopwords
        if not content_tokens:
            return []

        scored: List[Tuple[float, EvidenceReference]] = []
        for ev in pool:
            if not ev.text:
                continue
            ev_tokens = set(re.findall(r"\b[a-zA-Z]{3,}\b", ev.text.lower()))
            overlap = len(content_tokens & ev_tokens)
            if overlap > 0:
                score = overlap / (len(content_tokens | ev_tokens) or 1.0)
                # Boost if exact phrase appears
                if query.lower() in ev.text.lower() or ev.text.lower() in query.lower():
                    score += 1.0
                scored.append((score, ev))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [ev for _, ev in scored[:top_k]]

    def classify_and_extract(
        self,
        text: str,
        scene_id: Optional[int] = None,
        chapter_id: Optional[int] = None
    ) -> Tuple[str, List[Dict[str, Any]], str, Optional[str]]:
        """
        Classifies input text and extracts discrete empirical propositions.
        Returns (classification, propositions_list, rationale, error_reason).
        """
        if not text or not text.strip():
            return (
                ClaimClassification.AMBIGUOUS.value,
                [],
                "Input text is empty or whitespace-only",
                None
            )

        # If no LLM manager provided, execute deterministic heuristic classification
        if self.llm is None:
            return self._heuristic_classify_and_extract(text)

        sys_prompt = (
            "You are a precision epistemologist and fact-checking linguist for educational videos.\n"
            "Analyze the given spoken text line and classify it into exactly ONE category:\n"
            "1. 'empirical': An objective assertion about the physical universe, science, human body, history, or facts.\n"
            "2. 'subjective': An opinion, personal preference, value judgment, or aesthetic reaction.\n"
            "3. 'metaphorical': Figurative, poetic, or analogical observation not asserting literal physical truth.\n"
            "4. 'mixed': Combines figurative/subjective framing with at least one identifiable empirical proposition.\n"
            "5. 'ambiguous': Grammatically unparseable, contradictory, or too vague to formulate a checkable proposition.\n\n"
            "INSTRUCTIONS:\n"
            "- If 'empirical', extract each testable factual proposition into 'propositions'.\n"
            "- If 'mixed', extract ONLY the core empirical proposition(s), discarding the subjective/metaphorical framing.\n"
            "- If 'subjective', 'metaphorical', or 'ambiguous', 'propositions' MUST be empty [].\n"
            "- Assign 'risk_level' ('low', 'medium', 'high') to each extracted proposition.\n\n"
            "Return valid JSON matching:\n"
            "{\n"
            '  "classification": "empirical"|"subjective"|"metaphorical"|"mixed"|"ambiguous",\n'
            '  "rationale": "...",\n'
            '  "propositions": [\n'
            '    {"proposition": "...", "risk_level": "low"|"medium"|"high"}\n'
            "  ]\n"
            "}"
        )
        user_prompt = f"Analyze and classify this spoken line:\n\"{text}\""

        try:
            res = self.llm.generate_json(sys_prompt, user_prompt, temperature=0.1)
            if not isinstance(res, dict):
                return (
                    ClaimClassification.AMBIGUOUS.value,
                    [],
                    "LLM returned non-dictionary response",
                    f"Malformed verifier response: expected dict, got {type(res).__name__}"
                )

            raw_cls = (res.get("classification") or "").lower().strip()
            valid_classes = {c.value for c in ClaimClassification}
            if raw_cls not in valid_classes:
                raw_cls = ClaimClassification.AMBIGUOUS.value

            rationale = str(res.get("rationale") or f"Classified as {raw_cls}")
            props = res.get("propositions", [])
            clean_props = []

            if isinstance(props, list) and raw_cls in (ClaimClassification.EMPIRICAL.value, ClaimClassification.MIXED.value):
                for p in props:
                    if isinstance(p, dict) and p.get("proposition"):
                        p_txt = str(p["proposition"]).strip()
                        risk = str(p.get("risk_level", assess_risk_level(p_txt, raw_cls).value)).lower()
                        if risk not in {r.value for r in RiskLevel}:
                            risk = assess_risk_level(p_txt, raw_cls).value
                        clean_props.append({"proposition": p_txt, "risk_level": risk})
                    elif isinstance(p, str) and p.strip():
                        p_txt = p.strip()
                        clean_props.append({
                            "proposition": p_txt,
                            "risk_level": assess_risk_level(p_txt, raw_cls).value
                        })

            return raw_cls, clean_props, rationale, None

        except Exception as e:
            return (
                ClaimClassification.AMBIGUOUS.value,
                [],
                f"Classification error: {e}",
                f"Classifier service unavailable: {e}"
            )

    @staticmethod
    def _heuristic_classify_and_extract(text: str) -> Tuple[str, List[Dict[str, Any]], str, Optional[str]]:
        """Fast, deterministic rule-assisted fallback for testing and non-LLM environments."""
        clean = text.strip()
        lower = clean.lower()

        # Subjective patterns
        subjective_signals = [
            "the best smell", "the worst smell", "my favorite", "i think", "in my opinion",
            "is the most beautiful", "is the most nostalgic", "feels amazing", "tastes best"
        ]
        if any(sig in lower for sig in subjective_signals):
            return ClaimClassification.SUBJECTIVE.value, [], "Contains explicit aesthetic or personal judgment", None

        # Metaphorical patterns
        metaphor_signals = [
            "is just charging your biological battery",
            "is running a background diagnostic",
            "the universe is a clock",
            "life is a video game",
            "clapping is just repeatedly slapping yourself"
        ]
        if any(sig in lower for sig in metaphor_signals) and "because" not in lower and "damages" not in lower:
            return ClaimClassification.METAPHORICAL.value, [], "Figurative or poetic observation; non-literal assertion", None

        # Mixed patterns (figurative framing + empirical assertion)
        if ("is terrifying because" in lower or "the ultimate villain because" in lower or "wildest part is that" in lower):
            # Extract proposition following the causal bridge
            match = re.search(r"\bbecause\s+(.+)$", clean, re.IGNORECASE)
            if match:
                core_prop = match.group(1).strip()
                core_prop = re.sub(r"^[.…\-—\s]+", "", core_prop)
                if core_prop and core_prop[0].islower():
                    core_prop = core_prop[0].upper() + core_prop[1:]
                return (
                    ClaimClassification.MIXED.value,
                    [{"proposition": core_prop, "risk_level": assess_risk_level(core_prop, ClaimClassification.EMPIRICAL.value).value}],
                    "Extracted empirical core proposition following figurative framing",
                    None
                )

        # Ambiguous / unparseable
        if len(clean.split()) < 3 or clean in ("...", "???", "Which is why..."):
            return ClaimClassification.AMBIGUOUS.value, [], "Fragmented or unparseable assertion", None

        # Default to empirical
        risk = assess_risk_level(clean, ClaimClassification.EMPIRICAL.value).value
        return (
            ClaimClassification.EMPIRICAL.value,
            [{"proposition": clean, "risk_level": risk}],
            "Treated as testable empirical proposition",
            None
        )

    def verify_proposition(
        self,
        proposition: str,
        candidate_evidence: Optional[List[EvidenceReference]] = None
    ) -> Tuple[str, List[EvidenceReference], str, Optional[str]]:
        """
        Evaluates an extracted empirical proposition against candidate evidence records.
        Returns:
            (outcome, supporting_evidence_list, rationale, error_reason)
        """
        if not proposition or not proposition.strip():
            return (
                VerificationOutcome.AMBIGUOUS.value,
                [],
                "Cannot verify empty proposition",
                None
            )

        if not candidate_evidence:
            return (
                VerificationOutcome.UNVERIFIABLE.value,
                [],
                "No candidate evidence found in repository or provided references",
                None
            )

        # Check for numerical precision mismatch first
        prop_numbers = set(_NUMERICAL_PATTERN.findall(proposition.lower()))

        # If no LLM manager is configured, perform deterministic evidence matching
        if self.llm is None:
            return self._heuristic_verify(proposition, candidate_evidence, prop_numbers)

        # Format evidence records for verifier prompt without fabricating metadata
        ev_lines = []
        for idx, ev in enumerate(candidate_evidence, 1):
            ref_id = f" [ID: {ev.id}]" if ev.id else ""
            src = f" [Source: {ev.source}]" if ev.source else ""
            ev_lines.append(f"Evidence #{idx}{ref_id}{src}:\n\"{ev.text}\"")
        evidence_block = "\n\n".join(ev_lines)

        sys_prompt = (
            "You are a strict, objective scientific verification judge.\n"
            "Assess whether the provided candidate evidence DIRECTLY supports or contradicts the given empirical proposition.\n\n"
            "RULES:\n"
            "1. Assess ONLY what the provided candidate evidence explicitly states. Do not invent facts or cite external knowledge not in the evidence.\n"
            "2. 'supported': The candidate evidence directly and relevantly corroborates the proposition.\n"
            "3. 'contradicted': The candidate evidence directly conflicts with or disproves the proposition.\n"
            "4. 'unverifiable': The candidate evidence discusses a different topic, is insufficient, or does not address the claim.\n"
            "5. 'ambiguous': The proposition is unclear or evidence contains mutually exclusive definitions.\n"
            "6. NUMERICAL SCOPE: If the proposition makes a specific numerical assertion (e.g. '95%') that is unsupported by the evidence, do NOT mark supported.\n\n"
            "Return valid JSON:\n"
            "{\n"
            '  "outcome": "supported"|"contradicted"|"unverifiable"|"ambiguous",\n'
            '  "supporting_indices": [1, ...],\n'
            '  "rationale": "<concise explanation referencing specific evidence>"\n'
            "}"
        )
        user_prompt = (
            f"EMPIRICAL PROPOSITION:\n\"{proposition}\"\n\n"
            f"CANDIDATE EVIDENCE:\n{evidence_block}"
        )

        try:
            res = self.llm.generate_json(sys_prompt, user_prompt, temperature=0.1)
            if not isinstance(res, dict):
                return (
                    VerificationOutcome.VERIFICATION_UNAVAILABLE.value,
                    [],
                    f"Malformed verifier response: expected dict, got {type(res).__name__}",
                    f"Verifier returned non-dictionary JSON: {type(res).__name__}"
                )

            raw_outcome = (res.get("outcome") or "").lower().strip()
            valid_outcomes = {o.value for o in VerificationOutcome}
            if raw_outcome not in valid_outcomes:
                raw_outcome = VerificationOutcome.VERIFICATION_UNAVAILABLE.value
                return (
                    raw_outcome,
                    [],
                    f"Verifier returned unrecognized outcome: '{res.get('outcome')}'",
                    f"Invalid verifier outcome: '{res.get('outcome')}'"
                )

            rationale = str(res.get("rationale") or f"Assessed as {raw_outcome}")
            valid_supporting_refs: List[EvidenceReference] = []

            raw_indices = res.get("supporting_indices", [])
            if isinstance(raw_indices, list):
                for idx in raw_indices:
                    if isinstance(idx, int) and not isinstance(idx, bool) and 1 <= idx <= len(candidate_evidence):
                        ref = candidate_evidence[idx - 1]
                        if ref not in valid_supporting_refs:
                            valid_supporting_refs.append(ref)

            if raw_outcome == VerificationOutcome.SUPPORTED.value:
                if not valid_supporting_refs:
                    return (
                        VerificationOutcome.UNVERIFIABLE.value,
                        [],
                        f"Verifier asserted supported but provided no valid supporting evidence reference ({rationale})",
                        None
                    )
                # Safety assertion: If numerical claims differ materially, do not allow 'supported'
                if prop_numbers:
                    ev_combined_text = " ".join(e.text.lower() for e in valid_supporting_refs)
                    ev_numbers = set(_NUMERICAL_PATTERN.findall(ev_combined_text))
                    # If proposition specified explicit numbers not supported by evidence numbers
                    if prop_numbers and not (prop_numbers & ev_numbers):
                        return (
                            VerificationOutcome.CONTRADICTED.value,
                            valid_supporting_refs,
                            f"Numerical mismatch: proposition asserts {prop_numbers} not corroborated by evidence {ev_numbers}",
                            None
                        )
                return VerificationOutcome.SUPPORTED.value, valid_supporting_refs, rationale, None

            if raw_outcome == VerificationOutcome.CONTRADICTED.value:
                if not valid_supporting_refs:
                    rationale = f"{rationale} (Note: no specific conflicting evidence record index identified by verifier)"
                return VerificationOutcome.CONTRADICTED.value, valid_supporting_refs, rationale, None

            return raw_outcome, [], rationale, None

        except Exception as e:
            return (
                VerificationOutcome.VERIFICATION_UNAVAILABLE.value,
                [],
                f"Verifier execution error: {e}",
                f"Verification service unavailable: {e}"
            )

    @staticmethod
    def _heuristic_verify(
        proposition: str,
        candidate_evidence: List[EvidenceReference],
        prop_numbers: Set[str]
    ) -> Tuple[str, List[EvidenceReference], str, Optional[str]]:
        """Deterministic heuristic verification when LLM is unavailable."""
        p_clean = proposition.strip().lower()

        for ev in candidate_evidence:
            ev_clean = ev.text.strip().lower()

            # Direct match
            if p_clean in ev_clean or ev_clean in p_clean:
                # Check numerical precision
                ev_numbers = set(_NUMERICAL_PATTERN.findall(ev_clean))
                if prop_numbers and not (prop_numbers & ev_numbers):
                    return (
                        VerificationOutcome.CONTRADICTED.value,
                        [ev],
                        f"Numerical claim mismatch: {prop_numbers} vs evidence {ev_numbers}",
                        None
                    )
                return (
                    VerificationOutcome.SUPPORTED.value,
                    [ev],
                    f"Direct corroboration from evidence record '{ev.id or 'candidate'}'",
                    None
                )

            # Direct contradiction signals
            if ("not" in ev_clean or "never" in ev_clean or "does not" in ev_clean) and any(
                term in ev_clean for term in p_clean.split() if len(term) > 4
            ):
                return (
                    VerificationOutcome.CONTRADICTED.value,
                    [ev],
                    f"Evidence contradicts assertion: '{ev.text[:60]}...'",
                    None
                )

        return (
            VerificationOutcome.UNVERIFIABLE.value,
            [],
            "Available candidate evidence does not directly corroborate proposition",
            None
        )

    def inspect_scene(
        self,
        scene: Union[Dict[str, Any], str],
        scene_id: Optional[int] = None,
        chapter_id: Optional[int] = None,
        candidate_evidence: Optional[List[Union[Dict[str, Any], EvidenceReference, str]]] = None
    ) -> List[ClaimRecord]:
        """
        Inspects an individual scene, extracts claims, classifies them,
        and verifies any empirical propositions.
        """
        if isinstance(scene, dict):
            text = scene.get("spoken_text", "")
            s_id = scene.get("scene_id", scene_id)
            c_id = scene.get("chapter_id", chapter_id)
        else:
            text = str(scene)
            s_id = scene_id
            c_id = chapter_id

        classification, propositions, rationale, error_reason = self.classify_and_extract(
            text=text, scene_id=s_id, chapter_id=c_id
        )

        records: List[ClaimRecord] = []
        base_claim_id = f"claim_{s_id or 'x'}"

        # If subjective or metaphorical: exempt from empirical verification
        if classification in (ClaimClassification.SUBJECTIVE.value, ClaimClassification.METAPHORICAL.value):
            v_rationale = f"{classification.capitalize()} statement exempt from empirical verification"
            if rationale:
                v_rationale = f"{v_rationale} ({rationale})"
            records.append(
                ClaimRecord(
                    claim_id=f"{base_claim_id}_1",
                    scene_id=s_id,
                    chapter_id=c_id,
                    original_text=text,
                    extracted_proposition="",
                    classification=classification,
                    outcome=VerificationOutcome.NOT_APPLICABLE.value,
                    evidence=[],
                    rationale=v_rationale,
                    risk_level=RiskLevel.LOW.value,
                    error_reason=error_reason
                )
            )
            return records

        # If ambiguous or no propositions extracted
        if classification == ClaimClassification.AMBIGUOUS.value or not propositions:
            outcome = VerificationOutcome.VERIFICATION_UNAVAILABLE.value if error_reason else VerificationOutcome.AMBIGUOUS.value
            records.append(
                ClaimRecord(
                    claim_id=f"{base_claim_id}_1",
                    scene_id=s_id,
                    chapter_id=c_id,
                    original_text=text,
                    extracted_proposition="",
                    classification=classification,
                    outcome=outcome,
                    evidence=[],
                    rationale=rationale or "Ambiguous assertion; no verifiable proposition formulated",
                    risk_level=RiskLevel.LOW.value,
                    error_reason=error_reason
                )
            )
            return records

        # Process and verify each extracted empirical proposition
        for idx, prop_item in enumerate(propositions, 1):
            prop_text = prop_item.get("proposition", "")
            risk_val = prop_item.get("risk_level", assess_risk_level(prop_text, classification).value)

            # Find candidates for this specific proposition
            candidates = self.find_candidate_evidence(prop_text, top_k=5, additional_evidence=candidate_evidence)
            outcome, supporting_ev, v_rationale, v_error = self.verify_proposition(prop_text, candidates)

            claim_suffix = f"_{idx}" if len(propositions) > 1 else "_1"
            records.append(
                ClaimRecord(
                    claim_id=f"{base_claim_id}{claim_suffix}",
                    scene_id=s_id,
                    chapter_id=c_id,
                    original_text=text,
                    extracted_proposition=prop_text,
                    classification=classification,
                    outcome=outcome,
                    evidence=supporting_ev,
                    rationale=v_rationale or rationale,
                    risk_level=risk_val,
                    error_reason=v_error or error_reason
                )
            )

        return records

    def inspect_script(
        self,
        scenes: List[Union[Dict[str, Any], str]],
        candidate_evidence: Optional[List[Union[Dict[str, Any], EvidenceReference, str]]] = None
    ) -> ClaimInspectionReport:
        """
        Inspects an entire list of scenes and returns an auditable ClaimInspectionReport.
        Does not mutate the input scenes or write files to disk.
        """
        if not scenes:
            return ClaimInspectionReport(
                claims=[],
                summary={
                    "total_claims": 0,
                    "classifications": {},
                    "outcomes": {},
                    "risk_levels": {},
                    "has_contradicted": False,
                    "has_unavailable": False
                },
                status="completed"
            )

        all_claims: List[ClaimRecord] = []
        for idx, scene in enumerate(scenes, 1):
            scene_records = self.inspect_scene(
                scene=scene,
                scene_id=idx,
                candidate_evidence=candidate_evidence
            )
            all_claims.extend(scene_records)

        # Calculate metrics summary
        by_cls: Dict[str, int] = {}
        by_out: Dict[str, int] = {}
        by_risk: Dict[str, int] = {}

        for c in all_claims:
            by_cls[c.classification] = by_cls.get(c.classification, 0) + 1
            by_out[c.outcome] = by_out.get(c.outcome, 0) + 1
            by_risk[c.risk_level] = by_risk.get(c.risk_level, 0) + 1

        summary = {
            "total_claims": len(all_claims),
            "classifications": by_cls,
            "outcomes": by_out,
            "risk_levels": by_risk,
            "has_contradicted": by_out.get(VerificationOutcome.CONTRADICTED.value, 0) > 0,
            "has_unavailable": by_out.get(VerificationOutcome.VERIFICATION_UNAVAILABLE.value, 0) > 0
        }

        status = "failed" if summary["has_contradicted"] or summary["has_unavailable"] else "completed"

        return ClaimInspectionReport(
            claims=all_claims,
            summary=summary,
            status=status
        )
