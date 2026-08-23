"""
BlockState JSON Parser & Rule Evaluator.
Matches BlockState properties against 'variants' or 'multipart' definitions.
"""

from __future__ import annotations
import copy
from typing import Any, NamedTuple, Optional


class VariantMatch(NamedTuple):
    model_id: str
    rot_x: float = 0.0
    rot_y: float = 0.0
    uvlock: bool = False
    weight: int = 1


def parse_block_state_string(state_str: str) -> tuple[str, dict[str, str]]:
    """Parse 'minecraft:observer[facing=north,powered=false]' into ('minecraft:observer', {'facing': 'north', 'powered': 'false'})."""
    state_str = state_str.strip()
    if not state_str:
        return ("minecraft:air", {})

    bracket_idx = state_str.find("[")
    if bracket_idx == -1:
        block_id = state_str
        props = {}
    else:
        block_id = state_str[:bracket_idx]
        props_str = state_str[bracket_idx + 1:].rstrip("]")
        props = {}
        if props_str:
            for pair in props_str.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    props[k.strip()] = v.strip()

    if ":" not in block_id:
        block_id = f"minecraft:{block_id}"

    return block_id, props


class BlockStateResolver:
    def __init__(self, blockstate_loader_fn=None):
        self.blockstate_loader_fn = blockstate_loader_fn
        self._state_cache: dict[str, dict[str, Any]] = {}

    def register_blockstate(self, block_id: str, data: dict[str, Any]):
        if not block_id.startswith("minecraft:"):
            block_id = f"minecraft:{block_id}"
        self._state_cache[block_id] = data

    def load_raw_blockstate(self, block_id: str) -> Optional[dict[str, Any]]:
        if not block_id.startswith("minecraft:"):
            block_id = f"minecraft:{block_id}"
        if block_id in self._state_cache:
            return copy.deepcopy(self._state_cache[block_id])

        if self.blockstate_loader_fn:
            data = self.blockstate_loader_fn(block_id)
            if data:
                self._state_cache[block_id] = data
                return copy.deepcopy(data)
        return None

    def resolve_state(self, state_str: str) -> list[VariantMatch]:
        """
        Evaluate blockstate definition and return list of matched model variants to apply.
        """
        block_id, props = parse_block_state_string(state_str)
        raw_state = self.load_raw_blockstate(block_id)
        if not raw_state:
            # Fallback to direct model name
            short_name = block_id.split(":", 1)[-1]
            return [VariantMatch(model_id=f"minecraft:block/{short_name}")]

        # 1. Variants format
        if "variants" in raw_state:
            variants = raw_state["variants"]
            match = self._match_variant(variants, props)
            if match:
                return [match]
            # Fallback to first variant if no exact match
            if "" in variants:
                return [self._parse_variant_entry(variants[""])]
            elif variants:
                first_key = next(iter(variants))
                return [self._parse_variant_entry(variants[first_key])]

        # 2. Multipart format
        if "multipart" in raw_state:
            results = []
            for part in raw_state["multipart"]:
                when = part.get("when")
                apply = part.get("apply")
                if not apply:
                    continue

                if when is None or self._evaluate_multipart_when(when, props):
                    if isinstance(apply, list):
                        # Weighted random variant - take first or highest weight
                        results.append(self._parse_variant_entry(apply[0]))
                    else:
                        results.append(self._parse_variant_entry(apply))
            return results

        short_name = block_id.split(":", 1)[-1]
        return [VariantMatch(model_id=f"minecraft:block/{short_name}")]

    def _match_variant(self, variants: dict[str, Any], props: dict[str, str]) -> Optional[VariantMatch]:
        # Form exact sorted key
        exact_key = ",".join(f"{k}={v}" for k, v in sorted(props.items()))
        if exact_key in variants:
            return self._parse_variant_entry(variants[exact_key])

        # Try permutations or subset matching
        for v_key, v_entry in variants.items():
            if not v_key:
                continue
            v_props = dict(pair.split("=", 1) for pair in v_key.split(",") if "=" in pair)
            if all(props.get(k) == v for k, v in v_props.items()):
                return self._parse_variant_entry(v_entry)

        return None

    def _parse_variant_entry(self, entry: Any) -> VariantMatch:
        if isinstance(entry, list):
            entry = entry[0]
        if isinstance(entry, str):
            return VariantMatch(model_id=entry)
        return VariantMatch(
            model_id=entry.get("model", ""),
            rot_x=float(entry.get("x", 0.0)),
            rot_y=float(entry.get("y", 0.0)),
            uvlock=bool(entry.get("uvlock", False)),
            weight=int(entry.get("weight", 1)),
        )

    def _evaluate_multipart_when(self, when: dict[str, Any], props: dict[str, str]) -> bool:
        if "OR" in when:
            return any(self._evaluate_multipart_when(clause, props) for clause in when["OR"])
        if "AND" in when:
            return all(self._evaluate_multipart_when(clause, props) for clause in when["AND"])

        for prop_name, expected_vals in when.items():
            actual_val = props.get(prop_name)
            expected_list = [v.strip() for v in str(expected_vals).split("|")]
            if actual_val not in expected_list:
                return False
        return True
