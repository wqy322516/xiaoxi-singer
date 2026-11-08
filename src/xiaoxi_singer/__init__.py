"""xiaoxi-singer: a callable singing-voice agent.

Public surfaces:
    * ``xiaoxi_singer.engine``  -- RVC voice conversion (chunked, GPU friendly)
    * ``xiaoxi_singer.post``    -- post-processing chain (brightness / gate / reverb)
    * ``xiaoxi_singer.mix``     -- loudness-aligned vocal + instrumental mixing
    * ``xiaoxi_singer.pipeline``-- the full "cover" job
    * ``xiaoxi_singer.server``  -- HTTP API
    * ``xiaoxi_singer.mcp_server`` -- MCP tools for LLM agents
"""

from .config import Settings, settings

__all__ = ["Settings", "settings", "__version__"]
__version__ = "0.2.0"
