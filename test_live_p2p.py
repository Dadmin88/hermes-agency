#!/usr/bin/env python3
"""Live A2P test: katana sends to gpt via plugin NodeManager, Discord notifications fire."""
import sys, os, asyncio, time, types, importlib

plugin_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hermes-plugin')
hermes_dir = os.path.expanduser('~/.hermes/hermes-agent')
sys.path.insert(0, plugin_dir)
sys.path.insert(0, hermes_dir)

os.environ['AGENTANYCAST_REGISTRY_ADDRS'] = '100.123.57.115:50052'

# Patch relative imports in node_manager before importing
import node_manager
# Already loaded with relative imports resolved by the package structure

from node_manager import NodeManager

RELAY = '/ip4/100.123.57.115/tcp/4001/p2p/12D3KooWGE3zmqw2FJTyuNGAzSNCUxSNSeMvCtocULczXfX9Y8nK'

async def main():
    # gpt
    os.environ['HERMES_HOME'] = os.path.expanduser('~/.hermes/profiles/gpt')
    gpt_mgr = NodeManager()
    gpt_state = gpt_mgr.start_sync(timeout=30)
    print(f'[1] gpt started: {gpt_state.peer_id[:20]}...')

    # katana
    os.environ['HERMES_HOME'] = os.path.expanduser('~/.hermes/profiles/katana')
    katana_mgr = NodeManager()
    katana_state = katana_mgr.start_sync(timeout=30)
    print(f'[2] katana started: {katana_state.peer_id[:20]}...')

    for i in range(10):
        peers = katana_mgr.list_peers_sync()
        if peers:
            print(f'[3] Found {len(peers)} peer(s)')
            break
        time.sleep(1)

    print('[4] Sending katana → gpt...')
    result = katana_mgr.send_task_sync(
        message='Hey GPT! Live from Katana via A2A plugin with Discord notifications!',
        peer_id=gpt_state.peer_id,
        wait_seconds=10,
    )
    print(f'[5] Status: {result.get("status", "?")}')
    print(f'[6] Response: {result.get("artifact_text", "")[:100]}')
    print('[7] Check Discord #general!')

    katana_mgr.stop_sync()
    gpt_mgr.stop_sync()

asyncio.run(main())
