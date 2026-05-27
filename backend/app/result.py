"""Core result type for all external service fetches.

Every client returns one of three honest states — no fallbacks, no invented
values when a service is down.

  OK      service responded, data is valid
  ABSENT  service responded, nothing exists at this location
  FAILED  service error — we have no information
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

T = TypeVar("T")


class FetchStatus(str, Enum):
    OK     = "ok"
    ABSENT = "absent"
    FAILED = "failed"


@dataclass(frozen=True)
class FetchResult(Generic[T]):
    status: FetchStatus
    data:   T | None
    source: str
    error:  str | None = None

    @classmethod
    def ok(cls, data: T, source: str) -> "FetchResult[T]":
        return cls(FetchStatus.OK, data, source)

    @classmethod
    def absent(cls, source: str) -> "FetchResult[T]":
        return cls(FetchStatus.ABSENT, None, source)

    @classmethod
    def failed(cls, error: str, source: str) -> "FetchResult[T]":
        return cls(FetchStatus.FAILED, None, source, error)

    @property
    def is_ok(self) -> bool:
        return self.status == FetchStatus.OK

    @property
    def is_failed(self) -> bool:
        return self.status == FetchStatus.FAILED

    @property
    def is_absent(self) -> bool:
        return self.status == FetchStatus.ABSENT
