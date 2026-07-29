# Contributing

Contributions are welcome through issues and pull requests.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
pytest -q
python -m compileall -q app tests
bash -n scripts/*.sh
```

Please keep changes focused, add regression coverage, avoid live NVD calls in deterministic tests, preserve `.meta`-first synchronization and atomic replacement, document environment variables, and never commit secrets or runtime data.

Changes to `/rest/json/cves/2.0` must state whether behavior matches the official API or is a local best-effort implementation.
