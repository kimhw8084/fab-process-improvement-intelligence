"""Confirm a caller-provided macOS sandbox blocks an external socket attempt."""
import errno
import json
import socket
import sys

try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    sock.connect(("198.51.100.1", 80))  # TEST-NET-2 documentation address, never a service target.
except OSError as exc:
    if exc.errno in (errno.EPERM, errno.EACCES):
        print(json.dumps({"status": "DENIED", "errno": exc.errno, "network_access": False}))
        raise SystemExit(0)
    print(json.dumps({"status": "UNVERIFIED", "errno": exc.errno, "reason": str(exc)}))
    raise SystemExit(1)
else:
    sock.close()
    print(json.dumps({"status": "ALLOWED", "network_access": True}))
    raise SystemExit(1)
