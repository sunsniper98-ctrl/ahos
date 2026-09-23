"""Read-only token dossier composer — isolated from runtime, Lane A, and P5."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from architecture.identity.types import (
    ChainIdentity,
    IdentityResolution,
    IdentitySource,
    IdentityState,
    TokenIdentity,
)
from tests._mint_support import _mint_verified_for_tests
from architecture.identity.resolution import resolve_identity
from architecture.knowledge.dossier import (
    AliasKind,
    COMPOSER_VERSION,
    EpistemicStatus,
    TokenDossier,
    compose_dossier,
)

ROOT = Path(__file__).resolve().parents[1]
DOSSIER_SRC = (ROOT / "architecture" / "knowledge" / "dossier.py").read_text(encoding="utf-8")

FORBIDDEN_IMPORT_SNIPPETS = (
    "architecture.runtime",
    "architecture.pipeline",
    "discovery.",
    "paper_trading",
    "architecture.cognitive.memory.observation",
    "architecture.cognitive.loop.orchestrator",
    "architecture.cognitive.loop.binding",
    "import sqlite3",
    "import hashlib",
    "architecture.identity",
    "architecture.decision",
    "architecture.security",
    "architecture.scoring",
)

PRODUCTION_SURFACES = (
    ROOT / "architecture" / "runtime" / "__main__.py",
    ROOT / "architecture" / "runtime" / "__init__.py",
    ROOT / "architecture" / "runtime" / "observation_loop.py",
    ROOT / "architecture" / "pipeline" / "orchestrator.py",
    ROOT / "architecture" / "knowledge" / "__init__.py",
)


def _identity(
    *,
    state: IdentityState,
    chain: str | None = "solana",
    address: str | None = "So11111111111111111111111111111111111111112",
    token_id: str | None = None,
    symbol: str | None = "ABC",
    conflicts: tuple[str, ...] = (),
    provenance: tuple[dict, ...] = (),
    mint: bool | None = None,
) -> IdentityResolution:
    chain_state = state if state is not IdentityState.UNSUPPORTED else IdentityState.UNSUPPORTED
    resolution = IdentityResolution(
        chain=ChainIdentity(chain, chain, chain_state, "fixture"),
        token=TokenIdentity(
            chain=chain,
            address_canonical=address,
            address_input=address,
            token_id=token_id,
            symbol_alias=symbol,
            name_alias=None,
            state=state,
            reason="fixture",
        ),
        pool=None,
        dex=None,
        sources=(),
        conflicts=conflicts,
        provenance=provenance,
    )
    # Default: mint VERIFIED for positive dossier/graph paths. A1 uses mint=False.
    if mint is None:
        mint = state is IdentityState.VERIFIED
    if mint:
        return _mint_verified_for_tests(resolution)
    return resolution


def _identity_unminted(
    *,
    state: IdentityState = IdentityState.VERIFIED,
    chain: str | None = "solana",
    address: str | None = "So11111111111111111111111111111111111111112",
    token_id: str | None = "abc123canonicalid",
    symbol: str | None = "ABC",
    conflicts: tuple[str, ...] = (),
    provenance: tuple[dict, ...] = (),
) -> IdentityResolution:
    """Hand-built exact-typed VERIFIED without resolver mint (A1/A1b)."""
    return _identity(
        state=state,
        chain=chain,
        address=address,
        token_id=token_id,
        symbol=symbol,
        conflicts=conflicts,
        provenance=provenance,
        mint=False,
    )


def _decision(**kwargs):
    defaults = dict(
        outcome="NO_TRADE",
        identity_state=None,
        security_state=None,
        opportunity_score=None,
        unknowns=(),
        hard_vetoes=(),
        provenance={},
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _score(**kwargs):
    defaults = dict(
        opportunity_score=12.0,
        token_chain=None,
        token_address=None,
        token_symbol=None,
        missing_unknowns=(),
        provenance_sha256="",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _security(state: str, **kwargs):
    return SimpleNamespace(state=state, **kwargs)


def test_verified_input_remains_verified():
    ident = _identity(state=IdentityState.VERIFIED, token_id="abc123canonicalid")
    dossier = compose_dossier(identity=ident, composed_at=1.0)
    assert dossier.identity_state == "VERIFIED"
    assert dossier.canonical_token_id == "abc123canonicalid"


def test_unresolved_input_remains_unresolved():
    ident = _identity(state=IdentityState.UNRESOLVED, token_id=None)
    dossier = compose_dossier(identity=ident)
    assert dossier.identity_state == "UNRESOLVED"
    assert dossier.canonical_token_id is None


def test_conflict_input_remains_conflict():
    ident = _identity(
        state=IdentityState.CONFLICT,
        token_id=None,
        conflicts=("provider_address_mismatch:gecko",),
    )
    dossier = compose_dossier(identity=ident)
    assert dossier.identity_state == "CONFLICT"
    assert "provider_address_mismatch:gecko" in dossier.conflicts


def test_reject_input_remains_reject():
    dossier = compose_dossier(
        decision=_decision(outcome="REJECT"),
        security=_security("REJECT", veto_reasons=("honeypot",)),
    )
    assert dossier.decision_outcome == "REJECT"
    assert dossier.security_state == "REJECT"


def test_unknown_information_remains_unknown():
    dossier = compose_dossier()
    assert dossier.canonical_token_id is None
    assert dossier.identity_state is None
    assert "identity_state" in dossier.unknowns
    assert "canonical_token_id" in dossier.unknowns
    statuses = {e.field: e.status for e in dossier.epistemic_map}
    assert statuses["canonical_token_id"] is EpistemicStatus.UNAVAILABLE
    assert statuses["identity_state"] is EpistemicStatus.UNAVAILABLE


def test_symbol_alone_cannot_create_canonical_identity():
    ident = _identity(
        state=IdentityState.UNRESOLVED,
        chain="solana",
        address=None,
        token_id=None,
        symbol="PEPE",
    )
    dossier = compose_dossier(identity=ident, score=_score(token_symbol="PEPE", token_chain="solana"))
    assert dossier.canonical_token_id is None
    assert dossier.identity_state == "UNRESOLVED"
    assert any(k.scheme == "symbol_key" and k.kind is AliasKind.DISPLAY for k in dossier.join_keys)
    assert not any(k.kind is AliasKind.CANONICAL for k in dossier.join_keys)
    assert "canonical_identity_not_inferable_from_symbol" in dossier.unknowns


def test_alias_keys_remain_distinct():
    ident = _identity(
        state=IdentityState.VERIFIED,
        chain="ethereum",
        address="0xABCDEF",
        token_id="hash32tokenidvalue",
        symbol="ABC",
    )
    dossier = compose_dossier(identity=ident)
    schemes = {k.scheme for k in dossier.join_keys}
    kinds = {k.kind for k in dossier.join_keys}
    assert "token_id" in schemes
    assert "decision_token_key" in schemes
    assert "chain_address" in schemes
    assert "symbol_key" in schemes
    assert AliasKind.CANONICAL in kinds
    assert AliasKind.OPERATIONAL in kinds
    assert AliasKind.DISPLAY in kinds
    token_ids = [k.value for k in dossier.join_keys if k.scheme == "token_id"]
    symbols = [k.value for k in dossier.join_keys if k.scheme == "symbol_key"]
    assert token_ids == ["hash32tokenidvalue"]
    assert "ethereum:sym:ABC" in symbols
    assert all(k.value != "hash32tokenidvalue" for k in dossier.join_keys if k.scheme != "token_id")


def test_conflicting_aliases_are_preserved_not_merged():
    ident = _identity(
        state=IdentityState.UNRESOLVED,
        chain="solana",
        address="AddrOne",
        token_id=None,
        symbol="ABC",
    )
    score = _score(token_chain="solana", token_address="AddrTwo", token_symbol="ABC", opportunity_score=90.0)
    dossier = compose_dossier(identity=ident, score=score)
    addrs = {k.value for k in dossier.join_keys if k.scheme == "chain_address"}
    assert "solana:AddrOne" in addrs
    assert "solana:AddrTwo" in addrs
    assert any("alias_chain_address_disagreement" in c for c in dossier.conflicts)


def test_high_score_cannot_override_security_reject():
    dossier = compose_dossier(
        identity=_identity(state=IdentityState.UNRESOLVED, token_id=None),
        score=_score(opportunity_score=99.0),
        security=_security("REJECT", veto_reasons=("honeypot",)),
        decision=_decision(outcome="REJECT", opportunity_score=99.0),
    )
    assert dossier.security_state == "REJECT"
    assert dossier.decision_outcome == "REJECT"
    assert dossier.opportunity_score == 99.0
    assert dossier.identity_state == "UNRESOLVED"


def test_dossier_does_not_calculate_a_new_opportunity_score():
    dossier = compose_dossier(score=_score(opportunity_score=41.5))
    assert dossier.opportunity_score == 41.5
    note = next(e.note for e in dossier.epistemic_map if e.field == "opportunity_score")
    assert "not recalculated" in note


def test_dossier_does_not_calculate_a_new_identity():
    ident = _identity(state=IdentityState.UNRESOLVED, token_id=None, address="0xabc", chain="ethereum")
    dossier = compose_dossier(identity=ident)
    assert dossier.canonical_token_id is None
    assert "import hashlib" not in DOSSIER_SRC
    assert "hashlib.sha256" not in DOSSIER_SRC
    assert "token_id(" not in DOSSIER_SRC


def test_dossier_does_not_modify_input_objects():
    ident = _identity(
        state=IdentityState.CONFLICT,
        token_id=None,
        conflicts=("source_disagreement",),
    )
    unknowns = ["live_gap"]
    decision = _decision(outcome="WATCH", unknowns=unknowns)
    score = _score(opportunity_score=10.0, missing_unknowns=["liq"])
    compose_dossier(identity=ident, decision=decision, score=score)
    assert ident.conflicts == ("source_disagreement",)
    assert unknowns == ["live_gap"]
    assert score.missing_unknowns == ["liq"]


def test_dossier_is_deterministic_given_equivalent_inputs():
    ident = _identity(state=IdentityState.VERIFIED, token_id="sameid", symbol="AAA")
    kwargs = dict(
        identity=ident,
        decision=_decision(outcome="WATCH"),
        score=_score(opportunity_score=7.0, token_symbol="AAA"),
        security=_security("INCOMPLETE"),
        composed_at=9.0,
    )
    a = compose_dossier(**kwargs)
    b = compose_dossier(**kwargs)
    assert a == b
    assert a.as_dict() == b.as_dict()


def test_no_filesystem_or_database_access(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("dossier must not touch the filesystem")

    monkeypatch.setattr("builtins.open", _boom)
    compose_dossier(
        identity=_identity(state=IdentityState.UNRESOLVED, token_id=None),
        score=_score(opportunity_score=1.0),
        composed_at=0.0,
    )


def test_no_runtime_import_in_dossier_source():
    for snippet in FORBIDDEN_IMPORT_SNIPPETS:
        assert snippet not in DOSSIER_SRC, snippet


def test_no_p5_observation_grant_import():
    assert "memory.observation" not in DOSSIER_SRC
    assert "observation_grant" not in DOSSIER_SRC
    assert "CognitiveOrchestrator" not in DOSSIER_SRC


def test_no_lane_a_import():
    assert "discovery" not in DOSSIER_SRC
    assert "paper_trading" not in DOSSIER_SRC


def test_no_factual_premise_created_or_promoted():
    assert "FACTUAL_PREMISE" not in DOSSIER_SRC
    ident = _identity(state=IdentityState.UNRESOLVED, token_id=None)
    claim = SimpleNamespace(
        statement="this is verified fact",
        trust_class="AI_INTERPRETATION",
        category="CANONICAL",
        claim_id="c1",
        contradiction_edges=(),
        contradicting_evidence_ids=(),
    )
    dossier = compose_dossier(identity=ident, claims=(claim,))
    assert all(e.status is not EpistemicStatus.OBSERVED or e.field != "identity_state"
               for e in dossier.epistemic_map)
    assert dossier.identity_state == "UNRESOLVED"
    assert all(c.category != "FACTUAL_PREMISE" for c in dossier.claims)
    claim_entries = [e for e in dossier.epistemic_map if e.field.startswith("claim:")]
    assert claim_entries
    assert all(e.status is EpistemicStatus.INFERRED for e in claim_entries)


def test_import_boundary_production_surfaces_do_not_reference_dossier():
    for path in PRODUCTION_SURFACES:
        text = path.read_text(encoding="utf-8")
        assert "dossier" not in text, path
        assert "compose_dossier" not in text, path
    knowledge_init = (ROOT / "architecture" / "knowledge" / "__init__.py").read_text(encoding="utf-8")
    assert "dossier" not in knowledge_init


def test_importing_composer_does_not_load_lane_a_or_runtime():
    import subprocess
    import sys

    code = (
        "import importlib.util, sys\n"
        "from pathlib import Path\n"
        "root = Path(r'''" + str(ROOT) + "''')\n"
        "sys.path.insert(0, str(root))\n"
        "path = root / 'architecture' / 'knowledge' / 'dossier.py'\n"
        "spec = importlib.util.spec_from_file_location('ahos_dossier_isolated', path)\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "sys.modules[spec.name] = mod\n"
        "spec.loader.exec_module(mod)\n"
        "banned = [k for k in sys.modules if k == 'discovery' "
        "or k.startswith('discovery.') "
        "or k.startswith('paper_trading') "
        "or k.startswith('architecture.runtime') "
        "or k.startswith('architecture.pipeline') "
        "or k.startswith('architecture.cognitive.loop') "
        "or 'memory.observation' in k "
        "or k == 'architecture.identity' "
        "or k.startswith('architecture.identity.')]\n"
        "assert banned == [], banned\n"
        "assert mod.COMPOSER_VERSION\n"
    )
    proc = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_runtime_and_pipeline_modules_do_not_import_dossier():
    runtime_dir = ROOT / "architecture" / "runtime"
    for path in runtime_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "knowledge.dossier" not in text
        assert "compose_dossier" not in text
    orch = (ROOT / "architecture" / "pipeline" / "orchestrator.py").read_text(encoding="utf-8")
    assert "knowledge.dossier" not in orch


# --- adversarial ---


def test_adversarial_symbol_collision_different_chains():
    a = compose_dossier(identity=_identity(
        state=IdentityState.UNRESOLVED, chain="solana", address=None,
        token_id=None, symbol="ABC",
    ))
    b = compose_dossier(identity=_identity(
        state=IdentityState.UNRESOLVED, chain="ethereum", address=None,
        token_id=None, symbol="ABC",
    ))
    sa = next(k.value for k in a.join_keys if k.scheme == "symbol_key")
    sb = next(k.value for k in b.join_keys if k.scheme == "symbol_key")
    assert sa != sb
    assert sa.endswith(":sym:ABC")
    assert a.canonical_token_id is None and b.canonical_token_id is None


def test_adversarial_same_address_different_chain():
    addr = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    a = compose_dossier(identity=_identity(
        state=IdentityState.UNRESOLVED, chain="ethereum", address=addr, token_id=None, symbol="X",
    ))
    b = compose_dossier(identity=_identity(
        state=IdentityState.UNRESOLVED, chain="base", address=addr, token_id=None, symbol="X",
    ))
    ka = next(k.value for k in a.join_keys if k.scheme == "decision_token_key")
    kb = next(k.value for k in b.join_keys if k.scheme == "decision_token_key")
    assert ka != kb
    assert a.canonical_token_id is None and b.canonical_token_id is None


def test_adversarial_same_symbol_different_addresses():
    dossier = compose_dossier(
        identity=_identity(
            state=IdentityState.UNRESOLVED, chain="solana",
            address="Mint111111111111111111111111111111111111111",
            token_id=None, symbol="ABC",
        ),
        score=_score(
            token_chain="solana",
            token_address="Mint222222222222222222222222222222222222222",
            token_symbol="ABC",
            opportunity_score=88.0,
        ),
    )
    assert dossier.identity_state == "UNRESOLVED"
    assert dossier.canonical_token_id is None
    assert any("alias_chain_address_disagreement" in c for c in dossier.conflicts)


def test_adversarial_identity_conflict_plus_high_score():
    dossier = compose_dossier(
        identity=_identity(state=IdentityState.CONFLICT, token_id=None, conflicts=("source_disagreement",)),
        score=_score(opportunity_score=95.0),
        decision=_decision(outcome="NO_TRADE"),
    )
    assert dossier.identity_state == "CONFLICT"
    assert dossier.opportunity_score == 95.0
    assert dossier.decision_outcome == "NO_TRADE"


def test_adversarial_identity_unresolved_plus_high_score():
    dossier = compose_dossier(
        identity=_identity(state=IdentityState.UNRESOLVED, token_id=None),
        score=_score(opportunity_score=95.0),
    )
    assert dossier.identity_state == "UNRESOLVED"
    assert dossier.canonical_token_id is None
    assert dossier.opportunity_score == 95.0


def test_adversarial_security_reject_plus_high_score():
    dossier = compose_dossier(
        score=_score(opportunity_score=99.9),
        security=_security("REJECT", veto_reasons=("mint_authority_active",)),
        decision=_decision(outcome="REJECT"),
    )
    assert dossier.security_state == "REJECT"
    assert dossier.decision_outcome == "REJECT"
    assert "security_veto:mint_authority_active" in dossier.conflicts


def test_adversarial_unknown_security_plus_high_score():
    dossier = compose_dossier(
        score=_score(opportunity_score=80.0),
        security=_security("INCOMPLETE", unknown_critical=("lp_not_locked_fresh_pool",)),
        decision=_decision(outcome="INSUFFICIENT_EVIDENCE"),
    )
    assert dossier.security_state == "INCOMPLETE"
    assert any("lp_not_locked_fresh_pool" in u for u in dossier.unknowns)
    assert dossier.opportunity_score == 80.0
    assert dossier.decision_outcome == "INSUFFICIENT_EVIDENCE"


def test_adversarial_missing_identity_plus_complete_score():
    dossier = compose_dossier(
        identity=None,
        score=_score(opportunity_score=70.0, token_chain="solana", token_symbol="ZZ", token_address="MintZ"),
        decision=_decision(outcome="WATCH", identity_state="VERIFIED"),
    )
    assert dossier.canonical_token_id is None
    assert dossier.identity_state is None
    assert "identity_resolution_absent" in dossier.unknowns
    assert "identity_state" in dossier.unknowns
    assert any(u == "decision_identity_state:VERIFIED" for u in dossier.unknowns)
    assert any(
        p.get("source") == "decision_identity_state_diagnostic"
        and p.get("identity_state") == "VERIFIED"
        for p in dossier.provenance
    )
    id_ep = next(e for e in dossier.epistemic_map if e.field == "identity_state")
    assert id_ep.status is EpistemicStatus.UNAVAILABLE
    assert not any(k.kind is AliasKind.CANONICAL for k in dossier.join_keys)


def test_adversarial_existing_canonical_id_plus_multiple_aliases():
    ident = _identity(
        state=IdentityState.VERIFIED,
        chain="ethereum",
        address="0xAbCdEf",
        token_id="preservedhashid",
        symbol="UNI",
        provenance=({"provider": "gecko", "retrieved_ts": 1.0},),
    )
    dossier = compose_dossier(
        identity=ident,
        score=_score(opportunity_score=33.0, token_chain="ethereum", token_address="0xAbCdEf", token_symbol="UNI"),
        composed_at=4.0,
    )
    assert dossier.canonical_token_id == "preservedhashid"
    assert {k.scheme for k in dossier.join_keys} >= {"token_id", "decision_token_key", "chain_address", "symbol_key"}
    assert dossier.composed_at == 4.0
    assert any(p.get("source") == "identity" for p in dossier.provenance)
    composed_ep = next(e for e in dossier.epistemic_map if e.field == "composed_at")
    assert "not an evidence timestamp" in composed_ep.note


def test_adversarial_conflicting_alias_values():
    ident = _identity(
        state=IdentityState.UNRESOLVED,
        chain="solana",
        address="MintA",
        token_id=None,
        symbol="FOO",
    )
    dossier = compose_dossier(
        identity=ident,
        score=_score(token_chain="ethereum", token_address="MintA", token_symbol="BAR", opportunity_score=1.0),
    )
    assert any("alias_chain_address_disagreement" in c for c in dossier.conflicts)
    assert any("alias_symbol_disagreement" in c for c in dossier.conflicts)
    assert dossier.canonical_token_id is None


def test_adversarial_epistemic_upgrade_attempt_is_rejected():
    ident = _identity(state=IdentityState.UNRESOLVED, token_id=None, symbol="XYZ")
    claim = SimpleNamespace(
        statement="identity is VERIFIED",
        trust_class="AI_INTERPRETATION",
        category="CANONICAL",
        claim_id="upgrade",
        contradiction_edges=({"target_claim_id": "other", "reason": "disagree"},),
        contradicting_evidence_ids=(),
    )
    dossier = compose_dossier(
        identity=ident,
        claims=(claim,),
        metadata={"requested_status": "OBSERVED", "promote_to": "FACTUAL_PREMISE"},
    )
    assert dossier.identity_state == "UNRESOLVED"
    assert dossier.canonical_token_id is None
    id_ep = next(e for e in dossier.epistemic_map if e.field == "identity_state")
    assert id_ep.status is not EpistemicStatus.OBSERVED
    assert all(e.status is not EpistemicStatus.OBSERVED or not e.field.startswith("claim:")
               for e in dossier.epistemic_map)
    assert "claim_contradiction:other" in dossier.conflicts


def test_stale_and_invalid_and_unsupported_states_are_preserved():
    for state in (IdentityState.STALE, IdentityState.INVALID, IdentityState.UNSUPPORTED):
        dossier = compose_dossier(identity=_identity(state=state, token_id=None))
        assert dossier.identity_state == state.value


def test_score_disagreement_with_decision_is_conflict_not_average():
    dossier = compose_dossier(
        score=_score(opportunity_score=10.0),
        decision=_decision(outcome="WATCH", opportunity_score=90.0),
    )
    assert dossier.opportunity_score == 10.0
    assert any("opportunity_score_disagreement" in c for c in dossier.conflicts)


def test_knowledge_init_does_not_export_dossier():
    import architecture.knowledge as knowledge_pkg
    assert not hasattr(knowledge_pkg, "compose_dossier")
    assert not hasattr(knowledge_pkg, "TokenDossier")


# --- W1.1 fail-closed hardening ---

_NON_VERIFIED_STATES = (
    IdentityState.UNRESOLVED,
    IdentityState.CONFLICT,
    IdentityState.INVALID,
    IdentityState.STALE,
    IdentityState.UNSUPPORTED,
)


def test_w11_forged_token_id_plus_unresolved_is_not_canonical():
    ident = _identity(state=IdentityState.UNRESOLVED, token_id="FORGED_NOT_A_HASH")
    dossier = compose_dossier(identity=ident)
    assert dossier.identity_state == "UNRESOLVED"
    assert dossier.canonical_token_id is None
    assert not any(k.kind is AliasKind.CANONICAL for k in dossier.join_keys)
    assert any(
        k.kind is AliasKind.OPERATIONAL
        and k.scheme == "unvalidated_token_id"
        and k.value == "FORGED_NOT_A_HASH"
        for k in dossier.join_keys
    )
    assert "canonical_token_id" in dossier.unknowns


def test_w11_missing_identity_plus_decision_verified_does_not_fill_primary():
    dossier = compose_dossier(
        identity=None,
        decision=_decision(outcome="WATCH", identity_state="VERIFIED"),
    )
    assert dossier.identity_state is None
    assert dossier.canonical_token_id is None
    assert "identity_resolution_absent" in dossier.unknowns
    assert any(u == "decision_identity_state:VERIFIED" for u in dossier.unknowns)
    assert any(
        p.get("source") == "decision_identity_state_diagnostic"
        and p.get("identity_state") == "VERIFIED"
        for p in dossier.provenance
    )
    assert not any(k.kind is AliasKind.CANONICAL for k in dossier.join_keys)


def test_w11_missing_identity_plus_decision_buy_does_not_create_identity():
    dossier = compose_dossier(
        identity=None,
        decision=_decision(outcome="BUY", identity_state="VERIFIED"),
    )
    assert dossier.identity_state is None
    assert dossier.decision_outcome == "BUY"
    assert dossier.canonical_token_id is None
    assert "identity_resolution_absent" in dossier.unknowns
    assert not any(k.kind is AliasKind.CANONICAL for k in dossier.join_keys)


def test_w11_overlay_reject_plus_decision_pass_preserves_both():
    dossier = compose_dossier(
        security=_security("REJECT", veto_reasons=("honeypot",)),
        decision=_decision(outcome="REJECT", security_state="PASS"),
    )
    assert dossier.security_state == "REJECT"
    assert dossier.decision_outcome == "REJECT"
    assert any("security_state_disagreement:overlay=REJECT:decision=PASS" in c for c in dossier.conflicts)
    assert "security_veto:honeypot" in dossier.conflicts
    assert any(
        p.get("source") == "security_state_disagreement"
        and p.get("overlay_security_state") == "REJECT"
        and p.get("decision_security_state") == "PASS"
        and p.get("effective_security_state") == "REJECT"
        for p in dossier.provenance
    )


def test_w11_overlay_pass_plus_decision_reject_preserves_both():
    dossier = compose_dossier(
        security=_security("PASS"),
        decision=_decision(outcome="REJECT", security_state="REJECT"),
    )
    assert dossier.security_state == "PASS"
    assert dossier.decision_outcome == "REJECT"
    assert any("security_state_disagreement:overlay=PASS:decision=REJECT" in c for c in dossier.conflicts)
    assert any(
        p.get("source") == "security_state_disagreement"
        and p.get("overlay_security_state") == "PASS"
        and p.get("decision_security_state") == "REJECT"
        and p.get("effective_security_state") == "PASS"
        for p in dossier.provenance
    )


def test_w11_nested_provenance_mutation_is_isolated_both_directions():
    nested = {"retrieved_ts": 1.0, "inner": {"k": "v"}}
    caller_blob = {"provider": "gecko", "nested": nested}
    decision_nested = {"trace": {"id": "t1"}}
    ident = _identity(
        state=IdentityState.VERIFIED,
        token_id="abc123canonicalid",
        provenance=(caller_blob,),
    )
    decision = _decision(outcome="WATCH", provenance={"nested": decision_nested, "step": "decide"})
    dossier = compose_dossier(identity=ident, decision=decision)

    nested["retrieved_ts"] = 999
    nested["inner"]["k"] = "mutated"
    caller_blob["provider"] = "forged"
    decision_nested["trace"]["id"] = "mutated"
    decision.provenance["step"] = "mutated"

    id_prov = next(p for p in dossier.provenance if p.get("source") == "identity")
    dec_prov = next(p for p in dossier.provenance if p.get("source") == "decision")
    assert id_prov["provider"] == "gecko"
    assert id_prov["nested"]["retrieved_ts"] == 1.0
    assert id_prov["nested"]["inner"]["k"] == "v"
    assert dec_prov["nested"]["trace"]["id"] == "t1"
    assert dec_prov["step"] == "decide"

    raised = False
    try:
        id_prov["provider"] = "from_dossier"
    except (TypeError, AttributeError):
        raised = True
    try:
        id_prov["nested"]["inner"]["k"] = "from_dossier"  # type: ignore[index]
    except (TypeError, AttributeError):
        raised = True
    assert raised
    assert caller_blob["provider"] == "forged"
    assert nested["inner"]["k"] == "mutated"

    exported = dossier.as_dict()
    exported["provenance"][0]["provider"] = "from_export"
    exported["provenance"][0]["nested"]["inner"]["k"] = "from_export"
    id_after = next(p for p in dossier.provenance if p.get("source") == "identity")
    assert id_after["provider"] == "gecko"
    assert id_after["nested"]["inner"]["k"] == "v"
    assert caller_blob["provider"] == "forged"
    assert nested["inner"]["k"] == "mutated"


def test_w11_conflict_identity_plus_buy_does_not_create_canonical():
    dossier = compose_dossier(
        identity=_identity(
            state=IdentityState.CONFLICT,
            token_id="looks_like_a_hash",
            conflicts=("source_disagreement",),
        ),
        decision=_decision(outcome="BUY", identity_state="VERIFIED"),
    )
    assert dossier.identity_state == "CONFLICT"
    assert dossier.decision_outcome == "BUY"
    assert dossier.canonical_token_id is None
    assert not any(k.kind is AliasKind.CANONICAL for k in dossier.join_keys)
    assert "source_disagreement" in dossier.conflicts
    assert any("identity_state_disagreement" in c for c in dossier.conflicts)


def test_w11_canonical_join_key_absent_for_all_non_verified_identity_states():
    for state in _NON_VERIFIED_STATES:
        dossier = compose_dossier(
            identity=_identity(state=state, token_id="looks_canonical_but_unverified"),
        )
        assert dossier.identity_state == state.value, state
        assert dossier.canonical_token_id is None, state
        assert not any(k.kind is AliasKind.CANONICAL for k in dossier.join_keys), state
        assert any(
            k.kind is AliasKind.OPERATIONAL
            and k.scheme == "unvalidated_token_id"
            and k.value == "looks_canonical_but_unverified"
            for k in dossier.join_keys
        ), state


# --- W1.2 boundary hardening ---

class _StrPassNoState:
    def __str__(self) -> str:
        return "PASS"


class _StrRejectNoState:
    def __str__(self) -> str:
        return "REJECT"


def _spoofed_identity_resolution(**namespace):
    cls = type("IdentityResolution", (), namespace)
    cls.__module__ = ".".join(("architecture", "identity", "types"))
    return cls()


def _assert_no_canonical(dossier) -> None:
    assert dossier.canonical_token_id is None
    assert not any(k.kind is AliasKind.CANONICAL for k in dossier.join_keys)
    assert dossier.identity_state != "VERIFIED"


def test_w12_str_pass_without_state_is_not_security_authority():
    dossier = compose_dossier(security=_StrPassNoState())
    assert dossier.security_state is None
    assert "security_state_field_absent" in dossier.unknowns
    assert any(p.get("source") == "security_overlay_rejected" for p in dossier.provenance)


def test_w12_str_reject_without_state_is_not_security_authority():
    dossier = compose_dossier(security=_StrRejectNoState())
    assert dossier.security_state is None
    assert "security_state_field_absent" in dossier.unknowns


def test_w12_explicit_state_pass_is_preserved():
    dossier = compose_dossier(security=_security("PASS"))
    assert dossier.security_state == "PASS"


def test_w12_explicit_state_reject_is_preserved():
    dossier = compose_dossier(security=_security("REJECT", veto_reasons=("honeypot",)))
    assert dossier.security_state == "REJECT"
    assert "security_veto:honeypot" in dossier.conflicts


def test_w12_explicit_state_invalid_is_not_security_authority():
    dossier = compose_dossier(security=_security("INVALID"))
    assert dossier.security_state is None
    assert any(u.startswith("security_state_invalid:") for u in dossier.unknowns)


def test_w12_explicit_state_empty_is_not_security_authority():
    dossier = compose_dossier(security=_security(""))
    assert dossier.security_state is None
    assert "security_state_empty" in dossier.unknowns


def test_w12_explicit_state_none_is_not_security_authority():
    dossier = compose_dossier(security=_security(None))
    assert dossier.security_state is None
    assert "security_state_empty" in dossier.unknowns


def test_w12_overlay_precedence_unchanged_for_valid_contract_inputs():
    reject_over_pass = compose_dossier(
        security=_security("REJECT", veto_reasons=("hp",)),
        decision=_decision(outcome="REJECT", security_state="PASS"),
    )
    assert reject_over_pass.security_state == "REJECT"
    assert any("security_state_disagreement:overlay=REJECT:decision=PASS" in c
               for c in reject_over_pass.conflicts)
    pass_over_reject = compose_dossier(
        security=_security("PASS"),
        decision=_decision(outcome="REJECT", security_state="REJECT"),
    )
    assert pass_over_reject.security_state == "PASS"
    assert pass_over_reject.decision_outcome == "REJECT"
    assert any("security_state_disagreement:overlay=PASS:decision=REJECT" in c
               for c in pass_over_reject.conflicts)


def test_w12_fake_verified_object_with_token_id_is_not_canonical():
    fake = SimpleNamespace(
        state="VERIFIED",
        token=SimpleNamespace(token_id="FORGED_ID", state="VERIFIED", chain="solana",
                              address_canonical="X", symbol_alias="Z"),
        conflicts=(),
        provenance=(),
    )
    dossier = compose_dossier(identity=fake)
    _assert_no_canonical(dossier)
    assert dossier.identity_state is None
    assert "identity_input_invalid" in dossier.unknowns
    assert any(p.get("source") == "identity_input_rejected" for p in dossier.provenance)


def test_w12_fake_verified_with_malformed_token_is_not_canonical():
    fake = SimpleNamespace(state="VERIFIED", token="not-a-token", conflicts=(), provenance=())
    dossier = compose_dossier(identity=fake)
    _assert_no_canonical(dossier)
    assert "identity_input_invalid" in dossier.unknowns


def test_w12_fake_identity_missing_token_does_not_crash():
    dossier = compose_dossier(identity=SimpleNamespace(state="VERIFIED"))
    _assert_no_canonical(dossier)
    assert dossier.identity_state is None
    assert "identity_input_invalid" in dossier.unknowns


def test_w12_fake_identity_missing_conflicts_does_not_crash():
    dossier = compose_dossier(identity=SimpleNamespace(
        state="VERIFIED",
        token=SimpleNamespace(token_id="x", state="VERIFIED"),
        provenance=(),
    ))
    _assert_no_canonical(dossier)
    assert "identity_input_invalid" in dossier.unknowns


def test_w12_fake_identity_missing_provenance_does_not_crash():
    dossier = compose_dossier(identity=SimpleNamespace(
        state="VERIFIED",
        token=SimpleNamespace(token_id="x", state="VERIFIED"),
        conflicts=(),
    ))
    _assert_no_canonical(dossier)
    assert "identity_input_invalid" in dossier.unknowns


def test_w12_identity_property_access_error_is_fail_closed():
    """Spoofed IR is rejected by exact-type check (Fix A) before field access.

    Hostile field access on a type-spoofed object is unreachable under Fix A;
    fail-closed no-canonical still holds. Access-error path for *exact* types
    is covered when a real IdentityResolution exposes an unreadable field.
    """
    boom = _spoofed_identity_resolution(
        token=property(lambda self: (_ for _ in ()).throw(RuntimeError("hostile"))),
        conflicts=(),
        provenance=(),
    )
    dossier = compose_dossier(identity=boom)
    _assert_no_canonical(dossier)
    assert dossier.identity_state is None
    assert "identity_input_invalid" in dossier.unknowns
    assert any(p.get("source") == "identity_input_rejected" for p in dossier.provenance)

    # Exact-type IR with hostile token descriptor via class monkeypatch.
    real = _identity(state=IdentityState.VERIFIED, token_id="will_not_read")
    original = IdentityResolution.__dict__.get("token")
    def _hostile_token(_self):
        raise RuntimeError("hostile")
    try:
        IdentityResolution.token = property(_hostile_token)  # type: ignore[misc, assignment]
        hostile_dossier = compose_dossier(identity=real)
    finally:
        if original is not None:
            IdentityResolution.token = original  # type: ignore[misc, assignment]
        else:
            delattr(IdentityResolution, "token")
    _assert_no_canonical(hostile_dossier)
    assert hostile_dossier.identity_state is None
    assert "identity_resolution_invalid" in hostile_dossier.unknowns
    assert any(
        p.get("source") == "identity_input_rejected"
        and "access_error" in str(p.get("detail"))
        for p in hostile_dossier.provenance
    )


def test_w12_real_verified_identity_resolution_still_authorizes_canonical():
    ident = _identity(state=IdentityState.VERIFIED, token_id="abc123canonicalid")
    dossier = compose_dossier(identity=ident)
    assert dossier.identity_state == "VERIFIED"
    assert dossier.canonical_token_id == "abc123canonicalid"
    assert any(k.kind is AliasKind.CANONICAL and k.value == "abc123canonicalid" for k in dossier.join_keys)


def test_w12_real_unresolved_identity_resolution_is_not_canonical():
    ident = _identity(state=IdentityState.UNRESOLVED, token_id="FORGED_NOT_A_HASH")
    dossier = compose_dossier(identity=ident)
    assert dossier.identity_state == "UNRESOLVED"
    _assert_no_canonical(dossier)


def test_w12_real_conflict_identity_resolution_is_not_canonical():
    ident = _identity(state=IdentityState.CONFLICT, token_id="FORGED_NOT_A_HASH", conflicts=("src",))
    dossier = compose_dossier(identity=ident)
    assert dossier.identity_state == "CONFLICT"
    _assert_no_canonical(dossier)
    assert "src" in dossier.conflicts


def test_w12_empty_namespace_identity_does_not_raise():
    dossier = compose_dossier(identity=SimpleNamespace())
    _assert_no_canonical(dossier)
    assert dossier.identity_state is None
    assert "identity_input_invalid" in dossier.unknowns


def test_w12_spoofed_resolution_with_malformed_token_is_rejected():
    """Under Fix A, type-spoofed IR is rejected as identity_input_invalid."""
    boom = _spoofed_identity_resolution(
        token=SimpleNamespace(state="VERIFIED", token_id="FORGED_ID"),
        conflicts=(),
        provenance=(),
    )
    dossier = compose_dossier(identity=boom)
    _assert_no_canonical(dossier)
    assert "identity_input_invalid" in dossier.unknowns


def test_w12_composer_source_has_no_contiguous_identity_import_token():
    assert "architecture.identity" not in DOSSIER_SRC
    assert "import hashlib" not in DOSSIER_SRC
    assert "FACTUAL_PREMISE" not in DOSSIER_SRC


# --- W1.3 exact class identity + always-recompose (Fix A + Fix B) ---

def _dynamic_token_identity(**attrs):
    defaults = dict(
        token_id="FORGED_CANONICAL",
        state="VERIFIED",
        chain="solana",
        address_canonical="So11111111111111111111111111111111111111112",
        address_input="So11111111111111111111111111111111111111112",
        symbol_alias="FAKE",
    )
    defaults.update(attrs)
    cls = type("TokenIdentity", (), {"__module__": ".".join(("architecture", "identity", "types")), **defaults})
    return cls()


def _dynamic_identity_resolution(*, token, conflicts=(), provenance=()):
    cls = type(
        "IdentityResolution",
        (),
        {
            "__module__": ".".join(("architecture", "identity", "types")),
            "token": token,
            "conflicts": conflicts,
            "provenance": provenance,
        },
    )
    return cls()


def test_w13_t1_dynamic_class_spoof_both_ir_and_ti_no_verified_canonical():
    """T1: dynamic type() spoof of IR+TI must not mint VERIFIED/canonical."""
    spoof = _dynamic_identity_resolution(token=_dynamic_token_identity())
    dossier = compose_dossier(identity=spoof)
    _assert_no_canonical(dossier)
    assert dossier.identity_state is None
    assert "identity_input_invalid" in dossier.unknowns


def test_w13_t2_forge_ir_only_or_ti_only_rejected():
    """T2: forging only IR or only TI is rejected."""
    real_ti = TokenIdentity(
        chain="solana",
        address_canonical="So11111111111111111111111111111111111111112",
        address_input="So11111111111111111111111111111111111111112",
        token_id="real_but_wrapped",
        symbol_alias="ABC",
        name_alias=None,
        state=IdentityState.VERIFIED,
        reason="fixture",
    )
    ir_only = _dynamic_identity_resolution(token=real_ti)
    d_ir = compose_dossier(identity=ir_only)
    _assert_no_canonical(d_ir)
    assert d_ir.identity_state is None

    fake_ti = _dynamic_token_identity(token_id="FORGED_TI_ONLY")
    ir_with_fake_ti = IdentityResolution(
        chain=ChainIdentity("solana", "solana", IdentityState.VERIFIED, "fixture"),
        token=fake_ti,
        pool=None,
        dex=None,
        sources=(),
        conflicts=(),
        provenance=(),
    )
    d_ti = compose_dossier(identity=ir_with_fake_ti)
    _assert_no_canonical(d_ti)
    assert d_ti.identity_state is None
    assert "identity_resolution_invalid" in d_ti.unknowns


def test_w13_t3_real_verified_still_canonical():
    """T3: real VERIFIED IdentityResolution still authorizes canonical."""
    ident = _identity(state=IdentityState.VERIFIED, token_id="abc123canonicalid")
    dossier = compose_dossier(identity=ident)
    assert dossier.identity_state == "VERIFIED"
    assert dossier.canonical_token_id == "abc123canonicalid"
    assert dossier.composer_version == COMPOSER_VERSION


def test_w13_t4_real_unresolved_and_conflict_unchanged():
    """T4: real UNRESOLVED/CONFLICT remain non-canonical."""
    unresolved = compose_dossier(
        identity=_identity(state=IdentityState.UNRESOLVED, token_id="FORGED_NOT_A_HASH")
    )
    assert unresolved.identity_state == "UNRESOLVED"
    _assert_no_canonical(unresolved)

    conflict = compose_dossier(
        identity=_identity(
            state=IdentityState.CONFLICT,
            token_id="FORGED_NOT_A_HASH",
            conflicts=("src",),
        )
    )
    assert conflict.identity_state == "CONFLICT"
    _assert_no_canonical(conflict)
    assert "src" in conflict.conflicts


def test_w13_t7_dossier_source_lacks_contiguous_identity_and_hashlib():
    """T7: dossier source lacks contiguous architecture.identity, hashlib, and seal symbols."""
    src = (ROOT / "architecture" / "knowledge" / "dossier.py").read_text(encoding="utf-8")
    assert "architecture.identity" not in src
    assert "import hashlib" not in src
    assert "import sys" in src
    assert "_exact_type" in src
    assert "_COMPOSER_SEAL" not in src
    assert "composer_seal" not in src


def test_w13_t9_dynamic_spoof_fails_via_compose_dossier_path():
    """T9: after Fix A, dynamic spoof fails on compose_dossier path used by W2."""
    spoof = _dynamic_identity_resolution(token=_dynamic_token_identity(token_id="SPOOF_W2_PATH"))
    dossier = compose_dossier(identity=spoof)
    _assert_no_canonical(dossier)
    # Spoofed identity composition carries no canonical.
    assert dossier.canonical_token_id is None


def test_w13_t10_combined_a_and_b_paths_closed():
    """T10: Fix A closes string-type spoof; Fix B closes hand-built dossier."""
    # Path A (compose_dossier identity spoof)
    spoof = _dynamic_identity_resolution(token=_dynamic_token_identity())
    a = compose_dossier(identity=spoof)
    _assert_no_canonical(a)

    # Path B (hand-built TokenDossier scalars — W2 must ignore; see evidence_graph T11)
    hand = TokenDossier(
        canonical_token_id="FORGED",
        join_keys=(),
        identity_state="VERIFIED",
        security_state=None,
        decision_outcome=None,
        opportunity_score=None,
        epistemic_map=(),
        conflicts=(),
        unknowns=(),
        provenance=(),
        composed_at=None,
        claims=(),
    )
    assert hand.identity_state == "VERIFIED"  # scalars present on object
    # W2 must ignore hand-built dossier (covered by evidence_graph T5/T11).
    real = compose_dossier(identity=_identity(state=IdentityState.VERIFIED, token_id="abc123canonicalid"))
    assert real.identity_state == "VERIFIED"
    assert real.canonical_token_id == "abc123canonicalid"


# --- W1.4 resolver-mint marker (dossier refuse unminted VERIFIED) ---


def test_w14_a1_unminted_verified_rejected():
    """A1: hand-built exact-typed VERIFIED without mint → identity_verified_unminted."""
    ident = _identity_unminted(token_id="abc123canonicalid")
    assert getattr(ident, "_ahos_verified_mint", None) is None
    dossier = compose_dossier(identity=ident)
    assert "identity_verified_unminted" in dossier.unknowns
    assert dossier.canonical_token_id is None
    assert dossier.identity_state is None
    # No silent demotion to UNRESOLVED as primary accepted state
    assert dossier.identity_state != "UNRESOLVED"
    assert dossier.identity_state != "VERIFIED"
    reasons = [dict(p).get("reason") for p in dossier.provenance]
    assert "identity_verified_unminted" in reasons
    details = [dict(p).get("detail") for p in dossier.provenance]
    assert "verified_without_resolver_mint" in details


def test_w14_a1b_forged_cookie_and_replace_fail():
    """A1b: forged cookie / dataclasses.replace plant fails; same reject."""
    ident = _identity_unminted(token_id="abc123canonicalid")
    # dataclasses.replace cannot plant init=False field
    try:
        planted = replace(ident, _ahos_verified_mint=object())
        # If somehow constructed, still must fail is-check unless cookie is exact sentinel
        dossier = compose_dossier(identity=planted)
        assert dossier.canonical_token_id is None
        assert "identity_verified_unminted" in dossier.unknowns
    except (TypeError, ValueError):
        pass  # CPython 3.11+ raises ValueError for init=False in replace; TypeError kept for other runtimes

    # Forged cookie via object.__setattr__ with wrong sentinel
    forged = _identity_unminted(token_id="abc123canonicalid")
    object.__setattr__(forged, "_ahos_verified_mint", object())
    dossier = compose_dossier(identity=forged)
    assert dossier.canonical_token_id is None
    assert "identity_verified_unminted" in dossier.unknowns
    assert dossier.identity_state is None


def test_w14_a3_minted_via_support_and_resolve_identity():
    """A3: minted via _mint_support or resolve_identity → VERIFIED + canonical."""
    # Path 1: test mint helper
    minted = _mint_verified_for_tests(
        _identity_unminted(token_id="abc123canonicalid")
    )
    d1 = compose_dossier(identity=minted)
    assert d1.identity_state == "VERIFIED"
    assert d1.canonical_token_id == "abc123canonicalid"
    assert d1.composer_version == COMPOSER_VERSION
    assert COMPOSER_VERSION == "token-dossier-composer-v1.3"

    # Path 2: default _identity (auto-mint)
    d2 = compose_dossier(
        identity=_identity(state=IdentityState.VERIFIED, token_id="abc123canonicalid")
    )
    assert d2.identity_state == "VERIFIED"
    assert d2.canonical_token_id == "abc123canonicalid"

    # Path 3: real resolve_identity with independent sources
    addr = "So11111111111111111111111111111111111111112"
    sources = (
        IdentitySource(provider="a", chain="solana", address=addr, kind="onchain"),
        IdentitySource(provider="b", chain="solana", address=addr, kind="market"),
    )
    resolved = resolve_identity(chain="solana", address=addr, sources=sources, symbol="SOL")
    assert resolved.token.state is IdentityState.VERIFIED
    assert getattr(resolved, "_ahos_verified_mint", None) is not None
    d3 = compose_dossier(identity=resolved)
    assert d3.identity_state == "VERIFIED"
    assert d3.canonical_token_id is not None
    assert d3.canonical_token_id == resolved.token.token_id


def test_w14_a7_no_contiguous_architecture_identity_in_dossier():
    """A7: dossier.py has no contiguous architecture.identity import token."""
    src = (ROOT / "architecture" / "knowledge" / "dossier.py").read_text(encoding="utf-8")
    assert "architecture.identity" not in src
    assert "AHOS_ALLOW_UNMINTED_VERIFIED" not in src


def test_w14_a9_mint_helpers_not_in_identity_all():
    """A9: mint attach / test mint absent from architecture.identity.__all__."""
    import architecture.identity as ident_pkg
    exported = set(getattr(ident_pkg, "__all__", ()))
    banned = {
        "_attach_verified_mint",
        "_mint_verified_for_tests",
        "_VERIFIED_MINT",
        "mint_verified_resolution",
        "_ahos_verified_mint",
    }
    assert exported.isdisjoint(banned)
    for name in banned:
        assert not hasattr(ident_pkg, name) or name.startswith("_") and name not in exported
