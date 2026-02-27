from datetime import datetime, timezone
from uuid import uuid4


def prefixed_id(prefix: str) -> str:
    ts = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    suffix = uuid4().hex[:10]
    return f'{prefix}_{ts}_{suffix}'
