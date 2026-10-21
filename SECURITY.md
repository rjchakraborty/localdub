# Security and privacy

LocalDub is a single-user localhost application. Do not expose its HTTP service
to a LAN or the internet. It validates the loopback Host header and requires a
per-process token for state-changing requests. Downloads reject private,
loopback and reserved addresses, validate redirects, pin the checked connection
address and bound the byte count. FFmpeg input protocols are restricted.

Model revisions are pinned and downloaded files are verified on first setup.
Optional source plugins are trusted executable Python packages; install only
code you have reviewed. Models and dependencies can still contain defects.

Recordings, transcripts, signed source URLs and logs stay in the selected local
workspace. This is not an encrypted vault. Exported JSON strips URL queries and
userinfo, but spoken content, titles and transcripts may contain personal data.
Review files before sharing and use OS account/file protection for private work.

Never commit `.env`, credentials, model weights, job output, recordings or private
plugins. The public-tree check is a release guard, not a complete secret scanner.
Run a dedicated secret scan and inspect the actual Git diff before publication.

Use GitHub private vulnerability reporting after it is enabled for the repository.
Do not post credentials or private recordings in public issues.
