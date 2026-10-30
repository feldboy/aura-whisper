"""HTTPS server that lets a paired phone act as AuraWhisper's microphone.

The phone opens a page served from here, records speech, and uploads it as a
16 kHz WAV. The audio goes through the normal dictation pipeline (Whisper →
optional AI mode → paste into the frontmost Mac app) and the final text is
returned to the phone.

Security model:
- HTTPS only (self-signed cert; browsers only allow the mic over HTTPS).
- Only clients on private/loopback addresses are served.
- Phones must pair: the QR carries a one-time code (URL fragment, never sent
  in a query string) that expires in 5 minutes, and each new phone has to be
  approved on the Mac. Each phone then gets its own random key; only its
  SHA-256 hash is stored on the Mac.
- Request size limits; pairing locks after repeated wrong codes.

Qt-free: the app supplies callbacks (see ``PhoneServer``), which run on the
HTTP threads and must hand work over to the GUI thread themselves.
"""

from __future__ import annotations

import hashlib
import io
import ipaddress
import json
import os
import secrets
import socket
import ssl
import subprocess
import threading
import time
import wave
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

from aura_whisper.config import APP_SUPPORT_DIR

DATA_DIR = APP_SUPPORT_DIR / "remote"
PAGE = Path(__file__).with_name("index.html")
SAMPLE_RATE = 16_000

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # ~13 minutes of 16 kHz mono PCM
MAX_CHUNK_BYTES = 1024 * 1024  # one live-stream chunk (~30 s of PCM)
CHUNK_TIMEOUT_S = 10
PAIR_CODE_TTL = 300
PAIR_MAX_FAILURES = 5
APPROVAL_TIMEOUT_S = 75
# Whisper + an AI mode can take a while; the phone waits for the final text.
RESULT_TIMEOUT_S = 240

# Whisper "hears" these in silence or noise; never paste them on their own.
HALLUCINATIONS = {"תודה רבה", "תודה", "thank you", "thanks for watching", "you"}


def is_hallucination(text: str) -> bool:
    return text.strip().rstrip(".!?, ").lower() in HALLUCINATIONS


class Busy(Exception):
    """The Mac is already recording or processing something."""


class StreamGone(Exception):
    """The live stream was cancelled or timed out on the Mac."""


# ---------------------------------------------------------------- devices


class Devices:
    """Paired phones, persisted as {id: {name, key_sha256, added}}."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        try:
            self.items: dict = json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self.items = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(self.items, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def add(self, name: str) -> str:
        """Register a phone; returns its key ("<id>.<secret>"), shown once."""
        device_id, secret = secrets.token_hex(8), secrets.token_urlsafe(32)
        with self.lock:
            self.items[device_id] = {
                "name": name[:60],
                "key_sha256": hashlib.sha256(secret.encode()).hexdigest(),
                "added": int(time.time()),
            }
            self._save()
        return f"{device_id}.{secret}"

    def check(self, key: str) -> bool:
        device_id, _, secret = key.partition(".")
        with self.lock:
            item = self.items.get(device_id)
        if not item or not secret:
            return False
        digest = hashlib.sha256(secret.encode()).hexdigest()
        return secrets.compare_digest(digest, item["key_sha256"])

    def clear(self) -> None:
        with self.lock:
            self.items = {}
            self._save()

    def __len__(self) -> int:
        return len(self.items)


class Pairing:
    """One active one-time pairing code at a time."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.code: str | None = None
        self.expires = 0.0
        self.failures = 0

    def new_code(self) -> str:
        with self.lock:
            self.code = secrets.token_urlsafe(16)
            self.expires = time.time() + PAIR_CODE_TTL
            self.failures = 0
            return self.code

    def consume(self, code: str) -> bool:
        with self.lock:
            valid = (
                self.code is not None
                and time.time() < self.expires
                and secrets.compare_digest(code, self.code)
            )
            if valid:
                self.code = None
            else:
                self.failures += 1
                if self.failures >= PAIR_MAX_FAILURES:
                    self.code = None  # someone is guessing: kill the code
            return valid


# ---------------------------------------------------------------- system


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def is_local_address(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


OPENSSL = "/usr/bin/openssl"  # absolute: the .app bundle runs with a minimal PATH
CA_NAME = "AuraWhisper Local CA"
# Browsers want leaf certs short-lived; renewed automatically well before.
LEAF_DAYS = 397
LEAF_RENEW_S = 300 * 86400
# The CA can only vouch for LAN/loopback addresses (X.509 name constraints),
# so installing it on the phone can't be abused to impersonate real websites.
CA_NAME_CONSTRAINTS = ",".join(
    [
        "critical",
        "permitted;IP:10.0.0.0/255.0.0.0",
        "permitted;IP:172.16.0.0/255.240.0.0",
        "permitted;IP:192.168.0.0/255.255.0.0",
        "permitted;IP:127.0.0.0/255.0.0.0",
        "permitted;DNS:localhost",
    ]
)


def _openssl(*args: str, cwd: Path | None = None) -> None:
    subprocess.run([OPENSSL, *args], check=True, capture_output=True, cwd=cwd)


def ensure_ca(cert_dir: Path) -> tuple[Path, Path]:
    """The local CA the phone installs once so the page shows as secure."""
    ca_cert, ca_key = cert_dir / "ca.crt", cert_dir / "ca.key"
    if ca_cert.exists() and ca_key.exists():
        return ca_cert, ca_key
    _openssl(
        "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256",
        "-keyout", str(ca_key), "-out", str(ca_cert), "-days", "3650",
        "-subj", f"/CN={CA_NAME}/O=AuraWhisper",
        "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
        "-addext", f"nameConstraints={CA_NAME_CONSTRAINTS}",
    )
    os.chmod(ca_key, 0o600)
    return ca_cert, ca_key


def ensure_cert(ip: str, cert_dir: Path = DATA_DIR / "certs") -> tuple[Path, Path]:
    """Server cert for ``ip`` signed by the local CA; reissued when the LAN
    IP changes or it gets old."""
    cert_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(cert_dir, 0o700)
    ca_cert, ca_key = ensure_ca(cert_dir)
    cert, key = cert_dir / "server.crt", cert_dir / "server.key"
    meta = cert_dir / "server.json"
    try:
        info = json.loads(meta.read_text())
        fresh = info["ip"] == ip and time.time() - info["issued"] < LEAF_RENEW_S
    except (OSError, ValueError, KeyError, TypeError):
        fresh = False
    if fresh and cert.exists() and key.exists():
        return cert, key
    csr, ext = cert_dir / "server.csr", cert_dir / "server.ext"
    ext.write_text(
        f"subjectAltName=IP:{ip},IP:127.0.0.1,DNS:localhost\n"
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n"
    )
    try:
        _openssl(
            "req", "-new", "-newkey", "rsa:2048", "-nodes", "-sha256",
            "-keyout", str(key), "-out", str(csr), "-subj", "/CN=AuraWhisper",
        )
        os.chmod(key, 0o600)
        _openssl(
            "x509", "-req", "-sha256", "-in", str(csr),
            "-CA", str(ca_cert), "-CAkey", str(ca_key),
            "-set_serial", str(secrets.randbits(63)),
            "-days", str(LEAF_DAYS), "-extfile", str(ext), "-out", str(cert),
        )
    finally:
        csr.unlink(missing_ok=True)
        ext.unlink(missing_ok=True)
    meta.write_text(json.dumps({"ip": ip, "issued": int(time.time())}))
    return cert, key


def decode_pcm(data: bytes) -> np.ndarray:
    """Raw 16 kHz mono 16-bit little-endian PCM → float32 in [-1, 1]."""
    usable = len(data) // 2 * 2
    return np.frombuffer(data[:usable], dtype="<i2").astype(np.float32) / 32768.0


def decode_wav(data: bytes) -> np.ndarray:
    """16-bit PCM WAV → 16 kHz mono float32 in [-1, 1]."""
    with wave.open(io.BytesIO(data)) as w:
        if w.getsampwidth() != 2:
            raise ValueError("expected 16-bit PCM WAV")
        channels, rate = w.getnchannels(), w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    audio = pcm.astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio[: len(audio) // channels * channels]
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE and len(audio):
        # The page already resamples to 16 kHz; this only covers odd clients.
        n = round(len(audio) * SAMPLE_RATE / rate)
        audio = np.interp(
            np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio
        ).astype(np.float32)
    return audio


# ---------------------------------------------------------------- http


SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'"
    ),
}


@dataclass
class Hooks:
    """App callbacks; all are called on HTTP threads."""

    # (audio, AI mode name or "") → Future resolving to the delivered text;
    # raise/resolve with Busy when the Mac can't take it right now.
    submit_audio: Callable[[np.ndarray, str], Future]
    # (phone name, ip) → Future resolving to True if the user approved.
    request_approval: Callable[[str, str], Future]
    mode_names: Callable[[], list]
    ready: Callable[[], bool]
    # Called after a phone is paired (e.g. to refresh the pair dialog).
    paired: Callable[[str], None] = lambda name: None
    # Live streaming, so the Mac transcribes while the user is still talking:
    # begin(mode) → Future[stream id]; chunk(id, audio) → Future[None];
    # end(id, last audio) → Future[delivered text]. Unknown id → StreamGone.
    stream_begin: Callable[[str], Future] | None = None
    stream_chunk: Callable[[str, np.ndarray], Future] | None = None
    stream_end: Callable[[str, np.ndarray], Future] | None = None


class _Handler(BaseHTTPRequestHandler):
    server_version = "AuraWhisper"
    sys_version = ""
    timeout = 30  # per socket read; the TLS handshake happens in setup()
    owner: PhoneServer  # set on the per-server subclass

    def setup(self) -> None:
        # The handshake runs here, on the request thread, so one slow or
        # stalled client can't block the accept loop.
        self.request.settimeout(self.timeout)
        self.request.do_handshake()
        super().setup()

    def log_message(self, fmt, *args) -> None:
        pass  # never log paths/headers

    def _send(
        self, status: int, body: bytes, ctype: str, extra: dict | None = None
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json")

    def _local_client(self) -> bool:
        if is_local_address(self.client_address[0]):
            return True
        self._json(403, {"error": "forbidden"})
        return False

    def _authorized(self) -> bool:
        if self.owner.devices.check(self.headers.get("X-Device-Key", "")):
            return True
        self._json(401, {"error": "unpaired"})
        return False

    def _body(self, limit: int) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > limit:
            self.close_connection = True
            self._json(413, {"error": "too large"})
            return None
        return self.rfile.read(length)

    def do_GET(self) -> None:  # noqa: N802
        if not self._local_client():
            return
        path = urlparse(self.path).path
        hooks = self.owner.hooks
        if path == "/":
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif path == "/ca.crt":
            # Public certificate only (never the key): installing it on the
            # phone makes the page trusted.
            # A plain download: Android won't install a CA straight from the
            # browser (the x509 type makes it silently drop the file); the
            # user installs it from Settings instead.
            self._send(
                200,
                (self.owner.data_dir / "certs" / "ca.crt").read_bytes(),
                "application/octet-stream",
                {"Content-Disposition": 'attachment; filename="AuraWhisper-CA.crt"'},
            )
        elif path == "/api/status":
            if self._authorized():
                self._json(200, {"ready": bool(hooks.ready())})
        elif path == "/api/modes":
            if self._authorized():
                self._json(200, {"modes": list(hooks.mode_names())})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._local_client():
            return
        url = urlparse(self.path)
        if url.path == "/api/pair":
            return self._pair()
        if not self._authorized():
            return
        query = parse_qs(url.query)
        mode = query.get("mode", [""])[0][:100]
        stream_id = query.get("id", [""])[0][:64]
        hooks = self.owner.hooks
        if url.path == "/api/transcribe":
            data = self._body(MAX_AUDIO_BYTES)
            if data is None:
                return
            try:
                audio = decode_wav(data)
            except (wave.Error, ValueError, EOFError):
                return self._json(400, {"error": "bad audio"})
            return self._wait(lambda: hooks.submit_audio(audio, mode), "text")
        if hooks.stream_begin is None:
            return self._json(404, {"error": "not found"})
        if url.path == "/api/stream/begin":
            if self._body(0) is not None:
                self._wait(lambda: hooks.stream_begin(mode), "id", CHUNK_TIMEOUT_S)
            return
        if url.path not in ("/api/stream/chunk", "/api/stream/end"):
            return self._json(404, {"error": "not found"})
        end = url.path.endswith("/end")
        data = self._body(MAX_AUDIO_BYTES if end else MAX_CHUNK_BYTES)
        if data is None:
            return
        audio = decode_pcm(data)
        if end:
            self._wait(lambda: hooks.stream_end(stream_id, audio), "text")
        else:
            self._wait(lambda: hooks.stream_chunk(stream_id, audio), "ok", CHUNK_TIMEOUT_S)

    def _wait(self, submit, field: str, timeout: float = RESULT_TIMEOUT_S) -> None:
        """Run an app hook and answer the phone with its result."""
        try:
            value = submit().result(timeout)
        except Busy:
            return self._json(409, {"error": "busy"})
        except StreamGone:
            return self._json(410, {"error": "gone"})
        except FutureTimeout:
            return self._json(504, {"error": "timed out"})
        except Exception as e:  # report to the phone instead of hanging it
            return self._json(500, {"error": str(e) or "failed"})
        self._json(200, {field: True if value is None else value})

    def _pair(self) -> None:
        raw = self._body(2048)
        if raw is None:
            return
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._json(400, {"error": "bad request"})
        if not isinstance(data, dict) or not self.owner.pairing.consume(str(data.get("code", ""))):
            return self._json(403, {"error": "bad code"})
        name = str(data.get("name", "Phone")).strip()[:60] or "Phone"
        try:
            approved = self.owner.hooks.request_approval(
                name, self.client_address[0]
            ).result(APPROVAL_TIMEOUT_S)
        except Exception:
            approved = False
        if not approved:
            return self._json(403, {"error": "rejected"})
        key = self.owner.devices.add(name)
        self.owner.hooks.paired(name)
        self._json(200, {"key": key})


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        pass  # TLS warnings from phones that haven't trusted the cert yet


class PhoneServer:
    """Owns the paired-device store, the pairing code and the HTTPS server."""

    def __init__(self, hooks: Hooks, port: int, data_dir: Path = DATA_DIR) -> None:
        self.hooks = hooks
        self.port = port
        self.data_dir = data_dir
        self.devices = Devices(data_dir / "devices.json")
        self.pairing = Pairing()
        self.ip = ""
        self._httpd: _Server | None = None

    @property
    def running(self) -> bool:
        return self._httpd is not None

    def start(self) -> None:
        """Bind and serve in a daemon thread. Raises OSError if the port is taken."""
        if self._httpd is not None:
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.data_dir, 0o700)
        self.ip = lan_ip()
        cert, key = ensure_cert(self.ip, self.data_dir / "certs")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(cert, key)
        handler = type("Handler", (_Handler,), {"owner": self})
        httpd = _Server(("0.0.0.0", self.port), handler)
        httpd.socket = ctx.wrap_socket(
            httpd.socket, server_side=True, do_handshake_on_connect=False
        )
        threading.Thread(
            target=httpd.serve_forever, name="phone-mic", daemon=True
        ).start()
        self._httpd = httpd

    def stop(self) -> None:
        httpd, self._httpd = self._httpd, None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()

    def pairing_url(self) -> str:
        """A fresh one-time pairing link. The code rides in the fragment, so
        the browser never sends it in a request line or Referer."""
        if self.running and lan_ip() != self.ip:
            # New network/DHCP lease: the cert must name the current IP.
            self.stop()
            self.start()
        return f"https://{self.ip or lan_ip()}:{self.port}/#pair={self.pairing.new_code()}"
