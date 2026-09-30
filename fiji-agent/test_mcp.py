import asyncio
import json
import sys
from datetime import timedelta
from environment import ROOT, SERVER, configure
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / 'start_fiji_mcp.py')], env=configure(), cwd=str(ROOT))
    with (ROOT / 'mcp-server-stderr.log').open('w', encoding='utf-8') as log:
        async with stdio_client(params, errlog=log) as (reader, writer):
            async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=180)) as session:
                init = await session.initialize()
                listing = await session.list_tools()
                names = [tool.name for tool in listing.tools]
                print('MCP initialized; tools:', names, flush=True)
                assert len(names) == 9 and 'get_state' in names
                state = await session.call_tool('get_state', {})
                data = state.model_dump(mode='json')
                print(json.dumps(data, indent=2), flush=True)
                assert not state.isError, data
                texts = [json.loads(c.text) for c in state.content if c.type == 'text']
                assert texts and all(t.get('ok', True) for t in texts), texts
                result = {'passed': True, 'server': init.serverInfo.model_dump(mode='json'),
                          'executable': str(SERVER), 'tools': names, 'state': data}
                (ROOT / 'mcp-test-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')

if __name__ == '__main__':
    asyncio.run(main())

