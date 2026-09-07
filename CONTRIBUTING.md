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
