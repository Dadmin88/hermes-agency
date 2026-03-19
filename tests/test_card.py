"""Tests for AgentCard and Skill data models."""

from agentanycast import AgentCard, Skill


def test_skill_roundtrip():
    skill = Skill(id="analyze_csv", description="Analyze CSV data")
    d = skill.to_dict()
    restored = Skill.from_dict(d)
    assert restored.id == "analyze_csv"
    assert restored.description == "Analyze CSV data"


def test_agent_card_roundtrip():
    card = AgentCard(
        name="DataAnalyst",
        description="Analyzes data",
        skills=[
            Skill(id="analyze_csv", description="Analyze CSV"),
            Skill(id="generate_chart", description="Generate chart"),
        ],
    )
    d = card.to_dict()
    assert d["name"] == "DataAnalyst"
    assert len(d["skills"]) == 2

    restored = AgentCard.from_dict(d)
    assert restored.name == "DataAnalyst"
    assert len(restored.skills) == 2
    assert restored.skills[0].id == "analyze_csv"


def test_agent_card_with_p2p_extension():
    card = AgentCard(
        name="Test",
        peer_id="12D3KooWTest",
        supported_transports=["tcp", "quic"],
        relay_addresses=["/ip4/1.2.3.4/tcp/4001/p2p/12D3KooWRelay"],
    )
    d = card.to_dict()
    assert "agentanycast" in d
    assert d["agentanycast"]["peer_id"] == "12D3KooWTest"

    restored = AgentCard.from_dict(d)
    assert restored.peer_id == "12D3KooWTest"
    assert restored.supported_transports == ["tcp", "quic"]


def test_agent_card_with_did_key():
    card = AgentCard(
        name="DIDTest",
        peer_id="12D3KooWTest",
        did_key="did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK",
    )
    d = card.to_dict()
    expected_did = "did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK"
    assert d["agentanycast"]["did_key"] == expected_did

    restored = AgentCard.from_dict(d)
    assert restored.did_key == "did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK"
    assert restored.peer_id == "12D3KooWTest"


def test_agent_card_with_identity_fields():
    card = AgentCard(
        name="IdentityTest",
        peer_id="12D3KooWTest",
        did_key="did:key:z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK",
        did_web="did:web:example.com:agents:myagent",
        did_dns="did:dns:example.com",
        verifiable_credentials=['{"type": "VerifiableCredential"}'],
    )
    d = card.to_dict()
    p2p = d["agentanycast"]
    assert p2p["did_web"] == "did:web:example.com:agents:myagent"
    assert p2p["did_dns"] == "did:dns:example.com"
    assert p2p["verifiable_credentials"] == ['{"type": "VerifiableCredential"}']

    restored = AgentCard.from_dict(d)
    assert restored.did_web == "did:web:example.com:agents:myagent"
    assert restored.did_dns == "did:dns:example.com"
    assert restored.verifiable_credentials == ['{"type": "VerifiableCredential"}']


def test_agent_card_identity_fields_default_empty():
    card = AgentCard(name="Minimal", peer_id="12D3KooWTest")
    d = card.to_dict()
    p2p = d["agentanycast"]
    assert "did_web" not in p2p
    assert "did_dns" not in p2p
    assert "verifiable_credentials" not in p2p

    restored = AgentCard.from_dict(d)
    assert restored.did_web is None
    assert restored.did_dns is None
    assert restored.verifiable_credentials == []


def test_agent_card_without_p2p_extension():
    card = AgentCard(name="Simple")
    d = card.to_dict()
    assert "agentanycast" not in d
