import bpy


def process_node_tree_interpolation(node_tree, target_interpolation="Closest", visited_trees=None):
    """Recursively set interpolation on image texture nodes within a node tree and nested group nodes."""
    if visited_trees is None:
        visited_trees = set()

    if not node_tree or node_tree in visited_trees:
        return 0

    visited_trees.add(node_tree)
    modified_count = 0

    for node in node_tree.nodes:
        if node.type == "TEX_IMAGE":
            if getattr(node, "interpolation", None) != target_interpolation:
                node.interpolation = target_interpolation
                modified_count += 1
        elif node.type == "GROUP" and getattr(node, "node_tree", None):
            modified_count += process_node_tree_interpolation(
                node.node_tree, target_interpolation, visited_trees
            )

    return modified_count


def set_materials_texture_interpolation_closest(objects, target_interpolation="Closest"):
    """Traverse all materials on given objects and set image texture node interpolation.

    :param objects: Iterable of bpy.types.Object
    :param target_interpolation: Target interpolation mode ('Closest', 'Linear', etc.)
    :return: tuple of (materials_processed_count, nodes_modified_count)
    """
    processed_materials = set()
    total_nodes_updated = 0

    for obj in objects:
        materials_to_check = set()

        if hasattr(obj, "material_slots"):
            for slot in obj.material_slots:
                if slot.material:
                    materials_to_check.add(slot.material)

        if hasattr(obj, "data") and hasattr(obj.data, "materials"):
            for mat in obj.data.materials:
                if mat:
                    materials_to_check.add(mat)

        for mat in materials_to_check:
            if mat not in processed_materials:
                processed_materials.add(mat)
                if mat.use_nodes and mat.node_tree:
                    updated = process_node_tree_interpolation(
                        mat.node_tree, target_interpolation=target_interpolation
                    )
                    total_nodes_updated += updated

    return len(processed_materials), total_nodes_updated
