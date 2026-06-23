#!/usr/bin/env python3
"""
Hermes Agency Pool CLI
hermes agency pool <command>
"""
import sys
import requests
from manager import PoolManager

pm = PoolManager()
BASE = f"http://localhost:{pm.config['pool']['port']}"

def main():
    if len(sys.argv) < 2:
        print("Usage: hermes agency pool [status|list|wake|sleep|find]")
        return

    cmd = sys.argv[1]
    if cmd == "status":
        print(pm.get_status())
    elif cmd == "list":
        print(list(pm.registry["agents"].keys()))
    elif cmd == "wake" and len(sys.argv) > 2:
        print(pm.wake_agent(sys.argv[2]))
    elif cmd == "sleep" and len(sys.argv) > 2:
        print(pm.sleep_agent(sys.argv[2]))
    elif cmd == "find" and len(sys.argv) > 2:
        skill = sys.argv[2]
        matches = [n for n, a in pm.registry["agents"].items() if skill.lower() in str(a.get("skills", [])).lower()]
        print(matches)
    else:
        print("Unknown command")

if __name__ == "__main__":
    main()