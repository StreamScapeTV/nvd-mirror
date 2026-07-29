{{- define "nvd-mirror.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "nvd-mirror.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "nvd-mirror.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "nvd-mirror.labels" -}}
helm.sh/chart: {{ include "nvd-mirror.chart" . }}
{{ include "nvd-mirror.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "nvd-mirror.selectorLabels" -}}
app.kubernetes.io/name: {{ include "nvd-mirror.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "nvd-mirror.postgresqlSelectorLabels" -}}
app.kubernetes.io/name: {{ include "nvd-mirror.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: postgresql
{{- end }}

{{- define "nvd-mirror.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "nvd-mirror.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "nvd-mirror.image" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) }}
{{- end }}

{{- define "nvd-mirror.postgresqlFullname" -}}
{{- printf "%s-postgresql" (include "nvd-mirror.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "nvd-mirror.postgresqlSecretName" -}}
{{- printf "%s-postgresql" (include "nvd-mirror.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "nvd-mirror.databaseUrl" -}}
{{- if .Values.postgresql.enabled -}}
{{- printf "postgresql+psycopg://%s:%s@%s:%v/%s" (.Values.postgresql.auth.username | urlquery) (.Values.postgresql.auth.password | urlquery) (include "nvd-mirror.postgresqlFullname" .) .Values.postgresql.service.port (.Values.postgresql.auth.database | urlquery) -}}
{{- else -}}
{{- required "database.url must be set when postgresql.enabled=false and database.existingSecret is empty" .Values.database.url -}}
{{- end -}}
{{- end }}

{{- define "nvd-mirror.validateValues" -}}
{{- if ne (int .Values.replicaCount) 1 -}}
{{- fail "replicaCount must remain 1 because the scheduler and local mirror are singleton resources" -}}
{{- end -}}
{{- if and .Values.postgresql.enabled (empty .Values.postgresql.auth.password) -}}
{{- fail "postgresql.auth.password is required when postgresql.enabled=true" -}}
{{- end -}}
{{- if and (not .Values.postgresql.enabled) (empty .Values.database.existingSecret) (empty .Values.database.url) -}}
{{- fail "set database.existingSecret or database.url when postgresql.enabled=false" -}}
{{- end -}}
{{- end }}

{{- define "nvd-mirror.secretEnv" -}}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      {{- if .Values.database.existingSecret }}
      name: {{ .Values.database.existingSecret | quote }}
      key: {{ .Values.database.existingSecretKey | quote }}
      {{- else }}
      name: {{ include "nvd-mirror.fullname" . }}
      key: DATABASE_URL
      {{- end }}
- name: NVD_API_KEY
  valueFrom:
    secretKeyRef:
      {{- if .Values.nvdApiKey.existingSecret }}
      name: {{ .Values.nvdApiKey.existingSecret | quote }}
      key: {{ .Values.nvdApiKey.existingSecretKey | quote }}
      {{- else }}
      name: {{ include "nvd-mirror.fullname" . }}
      key: NVD_API_KEY
      {{- end }}
{{- end }}

{{- define "nvd-mirror.commonVolumeMounts" -}}
- name: mirror
  mountPath: {{ .Values.config.nvdFeedMirrorDir | quote }}
{{- if .Values.certificates.existingSecret }}
- name: certificates
  mountPath: {{ .Values.certificates.mountPath | quote }}
  readOnly: true
{{- end }}
{{- with .Values.extraVolumeMounts }}
{{ toYaml . }}
{{- end }}
{{- end }}
