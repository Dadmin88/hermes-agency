#!/usr/bin/env python3
"""
Hermes Agency Pool Setup Script
Interactive configuration for agency-* profiles only.
Saves to ~/.hermes/agency/config.yaml
"""
import os
import sys
import yaml
from pathlib import Path

AGENCY_PROFILES_DIR = "/home/dadmin/Hermes_Agency/hermes-agency/default_staff/profiles"
CONFIG_DIR = Path.home() / ".hermes" / "agency"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

MODELS = {
    "1": {"model": "gpt-5.5", "provider": "openai"},
    "2": {"model": "grok-4.3", "provider": "xai"},
    "3": {"model": "mimo-v2.5-pro", "provider": "xiaomi"}
}

IMAGE_GENS = {
    "1": {"provider": "openai", "model": "gpt-image-2"},
    "2": {"provider": "xai", "model": "grok-imagine"},
    "3": None
}

CATEGORIES = {
    "engineering": ["agency-frontend-engineer", "agency-backend-engineer", "agency-ai-engineer", "agency-devops-engineer", "agency-data-engineer", "agency-automation-engineer"],
    "design": ["agency-art-director", "agency-brand-designer", "agency-asset-artist", "agency-creative-director", "agency-ui-ux-designer"],
    "management": ["agency-orchestrator", "agency-chief-of-staff", "agency-project-manager"],
    "content": ["agency-copywriter", "agency-content-writer"],
    "quality": ["agency-code-reviewer", "agency-accessibility-reviewer", "agency-compliance-reviewer"],
    "research": ["agency-analytics-specialist", "agency-business-analyst", "agency-competitive-analyst"],
    "marketing": ["agency-community-manager"],
    "business": ["agency-customer-success"],
    # Add remaining as needed for full 83
}

def detect_providers():
    return "OpenAI (gpt-5.5), xAI (grok-4.3), Xiaomi (mimo-v2.5-pro)"

def main():
    print("Welcome to Hermes Agency Setup!")
    print(f"Detected providers: {detect_providers()}")
    print(f"Only agency-* profiles will be configured ({len([d for d in os.listdir(AGENCY_PROFILES_DIR) if d.startswith('agency-')])} agents).")
    print()

    config = {"pool": {"max_active_agents": 10, "idle_timeout_minutes": 5, "port": 8090},
              "models": {"default": {"model": "gpt-5.5", "provider": "openai"}, "groups": {}, "overrides": {}},
              "image_gen": {"provider": "xai", "model": "grok-imagine"}}

    # Step 1: Group assignment (simplified for demo)
    print("Step 1: Assign models by group")
    for cat, agents in CATEGORIES.items():
        print(f"\n{cat.capitalize()} ({len(agents)} agents): {', '.join(agents[:3])}...")
        print("  1) gpt-5.5 (OpenAI)  2) grok-4.3 (xAI)  3) mimo-v2.5-pro (Xiaomi)")
        choice = input(f"  Choose model for {cat} [1]: ").strip() or "1"
        if choice in MODELS:
            config["models"]["groups"][cat] = MODELS[choice]

    # Step 2: Individual overrides (optional, demo)
    print("\nStep 2: Customize individual agents (press Enter to skip)")
    for agent in ["agency-frontend-engineer", "agency-orchestrator"]:
        ans = input(f"  {agent} — change model? [y/N]: ").strip().lower()
        if ans == "y":
            print("    1) gpt-5.5 2) grok-4.3 3) mimo")
            c = input("    > ").strip()
            if c in MODELS:
                config["models"]["overrides"][agent] = MODELS[c]

    # Step 3: Image gen
    print("\nStep 3: Image generation for creative roles")
    print("  1) GPT-Image-2 (OpenAI)  2) Grok Imagine (xAI)  3) None")
    ig = input("  > ").strip() or "2"
    if ig in IMAGE_GENS and IMAGE_GENS[ig]:
        config["image_gen"] = IMAGE_GENS[ig]

    # Step 4: Pool settings
    print("\nStep 4: Pool settings")
    config["pool"]["max_active_agents"] = int(input("  Max active agents [10]: ") or 10)
    config["pool"]["idle_timeout_minutes"] = int(input("  Idle timeout (minutes) [5]: ") or 5)
    config["pool"]["port"] = int(input("  Pool manager port [8090]: ") or 8090)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False)

    print(f"\nSetup complete! Config saved to {CONFIG_FILE}")
    print("Run: python pool/manager.py or start the service.")

if __name__ == "__main__":
    main()