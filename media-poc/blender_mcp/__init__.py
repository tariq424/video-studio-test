"""Blender over MCP for the media POC (route r11).

Text description -> shot plan (local Ollama) -> photoreal scene built in a live Blender through the
MCP for Blender server (Poly Haven HDRI / PBR / models via search_assets + import_asset, layout and
camera via execute_blender_code under safe mode) -> Cycles GPU frames -> MP4.
Blender is started on demand and closed when the frames are done; the Video Studio GPU lock is held
throughout. Entry point: pipeline.render(desc, aspect, work_dir, quality, duration_s, log).
"""
