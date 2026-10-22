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
app always uses its selected workspace. Source integrations lists installed
adapters and lets you enable or disable them without loading disabled code.
Package installation remains a local administrative action. No private plugin is shipped in
the public source or app bundle.

## Local multilingual batches

Paste up to 200 URLs, select the primary language and optional **More languages for URL batches**, then select
**Add to queue**. Each unique URL is processed in each selected language by the
single local worker. A persistent batch manifest survives app restarts; retrying
the same submission after a lost response does not create duplicate jobs.

Pause stops the next job from starting and lets the current job finish. Resume
continues queued jobs. Retry failed jobs resumes only failed, interrupted or
cancelled jobs, retaining completed stages. Completed and listening-review jobs
are preserved. One failed source does not stop the remaining sources.

Exports are automatic for successful batch jobs:
`Exports/Batches/<batch-id>/<podcast-title>/<language>/<version>/`.
Each immutable version includes audio, subtitles, reports and a checksum
manifest. Original sources remain unchanged. Export failures appear on the job;
use **Save export bundle** to retry without regenerating audio. Speech checks do
not establish translation or emotional fidelity; listening review still applies.
No cloud upload or podcast publishing runs in this workflow.

## Catalogue plugins

Trusted private packages may also register `localdub.catalogues` with the same
entry-point name as their source adapter. The factory receives the private
`<workspace>/Plugins/<plugin-name>` directory and returns an object with:

- `providers()`: dictionaries with `id`, `label`, `configured` (never credentials).
- `scan(provider_id)`: an iterator of `{id, title, source}` metadata dictionaries.

Only enabled source plugins are loaded. Configuration and credentials remain
private local files managed by the plugin; never add them to this repository or
an installer. Plugins must enumerate the complete collection or raise an error,
use stable IDs, and never download media in `scan`. The core accepts at most
10,000 unique episodes and rejects conflicting duplicate IDs. A partial scan
never becomes a runnable batch. The normal downloader checks each source and
redirect immediately before fetching media.

Open **Import a podcast collection**, refresh sources, choose a configured source
and **Load all episodes**. Review the count, select **Translate into** above and
choose **Queue collection in selected language**. A durable snapshot records the
import; each job downloads, transcribes, translates, synthesizes and exports
before the next starts. Keep LocalDub open and the Mac awake. After an app
restart, use **Retry failed jobs** for interrupted work; completed jobs stay
untouched. A new import/start creates a new run; it does not deduplicate against
earlier completed batches. Provider credentials are never included in exports.

Jobs are paged in groups of 50, with the active job visible on the first page.
Bulk batches pause before starting another episode when workspace free space
falls below 10 GiB. Free storage and resume the batch. Jobs retain intermediate
audio for recovery, so a large catalogue can require substantial disk space.
Output versions use `<UTC timestamp>-<job ID prefix>-<audio hash prefix>` and
filenames use the sanitized title and language. Same-title episodes remain
distinct through their job IDs and immutable manifests.

## Private export extensions

An enabled source plugin can register the same name in `localdub.exports`,
pointing to `export(job_folder, receipt, config_dir)`. It runs after the normal
immutable export succeeds, including on retry of an existing export. The receipt
contains the generic bundle folder and checksums. Return `None` for unrelated
jobs, or a JSON-serializable result identifying the additional local export.
The config directory is `<workspace>/Plugins/<plugin-name>`. Disabled plugins
never execute. Extensions are trusted local code and must validate identities,
keep paths inside their intended output directory, publish manifests atomically,
retain earlier versions and make retries idempotent. Exceptions are redacted;
the generic bundle is retained and the job shows an export error for retry.
No private layout, mapping or credentials are part of the public app.
