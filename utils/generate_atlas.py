"""
Compatibility shim for utils.generate_atlas.
Redirects to utils.materials.atlas_generator.
"""

from .materials.atlas_generator import *

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate Minecraft Texture Atlas from Resource Pack / JAR.")
    parser.add_argument("resource_path", help="Path to resource pack ZIP/JAR or unpacked directory")
    parser.add_argument("-o", "--output", default="./dist_atlas", help="Output directory for generated atlas files")
    args = parser.parse_args()

    gen = AtlasGenerator(args.resource_path)
    gen.build(args.output)
