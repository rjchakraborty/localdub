# Contributing

Open an issue describing the source format, expected result and reproducible
steps. Use an audio sample you may redistribute; remove private content and URL
credentials. For audio quality reports, include language, model options and the
smallest relevant passage. Machine readback scores alone do not establish quality.

Use Python 3.11. Run the tests and public-tree check described in the README.
Keep changes focused and include a regression test for a confirmed defect.
Test UI changes in the native app as well as the backend. Model changes require
actual speech samples and listening review, with their licenses documented.

Do not commit virtual environments, models, generated audio, secrets or private
integrations. Contributions to application code are accepted under MIT; retain
third-party notices. Release builds are made from reviewed commits on a trusted
Mac. Fork pull requests never execute on the maintainer's Mac.
