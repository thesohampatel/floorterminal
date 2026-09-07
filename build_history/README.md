# Private build records

This is the owner-side audit archive for every native build attempt.

Generated layout:

    YYYY/MM/DD/<build-uuid>/

Each attempt contains `build.log` and `build_record.json`. The record identifies the release profile and stores the exact isolated release directory. Successful records also
retain the exact generated software-information notices. A compact JSON
Lines index is appended at the project root as BUILD_HISTORY.jsonl.

The index and generated record directories are excluded from Git and release
release packages. Back them up securely: records contain release identity and
local build-path metadata, but never integration credentials. Use the environment
variables FLOORTERMINAL_BUILD_PURPOSE and
FLOORTERMINAL_BUILD_DESCRIPTION to label test, evaluation, development, or
special downstream builds.
