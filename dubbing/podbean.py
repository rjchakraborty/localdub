"""Extract one audio enclosure from a specific public Podbean episode."""
import json
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup


def podbean_episode(html, page_url):
    host = (urlsplit(page_url).hostname or '').lower()
    if host != 'podbean.com' and not host.endswith('.podbean.com'):
        raise ValueError('Expected a Podbean episode page')
    soup = BeautifulSoup(html, 'html.parser')

    def objects(value, depth=0):
        if depth > 8:
            return
        if isinstance(value, list):
            for item in value:
                yield from objects(item, depth+1)
        elif isinstance(value, dict):
            yield value
            yield from objects(value.get('@graph'), depth+1)

    candidates = {}
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.get_text())
        except (json.JSONDecodeError, RecursionError):
            continue
        for episode in objects(data):
            kind = episode.get('@type', [])
            if isinstance(kind, str):
                kind = [kind]
            if 'PodcastEpisode' not in kind:
                continue
            canonical = episode.get('url')
            if canonical is not None and not isinstance(canonical, str):
                continue
            if canonical and urlsplit(page_url).path.startswith('/e/') and urlsplit(urljoin(page_url, canonical)).path.rstrip('/') != urlsplit(page_url).path.rstrip('/'):
                continue
            media = episode.get('associatedMedia', episode.get('encoding', []))
            if isinstance(media, dict):
                media = [media]
            for item in media if isinstance(media, list) else []:
                if not isinstance(item, dict):
                    continue
                audio = item.get('contentUrl')
                if isinstance(audio, str) and audio.strip():
                    url = urljoin(page_url, audio.strip())
                    if urlsplit(url).scheme not in {'https', 'http'}:
                        continue
                    title = episode.get('name') or (soup.title.get_text() if soup.title else 'Podcast episode')
                    candidates[url] = {'title': str(title)[:500], 'page_url': page_url, 'audio_url': url}
    if len(candidates) != 1:
        raise ValueError('Provide a specific Podbean episode with one unambiguous audio enclosure')
    return next(iter(candidates.values()))
