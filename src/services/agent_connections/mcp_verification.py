"""Bounded read-only validation shared by host setup and the operator CLI."""
import asyncio


async def check_mcp(manifest, token, *, transport=None):
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    async with asyncio.timeout(40):
        async with httpx.AsyncClient(transport=transport, headers={'Authorization': 'Bearer ' + token},
                                     timeout=30, follow_redirects=False) as client:
            async with streamable_http_client(manifest['mcp_url'], http_client=client,
                                               terminate_on_close=False) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = {tool.name for tool in tools.tools}
                    # MCP discovery is global; each invocation enforces delegation scopes.
                    # The managed Agent independently restricts its tools to this manifest.
                    if not set(manifest['tools']) <= names or any(
                            not tool.annotations or tool.annotations.readOnlyHint is not True
                            for tool in tools.tools if tool.name in manifest['tools']):
                        raise ValueError('MCP tools differ from personal read-only policy')
                    result = await session.call_tool('list_subscriptions', {})
                    if result.isError:
                        raise ValueError('Personal MCP read failed')
