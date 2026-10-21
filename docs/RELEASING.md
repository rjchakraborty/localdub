# Mac release pipeline

Public contributor tests run on GitHub-hosted Linux. MLX inference and native
packaging run on a trusted Apple Silicon Mac with macOS 26+, Xcode command-line
tools, Python 3.11, a tested inference environment, FFmpeg for tests, and uv
0.11.19. Do not register an everyday development Mac as a public-repository
self-hosted runner. Fork PR code must not reach its credentials or private files.

## Build

Review and commit the complete source. From the tested Python environment:

```sh
python scripts/release.py build --output /absolute/new-release-directory \
  --media-root /absolute/media-build-cache --uv /absolute/path/to/uv
```

The command rejects a dirty checkout, runs source/media/API tests, verifies and
builds FFmpeg/LAME from pinned source, packages the native app with uv and licenses,
verifies its ad-hoc signature, and emits a ZIP, checksums and commit-bound
`candidate.json`. Build caches and outputs must be outside the source checkout.
The build does not claim bit-for-bit reproducibility across Xcode versions.

Current packaging is **ad-hoc signed and not notarized**. Developer ID signing
and notarization require the maintainer's appropriate certificate/profile and
are not implemented yet. Do not describe this as a notarized consumer installer
or disable Gatekeeper to test it. Disclose the signing state in release notes.

## Accept the actual product

Complete [product acceptance](VALIDATION.md) against that exact app and source.
Create an external `acceptance.json` containing the candidate's `commit` and
`sha256`, a `reviewed_at` timestamp, `secrets_reviewed: true`, public-safe `evidence`
references, and a `checks` object with these booleans, each true only if verified:
`first_launch`, `native_ui`, `batch`, `file_and_url`, `mandarin`, `spanish`,
`cancel_resume`, `exports`, `privacy`, `listening_review`, `resource_usage`.
Do not invent acceptance to unblock a release. A test suite pass is insufficient.

## Stage and publish

Use a command-scoped authenticated personal GitHub account. Push the reviewed
commit and a matching lightweight version tag to the intended personal repository.
Wait for main-branch CI to pass. Prepare public release notes and run:

```sh
python scripts/release.py stage --repo OWNER/localdub \
  --package /absolute/new-release-directory/package \
  --acceptance /absolute/acceptance.json --notes /absolute/release-notes.md
```

This verifies the current account, repository, clean commit, remote tag,
installer checksum and acceptance before creating one draft release with assets.
An uncertain network result must be checked on GitHub before retrying. Inspect
the draft and uploaded assets, then dispatch **Publish verified Mac release**
on `main` with its tag. The hosted workflow rechecks artifact/commit acceptance,
main ancestry and successful CI before publishing the draft. No Mac runner or
signing secret is exposed to public PRs.

The source repository and workflows have not yet been published or executed on
GitHub. CI/CD configuration validation and local execution must be distinguished
from an actual hosted run until the first release is completed.
