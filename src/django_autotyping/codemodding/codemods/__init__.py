from __future__ import annotations

from typing import TypeAlias

__all__ = ("ForwardRelationTypingCodemod", "RulesT", "gather_codemods", "rules")

from collections.abc import Container
from typing import Literal

from .base import BaseVisitorBasedCodemod
from .forward_relation_typing_codemod import ForwardRelationTypingCodemod

RulesT: TypeAlias = Literal["DJA001"]

rules: list[tuple[RulesT, type[BaseVisitorBasedCodemod]]] = [
    ("DJA001", ForwardRelationTypingCodemod),
]


def gather_codemods(
    ignore: Container[RulesT] = [], include: Container[RulesT] = []
) -> list[type[BaseVisitorBasedCodemod]]:
    if include:
        return [rule[1] for rule in rules if rule[0] in include]
    return [rule[1] for rule in rules if rule[0] not in ignore]
