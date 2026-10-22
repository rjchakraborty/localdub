# LocalDub 0.1.0 preview validation

This preview provides a native Apple Silicon Mac app with automatic Python,
package and model setup, local audio-file and URL inputs, optional public Podbean
resolution, configurable Mandarin/Spanish dubbing, sequential multilingual URL
batches, cancellation/resume and versioned local exports.

## Evidence and scope

The inference code in this release was exercised on a 24 GB M4 Mac mini with two
complete English recordings in both target languages. All four outputs completed
with 298/298 automated speech checks after one targeted Spanish numeric repair.
All 28 final export files matched their manifest hashes. These recordings and
the organization-specific source adapter remain private and are not distributed.

Native start/stop/restart, cached model setup, batch submission and progress were
exercised on the same Mac. Completed work survived restart. Public core tests
cover media decoding and assembly, source validation, API/job controls, batch
idempotency, cancellation, exports, privacy and release verification. The release
candidate records the exact source commit and ZIP checksum; its acceptance asset
records which checks passed and which remain pending.

Source and history are scanned for credentials. The app includes generic code,
standalone tools and their licenses/source notices. No organization plugin,
account configuration, credentials, models or recordings are bundled. No public
repository runner executes on the maintainer's Mac: hosted Linux runs core CI
and publishes a locally built, hash-verified candidate.

## Pending validation and limits

- Human bilingual listening review for meaning, pronunciation, emotion, pauses
  and voice likeness is pending. Automated readback cannot establish these.
- First-setup evidence predates packaging of this exact release commit. A fresh
  clean install and disconnected-network recovery on this exact ZIP are pending.
- Earlier process sampling observed about 4.53 GB peak pipeline RSS; it excluded
  Metal allocations and total machine memory. Controlled performance testing of
  this exact candidate is pending. No broad resource-efficiency claim is made.
- The app is ad-hoc signed and not notarized. macOS may block opening it; no
  Gatekeeper protections are changed. Developer ID distribution is future work.
- Apple Silicon and macOS 26+ are required. Intel, Windows, Linux inference and
  lower-memory Macs are not certified. Initial models use about 7.84 GB of
  downloads; allow at least 25 GB free for setup and working files.
- Cloud catalogue import, private account publishing, multi-speaker diarization
  and guaranteed preservation of emotion or speaker identity are not included.

Review generated recordings before sharing. Model and software licenses are
separate from the application's MIT license; see the third-party notices.
