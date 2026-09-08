# Contributing

Contributions are welcome under the MIT License.

1. Open an issue for substantial behavior or contract changes.
2. Create a focused branch and keep generated build, runtime, credential, and log
   files out of commits.
3. Add or update offline tests. Tests must never contact an external service.
4. Run:

   ```bash
   PYTHONPATH=src python3 -m unittest discover -s tests -v
   ruff check src tests scripts/build/build.py
   ```

5. Explain operational, security, compatibility, and migration effects in the
   pull request.

Do not submit secrets, real connector endpoints, facility names, employee data,
or proprietary third-party documentation. New dependencies require justification,
license review, version constraints, and a security review.

## Checks and dependency maintenance

Changes to `main` go through pull requests with the Python 3.11–3.14 test matrix,
secret scan and CodeQL analysis passing. Keep the branch current, resolve review
conversations and use a squash merge. Do not force-push or delete `main`.
A second reviewer is not mandatory for the sole maintainer; automated checks still
apply. Maintainers remain responsible for reviewing behavior and security effects.

Dependabot proposes routine updates weekly in two groups: Python development tools
and GitHub Actions. Related action steps, including CodeQL initialization and
analysis, should stay on the same pinned release. These proposals are not app
failures and are not automatically merged. Security updates remain separate from
the weekly version-update groups and must be evaluated promptly.

Actions are pinned to immutable upstream commit IDs. A dependency update must keep
those pins, CI tool versions and `pyproject.toml` consistent. Pull requests run CI
once; branch-push CI is reserved for `main` to avoid duplicate bot runs.
