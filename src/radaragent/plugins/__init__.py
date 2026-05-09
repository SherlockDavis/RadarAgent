from radaragent.plugins.base import SourcePlugin
from radaragent.plugins.examples import ArxivPlugin, HackerNewsPlugin, SECEdgarPlugin
from radaragent.plugins.http_api import HTTPAPIPlugin
from radaragent.plugins.rss import RSSPlugin

PLUGIN_REGISTRY: dict[str, type[SourcePlugin]] = {
    "rss": RSSPlugin,
    "http_api": HTTPAPIPlugin,
    "hackernews": HackerNewsPlugin,
    "arxiv": ArxivPlugin,
    "sec_edgar": SECEdgarPlugin,
}


def build_plugin(plugin_type: str, plugin_id: str, config: dict) -> SourcePlugin:
    """Instantiate a SourcePlugin from a registered type."""
    try:
        cls = PLUGIN_REGISTRY[plugin_type]
    except KeyError as exc:
        raise ValueError(
            f"unknown plugin type {plugin_type!r}; registered: {sorted(PLUGIN_REGISTRY)}"
        ) from exc
    return cls(plugin_id=plugin_id, config=config)


__all__ = [
    "PLUGIN_REGISTRY",
    "ArxivPlugin",
    "HTTPAPIPlugin",
    "HackerNewsPlugin",
    "RSSPlugin",
    "SECEdgarPlugin",
    "SourcePlugin",
    "build_plugin",
]
