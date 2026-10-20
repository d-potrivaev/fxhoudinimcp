"""MCP tool definitions for DOP (dynamics/simulation) operations."""

from __future__ import annotations

# Built-in
# Third-party
from fxhoudinimcp._sdk import Context

# Internal
from fxhoudinimcp.bridge import NO_TIMEOUT
from fxhoudinimcp.server import _get_bridge, mcp


@mcp.tool()
async def get_simulation_info(ctx: Context, node_path: str) -> dict:
    """Get DOP network simulation state, cooked at the current frame.

    `simulation_frame` is the frame the simulation actually holds. Going
    back to a frame the memory cache no longer keeps, Houdini gives the
    frame it kept instead of simulating again; `note` then says so, and
    every node reading the network has that frame too. Check this before
    measuring or rendering a frame reached backwards. A scene ahead of the
    simulation is simulated up to its frame first, under Houdini's
    interrupt dialog and with no deadline: wait for the reply. Stopped
    there, it says so (`interrupted`) with the frame reached.

    Args:
        node_path: DOP network node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "dops.get_simulation_info", {"node_path": node_path}, timeout=NO_TIMEOUT
    )


@mcp.tool()
async def list_dop_objects(ctx: Context, node_path: str) -> dict:
    """List all DOP objects in a simulation.

    Args:
        node_path: DOP network node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("dops.list_dop_objects", {"node_path": node_path})


@mcp.tool()
async def get_dop_object(ctx: Context, node_path: str, object_name: str) -> dict:
    """Get detailed data for a specific DOP object.

    Args:
        node_path: DOP network node path.
        object_name: DOP object name.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "dops.get_dop_object",
        {"node_path": node_path, "object_name": object_name},
    )


@mcp.tool()
async def get_dop_field(
    ctx: Context,
    node_path: str,
    object_name: str,
    data_path: str,
    field_name: str,
) -> dict:
    """Read a specific field value from a DOP record.

    Args:
        node_path: DOP network node path.
        object_name: DOP object name.
        data_path: Dot-separated subdata path (e.g. "Geometry", "Forces/Gravity").
        field_name: Field name to read.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "dops.get_dop_field",
        {
            "node_path": node_path,
            "object_name": object_name,
            "data_path": data_path,
            "field_name": field_name,
        },
    )


@mcp.tool()
async def get_dop_relationships(ctx: Context, node_path: str) -> dict:
    """List all relationships between DOP objects.

    Args:
        node_path: DOP network node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("dops.get_dop_relationships", {"node_path": node_path})


@mcp.tool()
async def step_simulation(ctx: Context, node_path: str, steps: int = 1) -> dict:
    """Advance the simulation by a number of frames.

    Args:
        node_path: DOP network node path.
        steps: Number of frames to advance.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute(
        "dops.step_simulation",
        {"node_path": node_path, "steps": steps},
    )


@mcp.tool()
async def reset_simulation(ctx: Context, node_path: str) -> dict:
    """Reset the simulation to its initial state.

    Args:
        node_path: DOP network node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("dops.reset_simulation", {"node_path": node_path})


@mcp.tool()
async def get_sim_memory_usage(ctx: Context, node_path: str) -> dict:
    """Get detailed memory breakdown for the simulation.

    Args:
        node_path: DOP network node path.
    """
    bridge = _get_bridge(ctx)
    return await bridge.execute("dops.get_sim_memory_usage", {"node_path": node_path})
