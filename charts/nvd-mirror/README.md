# nvd-mirror Helm chart

This chart deploys the NVD Mirror API, dashboard, scheduler, persistent raw-feed storage, and optionally a single-instance PostgreSQL database.

The API and scheduler run as two containers in one pod and share the same mirror volume. The Deployment uses the `Recreate` strategy so `ReadWriteOnce` storage does not create multi-attach failures during upgrades.

## Release artifacts

Release `v0.2.0` aligns the application and chart versions:

```text
Application image: ghcr.io/streamscapetv/nvd-mirror:0.2.0
Helm chart:        oci://ghcr.io/streamscapetv/charts/nvd-mirror --version 0.2.0
```

The chart uses its `appVersion` as the default application image tag, so installing chart `0.2.0` pulls image `0.2.0` unless `image.tag` is overridden.

## Install from GitHub Container Registry

Published releases are OCI Helm artifacts:

```bash
helm upgrade --install nvd-mirror \
  oci://ghcr.io/streamscapetv/charts/nvd-mirror \
  --version 0.2.0 \
  --namespace nvd-mirror \
  --create-namespace \
  --set-string postgresql.auth.password='replace-with-a-strong-password'
```

The first installation runs the historical bootstrap in an init container by default. The API starts after bootstrap succeeds. A completion marker on the mirror PVC prevents repeated full bootstraps.

Disable automatic bootstrap when attaching an existing populated database:

```bash
--set bootstrap.enabled=false
```

## Install from the repository

Source contributors can install the checked-out chart directly:

```bash
helm upgrade --install nvd-mirror ./charts/nvd-mirror \
  --namespace nvd-mirror \
  --create-namespace \
  --set-string postgresql.auth.password='replace-with-a-strong-password'
```

## Ingress

```bash
helm upgrade --install nvd-mirror \
  oci://ghcr.io/streamscapetv/charts/nvd-mirror \
  --version 0.2.0 \
  --namespace nvd-mirror \
  --create-namespace \
  --set-string postgresql.auth.password='replace-with-a-strong-password' \
  --set ingress.enabled=true \
  --set ingress.className=nginx \
  --set ingress.hosts[0].host=nvd.example.org \
  --set ingress.tls[0].secretName=nvd-example-tls \
  --set ingress.tls[0].hosts[0]=nvd.example.org
```

The dashboard is available at `/dashboard`; the compatible CVE endpoint is `/rest/json/cves/2.0`.

## External PostgreSQL

Create a Secret containing the complete SQLAlchemy URL:

```bash
kubectl -n nvd-mirror create secret generic nvd-mirror-database \
  --from-literal=DATABASE_URL='postgresql+psycopg://user:password@postgres.example:5432/nvd'
```

Then install with:

```bash
helm upgrade --install nvd-mirror \
  oci://ghcr.io/streamscapetv/charts/nvd-mirror \
  --version 0.2.0 \
  --namespace nvd-mirror \
  --create-namespace \
  --set postgresql.enabled=false \
  --set database.existingSecret=nvd-mirror-database \
  --set bootstrap.enabled=false
```

Set `bootstrap.enabled=true` when the external database is empty and should be populated by the chart.

## Existing mirror PVC

```bash
--set persistence.existingClaim=my-nvd-mirror-pvc
```

The PVC must support the access mode selected in `persistence.accessModes`. One replica is intentional because the scheduler and local raw mirror are singleton resources.

## Private CA or application TLS files

Mount an existing Secret under `/certs`:

```bash
--set certificates.existingSecret=nvd-mirror-certificates \
--set config.upstreamCaBundle=/certs/ca.crt
```

Ingress TLS is recommended instead of application-level TLS.

## Important values

| Value | Default | Description |
|---|---:|---|
| `image.repository` | `ghcr.io/streamscapetv/nvd-mirror` | Application image repository |
| `image.tag` | chart `appVersion` | Application image tag |
| `bootstrap.enabled` | `true` | Run resumable historical bootstrap before the API starts |
| `persistence.size` | `20Gi` | Raw feed mirror PVC size |
| `postgresql.enabled` | `true` | Deploy the included single-instance PostgreSQL StatefulSet |
| `postgresql.auth.password` | empty | Required when included PostgreSQL is enabled |
| `database.existingSecret` | empty | Secret containing `DATABASE_URL` for an external database |
| `scheduler.enabled` | `true` | Run the built-in scheduler sidecar |
| `ingress.enabled` | `false` | Create a Kubernetes Ingress |
| `resources.limits.memory` | `1Gi` | API memory limit |
| `scheduler.resources.limits.memory` | `1Gi` | Scheduler memory limit |

See [`values.yaml`](values.yaml) for all settings.
