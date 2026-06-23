#!/usr/bin/env python3
"""
Hermes Agency Pool CLI
hermes agency pool <command>
"""

import argparse
import requests
from manager import PoolManager

pm = PoolManager()
BASE = f"http://localhost:{pm.config['pool']['port']}"

def status():
    try:
        r = requests.get(f"{BASE}/pool/status")
        print(r.json())
    except:
        print(pm.get_status())

def list_agents():
    try:
        r = requests.get(f"{BASE}/pool/agents")
        print(r.json())
    except:
        print("Active:", list(pm.active_agents.keys()))

def wake(agent):
    r = requests.post(f"{BASE}/pool/agents/{agent}/wake")
    print(r.json())

def sleep(agent):
    r = requests.post(f"{BASE}/pool/agents/{agent}/sleep")
    print(r.json())

def find(skill):
    matches = [name for name, data in pm.registry.items() 
               if skill.lower() in str(data.get("skills", [])).lower()]
    print(matches[:10])

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("status")
    sub.add_parser("list")
    p = sub.add_parser("wake"); p.add_argument("agent")
    p = sub.add_parser("sleep"); p.add_argument("agent")
    p = sub.add_parser("find"); p.add_argument("skill")
    args = parser.parse_args()
    
    if args.cmd == "status": status()
    elif args.cmd == "list": list_agents()
    elif args.cmd == "wake": wake(args.agent)
    elif args.cmd == "sleep": sleep(args.agent)
    elif args.cmd == "find": find(args.skill)
    else: parser.print_help()