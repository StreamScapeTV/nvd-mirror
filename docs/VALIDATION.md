# Validation

Run the deterministic application validation suite before merging changes:

```bash
python -m pip install -r requirements-dev.txt
pytest -q
python -m compileall -q app tests
bash -n scripts/*.sh
```

Validate the Helm chart with both its included PostgreSQL deployment and an external database configuration:

```bash
helm lint charts/nvd-mirror \
  --set-string postgresql.auth.password=ci-password \
  --set bootstrap.enabled=false

helm template nvd-mirror charts/nvd-mirror \
  --namespace nvd-mirror \
  --set-string postgresql.auth.password=ci-password \
  --set bootstrap.enabled=false \
  --set ingress.enabled=true \
  --set ingress.className=nginx \
  --set-string ingress.hosts[0].host=nvd.example.org \
  > /tmp/nvd-mirror-internal.yaml

helm template nvd-mirror charts/nvd-mirror \
  --namespace nvd-mirror \
  --set postgresql.enabled=false \
  --set-string database.url='postgresql+psycopg://nvd:password@postgres.example:5432/nvd' \
  --set bootstrap.enabled=false \
  > /tmp/nvd-mirror-external.yaml

helm package charts/nvd-mirror --destination /tmp
```

GitHub Actions runs the application suite on Python 3.12, 3.13, and 3.14, compiles the Python sources, validates shell scripts, builds the runtime container image, lints and renders the chart with Helm 3 and Helm 4, and verifies that the chart can be packaged.

Live NVD parity scripts intentionally remain outside normal deterministic CI because they contact public NVD services and are subject to upstream availability and rate limits.
