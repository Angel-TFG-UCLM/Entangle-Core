"""
Tests for src.analysis.discipline_classifier
=============================================
Pure logic tests — no external dependencies needed.
"""
import pytest
from src.analysis.discipline_classifier import (
    classify_user,
    _classify_repo_discipline,
    _empty_analysis,
    DISCIPLINES,
    DISCIPLINE_COLORS,
    DISCIPLINE_LABELS,
)


# ── Helpers ──

def _make_user(bio="", company="", top_languages=None, organizations=None, quantum_score=0):
    return {
        "login": "testuser",
        "bio": bio,
        "company": company,
        "top_languages": top_languages or [],
        "organizations": organizations or [],
        "quantum_expertise_score": quantum_score,
    }


class TestConstants:
    """Verify discipline constants are consistent."""

    def test_all_disciplines_have_colors(self):
        for d in DISCIPLINES:
            assert d in DISCIPLINE_COLORS

    def test_all_disciplines_have_labels(self):
        for d in DISCIPLINES:
            assert d in DISCIPLINE_LABELS

    def test_discipline_count(self):
        assert len(DISCIPLINES) == 6


class TestClassifyUserBioSignals:
    """Signal 1: Bio keywords classification."""

    def test_quantum_software_from_bio(self):
        user = _make_user(bio="I'm a quantum developer working on SDKs")
        result = classify_user(user, [], [])
        assert result["discipline"] == "quantum_software"
        assert result["discipline_confidence"] > 0

    def test_quantum_physics_from_bio(self):
        user = _make_user(bio="Physicist working on quantum mechanics at CERN")
        result = classify_user(user, [], [])
        assert result["discipline"] == "quantum_physics"

    def test_quantum_hardware_from_bio(self):
        user = _make_user(bio="Hardware engineer building superconducting quantum devices")
        result = classify_user(user, [], [])
        assert result["discipline"] == "quantum_hardware"

    def test_education_research_from_bio(self):
        user = _make_user(bio="Professor of quantum computing at MIT")
        result = classify_user(user, [], [])
        assert result["discipline"] in ("education_research", "quantum_physics", "multidisciplinary")

    def test_no_signals_returns_classical_tooling(self):
        user = _make_user(bio="")
        result = classify_user(user, [], [])
        assert result["discipline"] == "classical_tooling"
        assert result["discipline_confidence"] == 0.0
        assert result["discipline_signals"] == []


class TestClassifyUserCompanySignals:
    """Signal from company field matching org signals."""

    def test_company_qiskit(self):
        user = _make_user(company="Qiskit team at IBM")
        result = classify_user(user, [], [])
        assert result["discipline"] == "quantum_software"

    def test_company_ionq(self):
        user = _make_user(company="IonQ")
        result = classify_user(user, [], [])
        assert result["discipline"] == "quantum_hardware"

    def test_company_cern(self):
        user = _make_user(company="CERN")
        result = classify_user(user, [], [])
        assert result["discipline"] == "quantum_physics"


class TestClassifyUserOrgSignals:
    """Signal 2: Organization affiliations."""

    def test_org_matching(self):
        orgs = [{"login": "qiskit", "name": "Qiskit", "description": "Open-source quantum SDK"}]
        user = _make_user(organizations=orgs)
        result = classify_user(user, [], [])
        assert result["discipline"] == "quantum_software"

    def test_multiple_orgs(self):
        orgs = [
            {"login": "rigetti", "name": "Rigetti Computing", "description": "Quantum hardware"},
            {"login": "ionq", "name": "IonQ", "description": "Trapped-ion quantum"},
        ]
        user = _make_user(organizations=orgs)
        result = classify_user(user, [], [])
        assert result["discipline"] == "quantum_hardware"


class TestClassifyUserTopicSignals:
    """Signal 3: Repository topic signals."""

    def test_quantum_circuit_topics(self):
        user = _make_user()
        topics = [["quantum-circuit", "quantum-gate", "openqasm"]]
        result = classify_user(user, topics, [])
        assert result["discipline"] == "quantum_software"

    def test_hamiltonian_topics(self):
        user = _make_user()
        topics = [["hamiltonian", "quantum-simulation", "many-body", "tensor-network"]]
        result = classify_user(user, topics, [])
        assert result["discipline"] == "quantum_physics"

    def test_hardware_topics(self):
        user = _make_user()
        topics = [["trapped-ion", "quantum-hardware", "quantum-error-correction"]]
        result = classify_user(user, topics, [])
        assert result["discipline"] == "quantum_hardware"

    def test_education_topics(self):
        user = _make_user()
        topics = [["tutorial", "education", "quantum-education", "learn", "teaching"]]
        result = classify_user(user, topics, [])
        assert result["discipline"] == "education_research"

    def test_empty_topics(self):
        user = _make_user()
        result = classify_user(user, [[]], [])
        assert result["discipline"] == "classical_tooling"

    def test_none_topics_handled(self):
        user = _make_user()
        result = classify_user(user, [None, []], [None])
        assert "discipline" in result


class TestClassifyUserLanguageSignals:
    """Signal 4: Language-based signals."""

    def test_physics_languages(self):
        user = _make_user(top_languages=["Julia", "Fortran", "Mathematica"])
        result = classify_user(user, [], [])
        assert result["discipline"] == "quantum_physics"

    def test_hardware_languages(self):
        user = _make_user(top_languages=["Verilog", "VHDL", "SystemVerilog"])
        result = classify_user(user, [], [])
        assert result["discipline"] == "quantum_hardware"

    def test_classical_languages(self):
        user = _make_user(top_languages=["TypeScript", "Go", "Rust"])
        result = classify_user(user, [], [])
        assert result["discipline"] == "classical_tooling"

    def test_repo_languages(self):
        user = _make_user()
        repo_langs = ["Verilog", "VHDL", "C++"]
        result = classify_user(user, [], repo_langs)
        assert result["discipline"] == "quantum_hardware"


class TestClassifyUserQuantumScoreModifier:
    """Signal 5: Quantum expertise score."""

    def test_high_quantum_score_boosts_software(self):
        user = _make_user(quantum_score=80)
        result = classify_user(user, [], [])
        assert result["discipline"] == "quantum_software"
        assert result["discipline_confidence"] > 0

    def test_low_quantum_score_no_effect(self):
        user = _make_user(quantum_score=5)
        result = classify_user(user, [], [])
        assert result["discipline"] == "classical_tooling"


class TestMultidisciplinaryClassification:
    """When 2+ disciplines have significant scores."""

    def test_multidisciplinary_physics_and_software(self):
        user = _make_user(
            bio="Physicist and quantum developer",
            top_languages=["Python", "Julia"],
        )
        topics = [["quantum-circuit", "hamiltonian", "quantum-simulation"]]
        result = classify_user(user, topics, [])
        assert result["discipline"] in ("multidisciplinary", "quantum_physics", "quantum_software")

    def test_multidisciplinary_has_top_colors(self):
        user = _make_user(
            bio="Physicist and software engineer building quantum hardware",
        )
        topics = [
            ["quantum-circuit", "trapped-ion", "hamiltonian"],
        ]
        result = classify_user(user, topics, [])
        if result["discipline"] == "multidisciplinary":
            assert "discipline_top_colors" in result
            assert len(result["discipline_top_colors"]) >= 2


class TestResultStructure:
    """Verify the output structure is always consistent."""

    def test_required_keys(self):
        user = _make_user(bio="quantum developer")
        result = classify_user(user, [], [])
        assert "discipline" in result
        assert "discipline_color" in result
        assert "discipline_label" in result
        assert "discipline_confidence" in result
        assert "discipline_signals" in result

    def test_color_is_hex(self):
        user = _make_user(bio="physicist")
        result = classify_user(user, [], [])
        assert result["discipline_color"].startswith("#")

    def test_confidence_range(self):
        user = _make_user(bio="quantum developer at Qiskit")
        result = classify_user(user, [], [])
        assert 0 <= result["discipline_confidence"] <= 1

    def test_signals_is_list(self):
        user = _make_user(bio="quantum developer")
        result = classify_user(user, [], [])
        assert isinstance(result["discipline_signals"], list)


class TestClassifyRepoDiscipline:
    """Tests for the repo-level quick classifier."""

    def test_software_repo(self):
        result = _classify_repo_discipline("quantum-circuit openqasm transpiler", "Python")
        assert result == "quantum_software"

    def test_physics_repo(self):
        result = _classify_repo_discipline("hamiltonian quantum-simulation many-body", "Julia")
        assert result == "quantum_physics"

    def test_hardware_repo(self):
        result = _classify_repo_discipline("trapped-ion superconducting quantum-hardware", "C++")
        assert result == "quantum_hardware"

    def test_education_repo(self):
        result = _classify_repo_discipline("tutorial education quantum-learning", "Python")
        assert result == "education_research"

    def test_no_signals_defaults_to_software(self):
        result = _classify_repo_discipline("some random text", "Python")
        assert result == "quantum_software"

    def test_language_hint(self):
        result = _classify_repo_discipline("some project", "Verilog")
        assert result == "quantum_hardware"


class TestEmptyAnalysis:
    """Tests for the _empty_analysis helper."""

    def test_structure(self):
        result = _empty_analysis()
        assert "distribution" in result
        assert "distribution_pct" in result
        assert "mixing_matrix" in result
        assert "cross_discipline_index" in result
        assert "total_classified" in result
        assert "bridge_profiles" in result
        assert "discipline_colors" in result
        assert "discipline_labels" in result

    def test_all_zeroes(self):
        result = _empty_analysis()
        assert all(v == 0 for v in result["distribution"].values())
        assert result["total_classified"] == 0
        assert result["cross_discipline_index"] == 0.0
        assert result["bridge_profiles"] == []
