"""Reusable Face Selector node groups (Vector, Int, Color, Float) that dispatch 6-face attributes based on Normal."""

from __future__ import annotations

import bpy
from ..core import ensure_gn_group, ensure_socket, finalize_group

GROUP_NAME_FACE_SELECTOR_VECTOR = "Yefira_Face_Selector_Vector"
GROUP_NAME_FACE_SELECTOR_INT = "Yefira_Face_Selector_Int"
GROUP_NAME_FACE_SELECTOR_COLOR = "Yefira_Face_Selector_Color"
GROUP_NAME_FACE_SELECTOR_FLOAT = "Yefira_Face_Selector_Float"
FACE_SELECTOR_VERSION = 5


def get_or_create_face_selector_vector_group() -> bpy.types.GeometryNodeTree:
    """Reusable node group: Selects a Vector from 6 face inputs based on Face ID."""
    tree, needs_build = ensure_gn_group(GROUP_NAME_FACE_SELECTOR_VECTOR, FACE_SELECTOR_VERSION)
    if not needs_build:
        return tree

    ensure_socket(tree, "Face ID", "INPUT", "NodeSocketInt", default_value=0)
    ensure_socket(tree, "Top (+Z)", "INPUT", "NodeSocketVector")
    ensure_socket(tree, "Bottom (-Z)", "INPUT", "NodeSocketVector")
    ensure_socket(tree, "North (+Y)", "INPUT", "NodeSocketVector")
    ensure_socket(tree, "South (-Y)", "INPUT", "NodeSocketVector")
    ensure_socket(tree, "East (+X)", "INPUT", "NodeSocketVector")
    ensure_socket(tree, "West (-X)", "INPUT", "NodeSocketVector")
    ensure_socket(tree, "Selected", "OUTPUT", "NodeSocketVector")

    nodes, links = tree.nodes, tree.links
    gin = nodes.new("NodeGroupInput")
    gin.location = (-500, 0)
    gout = nodes.new("NodeGroupOutput")
    gout.location = (880, -60)

    def compare_id(fid: int, y: float):
        cmp_node = nodes.new("FunctionNodeCompare")
        cmp_node.data_type, cmp_node.operation = "INT", "EQUAL"
        cmp_node.inputs["B"].default_value = fid
        cmp_node.location = (-200, y)
        links.new(gin.outputs["Face ID"], cmp_node.inputs["A"])
        return cmp_node

    cmp_bottom = compare_id(1, 240)
    cmp_north = compare_id(2, 120)
    cmp_south = compare_id(3, 0)
    cmp_east = compare_id(4, -120)
    cmp_west = compare_id(5, -240)

    def make_switch(cmp_node, false_socket, true_socket, x: float, y: float):
        sw = nodes.new("GeometryNodeSwitch")
        sw.input_type = "VECTOR"
        sw.location = (x, y)
        links.new(cmp_node.outputs["Result"], sw.inputs["Switch"])
        links.new(false_socket, sw.inputs["False"])
        links.new(true_socket, sw.inputs["True"])
        return sw.outputs["Output"]

    v1 = make_switch(cmp_bottom, gin.outputs["Top (+Z)"], gin.outputs["Bottom (-Z)"], 60, 180)
    v2 = make_switch(cmp_north, v1, gin.outputs["North (+Y)"], 220, 120)
    v3 = make_switch(cmp_south, v2, gin.outputs["South (-Y)"], 380, 60)
    v4 = make_switch(cmp_east, v3, gin.outputs["East (+X)"], 540, 0)
    v5 = make_switch(cmp_west, v4, gin.outputs["West (-X)"], 700, -60)

    links.new(v5, gout.inputs["Selected"])
    return finalize_group(tree)


def get_or_create_face_selector_int_group() -> bpy.types.GeometryNodeTree:
    """Reusable node group: Selects an Integer from 6 face inputs based on Face ID."""
    tree, needs_build = ensure_gn_group(GROUP_NAME_FACE_SELECTOR_INT, FACE_SELECTOR_VERSION)
    if not needs_build:
        return tree

    ensure_socket(tree, "Face ID", "INPUT", "NodeSocketInt", default_value=0)
    ensure_socket(tree, "Top (+Z)", "INPUT", "NodeSocketInt", default_value=0)
    ensure_socket(tree, "Bottom (-Z)", "INPUT", "NodeSocketInt", default_value=0)
    ensure_socket(tree, "North (+Y)", "INPUT", "NodeSocketInt", default_value=0)
    ensure_socket(tree, "South (-Y)", "INPUT", "NodeSocketInt", default_value=0)
    ensure_socket(tree, "East (+X)", "INPUT", "NodeSocketInt", default_value=0)
    ensure_socket(tree, "West (-X)", "INPUT", "NodeSocketInt", default_value=0)
    ensure_socket(tree, "Selected", "OUTPUT", "NodeSocketInt")

    nodes, links = tree.nodes, tree.links
    gin = nodes.new("NodeGroupInput")
    gin.location = (-500, 0)
    gout = nodes.new("NodeGroupOutput")
    gout.location = (880, -60)

    def compare_id(fid: int, y: float):
        cmp_node = nodes.new("FunctionNodeCompare")
        cmp_node.data_type, cmp_node.operation = "INT", "EQUAL"
        cmp_node.inputs["B"].default_value = fid
        cmp_node.location = (-200, y)
        links.new(gin.outputs["Face ID"], cmp_node.inputs["A"])
        return cmp_node

    cmp_bottom = compare_id(1, 240)
    cmp_north = compare_id(2, 120)
    cmp_south = compare_id(3, 0)
    cmp_east = compare_id(4, -120)
    cmp_west = compare_id(5, -240)

    def make_switch(cmp_node, false_socket, true_socket, x: float, y: float):
        sw = nodes.new("GeometryNodeSwitch")
        sw.input_type = "INT"
        sw.location = (x, y)
        links.new(cmp_node.outputs["Result"], sw.inputs["Switch"])
        links.new(false_socket, sw.inputs["False"])
        links.new(true_socket, sw.inputs["True"])
        return sw.outputs["Output"]

    v1 = make_switch(cmp_bottom, gin.outputs["Top (+Z)"], gin.outputs["Bottom (-Z)"], 60, 180)
    v2 = make_switch(cmp_north, v1, gin.outputs["North (+Y)"], 220, 120)
    v3 = make_switch(cmp_south, v2, gin.outputs["South (-Y)"], 380, 60)
    v4 = make_switch(cmp_east, v3, gin.outputs["East (+X)"], 540, 0)
    v5 = make_switch(cmp_west, v4, gin.outputs["West (-X)"], 700, -60)

    links.new(v5, gout.inputs["Selected"])
    return finalize_group(tree)


def get_or_create_face_selector_color_group() -> bpy.types.GeometryNodeTree:
    """Reusable node group: Selects a Color (RGBA) from 6 face inputs based on Face ID."""
    tree, needs_build = ensure_gn_group(GROUP_NAME_FACE_SELECTOR_COLOR, FACE_SELECTOR_VERSION)
    if not needs_build:
        return tree

    ensure_socket(tree, "Face ID", "INPUT", "NodeSocketInt", default_value=0)
    ensure_socket(tree, "Top (+Z)", "INPUT", "NodeSocketColor")
    ensure_socket(tree, "Bottom (-Z)", "INPUT", "NodeSocketColor")
    ensure_socket(tree, "North (+Y)", "INPUT", "NodeSocketColor")
    ensure_socket(tree, "South (-Y)", "INPUT", "NodeSocketColor")
    ensure_socket(tree, "East (+X)", "INPUT", "NodeSocketColor")
    ensure_socket(tree, "West (-X)", "INPUT", "NodeSocketColor")
    ensure_socket(tree, "Selected", "OUTPUT", "NodeSocketColor")

    nodes, links = tree.nodes, tree.links
    gin = nodes.new("NodeGroupInput")
    gin.location = (-500, 0)
    gout = nodes.new("NodeGroupOutput")
    gout.location = (880, -60)

    def compare_id(fid: int, y: float):
        cmp_node = nodes.new("FunctionNodeCompare")
        cmp_node.data_type, cmp_node.operation = "INT", "EQUAL"
        cmp_node.inputs["B"].default_value = fid
        cmp_node.location = (-200, y)
        links.new(gin.outputs["Face ID"], cmp_node.inputs["A"])
        return cmp_node

    cmp_bottom = compare_id(1, 240)
    cmp_north = compare_id(2, 120)
    cmp_south = compare_id(3, 0)
    cmp_east = compare_id(4, -120)
    cmp_west = compare_id(5, -240)

    def make_switch(cmp_node, false_socket, true_socket, x: float, y: float):
        sw = nodes.new("GeometryNodeSwitch")
        sw.input_type = "RGBA"
        sw.location = (x, y)
        links.new(cmp_node.outputs["Result"], sw.inputs["Switch"])
        links.new(false_socket, sw.inputs["False"])
        links.new(true_socket, sw.inputs["True"])
        return sw.outputs["Output"]

    v1 = make_switch(cmp_bottom, gin.outputs["Top (+Z)"], gin.outputs["Bottom (-Z)"], 60, 180)
    v2 = make_switch(cmp_north, v1, gin.outputs["North (+Y)"], 220, 120)
    v3 = make_switch(cmp_south, v2, gin.outputs["South (-Y)"], 380, 60)
    v4 = make_switch(cmp_east, v3, gin.outputs["East (+X)"], 540, 0)
    v5 = make_switch(cmp_west, v4, gin.outputs["West (-X)"], 700, -60)

    links.new(v5, gout.inputs["Selected"])
    return finalize_group(tree)


def get_or_create_face_selector_float_group() -> bpy.types.GeometryNodeTree:
    """Reusable node group: Selects a Float from 6 face inputs based on Face ID."""
    tree, needs_build = ensure_gn_group(GROUP_NAME_FACE_SELECTOR_FLOAT, FACE_SELECTOR_VERSION)
    if not needs_build:
        return tree

    ensure_socket(tree, "Face ID", "INPUT", "NodeSocketInt", default_value=0)
    ensure_socket(tree, "Top (+Z)", "INPUT", "NodeSocketFloat", default_value=0.0)
    ensure_socket(tree, "Bottom (-Z)", "INPUT", "NodeSocketFloat", default_value=0.0)
    ensure_socket(tree, "North (+Y)", "INPUT", "NodeSocketFloat", default_value=0.0)
    ensure_socket(tree, "South (-Y)", "INPUT", "NodeSocketFloat", default_value=0.0)
    ensure_socket(tree, "East (+X)", "INPUT", "NodeSocketFloat", default_value=0.0)
    ensure_socket(tree, "West (-X)", "INPUT", "NodeSocketFloat", default_value=0.0)
    ensure_socket(tree, "Selected", "OUTPUT", "NodeSocketFloat")

    nodes, links = tree.nodes, tree.links
    gin = nodes.new("NodeGroupInput")
    gin.location = (-500, 0)
    gout = nodes.new("NodeGroupOutput")
    gout.location = (880, -60)

    def compare_id(fid: int, y: float):
        cmp_node = nodes.new("FunctionNodeCompare")
        cmp_node.data_type, cmp_node.operation = "INT", "EQUAL"
        cmp_node.inputs["B"].default_value = fid
        cmp_node.location = (-200, y)
        links.new(gin.outputs["Face ID"], cmp_node.inputs["A"])
        return cmp_node

    cmp_bottom = compare_id(1, 240)
    cmp_north = compare_id(2, 120)
    cmp_south = compare_id(3, 0)
    cmp_east = compare_id(4, -120)
    cmp_west = compare_id(5, -240)

    def make_switch(cmp_node, false_socket, true_socket, x: float, y: float):
        sw = nodes.new("GeometryNodeSwitch")
        sw.input_type = "FLOAT"
        sw.location = (x, y)
        links.new(cmp_node.outputs["Result"], sw.inputs["Switch"])
        links.new(false_socket, sw.inputs["False"])
        links.new(true_socket, sw.inputs["True"])
        return sw.outputs["Output"]

    v1 = make_switch(cmp_bottom, gin.outputs["Top (+Z)"], gin.outputs["Bottom (-Z)"], 60, 180)
    v2 = make_switch(cmp_north, v1, gin.outputs["North (+Y)"], 220, 120)
    v3 = make_switch(cmp_south, v2, gin.outputs["South (-Y)"], 380, 60)
    v4 = make_switch(cmp_east, v3, gin.outputs["East (+X)"], 540, 0)
    v5 = make_switch(cmp_west, v4, gin.outputs["West (-X)"], 700, -60)

    links.new(v5, gout.inputs["Selected"])
    return finalize_group(tree)
