"""Run only after explicit approval to modify the user's global Codex config."""
from datetime import datetime
from pathlib import Path
import hashlib
import json
import tomllib

ROOT = Path(__file__).resolve().parent
config_path = Path(r'C:\Users\ethan\.codex\config.toml')
original = config_path.read_bytes()
old = tomllib.loads(original.decode('utf-8-sig'))
assert 'fiji' not in old.get('mcp_servers', {}), 'Fiji entry already exists; inspect before changing it.'
snippet = (ROOT / 'codex-fiji.snippet.toml').read_text(encoding='utf-8-sig')
candidate = original + b'\n\n' + snippet.encode('utf-8')
parsed = tomllib.loads(candidate.decode('utf-8-sig'))
expected_fiji = parsed['mcp_servers'].pop('fiji')
if 'mcp_servers' not in old:
    parsed.pop('mcp_servers')
assert parsed == old, 'Refusing to change existing configuration.'
backup = config_path.with_name('config.toml.before-fiji-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.bak')
with backup.open('xb') as stream:
    stream.write(original)
assert config_path.read_bytes() == original, 'Config changed concurrently; inspect and retry.'
with config_path.open('ab') as stream:
    stream.write(b'\n\n' + snippet.encode('utf-8'))
assert config_path.read_bytes() == candidate
result = {'config': str(config_path), 'backup': str(backup), 'existing_settings_preserved': True,
          'original_sha256': hashlib.sha256(original).hexdigest(), 'fiji': expected_fiji}
(ROOT / 'config-install-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result, indent=2))
