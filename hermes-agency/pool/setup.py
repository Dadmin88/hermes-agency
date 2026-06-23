#!/usr/bin/env python3
"""
Hermes Agency Pool Setup Script
Interactive configuration for agency-* profiles only.
"""

from pathlib import Path

import yaml

AGENCY_DIR = Path("/home/dadmin/.hermes/agency")
CONFIG_PATH = AGENCY_DIR / "config.yaml"
PROVIDERS = {
    "1": {"name": "gpt-5.5", "provider": "openai-codex"},
    "2": {"name": "grok-4.3", "provider": "xai-oauth"},
    "3": {"name": "mimo-v2.5-pro", "provider": "xiaomi"},
}
IMAGE_PROVIDERS = {
    "1": {"name": "GPT-Image-2", "provider": "openai-codex"},
    "2": {"name": "Grok Imagine", "provider": "xai-oauth"},
    "3": {"name": "None", "provider": None},
}

GROUPS = {
    "engineering": [
        "frontend-engineer",
        "backend-engineer",
        "fullstack-engineer",
        "devops-engineer",
        "infrastructure-engineer",
        "database-engineer",
        "data-engineer",
        "integration-engineer",
        "platform-engineer",
        "tools-engineer",
        "performance-engineer",
        "automation-engineer",
        "ai-engineer",
        "godot-engineer",
        "game-designer",
        "level-designer",
        "environment-artist",
        "technical-artist",
    ],
    "design": [
        "art-director",
        "brand-designer",
        "asset-artist",
        "ui-ux-designer",
        "creative-director",
        "design-systems-designer",
        "motion-designer",
        "product-designer",
        "worldbuilder",
        "audio-designer",
    ],
    "management": [
        "orchestrator",
        "project-manager",
        "product-manager",
        "product-strategist",
        "chief-of-staff",
        "operations-manager",
        "scrum-master",
        "traffic-manager",
        "launch-manager",
    ],
    "content": [
        "copywriter",
        "content-writer",
        "technical-writer",
        "docs-writer",
        "dialogue-writer",
        "scriptwriter",
        "lore-writer",
        "editor-in-chief",
        "release-notes-writer",
    ],
    "quality": [
        "qa-lead",
        "qa-tester",
        "code-reviewer",
        "security-reviewer",
        "compliance-reviewer",
        "accessibility-reviewer",
        "red-team",
        "design-reviewer",
    ],
    "security": ["security-engineer", "security-reviewer", "compliance-reviewer", "red-team"],
    "research": [
        "competitive-analyst",
        "market-researcher",
        "user-researcher",
        "analytics-specialist",
        "business-analyst",
        "requirements-analyst",
    ],
    "marketing": [
        "marketing-strategist",
        "growth-marketer",
        "email-marketer",
        "seo-specialist",
        "social-media-manager",
        "public-relations",
        "community-manager",
    ],
    "operations": [
        "devops-engineer",
        "git-steward",
        "release-manager",
        "knowledge-manager",
        "onboarding-specialist",
        "training-specialist",
        "support-specialist",
    ],
    "business": [
        "finance-ops",
        "legal-ops",
        "procurement-specialist",
        "partnerships-manager",
        "customer-success",
        "monetization-strategist",
    ],
}


def detect_providers():
    print("Detected providers: OpenAI (gpt-5.5), xAI (grok-4.3), Xiaomi (mimo-v2.5-pro)")


def choose_model(group_name, agents):
    print(
        f"\n{group_name.title()} ({len(agents)} agents): {', '.join(agents[:5])}{'...' if len(agents) > 5 else ''}"
    )
    print("  Choose model for all in group:")
    for k, v in PROVIDERS.items():
        print(f"    {k}) {v['name']} ({v['provider']})")
    choice = input("  > ").strip() or "1"
    return PROVIDERS.get(choice, PROVIDERS["1"])


def main():
    print("Welcome to Hermes Agency Setup!")
    detect_providers()
    AGENCY_DIR.mkdir(parents=True, exist_ok=True)

    models = {"default": PROVIDERS["1"], "groups": {}, "overrides": {}}
    image_gen = {"provider": None, "model": None}

    # Step 1: Group models
    for group, agents in GROUPS.items():
        model = choose_model(group, agents)
        models["groups"][group] = model

    # Step 2: Individual overrides (simplified)
    print("\nStep 2: Customize individual agents (optional, press Enter to skip)")
    for group, agents in list(GROUPS.items())[:3]:  # demo on first 3 groups
        for agent in agents[:2]:
            full_name = f"agency-{agent}"
            ans = input(f"  {full_name} — change model? [y/N]: ").strip().lower()
            if ans == "y":
                print("    Choose: 1) gpt-5.5 2) grok-4.3 3) mimo-v2.5-pro")
                c = input("    > ").strip() or "1"
                models["overrides"][full_name] = PROVIDERS.get(c, PROVIDERS["1"])

    # Step 3: Image gen
    print("\nStep 3: Image generation for creative roles")
    for k, v in IMAGE_PROVIDERS.items():
        print(f"    {k}) {v['name']}")
    img_choice = input("  > ").strip() or "2"
    img = IMAGE_PROVIDERS.get(img_choice, IMAGE_PROVIDERS["2"])
    if img["provider"]:
        image_gen = {"provider": img["provider"], "model": img["name"].lower().replace(" ", "-")}

    # Step 4: Pool settings
    print("\nStep 4: Pool settings")
    max_active = input("  Max active agents [10]: ").strip() or "10"
    idle = input("  Idle timeout (minutes) [5]: ").strip() or "5"
    port = input("  Pool manager port [8090]: ").strip() or "8090"

    config = {
        "pool": {
            "max_active_agents": int(max_active),
            "idle_timeout_minutes": int(idle),
            "port": int(port),
        },
        "models": models,
        "image_gen": image_gen,
    }

    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False)
    print(f"\nSetup complete! Config saved to {CONFIG_PATH}")


if __name__ == "__main__":
    main()
