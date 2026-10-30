from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class FetchResult:
    body: bytes
    received_at: datetime
    content_type: str


class SourceAdapter(Protocol):
    async def fetch(self) -> FetchResult: ...
    async def healthcheck(self) -> bool: ...
