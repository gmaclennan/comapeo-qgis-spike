"""QLocalSocket client for the spike. Reads SPIKE_PATH / SPIKE_NAME from the
environment (set by run.js). Exits non-zero if the full-path form fails."""

import hashlib
import json
import os
import struct
import sys
import time

binding = None
import_errors = []
for candidate in ("qgis.PyQt", "PyQt6", "PyQt5"):
    try:
        if candidate == "qgis.PyQt":
            from qgis.PyQt.QtCore import (
                PYQT_VERSION_STR,
                QT_VERSION_STR,
                QCoreApplication,
                QTimer,
            )
            from qgis.PyQt.QtNetwork import QLocalSocket
        elif candidate == "PyQt6":
            from PyQt6.QtCore import (
                PYQT_VERSION_STR,
                QT_VERSION_STR,
                QCoreApplication,
                QTimer,
            )
            from PyQt6.QtNetwork import QLocalSocket
        else:
            from PyQt5.QtCore import (
                PYQT_VERSION_STR,
                QT_VERSION_STR,
                QCoreApplication,
                QTimer,
            )
            from PyQt5.QtNetwork import QLocalSocket
        binding = candidate
        break
    except ImportError as exc:
        import_errors.append("%s: %s" % (candidate, exc))

if binding is None:
    print("FAIL: no Qt binding importable: %s" % "; ".join(import_errors))
    sys.exit(1)

BIG_SIZE = 1024 * 1024
SESSION_TIMEOUT_MS = 30000
ERROR_NAMES = [
    "ConnectionRefusedError",
    "PeerClosedError",
    "ServerNotFoundError",
    "SocketAccessError",
    "SocketResourceError",
    "SocketTimeoutError",
    "DatagramTooLargeError",
    "ConnectionError",
    "UnsupportedSocketOperationError",
    "UnknownSocketError",
    "OperationError",
]


def log(msg):
    print(msg, flush=True)


def enum_member(owner, enum_name, member):
    scoped = getattr(owner, enum_name, None)
    if scoped is not None and hasattr(scoped, member):
        return getattr(scoped, member)
    return getattr(owner, member)


def error_name(code):
    for name in ERROR_NAMES:
        try:
            if enum_member(QLocalSocket, "LocalSocketError", name) == code:
                return name
        except AttributeError:
            pass
    return repr(code)


def connect_error_signal(sock, handler):
    if hasattr(sock, "errorOccurred"):
        sock.errorOccurred.connect(handler)
        return "errorOccurred"
    sock.error.connect(handler)
    return "error"


def encode_frame(msg):
    body = json.dumps(msg).encode("utf-8")
    return struct.pack("<I", len(body)) + body


CONNECTED_STATE = enum_member(QLocalSocket, "LocalSocketState", "ConnectedState")


class Session:
    """Runs the full protocol over one fresh connection."""

    def __init__(self, label, server_name, on_done):
        self.label = label
        self.server_name = server_name
        self.on_done = on_done
        self.buffer = b""
        self.phase = "connecting"
        self.finished = False
        self.connected_seen = False
        self.write_count = 0
        self.ready_reads = 0
        self.max_chunk = 0
        self.errors_seen = []
        self.events = []
        self.sub_sent_at = 0.0
        self.sub_delay_ms = 0
        self.writes_at_sub = 0
        self.big_hash = ""
        self.notes = []
        self.sock = QLocalSocket()
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.on_timeout)

    def start(self):
        log("--- [%s] connectToServer(%r)" % (self.label, self.server_name))
        self.sock.connected.connect(self.on_connected)
        self.sock.readyRead.connect(self.on_ready_read)
        self.sock.disconnected.connect(self.on_disconnected)
        self.error_signal = connect_error_signal(self.sock, self.on_error)
        self.timer.start(SESSION_TIMEOUT_MS)
        self.t0 = time.monotonic()
        self.sock.connectToServer(self.server_name)
        if not self.connected_seen and self.sock.state() == CONNECTED_STATE:
            self.notes.append("connected state reached without connected signal")
            self.on_connected()

    def finish(self, ok, msg):
        if self.finished:
            return
        self.finished = True
        self.timer.stop()
        self.sock.abort()
        summary = "%s; error signals: %s; readyRead calls: %d; max chunk: %d" % (
            msg,
            self.errors_seen or "none",
            self.ready_reads,
            self.max_chunk,
        )
        if self.notes:
            summary += "; notes: %s" % self.notes
        self.on_done(self.label, ok, summary)

    def send(self, msg):
        frame = encode_frame(msg)
        written = self.sock.write(frame)
        self.write_count += 1
        if written != len(frame):
            self.finish(False, "write() accepted %d of %d bytes" % (written, len(frame)))

    def on_timeout(self):
        self.finish(False, "timed out in phase %r" % self.phase)

    def on_error(self, code):
        name = error_name(code)
        self.errors_seen.append(name)
        log("[%s] error signal: %s (%s)" % (self.label, name, self.sock.errorString()))
        # A server-side close is reported as PeerClosedError before `disconnected`.
        if not (self.phase.startswith("bye") and name == "PeerClosedError"):
            self.finish(False, "socket error %s in phase %r" % (name, self.phase))

    def on_connected(self):
        if self.connected_seen:
            return
        self.connected_seen = True
        log(
            "[%s] connected in %.0f ms; fullServerName=%r"
            % (
                self.label,
                (time.monotonic() - self.t0) * 1000,
                self.sock.fullServerName(),
            )
        )
        self.phase = "echo"
        self.send({"hello": "wörld", "n": 1})

    def on_disconnected(self):
        log("[%s] disconnected signal in phase %r" % (self.label, self.phase))
        if self.phase == "bye-wait-disconnect":
            self.finish(True, "all checks passed")
        elif self.phase != "bye":
            self.finish(False, "unexpected disconnect in phase %r" % self.phase)
        else:
            self.phase = "bye-disconnected-early"

    def on_ready_read(self):
        chunk = self.sock.readAll().data()
        self.ready_reads += 1
        self.max_chunk = max(self.max_chunk, len(chunk))
        self.buffer += chunk
        while len(self.buffer) >= 4 and not self.finished:
            (length,) = struct.unpack("<I", self.buffer[:4])
            if len(self.buffer) < 4 + length:
                break
            body = self.buffer[4 : 4 + length]
            self.buffer = self.buffer[4 + length :]
            try:
                self.on_frame(json.loads(body.decode("utf-8")))
            except Exception as exc:
                self.finish(False, "frame handling failed in %r: %r" % (self.phase, exc))

    def subscribe(self, delay_ms):
        self.events = []
        self.sub_delay_ms = delay_ms
        self.sub_sent_at = time.monotonic()
        self.send({"subscribe": True, "delayMs": delay_ms})
        self.writes_at_sub = self.write_count

    def on_frame(self, msg):
        if self.phase == "echo":
            assert msg == {"echo": {"hello": "wörld", "n": 1}}, "bad echo: %r" % msg
            log("[%s] echo OK" % self.label)
            self.phase = "big"
            payload = (os.urandom(BIG_SIZE // 2).hex())[:BIG_SIZE]
            self.big_hash = hashlib.sha256(payload.encode()).hexdigest()
            reads_before = self.ready_reads
            self.reads_before_big = reads_before
            self.send({"big": payload})
            log(
                "[%s] big frame queued; bytesToWrite=%d"
                % (self.label, self.sock.bytesToWrite())
            )
        elif self.phase == "big":
            got = msg["echo"]["big"]
            assert len(got) == BIG_SIZE, "big length %d" % len(got)
            assert hashlib.sha256(got.encode()).hexdigest() == self.big_hash, "big hash"
            log(
                "[%s] 1 MB round trip OK (arrived over %d readyRead calls)"
                % (self.label, self.ready_reads - self.reads_before_big)
            )
            self.phase = "push-500"
            self.subscribe(500)
        elif self.phase in ("push-500", "push-3000"):
            if "echo" in msg:
                assert msg["echo"].get("subscribe") is True, "bad sub ack: %r" % msg
                return
            elapsed_ms = (time.monotonic() - self.sub_sent_at) * 1000
            self.events.append(msg["event"])
            assert self.write_count == self.writes_at_sub, "client wrote while idle"
            if len(self.events) == 1:
                assert elapsed_ms >= self.sub_delay_ms - 100, (
                    "first push too early: %.0f ms" % elapsed_ms
                )
                log(
                    "[%s] first push after %.0f ms idle (requested %d)"
                    % (self.label, elapsed_ms, self.sub_delay_ms)
                )
            if len(self.events) == 3:
                assert self.events == [1, 2, 3], "bad events: %r" % self.events
                log("[%s] 3 pushed events OK (%s)" % (self.label, self.phase))
                if self.phase == "push-500":
                    self.phase = "push-3000"
                    self.subscribe(3000)
                else:
                    self.phase = "bye"
                    self.send({"bye": True})
        elif self.phase in ("bye", "bye-disconnected-early"):
            assert msg == {"echo": {"bye": True}}, "bad bye echo: %r" % msg
            if self.phase == "bye-disconnected-early":
                self.finish(True, "all checks passed")
            else:
                self.phase = "bye-wait-disconnect"
        else:
            raise AssertionError("unexpected frame in phase %r" % self.phase)


class MissingServerTest:
    """Connecting to a path nobody listens on must error promptly."""

    def __init__(self, label, server_name, on_done):
        self.label = label
        self.server_name = server_name
        self.on_done = on_done
        self.finished = False
        self.sock = QLocalSocket()
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(
            lambda: self.finish(False, "no error within 5 s (would hang)")
        )

    def start(self):
        log("--- [%s] connectToServer(%r)" % (self.label, self.server_name))
        self.sock.connected.connect(
            lambda: self.finish(False, "unexpectedly connected")
        )
        connect_error_signal(self.sock, self.on_error)
        self.timer.start(5000)
        self.t0 = time.monotonic()
        self.sock.connectToServer(self.server_name)

    def on_error(self, code):
        elapsed_ms = (time.monotonic() - self.t0) * 1000
        self.finish(
            True,
            "error %s after %.0f ms (%s)"
            % (error_name(code), elapsed_ms, self.sock.errorString()),
        )

    def finish(self, ok, msg):
        if self.finished:
            return
        self.finished = True
        self.timer.stop()
        self.sock.abort()
        self.on_done(self.label, ok, msg)


def main():
    full_path = os.environ["SPIKE_PATH"]
    bare_name = os.environ["SPIKE_NAME"]
    expected = os.environ.get("SPIKE_EXPECT_BINDING")
    expected_qt_major = os.environ.get("SPIKE_EXPECT_QT_MAJOR")

    app = QCoreApplication(sys.argv)
    probe = QLocalSocket()
    log("binding: %s" % binding)
    log("Qt: %s  PyQt: %s" % (QT_VERSION_STR, PYQT_VERSION_STR))
    log("Python: %s" % sys.version.replace("\n", " "))
    log("platform: %s" % sys.platform)
    log(
        "enum access: scoped=%s unscoped=%s"
        % (
            hasattr(getattr(QLocalSocket, "LocalSocketState", None), "ConnectedState"),
            hasattr(QLocalSocket, "ConnectedState"),
        )
    )
    log(
        "signals: errorOccurred=%s error=%s; exec=%s exec_=%s"
        % (
            hasattr(probe, "errorOccurred"),
            hasattr(probe, "error"),
            hasattr(app, "exec"),
            hasattr(app, "exec_"),
        )
    )
    log("SPIKE_PATH=%r (%d bytes)" % (full_path, len(full_path.encode("utf-8"))))

    if expected and binding != expected:
        log("FAIL: expected binding %s but imported %s" % (expected, binding))
        return 1
    if expected_qt_major and QT_VERSION_STR.split(".")[0] != expected_qt_major:
        log("FAIL: expected Qt %s but got %s" % (expected_qt_major, QT_VERSION_STR))
        return 1

    results = []
    state = {"current": None}
    queue = [
        lambda done: Session("full-path", full_path, done),
        lambda done: Session("bare-name", bare_name, done),
        lambda done: MissingServerTest("missing-server", full_path + "-nope", done),
    ]

    def run_next():
        if not queue:
            app.quit()
            return
        state["current"] = queue.pop(0)(on_done)
        state["current"].start()

    def on_done(label, ok, msg):
        log("RESULT %s: %s - %s" % (label, "PASS" if ok else "FAIL", msg))
        results.append((label, ok, msg))
        QTimer.singleShot(0, run_next)

    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(lambda: (log("FAIL: global watchdog fired"), app.exit(3)))
    watchdog.start(120000)

    QTimer.singleShot(0, run_next)
    run_loop = getattr(app, "exec", None) or app.exec_
    code = run_loop()
    if code:
        return code

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(
                "**%s** Qt %s, PyQt %s, Python %s, %s\n\n"
                % (
                    binding,
                    QT_VERSION_STR,
                    PYQT_VERSION_STR,
                    sys.version.split()[0],
                    sys.platform,
                )
            )
            for label, ok, msg in results:
                fh.write("- %s: %s - %s\n" % (label, "PASS" if ok else "FAIL", msg))
            fh.write("\n")

    required = {"full-path", "missing-server"}
    failed = [label for label, ok, _ in results if not ok and label in required]
    if failed:
        log("FAIL: required checks failed: %s" % ", ".join(failed))
        return 1
    log("OK: required checks passed (bare-name is informational)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
