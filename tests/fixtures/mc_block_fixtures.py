"""
Minecraft BlockState, Model, and Expected Baked Quad Fixtures.
Provides real vanilla JSON definitions and expected ground-truth BakedFace data
for testing the Headless Model Baker.
"""

from typing import Any, NamedTuple

class ExpectedFace(NamedTuple):
    direction: str  # "east", "west", "up", "down", "south", "north"
    texture: str
    uv_rot: float  # 0.0, 90.0, 180.0, 270.0 degrees
    uv_bounds: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    tint_index: int = -1

# -------------------------------------------------------------------------
# Vanilla BlockStates Definitions
# -------------------------------------------------------------------------

FIXTURE_BLOCKSTATES: dict[str, dict[str, Any]] = {
    "minecraft:magenta_glazed_terracotta": {
        "variants": {
            "facing=north": {"model": "minecraft:block/magenta_glazed_terracotta"},
            "facing=east":  {"model": "minecraft:block/magenta_glazed_terracotta", "y": 90},
            "facing=south": {"model": "minecraft:block/magenta_glazed_terracotta", "y": 180},
            "facing=west":  {"model": "minecraft:block/magenta_glazed_terracotta", "y": 270}
        }
    },
    "minecraft:command_block": {
        "variants": {
            "conditional=false,facing=down":  {"model": "minecraft:block/command_block", "x": 180},
            "conditional=false,facing=east":  {"model": "minecraft:block/command_block", "x": 90, "y": 90},
            "conditional=false,facing=north": {"model": "minecraft:block/command_block", "x": 90},
            "conditional=false,facing=south": {"model": "minecraft:block/command_block", "x": 90, "y": 180},
            "conditional=false,facing=up":    {"model": "minecraft:block/command_block"},
            "conditional=false,facing=west":  {"model": "minecraft:block/command_block", "x": 90, "y": 270},
            "conditional=true,facing=down":   {"model": "minecraft:block/command_block_conditional", "x": 180},
            "conditional=true,facing=east":   {"model": "minecraft:block/command_block_conditional", "x": 90, "y": 90},
            "conditional=true,facing=north":  {"model": "minecraft:block/command_block_conditional", "x": 90},
            "conditional=true,facing=south":  {"model": "minecraft:block/command_block_conditional", "x": 90, "y": 180},
            "conditional=true,facing=up":     {"model": "minecraft:block/command_block_conditional"},
            "conditional=true,facing=west":   {"model": "minecraft:block/command_block_conditional", "x": 90, "y": 270}
        }
    },
    "minecraft:observer": {
        "variants": {
            "facing=down,powered=false":  {"model": "minecraft:block/observer", "x": 180},
            "facing=down,powered=true":   {"model": "minecraft:block/observer_on", "x": 180},
            "facing=east,powered=false":  {"model": "minecraft:block/observer", "x": 90, "y": 90},
            "facing=east,powered=true":   {"model": "minecraft:block/observer_on", "x": 90, "y": 90},
            "facing=north,powered=false": {"model": "minecraft:block/observer", "x": 90},
            "facing=north,powered=true":  {"model": "minecraft:block/observer_on", "x": 90},
            "facing=south,powered=false": {"model": "minecraft:block/observer", "x": 90, "y": 180},
            "facing=south,powered=true":  {"model": "minecraft:block/observer_on", "x": 90, "y": 180},
            "facing=up,powered=false":    {"model": "minecraft:block/observer"},
            "facing=up,powered=true":     {"model": "minecraft:block/observer_on"},
            "facing=west,powered=false":  {"model": "minecraft:block/observer", "x": 90, "y": 270},
            "facing=west,powered=true":   {"model": "minecraft:block/observer_on", "x": 90, "y": 270}
        }
    },
    "minecraft:piston": {
        "variants": {
            "extended=false,facing=down":  {"model": "minecraft:block/piston", "x": 180},
            "extended=false,facing=east":  {"model": "minecraft:block/piston", "x": 90, "y": 90},
            "extended=false,facing=north": {"model": "minecraft:block/piston", "x": 90},
            "extended=false,facing=south": {"model": "minecraft:block/piston", "x": 90, "y": 180},
            "extended=false,facing=up":    {"model": "minecraft:block/piston"},
            "extended=false,facing=west":  {"model": "minecraft:block/piston", "x": 90, "y": 270},
            "extended=true,facing=down":   {"model": "minecraft:block/piston_extended", "x": 180},
            "extended=true,facing=east":   {"model": "minecraft:block/piston_extended", "x": 90, "y": 90},
            "extended=true,facing=north":  {"model": "minecraft:block/piston_extended", "x": 90},
            "extended=true,facing=south":  {"model": "minecraft:block/piston_extended", "x": 90, "y": 180},
            "extended=true,facing=up":     {"model": "minecraft:block/piston_extended"},
            "extended=true,facing=west":   {"model": "minecraft:block/piston_extended", "x": 90, "y": 270}
        }
    }
}

# -------------------------------------------------------------------------
# Vanilla Models Definitions
# -------------------------------------------------------------------------

FIXTURE_MODELS: dict[str, dict[str, Any]] = {
    # Block base
    "minecraft:block/block": {
        "textures": {
            "particle": "minecraft:block/dirt"
        }
    },
    # Cube base
    "minecraft:block/cube": {
        "parent": "minecraft:block/block",
        "elements": [
            {
                "from": [0, 0, 0],
                "to": [16, 16, 16],
                "faces": {
                    "down":  {"uv": [0, 0, 16, 16], "texture": "#down", "cullface": "down"},
                    "up":    {"uv": [0, 0, 16, 16], "texture": "#up", "cullface": "up"},
                    "north": {"uv": [0, 0, 16, 16], "texture": "#north", "cullface": "north"},
                    "south": {"uv": [0, 0, 16, 16], "texture": "#south", "cullface": "south"},
                    "west":  {"uv": [0, 0, 16, 16], "texture": "#west", "cullface": "west"},
                    "east":  {"uv": [0, 0, 16, 16], "texture": "#east", "cullface": "east"}
                }
            }
        ]
    },
    # Glazed Terracotta
    "minecraft:block/template_glazed_terracotta": {
        "parent": "minecraft:block/block",
        "textures": {
            "particle": "#pattern"
        },
        "elements": [
            {
                "from": [0, 0, 0],
                "to": [16, 16, 16],
                "faces": {
                    "down":  {"uv": [0, 0, 16, 16], "texture": "#pattern", "cullface": "down"},
                    "up":    {"uv": [0, 0, 16, 16], "texture": "#pattern", "cullface": "up"},
                    "north": {"uv": [0, 0, 16, 16], "texture": "#pattern", "cullface": "north"},
                    "south": {"uv": [0, 0, 16, 16], "texture": "#pattern", "cullface": "south"},
                    "west":  {"uv": [0, 0, 16, 16], "texture": "#pattern", "cullface": "west"},
                    "east":  {"uv": [0, 0, 16, 16], "texture": "#pattern", "cullface": "east"}
                }
            }
        ]
    },
    "minecraft:block/magenta_glazed_terracotta": {
        "parent": "minecraft:block/template_glazed_terracotta",
        "textures": {
            "pattern": "minecraft:block/magenta_glazed_terracotta"
        }
    },
    # Command Block
    "minecraft:block/command_block": {
        "parent": "minecraft:block/cube",
        "textures": {
            "particle": "minecraft:block/command_block_front",
            "down": "minecraft:block/command_block_back",
            "up": "minecraft:block/command_block_front",
            "north": "minecraft:block/command_block_side",
            "east": "minecraft:block/command_block_side",
            "south": "minecraft:block/command_block_side",
            "west": "minecraft:block/command_block_side"
        }
    },
    "minecraft:block/command_block_conditional": {
        "parent": "minecraft:block/cube",
        "textures": {
            "particle": "minecraft:block/command_block_front",
            "down": "minecraft:block/command_block_back",
            "up": "minecraft:block/command_block_front",
            "north": "minecraft:block/command_block_conditional",
            "east": "minecraft:block/command_block_conditional",
            "south": "minecraft:block/command_block_conditional",
            "west": "minecraft:block/command_block_conditional"
        }
    },
    # Observer
    "minecraft:block/observer": {
        "parent": "minecraft:block/cube",
        "textures": {
            "particle": "minecraft:block/observer_top",
            "down": "minecraft:block/observer_top",
            "up": "minecraft:block/observer_top",
            "north": "minecraft:block/observer_front",
            "south": "minecraft:block/observer_back",
            "west": "minecraft:block/observer_side",
            "east": "minecraft:block/observer_side"
        }
    },
    "minecraft:block/observer_on": {
        "parent": "minecraft:block/cube",
        "textures": {
            "particle": "minecraft:block/observer_top",
            "down": "minecraft:block/observer_top",
            "up": "minecraft:block/observer_top",
            "north": "minecraft:block/observer_front",
            "south": "minecraft:block/observer_back_on",
            "west": "minecraft:block/observer_side",
            "east": "minecraft:block/observer_side"
        }
    },
    # Piston
    "minecraft:block/template_piston": {
        "parent": "minecraft:block/block",
        "textures": {
            "particle": "#bottom"
        },
        "elements": [
            {
                "from": [0, 0, 0],
                "to": [16, 16, 16],
                "faces": {
                    "down":  {"uv": [0, 0, 16, 16], "texture": "#bottom", "cullface": "down"},
                    "up":    {"uv": [0, 0, 16, 16], "texture": "#top", "cullface": "up"},
                    "north": {"uv": [0, 0, 16, 16], "texture": "#side", "cullface": "north"},
                    "south": {"uv": [0, 0, 16, 16], "texture": "#side", "cullface": "south"},
                    "west":  {"uv": [0, 0, 16, 16], "texture": "#side", "cullface": "west"},
                    "east":  {"uv": [0, 0, 16, 16], "texture": "#side", "cullface": "east"}
                }
            }
        ]
    },
    "minecraft:block/piston": {
        "parent": "minecraft:block/template_piston",
        "textures": {
            "bottom": "minecraft:block/piston_bottom",
            "side": "minecraft:block/piston_side",
            "top": "minecraft:block/piston_top"
        }
    }
}

# -------------------------------------------------------------------------
# Expected Ground-Truth 6-Face Data
# Ordered by Standard 6-Face indices:
# 0: East (+X), 1: West (-X), 2: Up (+Y), 3: Down (-Y), 4: South (+Z), 5: North (-Z)
# -------------------------------------------------------------------------

GROUND_TRUTH_FACES: dict[str, list[ExpectedFace]] = {
    # 1. Glazed Terracotta: facing=north (no rotation)
    "minecraft:magenta_glazed_terracotta[facing=north]": [
        ExpectedFace("east", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("west", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("up", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("down", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("south", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("north", "minecraft:block/magenta_glazed_terracotta", 0.0),
    ],
    # Glazed Terracotta: facing=east (y=90)
    "minecraft:magenta_glazed_terracotta[facing=east]": [
        ExpectedFace("east", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("west", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("up", "minecraft:block/magenta_glazed_terracotta", 90.0),
        ExpectedFace("down", "minecraft:block/magenta_glazed_terracotta", 270.0),
        ExpectedFace("south", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("north", "minecraft:block/magenta_glazed_terracotta", 0.0),
    ],
    # Glazed Terracotta: facing=south (y=180)
    "minecraft:magenta_glazed_terracotta[facing=south]": [
        ExpectedFace("east", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("west", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("up", "minecraft:block/magenta_glazed_terracotta", 180.0),
        ExpectedFace("down", "minecraft:block/magenta_glazed_terracotta", 180.0),
        ExpectedFace("south", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("north", "minecraft:block/magenta_glazed_terracotta", 0.0),
    ],
    # Glazed Terracotta: facing=west (y=270)
    "minecraft:magenta_glazed_terracotta[facing=west]": [
        ExpectedFace("east", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("west", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("up", "minecraft:block/magenta_glazed_terracotta", 270.0),
        ExpectedFace("down", "minecraft:block/magenta_glazed_terracotta", 90.0),
        ExpectedFace("south", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("north", "minecraft:block/magenta_glazed_terracotta", 0.0),
    ],
}

