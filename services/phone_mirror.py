"""
services/phone_mirror.py
Samsung S22 Ultra screen mirror with full touch control.
Auto-reconnect, connection detection, network-ready.
"""

import os
import subprocess
import threading
import time
from typing import Optional


class PhoneMirror:

    def __init__(self, device_ip="100.97.73.38", port=5555):
        self.device_ip = device_ip
        self.port = port
        self.target = f"{device_ip}:{port}"
        self.screen_width = 1080
        self.screen_height = 2340
        self.connected = False
        self.status_msg = "Not connected"
        self._frame = b""
        self._frame_lock = threading.Lock()
        self._capture_thread = None
        self._running = False
        self.adb = self._find_adb()

    def _find_adb(self) -> str:
        """Auto-detect ADB in common locations."""
        candidates = [
            os.environ.get("ADB_PATH", ""),
            r"C:\scrcpy-win64-v3.3.4\adb.exe",
            r"C:\platform-tools\adb.exe",
            r"C:\Users\{}\AppData\Local\Android\Sdk\platform-tools\adb.exe".format(
                os.environ.get("USERNAME", "")
            ),
            r"C:\Android\platform-tools\adb.exe",
            "adb",
        ]
        for path in candidates:
            if not path:
                continue
            try:
                result = subprocess.run(
                    [path, "version"],
                    capture_output=True, timeout=5,
                )
                if result.returncode == 0:
                    return path
            except Exception:
                continue
        return ""

    def connect(self) -> dict:
        """Connect to phone via WiFi ADB. Returns status dict."""
        if not self.adb:
            self.status_msg = "ADB not found. Install from https://developer.android.com/tools/releases/platform-tools"
            return {"ok": False, "msg": self.status_msg}

        try:
            subprocess.run([self.adb, "kill-server"], capture_output=True, timeout=10)
            time.sleep(1)
            subprocess.run([self.adb, "start-server"], capture_output=True, timeout=10)
            time.sleep(1)

            result = subprocess.run(
                [self.adb, "connect", self.target],
                capture_output=True, text=True, timeout=15,
            )
            output = (result.stdout + result.stderr).strip()

            if "connected" in output.lower():
                self.connected = True
                self.status_msg = f"Connected to {self.target}"
                self._start_capture()
                return {"ok": True, "msg": self.status_msg}
            else:
                self.connected = False
                self.status_msg = f"Failed: {output}"
                return {"ok": False, "msg": self.status_msg}

        except Exception as e:
            self.connected = False
            self.status_msg = f"Error: {str(e)}"
            return {"ok": False, "msg": self.status_msg}

    def disconnect(self) -> dict:
        """Disconnect from phone."""
        self._running = False
        self.connected = False
        try:
            subprocess.run([self.adb, "disconnect", self.target], capture_output=True, timeout=10)
        except Exception:
            pass
        self.status_msg = "Disconnected"
        return {"ok": True, "msg": self.status_msg}

    def check_connected(self) -> bool:
        """Verify phone is still reachable."""
        if not self.adb:
            return False
        try:
            result = subprocess.run(
                [self.adb, "devices"],
                capture_output=True, text=True, timeout=10,
            )
            self.connected = self.target in result.stdout
            if not self.connected:
                self.status_msg = "Phone not found. Is WiFi ADB enabled?"
            return self.connected
        except Exception:
            self.connected = False
            return False

    def reconnect(self) -> dict:
        """Force reconnect."""
        self.disconnect()
        time.sleep(1)
        return self.connect()

    def _shell(self, *args):
        """Run ADB shell command (non-blocking)."""
        if not self.connected:
            return
        try:
            subprocess.Popen(
                [self.adb, "-s", self.target, "shell"] + list(args),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    def tap(self, x: int, y: int):
        self._shell("input", "tap", str(x), str(y))

    def swipe(self, x1, y1, x2, y2, duration=300):
        self._shell("input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration))

    def key(self, keycode: str):
        self._shell("input", "keyevent", keycode)

    def text(self, t: str):
        escaped = t.replace(" ", "%s").replace("'", "\\'")
        self._shell("input", "text", escaped)

    def _start_capture(self):
        if self._capture_thread and self._capture_thread.is_alive():
            return
        self._running = True
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

    def _capture_loop(self):
        while self._running and self.connected:
            try:
                result = subprocess.run(
                    [self.adb, "-s", self.target, "exec-out", "screencap", "-p"],
                    capture_output=True, timeout=8,
                )
                if result.returncode == 0 and result.stdout:
                    with self._frame_lock:
                        self._frame = result.stdout
                else:
                    time.sleep(2)
            except Exception:
                time.sleep(2)

    def get_frame(self) -> Optional[bytes]:
        with self._frame_lock:
            return self._frame if self._frame else None

    def mjpeg_generator(self):
        """Yield frames as MJPEG stream."""
        while True:
            frame = self.get_frame()
            if frame:
                yield (b"--frame\r\n"
                       b"Content-Type: image/png\r\n\r\n" +
                       frame + b"\r\n")
            time.sleep(0.1)


def register_phone_routes(app, mirror):
    """Register all phone mirror routes on a Flask app/blueprint."""

    @app.route('/phone-status')
    def phone_status():
        mirror.check_connected()
        return {
            "connected": mirror.connected,
            "msg": mirror.status_msg,
            "device": mirror.target,
            "adb": bool(mirror.adb),
        }

    @app.route('/phone-connect', methods=['POST'])
    def phone_connect():
        result = mirror.reconnect()
        return result

    @app.route('/phone-disconnect', methods=['POST'])
    def phone_disconnect():
        return mirror.disconnect()

    @app.route('/phone-stream')
    def phone_stream():
        if not mirror.connected:
            return "Not connected", 503
        from flask import Response
        return Response(mirror.mjpeg_generator(), mimetype='multipart/x-mixed-replace; boundary=frame')

    @app.route('/phone-tap', methods=['POST'])
    def phone_tap():
        from flask import request, jsonify
        d = request.json or {}
        mirror.tap(int(d.get('x', 0)), int(d.get('y', 0)))
        return jsonify(ok=True)

    @app.route('/phone-swipe', methods=['POST'])
    def phone_swipe():
        from flask import request, jsonify
        d = request.json or {}
        mirror.swipe(
            int(d.get('x1', 0)), int(d.get('y1', 0)),
            int(d.get('x2', 0)), int(d.get('y2', 0)),
            int(d.get('duration', 300)),
        )
        return jsonify(ok=True)

    @app.route('/phone-key', methods=['POST'])
    def phone_key():
        from flask import request, jsonify
        d = request.json or {}
        mirror.key(d.get('key', 'KEYCODE_HOME'))
        return jsonify(ok=True)

    @app.route('/phone-text', methods=['POST'])
    def phone_text():
        from flask import request, jsonify
        d = request.json or {}
        mirror.text(d.get('text', ''))
        return jsonify(ok=True)
