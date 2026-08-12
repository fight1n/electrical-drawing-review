"""FreeCAD atomic tool wrappers for CAD-level inspection.

The reviewer's Tool-Use loop calls these to pull *precise* geometry/parameters
instead of guessing from text. FreeCAD is optional: when it is installed we can
load a real .FCStd/.step and expose its primitives; otherwise we operate on the
already-parsed element list (from the parsing pipeline) so the tool contract
stays identical and the system remains runnable without a CAD install.
"""
from edr.cad.freecad_tools import CAD_TOOL_SPECS, FreeCADTools, build_cad_tools

__all__ = ["FreeCADTools", "build_cad_tools", "CAD_TOOL_SPECS"]
