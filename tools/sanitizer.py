"""Build a ``sanitize_fn`` callable backed by this project's map file.

Plugs `_local/sanitize-map.yml` into :class:`virtuoso_bridge.SanitizingClient`.

Usage::

    from virtuoso_bridge import VirtuosoClient, SanitizingClient
    from tools.sanitizer import get_sanitize_fn

    client = SanitizingClient(VirtuosoClient.from_env(), get_sanitize_fn())
    client.download_file(remote, "output/netlists/foo.scs")
    # -> output/netlists/foo.scs              (raw)
    # -> output/netlists/sanitized/foo.scs    (redacted)
"""

from __future__ import annotations

from pathlib import Path

from tools.sanitize_snapshot import load_token_map, sanitize_text


_MAP_PATH = Path(__file__).resolve().parents[1] / "_local" / "sanitize-map.yml"


def get_sanitize_fn(map_path: Path | str | None = None):
    """Return a ``str -> str`` callable that applies the project's map."""
    tokens = load_token_map(Path(map_path) if map_path else _MAP_PATH)
    def _apply(text: str) -> str:
        return sanitize_text(text, tokens)[0]
    return _apply
