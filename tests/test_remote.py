import io
import json
import socket
import ssl
import time
import urllib.error
import urllib.request
import wave
from concurrent.futures import Future

import numpy as np
import pytest

from aura_whisper.remote import server as remote
from aura_whisper.remote.server import (
    Busy,
    Devices,
    Hooks,
    Pairing,
    PhoneServer,
    decode_wav,
    is_hallucination,
    is_local_address,
)


def _wav(samples: np.ndarray, rate: int = 16_000, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def _done(value) -> Future:
    f: Future = Future()
    if isinstance(value, BaseException):
        f.set_exception(value)
    else:
        f.set_result(value)
    return f


# ---------------------------------------------------------------- units


def test_devices_store_only_a_hash_and_check_the_secret(tmp_path):
    devices = Devices(tmp_path / "devices.json")
    key = devices.add("Pixel")
    device_id, _, secret = key.partition(".")
    stored = (tmp_path / "devices.json").read_text()
    assert secret not in stored
    assert (tmp_path / "devices.json").stat().st_mode & 0o777 == 0o600
    assert devices.check(key)
    assert not devices.check(f"{device_id}.wrong")
    assert not devices.check(device_id)
    assert not devices.check("")
    # Survives a restart.
    assert Devices(tmp_path / "devices.json").check(key)
    devices.clear()
    assert not devices.check(key)


def test_pairing_code_works_once():
    pairing = Pairing()
    code = pairing.new_code()
    assert pairing.consume(code)
    assert not pairing.consume(code)


def test_pairing_code_expires(monkeypatch):
    pairing = Pairing()
    code = pairing.new_code()
    monkeypatch.setattr(remote.time, "time", lambda: pairing.expires + 1)
    assert not pairing.consume(code)


def test_pairing_locks_after_repeated_wrong_codes():
    pairing = Pairing()
    code = pairing.new_code()
    for _ in range(remote.PAIR_MAX_FAILURES):
        assert not pairing.consume("guess")
    assert not pairing.consume(code)


def test_decode_wav_mono_16k():
    tone = 0.5 * np.sin(np.linspace(0, 200 * np.pi, 16_000)).astype(np.float32)
    audio = decode_wav(_wav(tone))
    assert audio.dtype == np.float32 and len(audio) == 16_000
    assert np.max(np.abs(audio - tone)) < 1e-3


def test_decode_wav_downmixes_and_resamples():
    stereo = np.zeros(48_000 * 2, dtype=np.float32)  # 1 s at 48 kHz
    stereo[0::2] = 0.4
    stereo[1::2] = 0.2
    audio = decode_wav(_wav(stereo, rate=48_000, channels=2))
    assert len(audio) == 16_000
    assert np.allclose(audio, 0.3, atol=1e-3)


def test_decode_wav_rejects_garbage():
    with pytest.raises((wave.Error, EOFError, ValueError)):
        decode_wav(b"not a wav")


def test_only_lan_and_loopback_clients():
    for ok in ("192.168.1.20", "10.0.0.5", "172.16.3.4", "127.0.0.1", "::1"):
        assert is_local_address(ok)
    for bad in ("8.8.8.8", "1.1.1.1", "garbage"):
        assert not is_local_address(bad)


def test_hallucinations():
    assert is_hallucination("תודה רבה.")
    assert is_hallucination(" Thank you. ")
    assert not is_hallucination("תודה רבה על העזרה")


# ---------------------------------------------------------------- server


@pytest.fixture
def phone(tmp_path):
    calls = {"audio": [], "approve": True, "result": "שלום עולם"}

    def submit(audio, mode):
        calls["audio"].append((audio, mode))
        return _done(calls["result"])

    hooks = Hooks(
        submit_audio=submit,
        request_approval=lambda name, ip: _done(calls["approve"]),
        mode_names=lambda: ["Cleanup", "Email"],
        ready=lambda: True,
    )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = PhoneServer(hooks, port, data_dir=tmp_path)
    server.start()
    yield server, calls
    server.stop()


def _request(server, path, body=None, headers=None):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        f"https://127.0.0.1:{server.port}{path}",
        data=body,
        headers=headers or {},
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as res:
            return res.status, res.read(), res.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def _pair(server, name="Test phone"):
    code = server.pairing_url().split("#pair=")[1]
    body = json.dumps({"code": code, "name": name}).encode()
    status, data, _ = _request(server, "/api/pair", body, {"Content-Type": "application/json"})
    return status, json.loads(data)


def test_page_is_served_with_security_headers(phone):
    server, _ = phone
    status, body, headers = _request(server, "/")
    assert status == 200
    assert b"AuraWhisper" in body
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    assert headers["X-Frame-Options"] == "DENY"


def test_api_requires_pairing(phone):
    server, calls = phone
    assert _request(server, "/api/status")[0] == 401
    assert _request(server, "/api/status", headers={"X-Device-Key": "x.y"})[0] == 401
    status, _, _ = _request(server, "/api/transcribe", _wav(np.zeros(1600)))
    assert status == 401
    assert calls["audio"] == []


def test_pair_then_dictate(phone):
    server, calls = phone
    status, data = _pair(server)
    assert status == 200
    key = data["key"]
    headers = {"X-Device-Key": key}
    assert json.loads(_request(server, "/api/status", headers=headers)[1]) == {"ready": True}
    modes = json.loads(_request(server, "/api/modes", headers=headers)[1])["modes"]
    assert modes == ["Cleanup", "Email"]

    tone = 0.3 * np.sin(np.linspace(0, 400 * np.pi, 32_000)).astype(np.float32)
    status, body, _ = _request(
        server,
        "/api/transcribe?mode=Email",
        _wav(tone),
        {**headers, "Content-Type": "audio/wav"},
    )
    assert status == 200
    assert json.loads(body) == {"text": "שלום עולם"}
    audio, mode = calls["audio"][0]
    assert mode == "Email" and len(audio) == 32_000


def test_pair_code_cannot_be_reused(phone):
    server, _ = phone
    code = server.pairing_url().split("#pair=")[1]
    body = json.dumps({"code": code, "name": "a"}).encode()
    assert _request(server, "/api/pair", body)[0] == 200
    assert _request(server, "/api/pair", body)[0] == 403


def test_rejected_pairing_issues_no_key(phone):
    server, calls = phone
    calls["approve"] = False
    status, data = _pair(server)
    assert status == 403 and "key" not in data
    assert len(server.devices) == 0


def test_busy_and_errors_reach_the_phone(phone):
    server, calls = phone
    headers = {"X-Device-Key": _pair(server)[1]["key"]}
    calls["result"] = Busy()
    assert _request(server, "/api/transcribe", _wav(np.zeros(1600)), headers)[0] == 409
    calls["result"] = RuntimeError("Ollama is down")
    status, body, _ = _request(server, "/api/transcribe", _wav(np.zeros(1600)), headers)
    assert status == 500 and json.loads(body)["error"] == "Ollama is down"
    assert _request(server, "/api/transcribe", b"garbage", headers)[0] == 400


def test_oversized_upload_is_refused(phone, monkeypatch):
    server, calls = phone
    headers = {"X-Device-Key": _pair(server)[1]["key"]}
    monkeypatch.setattr(remote, "MAX_AUDIO_BYTES", 1000)
    assert _request(server, "/api/transcribe", _wav(np.zeros(16_000)), headers)[0] == 413
    assert calls["audio"] == []


def test_stop_releases_the_port(phone):
    server, _ = phone
    server.stop()
    time.sleep(0.1)
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", server.port))


# ---------------------------------------------------------------- trust


def test_server_cert_is_trusted_through_the_local_ca(phone):
    server, _ = phone
    status, ca_pem, headers = _request(server, "/ca.crt")
    assert status == 200 and b"BEGIN CERTIFICATE" in ca_pem
    assert b"PRIVATE KEY" not in ca_pem
    ctx = ssl.create_default_context(cadata=ca_pem.decode())  # verifies host + chain
    with socket.create_connection(("127.0.0.1", server.port), timeout=5) as raw:
        with ctx.wrap_socket(raw, server_hostname="127.0.0.1") as tls:
            assert tls.version() in ("TLSv1.2", "TLSv1.3")


def test_ca_is_limited_to_lan_addresses(tmp_path):
    import subprocess

    remote.ensure_cert("192.168.1.50", tmp_path)
    text = subprocess.run(
        ["/usr/bin/openssl", "x509", "-in", str(tmp_path / "ca.crt"), "-noout", "-text"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "Name Constraints: critical" in text
    assert "IP:192.168.0.0/255.255.0.0" in text
    assert (tmp_path / "ca.key").stat().st_mode & 0o777 == 0o600


def test_cert_is_reissued_when_the_ip_changes(tmp_path):
    cert, _ = remote.ensure_cert("192.168.1.50", tmp_path)
    first = cert.read_bytes()
    assert remote.ensure_cert("192.168.1.50", tmp_path)[0].read_bytes() == first
    assert remote.ensure_cert("10.0.0.7", tmp_path)[0].read_bytes() != first


# ---------------------------------------------------------------- streaming


@pytest.fixture
def streaming(tmp_path):
    state = {"streams": {}, "next": 0}

    def begin(mode):
        state["next"] += 1
        sid = f"s{state['next']}"
        state["streams"][sid] = {"mode": mode, "chunks": []}
        return _done(sid)

    def chunk(sid, audio):
        if sid not in state["streams"]:
            return _done(remote.StreamGone())
        state["streams"][sid]["chunks"].append(audio)
        return _done(None)

    def end(sid, audio):
        s = state["streams"].pop(sid, None)
        if s is None:
            return _done(remote.StreamGone())
        total = sum(len(c) for c in s["chunks"]) + len(audio)
        return _done(f"{s['mode']}:{len(s['chunks'])}:{total}")

    hooks = Hooks(
        submit_audio=lambda a, m: _done(""),
        request_approval=lambda n, ip: _done(True),
        mode_names=lambda: [],
        ready=lambda: True,
        stream_begin=begin,
        stream_chunk=chunk,
        stream_end=end,
    )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = PhoneServer(hooks, port, data_dir=tmp_path)
    server.start()
    yield server
    server.stop()


def _pcm(n):
    return (0.2 * np.sin(np.arange(n) / 4) * 32767).astype("<i2").tobytes()


def test_live_stream_in_order(streaming):
    server = streaming
    headers = {"X-Device-Key": _pair(server)[1]["key"]}
    status, body, _ = _request(server, "/api/stream/begin?mode=Email", b"", headers)
    assert status == 200
    sid = json.loads(body)["id"]
    for _ in range(3):
        assert _request(server, f"/api/stream/chunk?id={sid}", _pcm(8000), headers)[0] == 200
    status, body, _ = _request(server, f"/api/stream/end?id={sid}", _pcm(1000), headers)
    assert status == 200
    assert json.loads(body)["text"] == "Email:3:25000"
    # The stream is over: late chunks are refused.
    assert _request(server, f"/api/stream/chunk?id={sid}", _pcm(10), headers)[0] == 410


def test_live_stream_requires_pairing(streaming):
    assert _request(streaming, "/api/stream/begin", b"")[0] == 401
    assert _request(streaming, "/api/stream/chunk?id=s1", _pcm(10))[0] == 401


def test_live_stream_chunk_size_limit(streaming):
    headers = {"X-Device-Key": _pair(streaming)[1]["key"]}
    sid = json.loads(_request(streaming, "/api/stream/begin", b"", headers)[1])["id"]
    big = b"\0" * (remote.MAX_CHUNK_BYTES + 2)
    # Refused before the body is read, so the client may see 413 or a reset.
    try:
        status = _request(streaming, f"/api/stream/chunk?id={sid}", big, headers)[0]
    except urllib.error.URLError:
        status = 413
    assert status == 413
