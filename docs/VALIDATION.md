# Validation

Run the deterministic validation suite before merging changes:

```bash
python -m pip install -r requirements-dev.txt
pytest -q
python -m compileall -q app tests
bash -n scripts/*.sh
```

The GitHub Actions CI workflow runs the test suite on Python 3.12, 3.13, and 3.14, compiles the Python sources, validates shell scripts, and builds the runtime container image.

Live NVD parity scripts intentionally remain outside normal deterministic CI because they contact public NVD services and are subject to upstream availability and rate limits.
