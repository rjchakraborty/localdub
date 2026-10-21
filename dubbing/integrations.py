"""Explicit opt-in source adapters. Private adapters are installed separately."""
from importlib.metadata import entry_points
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field
from .settings import home


class Integrations(BaseModel):
    model_config = ConfigDict(extra='forbid')
    podbean: bool = False
    plugins: list[str] = Field(default_factory=list, max_length=20)


def config_path():
    value = os.environ.get('LOCALDUB_CONFIG')
    if value:
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError('LOCALDUB_CONFIG must be an absolute path')
        return path
    return home().parent/'integrations.json'


def load():
    path = config_path()
    return Integrations.model_validate_json(path.read_text()) if path.exists() else Integrations()


def set_podbean(enabled):
    config = load()
    config.podbean = enabled
    path = config_path(); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(config.model_dump(), indent=2))
    temporary.chmod(0o600)
    temporary.replace(path)
    return config


def resolve_metadata(source, folder):
    from .sources import bounded_download
    config = load()

    def fetch_page(url):
        page = folder/'source-page.html'
        capture = bounded_download(url, page, limit=8*1024*1024)
        return page.read_text(), capture['resolved_url']

    host = urlsplit(source).hostname or ''
    if config.podbean and (host == 'podbean.com' or host.endswith('.podbean.com')):
        from .podbean import podbean_episode
        if urlsplit(source).path in {'', '/'}:
            raise ValueError('Provide a specific Podbean episode URL, not the show homepage')
        html, final_url = fetch_page(source)
        return podbean_episode(html, final_url)
    available = entry_points(group='localdub.sources')
    for name in config.plugins:
        matches = [item for item in available if item.name == name]
        if len(matches) != 1:
            raise ValueError('Enabled source adapter is missing or ambiguous: '+name)
        # Installing and enabling Python packages is a local trust decision.
        result = matches[0].load()(source, fetch_page)
        if result is not None:
            return result
    return None
