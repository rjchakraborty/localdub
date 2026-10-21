# Optional sources

By default LocalDub accepts a local file or a direct HTTP(S) audio URL.
It does not contain organization-specific page parsing, database connections or
account configuration.

## Podbean

Enable **Public Podbean episodes** in Source integrations. Paste a specific public
episode URL, not the show homepage. The resolver reads the public audio enclosure;
no Podbean client ID, secret or token is required. Private/premium episodes and
the authenticated Podbean management API are not implemented.

## S3 and Google Cloud Storage

Public objects and signed HTTPS download URLs work through the normal URL input.
Generate a read-only URL with sufficient lifetime to finish the download in your
provider's console or CLI. A URL must point to the audio bytes, not a console page.
Do not paste access keys or service-account JSON into LocalDub. Raw `s3://` and
`gs://` paths and authenticated bucket browsing are not supported in this release.
If a signed URL expires, submit a fresh URL as a new job. Private endpoint and
loopback hosts are intentionally rejected, including redirect targets.

## Private source plugins

A separately installed trusted Python package can declare an entry point:

```toml
[project.entry-points."localdub.sources"]
my-private-source = "my_private_source:resolve"
```

Its function is `resolve(url, fetch_page)`. Return `None` for a URL it does not
handle, or a dictionary containing `audio_url` and optionally `title`. The
`fetch_page(url)` callback returns `(html, final_url)` using the core's bounded
public-network downloader. The returned audio URL is independently validated
before download. Plugins run as trusted local Python code, not in a sandbox.

Install private packages into the same Python runtime as LocalDub. Keep their
source and credentials in a separate private location. For the native app the
runtime is `<selected workspace>/Runtime/venv/bin/python`; install with the
bundled uv's `pip install --python <that path> <private package directory>`.
Restart the engine after changing plugins.

Enable only explicitly installed entry-point names in
`<workspace>/integrations.json` (the parent of `DUBBING_HOME` for source runs):

```json
{"podbean": false, "plugins": ["my-private-source"]}
```

Source runs may override this path with an absolute `LOCALDUB_CONFIG`. The native
app always uses its selected workspace. The UI can toggle Podbean but cannot
install or enable arbitrary Python packages. No private plugin is shipped in
the public source or app bundle.
