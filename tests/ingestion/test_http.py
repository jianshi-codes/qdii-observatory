from __future__ import annotations

import httpx

from backend.app.ingestion.http import ProviderHttpClient, RetryPolicy


def test_http_client_retries_remote_protocol_disconnects() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.RemoteProtocolError(
                "Server disconnected without sending a response.", request=request
            )
        return httpx.Response(200, json={"ok": True}, request=request)

    with ProviderHttpClient(
        min_interval_seconds=0,
        retry=RetryPolicy(attempts=3, base_delay_seconds=0, max_delay_seconds=0),
        transport=httpx.MockTransport(handler),
    ) as client:
        response = client.request("GET", "https://example.invalid/data")

    assert response.json() == {"ok": True}
    assert calls == 3
