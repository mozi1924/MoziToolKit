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
    variant_props: Optional[dict[str, str]] = None


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
            # Fallback to direct model name with directional/facing rotation heuristic
            short_name = block_id.split(":", 1)[-1]
            facing = props.get("facing")
            axis = props.get("axis")
            rot_y = 0.0
            rot_x = 0.0

            if short_name == "bell":
                attachment = props.get("attachment", "floor")
                facing = props.get("facing", "north")
                if attachment == "floor":
                    rot_y = {"north": 0.0, "east": 90.0, "south": 180.0, "west": 270.0}.get(facing, 0.0)
                    return [VariantMatch(model_id="minecraft:block/bell_floor", rot_y=rot_y, variant_props=props)]
                elif attachment == "ceiling":
                    rot_y = {"north": 0.0, "east": 90.0, "south": 180.0, "west": 270.0}.get(facing, 0.0)
                    return [VariantMatch(model_id="minecraft:block/bell_ceiling", rot_y=rot_y, variant_props=props)]
                elif attachment == "single_wall":
                    rot_y = {"east": 0.0, "south": 90.0, "west": 180.0, "north": 270.0}.get(facing, 0.0)
                    return [VariantMatch(model_id="minecraft:block/bell_wall", rot_y=rot_y, variant_props=props)]
                elif attachment == "double_wall":
                    rot_y = {"east": 0.0, "south": 90.0, "west": 180.0, "north": 270.0}.get(facing, 0.0)
                    return [VariantMatch(model_id="minecraft:block/bell_between_walls", rot_y=rot_y, variant_props=props)]

            if "glazed_terracotta" in short_name:
                rot_y = {"south": 0.0, "west": 90.0, "north": 180.0, "east": 270.0}.get(facing, 0.0)
            elif short_name in ("dispenser", "dropper"):
                if facing == "up":
                    return [VariantMatch(model_id=f"minecraft:block/{short_name}_vertical", rot_x=0.0, rot_y=0.0, variant_props={"facing": "up"})]
                elif facing == "down":
                    return [VariantMatch(model_id=f"minecraft:block/{short_name}_vertical", rot_x=180.0, rot_y=0.0, variant_props={"facing": "down"})]
                else:
                    rot_y = {"north": 0.0, "east": 90.0, "south": 180.0, "west": 270.0}.get(facing, 0.0)
                    return [VariantMatch(model_id=f"minecraft:block/{short_name}", rot_x=0.0, rot_y=rot_y, variant_props={"facing": facing or "north"})]
            elif short_name == "barrel":
                # Vertical-base blocks (unrotated model points UP at +Y)
                if facing == "down":
                    rot_x = 180.0
                elif facing == "north":
                    rot_x = 90.0
                elif facing == "south":
                    rot_x = 90.0
                    rot_y = 180.0
                elif facing == "east":
                    rot_x = 90.0
                    rot_y = 90.0
                elif facing == "west":
                    rot_x = 90.0
                    rot_y = 270.0
            elif axis:
                if axis == "x":
                    rot_x = 90.0
                    rot_y = 90.0
                elif axis == "z":
                    rot_x = 90.0
            elif facing:
                rot_y = {"north": 0.0, "east": 90.0, "south": 180.0, "west": 270.0}.get(facing, 0.0)
                if facing == "up":
                    rot_x = 270.0
                elif facing == "down":
                    rot_x = 90.0
            return [VariantMatch(model_id=f"minecraft:block/{short_name}", rot_x=rot_x, rot_y=rot_y)]

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
            if results:
                return results

            # If no multipart condition matched (e.g. empty or default properties), fallback to first valid part
            for part in raw_state["multipart"]:
                apply = part.get("apply")
                if apply:
                    if isinstance(apply, list):
                        return [self._parse_variant_entry(apply[0])]
                    else:
                        return [self._parse_variant_entry(apply)]

        short_name = block_id.split(":", 1)[-1]
        return [VariantMatch(model_id=f"minecraft:block/{short_name}")]

    def _match_variant(self, variants: dict[str, Any], props: dict[str, str]) -> Optional[VariantMatch]:
        # Form exact sorted key
        exact_key = ",".join(f"{k}={v}" for k, v in sorted(props.items()))
        if exact_key in variants:
            return self._parse_variant_entry(variants[exact_key])

        # Match variants by scoring compatibility against props
        best_match = None
        best_score = -999999

        for v_key, v_entry in variants.items():
            if not v_key:
                if not props and best_score < 0:
                    best_score = 0
                    best_match = self._parse_variant_entry(v_entry)
                continue
            v_props = dict(pair.split("=", 1) for pair in v_key.split(",") if "=" in pair)

            # Compatibility: every property in props must match v_props if present in v_props
            compatible = True
            matched_keys = 0
            for k, v in props.items():
                if k in v_props:
                    if v_props[k] != v:
                        compatible = False
                        break
                    matched_keys += 1

            if not compatible:
                continue

            score = matched_keys * 100
            # Full exact match of all keys in variant
            if len(v_props) == len(props):
                score += 1000

            # Score keys in v_props that are not specified in props: prefer standard default states
            for vk, vv in v_props.items():
                if vk not in props:
                    if vv in ("false", "0", "none", "straight", "bottom", "lower", "single", "foot", "normal", "side", "y", "north"):
                        score += 10
                    elif vv in ("true", "1", "top", "upper", "head", "inner", "outer", "double", "x", "z", "south", "east", "west"):
                        score -= 10

            if score > best_score:
                best_score = score
                best_match = self._parse_variant_entry(v_entry, variant_props=v_props)

        return best_match

    def _parse_variant_entry(self, entry: Any, variant_props: Optional[dict[str, str]] = None) -> VariantMatch:
        if isinstance(entry, list):
            entry = entry[0]
        if isinstance(entry, str):
            return VariantMatch(model_id=entry, variant_props=variant_props)
        return VariantMatch(
            model_id=entry.get("model", ""),
            rot_x=float(entry.get("x", 0.0)),
            rot_y=float(entry.get("y", 0.0)),
            uvlock=bool(entry.get("uvlock", False)),
            weight=int(entry.get("weight", 1)),
            variant_props=variant_props,
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
