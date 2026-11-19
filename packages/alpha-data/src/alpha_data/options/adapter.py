"""The adapter protocol a provider (or the synthetic fixture) implements."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from alpha_data.options.schema import ChainSnapshot, ContractId


@runtime_checkable
class OptionsAdapter(Protocol):
    """Provider-neutral source of option chains. No provider code lives in this package yet."""

    def list_underlyings(self) -> list[str]: ...

    def chain(self, underlying: str, day: date) -> ChainSnapshot: ...

    def contracts(self, underlying: str, start: date, end: date) -> list[ContractId]: ...
