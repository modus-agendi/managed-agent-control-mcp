"""Optional cold-start loader: AWS SSM SecureStrings → environment variables.

Used only by the AWS Lambda deployment, and only when `SSM_PARAM_PREFIX` is set.
Every parameter under the prefix is loaded into `os.environ` (uppercased, with
`-`/`/` → `_`), so secrets like the Anthropic API key and the inbound bearer
token live in SSM rather than plaintext Lambda env vars. A no-op everywhere else
(local, container), keeping those paths free of any AWS dependency.
"""

from __future__ import annotations

import os
from functools import cache


def _env_name(prefix: str, ssm_key: str) -> str:
    relative = ssm_key.removeprefix(prefix).strip("/")
    return relative.upper().replace("-", "_").replace("/", "_")


@cache
def load_credentials_into_env() -> None:
    """Fetch all SSM SecureStrings under SSM_PARAM_PREFIX and populate os.environ.

    Cached so warm Lambda invocations skip the API call. `setdefault` means an
    explicitly-set Lambda env var still wins over SSM.
    """
    prefix = os.environ.get("SSM_PARAM_PREFIX")
    if not prefix:
        return  # local / container / tests — nothing to load

    import boto3  # lazy — only present with the [lambda] extra

    client = boto3.client("ssm")
    paginator = client.get_paginator("get_parameters_by_path")
    for page in paginator.paginate(Path=prefix, Recursive=True, WithDecryption=True):
        for param in page.get("Parameters", []):
            os.environ.setdefault(_env_name(prefix, param["Name"]), param["Value"])
