# Changelog

## 0.1.2

- `python:3.12-slim` re-pinned to the 2026-10-06 digest (3.12.15) for
  Debian's `perl-base` 5.40.1-6+deb13u1 — clears the image's three critical
  findings (CVE-2026-13221, CVE-2026-42496, CVE-2026-8376)

## 0.1.0

- Initial scaffold
- FastAPI service with /arrange endpoint
- LLM client for bossa transformations
- Arrangement pipeline: split → transform → assemble
