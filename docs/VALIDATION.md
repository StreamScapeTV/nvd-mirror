# Validation

Before publication, the generalized source was checked locally with:

```bash
pytest -q
python -m compileall -q app tests
bash -n scripts/*.sh
node --check dashboard-inline.js
```

The source snapshot completed with 44 tests passing and 3 opt-in integration tests skipped. GitHub Actions runs the current repository test matrix and Docker build for every pull request and push to `main`.

Live NVD parity scripts are intentionally excluded from normal deterministic CI because they contact the public NVD service and are rate-limited.
