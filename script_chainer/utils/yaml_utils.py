from typing import IO, Any

import yaml

try:
    from yaml import CSafeLoader as SafeLoader
except ImportError:
    from yaml import SafeLoader


def safe_load(stream: str | bytes | IO[str] | IO[bytes]) -> Any:
    """Safely parse YAML via CSafeLoader when available, else SafeLoader."""
    return yaml.load(stream, Loader=SafeLoader)
