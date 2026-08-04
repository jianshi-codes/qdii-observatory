# Third-party notices

Python and frontend dependencies retain their own licenses. The authoritative dependency graph is `pyproject.toml` and `frontend/pnpm-lock.yaml`; distributors must generate and review a dependency license inventory for the exact lockfile and Python environment used by each release.

No third-party fund report, market-data dataset, or complete provider response is bundled as release data. Test fixtures are synthetic or deliberately minimized parser/provider samples and remain subject to the provenance review described in `docs/contributing-parser-fixtures.md`.

The current source dependency review found:

- frontend packages primarily under MIT, Apache-2.0, ISC, 0BSD, or BSD-3-Clause
  terms, with `minimatch` under BlueOak-1.0.0 and `caniuse-lite` data under
  CC-BY-4.0;
- Python packages primarily under permissive terms, with `certifi` and `pathspec` under MPL-2.0 and `psycopg`/`psycopg-binary` under LGPL-3.0-only;
- `pypdfium2` carrying BSD-3-Clause, Apache-2.0, and bundled dependency notices.

This summary is not a substitute for the license files shipped by those packages. Exact versions can change within Python dependency ranges, so distributors must regenerate the inventory from the release image and preserve all required notices and source/relinking obligations.
