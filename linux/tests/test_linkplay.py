"""linkplay: URL encoding exactness, retry logic, status normalization."""

import requests

from radiowall.linkplay import LinkPlay, encode_stream_url


def test_encode_exactly_five_chars():
    url = "https://host.example/path?a=1&b=2"
    assert encode_stream_url(url) == (
        "https%3A%2F%2Fhost.example%2Fpath%3Fa%3D1%26b%3D2")


def test_encode_leaves_other_specials_alone():
    # Space, percent, plus, comma, hash must NOT be touched (ESP32 parity).
    assert encode_stream_url("http://h/a b%20+,#") == "http%3A%2F%2Fh%2Fa b%20+,#"


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text


class _FakeSession:
    """Scripted responses; an Exception instance means 'raise it'."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def get(self, url, timeout=None, verify=None):
        # The command must ride in the URL verbatim (no params= re-encoding).
        self.calls.append(url.split("?command=", 1)[1])
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeResponse(item)


def _wiim(script):
    return LinkPlay("192.0.2.1", session=_FakeSession(script))


def test_ok_on_first_attempt(monkeypatch):
    wiim = _wiim(["OK"])
    assert wiim.stop() is True
    assert wiim._session.calls == ["setPlayerCmd:stop"]


def test_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("radiowall.linkplay.time.sleep", lambda s: None)
    wiim = _wiim([requests.ConnectionError(), "", "OK"])
    assert wiim.stop() is True
    assert len(wiim._session.calls) == 3


def test_all_attempts_fail(monkeypatch):
    monkeypatch.setattr("radiowall.linkplay.time.sleep", lambda s: None)
    wiim = _wiim([requests.Timeout(), requests.Timeout(), requests.Timeout()])
    assert wiim.stop() is False


def test_non_ok_body_is_failure():
    wiim = _wiim(["Unknown Command"])
    assert wiim.stop() is False


def test_play_sends_encoded_url():
    wiim = _wiim(["OK"])
    assert wiim.play("http://a/b?c=d") is True
    assert wiim._session.calls == [
        "setPlayerCmd:play:http%3A%2F%2Fa%2Fb%3Fc%3Dd"]


def test_volume_clamped():
    wiim = _wiim(["OK"])
    wiim.set_volume(150)
    assert wiim._session.calls == ["setPlayerCmd:vol:100"]


def test_status_vol_as_string():
    wiim = _wiim(['{"status":"play","vol":"37"}'])
    assert wiim.get_status()["vol"] == 37


def test_status_vol_as_int():
    wiim = _wiim(['{"vol":55}'])
    assert wiim.get_status()["vol"] == 55


def test_status_unparseable_returns_none():
    wiim = _wiim(["<html>nope</html>", "<html>nope</html>"])
    assert wiim.get_status() is None


def test_get_volume():
    wiim = _wiim(['{"vol":"12"}'])
    assert wiim.get_volume() == 12
