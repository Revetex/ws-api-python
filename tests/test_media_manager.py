import time

from wsapp_gui.media_manager import MediaManager


class DummyResp:
    def __init__(self, status=200, content=b''):
        self.status_code = status
        self.content = content
        self.headers = {'content-type': 'image/png'}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("http error")


def test_logo_caching(monkeypatch):
    calls = {"count": 0}

    def fake_get(url, timeout=5):  # noqa: ARG001
        calls["count"] += 1
        # return small valid PNG (1x1 transparent)
        return DummyResp(200, b"\x89PNG\r\n\x1a\n")

    # patch HTTP client used by MediaManager
    import utils.http_client as http_client

    class DummyHTTP:
        def get(self, url, params=None):  # noqa: ARG002
            return fake_get(url)

    monkeypatch.setattr(http_client, 'HTTPClient', lambda **kw: DummyHTTP())

    mm = MediaManager(ttl_sec=9999)

    results = []

    def cb(img):
        results.append(img)

    mm.get_logo_async('TEST', cb)
    # wait for thread
    timeout = time.time() + 2
    while not results and time.time() < timeout:
        time.sleep(0.05)

    assert results, "Callback not invoked"
    assert calls["count"] == 1

    # second call should hit cache (no extra request)
    mm.get_logo_async('TEST', cb)
    timeout = time.time() + 2
    while len(results) < 2 and time.time() < timeout:
        time.sleep(0.05)

    assert calls["count"] == 1, "Expected cached image reuse"
    assert len(results) >= 2
