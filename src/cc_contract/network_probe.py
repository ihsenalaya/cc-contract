"""Kind-only bidirectional TCP probe between two indexed job pods."""
import json
import os
import socket
import socketserver
import threading
import time


def main():
    index = int(os.environ["JOB_COMPLETION_INDEX"])
    if index not in {0, 1}:
        raise ValueError("two indexed completions required")
    peer_index = 1 - index
    peer_name = f'{os.environ["CC_JOB_NAME"]}-{peer_index}.{os.environ["CC_SERVICE_NAME"]}.cc-contract.svc.cluster.local'
    received = threading.Event()

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            data = self.request.recv(64)
            if data == f"HELLO:{peer_index}".encode():
                self.request.sendall(f"ACK:{index}".encode())
                received.set()

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

    deadline = time.monotonic() + 45
    with Server(("0.0.0.0", 8080), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        while True:
            try:
                with socket.create_connection((peer_name, 8080), timeout=2) as connection:
                    connection.sendall(f"HELLO:{index}".encode())
                    if connection.recv(64) != f"ACK:{peer_index}".encode():
                        raise ValueError("peer acknowledgement mismatch")
                    peer_ip = connection.getpeername()[0]
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("cross-worker DNS/TCP connection failed")
                time.sleep(0.25)
        if not received.wait(max(0, deadline - time.monotonic())):
            raise TimeoutError("reverse connection missing")
        print(json.dumps({"scope": "KIND_CPU_NETWORK", "index": index, "peer_index": peer_index, "node": os.environ["CC_NODE_NAME"], "peer_dns": peer_name, "peer_ip": peer_ip, "verdict": "PASS", "gpu_executed": False}), flush=True)
        server.shutdown()


if __name__ == "__main__":
    main()
