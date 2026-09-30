import json
import queue
import shutil
import subprocess
import threading
import time
import tomllib
from environment import ROOT

# Test the real Codex protocol without creating a conversation or invoking a model.
# Default uses temporary CLI overrides; --saved uses the saved user configuration.
import sys
saved = '--saved' in sys.argv
config = tomllib.loads((ROOT / 'codex-fiji.snippet.toml').read_text(encoding='utf-8-sig'))
command = [shutil.which('codex') or r'C:\Users\ethan\AppData\Local\OpenAI\Codex\bin\faa963e871dd422c\codex.exe', 'app-server']
if not saved:
    for key, value in config['mcp_servers']['fiji'].items():
        if isinstance(value, dict):
            for k, v in value.items():
                command += ['-c', f'mcp_servers.fiji.{key}.{k}={json.dumps(v)}']
        else:
            command += ['-c', f'mcp_servers.fiji.{key}={json.dumps(value)}']
# Existing servers remain unchanged on disk; avoid launching unrelated apps in this diagnostic process.
command += ['-c', 'mcp_servers.civ6.enabled=false', '-c', 'mcp_servers.node_repl.enabled=false']
messages = queue.Queue()
with (ROOT / 'codex-probe-stderr.log').open('w', encoding='utf-8') as log:
    proc = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=log, text=True, encoding='utf-8')
    def read():
        for line in proc.stdout:
            try:
                messages.put(json.loads(line))
            except ValueError:
                pass
    threading.Thread(target=read, daemon=True).start()
    def send(message):
        proc.stdin.write(json.dumps(message) + '\n')
        proc.stdin.flush()
    def request(id, method, params, timeout=180):
        send({'id': id, 'method': method, 'params': params})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = messages.get(timeout=min(1, max(0.01, deadline-time.monotonic())))
            except queue.Empty:
                if proc.poll() is not None:
                    raise RuntimeError(f'Codex exited: {proc.returncode}; inspect codex-probe-stderr.log')
                continue
            if message.get('id') == id:
                if 'error' in message:
                    raise RuntimeError(message['error'])
                return message['result']
        raise TimeoutError(method)
    try:
        init = request(1, 'initialize', {'clientInfo': {'name': 'fiji_setup_probe', 'version': '1.0.0'}})
        send({'method': 'initialized', 'params': {}})
        listing = request(2, 'mcpServerStatus/list', {'detail': 'toolsAndAuthOnly', 'limit': 100})
        fiji = next((entry for entry in listing['data'] if entry['name'] == 'fiji'), None)
        result = {'saved_config': saved, 'codex': init, 'fiji': fiji}
        output = ROOT / ('codex-saved-test-result.json' if saved else 'codex-preview-test-result.json')
        output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        assert fiji and len(fiji.get('tools', {})) == 9, result
        print(json.dumps({'passed': True, 'saved_config': saved, 'name': fiji['name'],
                          'tools': list(fiji['tools']), 'connectionStatus': fiji.get('connectionStatus')}, indent=2))
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=10)
