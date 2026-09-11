"""Start the installed Blender MCP addon for this local visual authoring session."""
import bpy
bpy.ops.preferences.addon_enable(module='blender_mcp')
bpy.context.preferences.addons['blender_mcp'].preferences.telemetry_consent=False
bpy.ops.wm.save_userpref()
bpy.ops.blendermcp.start_server()
print('FLY_BLENDER_MCP_READY', bpy.context.scene.blendermcp_server_running)
