{{/*
Expand the name of the chart.
*/}}
{{- define "aci-pong.name" -}}
aci-pong
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "aci-pong.fullname" -}}
{{ .Release.Name }}-aci-pong
{{- end }}

{{/*
Chart name and version.
*/}}
{{- define "aci-pong.chart" -}}
{{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}