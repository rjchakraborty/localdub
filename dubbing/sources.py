"""Resolve public podcast metadata and download bounded public audio."""
import hashlib
import ipaddress
import json
import socket
import shutil
from contextlib import contextmanager
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit, unquote

import requests
from requests.adapters import HTTPAdapter

MAX_BYTES = 512 * 1024 * 1024


def public_addresses(url: str) -> list[str]:
    if len(url) > 4096:
        raise ValueError("URL exceeds 4096 characters")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Use a public HTTP(S) URL without credentials")
    if parts.port not in {None, 80, 443}:
        raise ValueError("Only standard HTTP(S) ports are supported")
    try:
        addresses = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("Source hostname could not be resolved") from exc
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Private, loopback and reserved network URLs are blocked")
    return sorted({item[4][0] for item in addresses},key=lambda address:ipaddress.ip_address(address).version)


def public_url(url: str) -> str:
    public_addresses(url)
    return url


class PublicAddressAdapter(HTTPAdapter):
    """Connect to the checked address while retaining hostname TLS verification."""
    def __init__(self,address,hostname):
        self.address = address
        self.hostname = hostname
        super().__init__()

    def get_connection_with_tls_context(self,request,verify,proxies=None,cert=None):
        if proxies:
            raise ValueError("Audio downloads cannot use an unverified proxy")
        host,pool = self.build_connection_pool_key_attributes(request,verify,cert)
        host["host"] = self.address
        if host["scheme"]=="https":
            pool["server_hostname"] = self.hostname
            pool["assert_hostname"] = self.hostname
        return self.poolmanager.connection_from_host(**host,pool_kwargs=pool)


@contextmanager
def get_public(url: str, method="GET"):
    for _ in range(6):
        addresses = public_addresses(url)
        parts = urlsplit(url)
        hostname = parts.hostname.encode("idna").decode("ascii")
        host_header = f"[{hostname}]" if ":" in hostname else hostname
        if parts.port:
            host_header += f":{parts.port}"
        for address in addresses[:4]:
            with requests.Session() as session:
                session.trust_env = False
                session.mount(parts.scheme+"://",PublicAddressAdapter(address,hostname))
                try:
                    response = session.request(method,url,headers={"Host":host_header},stream=True,timeout=(15,60),allow_redirects=False)
                except requests.exceptions.SSLError:
                    raise
                except (requests.ConnectionError, requests.Timeout) as exc:
                    last_error = exc
                    continue
                with response:
                    if response.is_redirect:
                        target = response.headers.get("Location")
                        if not target:
                            raise ValueError("Redirect has no destination")
                        url = urljoin(url,target)
                        break
                    response.raise_for_status()
                    yield response
                    return
        else:
            raise last_error
    raise ValueError("Too many redirects")


def bounded_download(url: str, target: Path, limit=MAX_BYTES):
    partial = target.with_suffix(target.suffix + ".part")
    try:
        with get_public(url) as response, partial.open("wb") as output:
            identity = {"etag": response.headers.get("ETag"), "last_modified": response.headers.get("Last-Modified"), "content_length": response.headers.get("Content-Length"), "resolved_url": response.url}
            if int(response.headers.get("Content-Length", "0")) > limit:
                raise ValueError("Remote file exceeds size limit")
            size = 0
            for chunk in response.iter_content(1024 * 256):
                size += len(chunk)
                if size > limit:
                    raise ValueError("Remote file exceeds size limit")
                output.write(chunk)
        if not size:
            raise ValueError("Remote file is empty")
        partial.replace(target)
        return identity
    finally:
        partial.unlink(missing_ok=True)


def reuse_source(url: str, folder: Path):
    """Reuse a locally verified capture when current HTTP metadata confirms freshness."""
    from .settings import home

    for path in (home()/"jobs").glob("*/source.json"):
        if path.parent == folder:
            continue
        metadata = json.loads(path.read_text())
        original = path.parent/"input.audio"
        if metadata.get("audio_url") != url or not original.is_file():
            continue
        try:
            with get_public(url, method="HEAD") as response:
                headers = response.headers
                if int(headers.get("Content-Length", "-1")) != original.stat().st_size:
                    continue
                captured = metadata.get("http", {})
                if captured.get("etag"):
                    fresh = captured["etag"] == headers.get("ETag")
                else:
                    # Legacy captures have no stored ETag; require the server's modification
                    # date to predate the capture and its current size to match.
                    modified = headers.get("Last-Modified")
                    fresh = bool(modified and parsedate_to_datetime(modified).timestamp() <= original.stat().st_mtime)
                if not fresh:
                    continue
                identity = {"etag": headers.get("ETag"), "last_modified": headers.get("Last-Modified"), "content_length": headers.get("Content-Length")}
        except (requests.RequestException, ValueError, OverflowError):
            # Some hosts support GET but reject HEAD. Re-fetch rather than trusting cache.
            continue
        with original.open("rb") as audio:
            digest = hashlib.file_digest(audio,"sha256").hexdigest()
        if digest != metadata.get("sha256"):
            continue
        partial = folder/"input.audio.part"
        shutil.copyfile(original,partial)
        with partial.open("rb") as copied:
            if hashlib.file_digest(copied,"sha256").hexdigest() != digest:
                partial.unlink()
                raise ValueError("Reused audio copy failed identity verification")
        partial.replace(folder/"input.audio")
        return {"http":identity,"reused_source_job":path.parent.name,"reuse_validation":"Current HTTP length/freshness metadata and local SHA256; remote SHA256 is not supplied"}
    return None


def resolve(source: str, folder: Path) -> dict:
    from .integrations import resolve_metadata
    parts = urlsplit(source)
    public_url(source)
    metadata = resolve_metadata(source, folder)
    if metadata is None:
        metadata = {"title": Path(unquote(parts.path)).stem or 'Audio URL', "audio_url": source}
    if not isinstance(metadata,dict) or not isinstance(metadata.get('audio_url'),str):
        raise ValueError('Source adapter did not return an audio URL')
    public_url(metadata['audio_url'])
    reused = reuse_source(metadata["audio_url"],folder)
    if reused:
        metadata.update(reused)
    else:
        metadata["http"] = bounded_download(metadata["audio_url"], folder / "input.audio")
    with (folder / "input.audio").open("rb") as audio:
        metadata["sha256"] = hashlib.file_digest(audio, "sha256").hexdigest()
    return metadata
