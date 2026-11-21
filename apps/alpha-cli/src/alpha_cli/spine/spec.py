"""Frozen public idea vocabulary and its canonical content identity."""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from typing import Annotated, Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    SerializerFunctionWrapHandler,
    Tag,
    model_serializer,
    model_validator,
)

from alpha_cli.spine.owner_rule import OwnerRule
from alpha_core import DataError


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class Rule(FrozenModel):
    kind: str
    fast: int | None = Field(default=None, ge=1)
    slow: int | None = Field(default=None, ge=2)
    window: int | None = Field(default=None, ge=2)
    lookback: int | None = Field(default=None, ge=1)
    skip: int | None = Field(default=None, ge=0)

    @model_validator(mode="before")
    @classmethod
    def check_names(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        names = {
            "ma_cross": ("fast", "slow"),
            "breakout": ("window",),
            "tsmom": ("lookback", "skip"),
        }
        kind = value.get("kind")
        if kind not in names:
            raise ValueError("unknown rule kind; known: ma_cross, breakout, tsmom")
        allowed = names[kind]
        unknown = set(value) - {"kind", *allowed}
        if unknown:
            raise ValueError(f"unknown parameter(s) {sorted(unknown)}; known: {', '.join(allowed)}")
        value = dict(value)
        if kind == "tsmom":
            value.setdefault("skip", 0)
        missing = [key for key in allowed if value.get(key) is None]
        if missing:
            raise ValueError(f"missing rule parameter(s): {', '.join(missing)}")
        if any(isinstance(value[key], bool) for key in allowed):
            raise ValueError("rule parameters must be integers, not booleans")
        return value

    @model_validator(mode="after")
    def check_order(self) -> Self:
        if self.fast is not None and self.slow is not None and self.fast >= self.slow:
            raise ValueError("fast must be less than slow")
        return self

    @property
    def params(self) -> dict[str, int]:
        return {
            key: value
            for key in ("fast", "slow", "window", "lookback", "skip")
            if (value := getattr(self, key)) is not None
        }

    @model_serializer
    def serialize(self) -> dict[str, Any]:
        return {"kind": self.kind, **self.params}

    @property
    def family_key(self) -> str:
        """The ledger family of this rule: the kind itself, as it always was."""
        return self.kind

    @property
    def default_name(self) -> str:
        return "-".join([self.kind, *map(str, self.params.values())])

    @property
    def labels(self) -> tuple[str, ...]:
        return ()

    @property
    def strategy(self) -> str:
        return {"ma_cross": "ma_crossover", "breakout": "breakout", "tsmom": "ts_momentum"}[
            self.kind
        ]


def _rule_tag(value: Any) -> str:
    kind = value.get("kind") if isinstance(value, dict) else getattr(value, "kind", None)
    return "owner" if kind == "owner" else "classic"


AnyRule = Annotated[
    Annotated[Rule, Tag("classic")] | Annotated[OwnerRule, Tag("owner")], Discriminator(_rule_tag)
]


class Costs(FrozenModel):
    fee_bps: float = Field(default=1.0, ge=0)
    slippage_bps: float = Field(default=2.0, ge=0)


class IdeaSpec(FrozenModel):
    name: str = ""
    idea: str = ""
    assets: tuple[Annotated[str, Field(min_length=1)], ...] = Field(min_length=1)
    rule: AnyRule
    costs: Costs = Field(default_factory=Costs)
    # Context gate: `{alias: "series@key"}` and an expression over the aliases. A spec without
    # them dumps without these keys, so its hash, run id and stored spec stay as before. The
    # stored spec keeps the text as written; the hash takes the canonical form (see canonical).
    context: dict[str, str] | None = None
    when: str | None = None
    # A link to an idea card. Excluded from dumps, so it is in no hash, run id or stored spec.
    idea_card: str = Field(default="", exclude=True)

    @model_validator(mode="after")
    def default_name(self) -> Self:
        if not self.name:
            object.__setattr__(self, "name", self.rule.default_name)
        return self

    @model_validator(mode="after")
    def check_gate(self) -> Self:
        if self.context is None and self.when is None:
            return self  # most specs: keep the heavy context code unloaded
        from alpha_cli._context_gate import check_context

        check_context(self.context, self.when)
        return self

    @model_serializer(mode="wrap")
    def omit_absent_gate(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        for key in ("context", "when"):
            if data.get(key) is None:
                data.pop(key, None)
        return data

    def canonical(self) -> str:
        data = self.model_dump(mode="json", exclude_none=True)
        if self.context is not None and self.when is not None:
            # Alias names and spacing are not identity: hash the canonical gate form.
            from alpha_cli._context_gate import canonical_fields

            data.update(canonical_fields(self.context, self.when))
        return json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @property
    def spec_sha256(self) -> str:
        return hashlib.sha256(self.canonical().encode()).hexdigest()


def _resolve_saved(raw: Any, data_dir: Path | None) -> Any:
    """Replace ``rule = {kind = "owner", saved = NAME}`` by the full inline rule, before hashing.

    The saved rule is read once, here, through the reader ``alpha rules`` uses. The spec then holds
    the whole rule, so its hash, its stored copy and its recheck never follow a later edit of NAME.
    """
    rule = raw.get("rule") if isinstance(raw, dict) else None
    if not isinstance(rule, dict) or "saved" not in rule:
        return raw
    name = rule["saved"]
    if rule.get("kind") != "owner" or set(rule) - {"kind", "saved"}:
        raise ValueError(
            f'saved rule {name!r}: write rule = {{kind = "owner", saved = NAME}} with no '
            "other key (an inline [rule.spec] cannot go with saved)"
        )
    if data_dir is None or not isinstance(name, str):
        raise ValueError(f"saved rule {name!r} cannot be read: no saved rules store was given")
    from alpha_cli import rules_cmds

    try:
        text = rules_cmds.load_rule_text(data_dir, name)
        spec = json.loads(text)
        if not isinstance(spec, dict):
            raise ValueError("it is not a rule spec object")
        resolved = OwnerRule(kind="owner", spec=spec)
    except (DataError, ValueError) as exc:
        raise ValueError(f"saved rule {name!r}: {exc}") from exc
    return {**raw, "rule": {"kind": "owner", "spec": resolved.spec}}


def load_spec(
    path: Path | None,
    *,
    rule: str | None = None,
    param: list[str] | None = None,
    asset: list[str] | None = None,
    name: str | None = None,
    idea: str | None = None,
    fee_bps: float | None = None,
    slippage_bps: float | None = None,
    idea_card: str | None = None,
    data_dir: Path | None = None,
) -> IdeaSpec:
    """Read one file or an equivalent complete set of flags, never a silent override.

    ``data_dir`` is the home that holds the saved rules (``alpha rules``); a file may name one.
    """
    if path is not None:
        flags = (rule, param, asset, name, idea, fee_bps, slippage_bps, idea_card)
        if any(value is not None for value in flags):
            raise ValueError("a spec path and rule flags cannot be used together")
        if path.suffix.lower() == ".toml":
            with path.open("rb") as stream:
                return IdeaSpec.model_validate(_resolve_saved(tomllib.load(stream), data_dir))
        if path.suffix.lower() == ".json":
            text = path.read_text(encoding="utf-8")
            raw = json.loads(text)
            resolved = _resolve_saved(raw, data_dir)
            if resolved is raw:
                return IdeaSpec.model_validate_json(text)
            return IdeaSpec.model_validate(resolved)
        raise ValueError("spec file must have .toml or .json suffix")
    if rule == "owner":
        raise ValueError("an owner rule needs a spec file with a [rule.spec] table")
    values: dict[str, Any] = {"kind": rule}
    for item in param or []:
        key, separator, raw = item.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"parameter must be name=value: {item!r}")
        key = key.strip()
        if key in values:
            raise ValueError(f"duplicate parameter {key!r}")
        values[key] = raw
    costs = {
        key: value
        for key, value in {"fee_bps": fee_bps, "slippage_bps": slippage_bps}.items()
        if value is not None
    }
    return IdeaSpec.model_validate(
        {
            "name": name or "",
            "idea": idea or "",
            "idea_card": idea_card or "",
            "assets": asset or [],
            "rule": values,
            "costs": costs,
        }
    )
