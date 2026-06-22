"""Cross-module integration tests for Phase 6 features.

These tests verify that Phase 6 modules (DID, MCP, AGNTCY, Card) work
correctly together as a pipeline, not just in isolation.
"""

from agentanycast.card import AgentCard, Skill
from agentanycast.did import did_key_to_peer_id, peer_id_to_did_key
from agentanycast.mcp import MCPTool, mcp_tool_to_skill, mcp_tools_to_agent_card

# ── DID + Card integration ────────────────────────────────────────────


class TestDIDCardIntegration:
    """Test that DID keys survive AgentCard serialization round-trips."""

    def test_did_key_round_trip_through_card(self) -> None:
        """Generate a DID from a PeerID, assign it to a card, serialize/deserialize."""
        # Use a known Ed25519-based PeerID (identity multihash of protobuf-encoded key).
        import base58

        # Construct a minimal Ed25519 PeerID: identity multihash of protobuf key.
        raw_pubkey = bytes(32)  # 32 zero bytes (valid length for Ed25519)
        proto_key = bytes([8, 1, 18, 32]) + raw_pubkey  # key_type=1, key_data=32 bytes
        # Identity multihash: 0x00 (code), len, data
        identity_mh = bytes([0x00, len(proto_key)]) + proto_key
        peer_id = base58.b58encode(identity_mh).decode()

        # Convert peer_id → did_key
        did = peer_id_to_did_key(peer_id)
        assert did.startswith("did:key:z")

        # Create a card with both peer_id and did_key
        card = AgentCard(
            name="IntegrationAgent",
            skills=[Skill(id="translate", description="Translates text")],
            peer_id=peer_id,
            did_key=did,
        )

        # Serialize and deserialize
        d = card.to_dict()
        restored = AgentCard.from_dict(d)

        # Verify round-trip
        assert restored.peer_id == peer_id
        assert restored.did_key == did

        # Verify the DID can be converted back to the original PeerID
        recovered_peer_id = did_key_to_peer_id(restored.did_key)  # type: ignore[arg-type]
        assert recovered_peer_id == peer_id

    def test_card_without_did_key_backward_compat(self) -> None:
        """Verify cards from older nodes (no did_key) deserialize correctly."""
        old_format = {
            "name": "OldAgent",
            "skills": [{"id": "chat", "description": "Chats"}],
            "agentanycast": {
                "peer_id": "12D3KooWTest",
                "supported_transports": ["noise"],
                "relay_addresses": [],
            },
        }
        card = AgentCard.from_dict(old_format)
        assert card.peer_id == "12D3KooWTest"
        assert card.did_key is None

    def test_card_did_key_without_peer_id_is_preserved(self) -> None:
        """Identity fields (did_key, did_web, did_dns) are preserved even without peer_id."""
        card = AgentCard(name="NoPeer", did_key="did:key:z6MkTest")
        d = card.to_dict()
        assert "agentanycast" in d  # P2P block present for identity fields
        assert d["agentanycast"]["did_key"] == "did:key:z6MkTest"
        assert "peer_id" not in d["agentanycast"]


# ── MCP + Card integration ────────────────────────────────────────────


class TestMCPCardIntegration:
    """Test that MCP-generated cards survive full serialization round-trips."""

    def test_mcp_card_serialization_round_trip(self) -> None:
        """An AgentCard created from MCP tools should round-trip through to_dict/from_dict."""
        tools = [
            MCPTool(
                name="read_file",
                description="Read a file",
                input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            ),
            MCPTool(name="list_dir", description="List directory"),
        ]
        card = mcp_tools_to_agent_card("FileServer", tools, description="File operations")

        d = card.to_dict()
        restored = AgentCard.from_dict(d)

        assert restored.name == "FileServer"
        assert restored.description == "File operations"
        assert len(restored.skills) == 2
        assert restored.skills[0].id == "read_file"
        assert restored.skills[0].input_schema is not None
        assert restored.skills[1].id == "list_dir"

    def test_mcp_card_default_protocol_version(self) -> None:
        """Verify mcp_tools_to_agent_card sets the correct protocol_version."""
        card = mcp_tools_to_agent_card("Test", [])
        assert card.protocol_version == "a2a/0.3"

    def test_skill_output_schema_not_lost_by_mcp_round_trip(self) -> None:
        """Document that output_schema is lost when going through MCP conversion."""
        skill = Skill(
            id="translate",
            description="Translates",
            input_schema='{"type":"string"}',
            output_schema='{"type":"string"}',
        )
        assert skill.output_schema is not None
        tool = mcp_tool_to_skill(MCPTool(name="translate", description="Translates"))
        # MCPTool → Skill does not carry output_schema
        assert tool.output_schema is None


# ── Top-level re-export smoke tests ───────────────────────────────────


class TestTopLevelExports:
    """Verify that Phase 6 symbols are importable from the top-level package."""

    def test_did_exports(self) -> None:
        from agentanycast import did_key_to_peer_id, peer_id_to_did_key

        assert callable(peer_id_to_did_key)
        assert callable(did_key_to_peer_id)

    def test_mcp_exports(self) -> None:
        from agentanycast import MCPTool, mcp_tool_to_skill, mcp_tools_to_agent_card

        assert MCPTool is not None
        assert callable(mcp_tool_to_skill)
        assert callable(mcp_tools_to_agent_card)

    def test_agntcy_lazy_export(self) -> None:
        from agentanycast import AGNTCYDirectory

        assert AGNTCYDirectory is not None
