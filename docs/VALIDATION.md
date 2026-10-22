# Product acceptance

This document describes the release gate. It is not a claim that every item has
passed. The extracted generic product is currently under validation.

Before a release, record the exact source commit and installer SHA-256 with:

- clean first setup, progress, cancellation/resume and offline cached restart;
- matching package receipt with a missing/recreated Python environment: required
  packages must be restored before model setup; cached checks must work offline;
- native file picker, direct public URL and a mixed batch in both output languages;
- malformed/empty/unsupported files, private/redirect URLs, limits and unavailable storage;
- cancel/resume, changed transcript/translation, selective retries and restart recovery;
- MP3/WAV/captions, output names, immutable export behavior and query redaction;
- real complete recordings in Mandarin and Spanish, transcript coverage, number
  accuracy and listening review for meaning, pronunciation, pauses and voice;
- peak memory and runtime on the stated hardware without concurrent heavy jobs;
- source/dependency/license review, secret scan, standalone tool linkage and signing status.

Unit/API/media tests run in CI without models. They do not certify native UX,
translation quality, emotional fidelity or full inference. Automated readback
flags suspicious speech; `needs_review` must remain visible and cannot be
reported as an accepted output. Keep prior accepted outputs when an experiment
fails. Only use redistributable demonstration audio in the public project.
