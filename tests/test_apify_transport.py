import asyncio
import httpx
from src.services.apify_transport import apify_http_client


def test_apify_uses_operator_proxy_settings(monkeypatch):
    seen={}
    def construct(**kwargs):
        seen.update(kwargs)
        return object()
    monkeypatch.setattr(httpx,'AsyncClient',construct)
    apify_http_client(timeout=10)
    assert seen['trust_env'] is True


def test_injected_transport_stays_local_even_with_system_proxy(monkeypatch):
    monkeypatch.setenv('HTTPS_PROXY','http://127.0.0.1:1')
    requests=[]
    def handler(request):
        requests.append(request.url.host)
        return httpx.Response(200,json={'data':{'status':'SUCCEEDED'}})
    async def run():
        async with apify_http_client(timeout=2,transport=httpx.MockTransport(handler)) as client:
            return (await client.get('https://api.apify.com/v2/actor-builds/test')).status_code
    assert asyncio.run(run())==200
    assert requests==['api.apify.com']
