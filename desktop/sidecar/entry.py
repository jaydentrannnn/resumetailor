"""PyInstaller entry script for the desktop sidecar (see `resumetailor.spec`)."""

import socket
import sys

from resume_tailor.infra.desktop_main import main


def _check_vertex_runtime() -> int:
    """Exercise the SDK's lazy tokenizer inside the bundle, without credentials or network."""
    def no_network(*_args, **_kwargs):
        raise RuntimeError("Vertex runtime check must not use the network")

    connect = socket.socket.connect
    socket.socket.connect = no_network
    try:
        from resume_tailor.infra.vertex_catalog import sdk

        sdk()
        from litellm.litellm_core_utils.default_encoding import encoding

        sample = "Vertex AI tokenizer smoke test"
        if encoding.decode(encoding.encode(sample)) != sample:
            raise RuntimeError("Vertex tokenizer round trip failed")
    finally:
        socket.socket.connect = connect
    print("Vertex tokenizer OK")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--check-vertex-runtime"]:
        raise SystemExit(_check_vertex_runtime())
    raise SystemExit(main())
