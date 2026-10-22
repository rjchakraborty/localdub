"""Explicit opt-in source adapters. Private adapters are installed separately."""
from importlib.metadata import entry_points
import json
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

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


def installed():
    """Inspect package metadata without executing disabled plugin code."""
    return [{'name': item.name, 'version': item.dist.version if item.dist else None}
            for item in entry_points(group='localdub.sources')]


def set_podbean(enabled, plugins=None):
    config = load()
    config.podbean = enabled
    if plugins is not None:
        names = [item['name'] for item in installed()]
        if len(plugins) > 20 or any(names.count(name) != 1 for name in plugins):
            raise ValueError('Source adapter is missing or ambiguous')
        config.plugins = list(dict.fromkeys(plugins))
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

    parts = urlsplit(source)
    host = parts.hostname or ''
    audio_suffix = Path(unquote(parts.path)).suffix.lower() in {
        '.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg', '.opus', '.aif', '.aiff', '.wma'
    }
    # Public enclosure URLs use the same domain as episode pages.
    # Keep direct audio on the normal bounded media-download path.
    if config.podbean and not audio_suffix and (host == 'podbean.com' or host.endswith('.podbean.com')):
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


def export_extensions(folder, receipt):
    """Run enabled trusted export hooks after the generic bundle is committed."""
    results = []
    available = entry_points(group='localdub.exports')
    for name in load().plugins:
        matches = [item for item in available if item.name == name]
        if not matches:
            continue
        if len(matches) != 1:
            raise ValueError('Export adapter is ambiguous: '+name)
        config = home().parent/'Plugins'/name
        config.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            result = matches[0].load()(folder, receipt, config)
        except Exception:
            raise ValueError('Private export adapter '+name+' could not finish. The generic audio bundle is retained; check its entity mapping and export configuration, then retry export.') from None
        if result is not None:
            results.append({'plugin':name, 'result':result})
    return results
