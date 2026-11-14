"""Container healthcheck: ping the simulator socket (not journaled)."""

import json
import os
import socket
import sys

path = os.environ.get("F1SIM_SOCKET", "/run/f1sim/sim.sock")
try:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(2.0)
        conn.connect(path)
        conn.sendall(b'{"cmd":"ping"}\n')
        sys.exit(0 if json.loads(conn.recv(4096).decode("utf-8")).get("ok") else 1)
except Exception:
    sys.exit(1)
