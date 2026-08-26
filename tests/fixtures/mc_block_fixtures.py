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
            "conditional=false,facing=down":  {"model": "minecraft:block/command_block", "x": 90},
            "conditional=false,facing=east":  {"model": "minecraft:block/command_block", "y": 90},
            "conditional=false,facing=north": {"model": "minecraft:block/command_block"},
            "conditional=false,facing=south": {"model": "minecraft:block/command_block", "y": 180},
            "conditional=false,facing=up":    {"model": "minecraft:block/command_block", "x": 270},
            "conditional=false,facing=west":  {"model": "minecraft:block/command_block", "y": 270},
            "conditional=true,facing=down":   {"model": "minecraft:block/command_block_conditional", "x": 90},
            "conditional=true,facing=east":   {"model": "minecraft:block/command_block_conditional", "y": 90},
            "conditional=true,facing=north":  {"model": "minecraft:block/command_block_conditional"},
            "conditional=true,facing=south":  {"model": "minecraft:block/command_block_conditional", "y": 180},
            "conditional=true,facing=up":     {"model": "minecraft:block/command_block_conditional", "x": 270},
            "conditional=true,facing=west":   {"model": "minecraft:block/command_block_conditional", "y": 270}
        }
    },
    "minecraft:observer": {
        "variants": {
            "facing=down,powered=false":  {"model": "minecraft:block/observer", "x": 90},
            "facing=down,powered=true":   {"model": "minecraft:block/observer_on", "x": 90},
            "facing=east,powered=false":  {"model": "minecraft:block/observer", "y": 90},
            "facing=east,powered=true":   {"model": "minecraft:block/observer_on", "y": 90},
            "facing=north,powered=false": {"model": "minecraft:block/observer"},
            "facing=north,powered=true":  {"model": "minecraft:block/observer_on"},
            "facing=south,powered=false": {"model": "minecraft:block/observer", "y": 180},
            "facing=south,powered=true":  {"model": "minecraft:block/observer_on", "y": 180},
            "facing=up,powered=false":    {"model": "minecraft:block/observer", "x": 270},
            "facing=up,powered=true":     {"model": "minecraft:block/observer_on", "x": 270},
            "facing=west,powered=false":  {"model": "minecraft:block/observer", "y": 270},
            "facing=west,powered=true":   {"model": "minecraft:block/observer_on", "y": 270}
        }
    },
    "minecraft:piston": {
        "variants": {
            "extended=false,facing=down":  {"model": "minecraft:block/piston", "x": 90},
            "extended=false,facing=east":  {"model": "minecraft:block/piston", "y": 90},
            "extended=false,facing=north": {"model": "minecraft:block/piston"},
            "extended=false,facing=south": {"model": "minecraft:block/piston", "y": 180},
            "extended=false,facing=up":    {"model": "minecraft:block/piston", "x": 270},
            "extended=false,facing=west":  {"model": "minecraft:block/piston", "y": 270},
            "extended=true,facing=down":   {"model": "minecraft:block/piston_extended", "x": 90},
            "extended=true,facing=east":   {"model": "minecraft:block/piston_extended", "y": 90},
            "extended=true,facing=north":  {"model": "minecraft:block/piston_extended"},
            "extended=true,facing=south":  {"model": "minecraft:block/piston_extended", "y": 180},
            "extended=true,facing=up":     {"model": "minecraft:block/piston_extended", "x": 270},
            "extended=true,facing=west":   {"model": "minecraft:block/piston_extended", "y": 270}
        }
    },
    "minecraft:poppy": {
        "variants": {
            "": {"model": "minecraft:block/poppy"}
        }
    },
    "minecraft:lily_pad": {
        "variants": {
            "": {"model": "minecraft:block/lily_pad"}
        }
    }
}

# -------------------------------------------------------------------------
# Vanilla Models Definitions
# -------------------------------------------------------------------------

FIXTURE_MODELS: dict[str, dict[str, Any]] = {
    # Cross base
    "minecraft:block/cross": {
        "ambientocclusion": False,
        "textures": {
            "particle": "#cross"
        },
        "elements": [
            {
                "from": [0.8, 0, 8],
                "to": [15.2, 16, 8],
                "rotation": {"origin": [8, 8, 8], "axis": "y", "angle": 45, "rescale": True},
                "shade": False,
                "faces": {
                    "north": {"uv": [0, 0, 16, 16], "texture": "#cross"},
                    "south": {"uv": [0, 0, 16, 16], "texture": "#cross"}
                }
            },
            {
                "from": [8, 0, 0.8],
                "to": [8, 16, 15.2],
                "rotation": {"origin": [8, 8, 8], "axis": "y", "angle": 45, "rescale": True},
                "shade": False,
                "faces": {
                    "west": {"uv": [0, 0, 16, 16], "texture": "#cross"},
                    "east": {"uv": [0, 0, 16, 16], "texture": "#cross"}
                }
            }
        ]
    },
    "minecraft:block/poppy": {
        "parent": "minecraft:block/cross",
        "textures": {
            "cross": "minecraft:block/poppy"
        }
    },
    "minecraft:block/lily_pad": {
        "ambientocclusion": False,
        "textures": {
            "particle": "minecraft:block/lily_pad",
            "texture": "minecraft:block/lily_pad"
        },
        "elements": [
            {
                "from": [0, 0.25, 0],
                "to": [16, 0.25, 16],
                "faces": {
                    "down": {"uv": [0, 0, 16, 16], "texture": "#texture"},
                    "up": {"uv": [0, 0, 16, 16], "texture": "#texture"}
                }
            }
        ]
    },
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
    # Cube Directional base
    "minecraft:block/cube_directional": {
        "parent": "minecraft:block/block",
        "elements": [
            {
                "from": [0, 0, 0],
                "to": [16, 16, 16],
                "faces": {
                    "down":  {"uv": [0, 0, 16, 16], "texture": "#down", "cullface": "down", "rotation": 180},
                    "up":    {"uv": [0, 0, 16, 16], "texture": "#up", "cullface": "up"},
                    "north": {"uv": [0, 0, 16, 16], "texture": "#north", "cullface": "north"},
                    "south": {"uv": [0, 0, 16, 16], "texture": "#south", "cullface": "south"},
                    "west":  {"uv": [0, 0, 16, 16], "texture": "#west", "cullface": "west", "rotation": 270},
                    "east":  {"uv": [0, 0, 16, 16], "texture": "#east", "cullface": "east", "rotation": 90}
                }
            }
        ]
    },
    # Command Block template
    "minecraft:block/template_command_block": {
        "parent": "minecraft:block/cube_directional",
        "textures": {
            "particle": "#back",
            "down": "#side",
            "up": "#side",
            "north": "#front",
            "east": "#side",
            "south": "#back",
            "west": "#side"
        }
    },
    # Command Block
    "minecraft:block/command_block": {
        "parent": "minecraft:block/template_command_block",
        "textures": {
            "back": "minecraft:block/command_block_back",
            "front": "minecraft:block/command_block_front",
            "side": "minecraft:block/command_block_side"
        }
    },
    "minecraft:block/command_block_conditional": {
        "parent": "minecraft:block/template_command_block",
        "textures": {
            "back": "minecraft:block/command_block_back",
            "front": "minecraft:block/command_block_front",
            "side": "minecraft:block/command_block_conditional"
        }
    },
    # Observer
    "minecraft:block/observer": {
        "parent": "minecraft:block/block",
        "textures": {
            "bottom": "minecraft:block/observer_back",
            "side": "minecraft:block/observer_side",
            "top": "minecraft:block/observer_top",
            "front": "minecraft:block/observer_front",
            "particle": "minecraft:block/observer_front"
        },
        "elements": [
            {
                "from": [0, 0, 0],
                "to": [16, 16, 16],
                "faces": {
                    "down":  {"uv": [0, 0, 16, 16], "texture": "#top", "cullface": "down"},
                    "up":    {"uv": [0, 16, 16, 0], "texture": "#top", "cullface": "up"},
                    "north": {"uv": [0, 0, 16, 16], "texture": "#front", "cullface": "north"},
                    "south": {"uv": [0, 0, 16, 16], "texture": "#bottom", "cullface": "south"},
                    "west":  {"uv": [0, 0, 16, 16], "texture": "#side", "cullface": "west"},
                    "east":  {"uv": [0, 0, 16, 16], "texture": "#side", "cullface": "east"}
                }
            }
        ]
    },
    "minecraft:block/observer_on": {
        "parent": "minecraft:block/block",
        "textures": {
            "bottom": "minecraft:block/observer_back_on",
            "side": "minecraft:block/observer_side",
            "top": "minecraft:block/observer_top",
            "front": "minecraft:block/observer_front",
            "particle": "minecraft:block/observer_front"
        },
        "elements": [
            {
                "from": [0, 0, 0],
                "to": [16, 16, 16],
                "faces": {
                    "down":  {"uv": [0, 0, 16, 16], "texture": "#top", "cullface": "down"},
                    "up":    {"uv": [0, 16, 16, 0], "texture": "#top", "cullface": "up"},
                    "north": {"uv": [0, 0, 16, 16], "texture": "#front", "cullface": "north"},
                    "south": {"uv": [0, 0, 16, 16], "texture": "#bottom", "cullface": "south"},
                    "west":  {"uv": [0, 0, 16, 16], "texture": "#side", "cullface": "west"},
                    "east":  {"uv": [0, 0, 16, 16], "texture": "#side", "cullface": "east"}
                }
            }
        ]
    },
    # Piston template
    "minecraft:block/template_piston": {
        "parent": "minecraft:block/block",
        "textures": {
            "particle": "#side"
        },
        "elements": [
            {
                "from": [0, 0, 0],
                "to": [16, 16, 16],
                "faces": {
                    "down":  {"uv": [0, 0, 16, 16], "texture": "#side", "rotation": 180, "cullface": "down"},
                    "up":    {"uv": [0, 0, 16, 16], "texture": "#side", "cullface": "up"},
                    "north": {"uv": [0, 0, 16, 16], "texture": "#platform", "cullface": "north"},
                    "south": {"uv": [0, 0, 16, 16], "texture": "#bottom", "cullface": "south"},
                    "west":  {"uv": [0, 0, 16, 16], "texture": "#side", "rotation": 270, "cullface": "west"},
                    "east":  {"uv": [0, 0, 16, 16], "texture": "#side", "rotation": 90, "cullface": "east"}
                }
            }
        ]
    },
    "minecraft:block/piston": {
        "parent": "minecraft:block/template_piston",
        "textures": {
            "bottom": "minecraft:block/piston_bottom",
            "side": "minecraft:block/piston_side",
            "platform": "minecraft:block/piston_top"
        }
    }
}

# -------------------------------------------------------------------------
# Expected Ground-Truth 6-Face Data
# Ordered by Standard 6-Face indices:
# 0: East (+X), 1: West (-X), 2: Up (+Y), 3: Down (-Y), 4: South (+Z), 5: North (-Z)
# -------------------------------------------------------------------------

GROUND_TRUTH_FACES: dict[str, list[ExpectedFace]] = {
    # Glazed Terracotta
    "minecraft:magenta_glazed_terracotta[facing=north]": [
        ExpectedFace("east", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("west", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("up", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("down", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("south", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("north", "minecraft:block/magenta_glazed_terracotta", 0.0),
    ],
    "minecraft:magenta_glazed_terracotta[facing=east]": [
        ExpectedFace("east", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("west", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("up", "minecraft:block/magenta_glazed_terracotta", 90.0),
        ExpectedFace("down", "minecraft:block/magenta_glazed_terracotta", 270.0),
        ExpectedFace("south", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("north", "minecraft:block/magenta_glazed_terracotta", 0.0),
    ],
    "minecraft:magenta_glazed_terracotta[facing=south]": [
        ExpectedFace("east", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("west", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("up", "minecraft:block/magenta_glazed_terracotta", 180.0),
        ExpectedFace("down", "minecraft:block/magenta_glazed_terracotta", 180.0),
        ExpectedFace("south", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("north", "minecraft:block/magenta_glazed_terracotta", 0.0),
    ],
    "minecraft:magenta_glazed_terracotta[facing=west]": [
        ExpectedFace("east", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("west", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("up", "minecraft:block/magenta_glazed_terracotta", 270.0),
        ExpectedFace("down", "minecraft:block/magenta_glazed_terracotta", 90.0),
        ExpectedFace("south", "minecraft:block/magenta_glazed_terracotta", 0.0),
        ExpectedFace("north", "minecraft:block/magenta_glazed_terracotta", 0.0),
    ],
    # Observer
    "minecraft:observer[facing=up,powered=false]": [
        ExpectedFace("east", "minecraft:block/observer_side", 270.0),
        ExpectedFace("west", "minecraft:block/observer_side", 90.0),
        ExpectedFace("up", "minecraft:block/observer_front", 180.0),
        ExpectedFace("down", "minecraft:block/observer_back", 0.0),
        ExpectedFace("south", "minecraft:block/observer_top", 270.0),
        ExpectedFace("north", "minecraft:block/observer_top", 180.0),
    ],
    "minecraft:observer[facing=down,powered=false]": [
        ExpectedFace("east", "minecraft:block/observer_side", 90.0),
        ExpectedFace("west", "minecraft:block/observer_side", 270.0),
        ExpectedFace("up", "minecraft:block/observer_back", 0.0),
        ExpectedFace("down", "minecraft:block/observer_front", 180.0),
        ExpectedFace("south", "minecraft:block/observer_top", 0.0),
        ExpectedFace("north", "minecraft:block/observer_top", 90.0),
    ],
    # Piston
    "minecraft:piston[extended=false,facing=up]": [
        ExpectedFace("east", "minecraft:block/piston_side", 0.0),
        ExpectedFace("west", "minecraft:block/piston_side", 0.0),
        ExpectedFace("up", "minecraft:block/piston_top", 180.0),
        ExpectedFace("down", "minecraft:block/piston_bottom", 0.0),
        ExpectedFace("south", "minecraft:block/piston_side", 0.0),
        ExpectedFace("north", "minecraft:block/piston_side", 0.0),
    ],
    "minecraft:piston[extended=false,facing=down]": [
        ExpectedFace("east", "minecraft:block/piston_side", 0.0),
        ExpectedFace("west", "minecraft:block/piston_side", 0.0),
        ExpectedFace("up", "minecraft:block/piston_bottom", 0.0),
        ExpectedFace("down", "minecraft:block/piston_top", 180.0),
        ExpectedFace("south", "minecraft:block/piston_side", 0.0),
        ExpectedFace("north", "minecraft:block/piston_side", 0.0),
    ],
}

