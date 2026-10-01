/**
 * What the operator enters in the sender, per preset, built from what the server says (address, ports, token,
 * topic). The labels are i18n keys under sources.field.
 *
 * Each line was written against the sender's own settings page; before a release every one is checked once
 * against the real thing.
 */

import type { Connection } from '../api/types'

export interface SetupLine {
  label: string
  value: string
  multiline?: boolean
  /** A short hint under the value, i18n key under sources.lineHint. */
  hint?: string
}

// escape makes a value safe inside a JSON string (Proxmox docs, webhook templates); without it a quote in a
// backup log would break the body. Proxmox sends no Content-Type of its own; nexsift reads JSON either way.
const PROXMOX_BODY = `{
  "title": "{{ escape title }}",
  "message": "{{ escape message }}",
  "severity": "{{ severity }}",
  "type": "{{ fields.type }}",
  "host": "{{ fields.hostname }}"
}`

// Paperless 3 fills Jinja placeholders. tojson writes each value as a JSON string itself, so a title with
// quotes still makes valid JSON (measured with Paperless-ngx 3.2.1 on 01.10.2026).
const PAPERLESS_BODY = `{
  "title": {{ ("New document: " ~ doc_title) | tojson }},
  "message": {{ correspondent | tojson }},
  "url": {{ doc_url | tojson }}
}`

/** The same webhook as a shoutrrr address, for tools that only take those. template=json sends the title too. */
function shoutrrrGeneric(url: string): string {
  if (url.startsWith('https://')) return `generic://${url.slice(8)}?template=json`
  return `generic://${url.replace(/^http:\/\//, '')}?disabletls=yes&template=json`
}

export function setupLines(preset: string, connection: Connection): SetupLine[] {
  const c = connection
  switch (preset) {
    case 'watchtower':
      return [
        { label: 'env', value: `WATCHTOWER_NOTIFICATION_URL=${c.shoutrrr}`, hint: 'watchtowerEnv' },
        { label: 'compose', value: `    environment:\n      WATCHTOWER_NOTIFICATIONS: shoutrrr\n      WATCHTOWER_NOTIFICATION_URL: "${c.shoutrrr}"`, multiline: true },
      ]
    case 'proxmox':
      return [
        { label: 'method', value: 'POST' },
        { label: 'url', value: c.url ?? '', hint: 'proxmoxNoHeader' },
        { label: 'body', value: PROXMOX_BODY, multiline: true, hint: 'proxmoxBody' },
      ]
    case 'uptimekuma':
      return [
        { label: 'url', value: c.url ?? '' },
        { label: 'requestBody', value: 'Preset - application/json', hint: 'kumaPreset' },
      ]
    case 'paperless':
      return [
        { label: 'url', value: c.url ?? '' },
        { label: 'body', value: PAPERLESS_BODY, multiline: true, hint: 'paperlessBody' },
      ]
    case 'webhook':
      return [
        { label: 'url', value: c.url ?? '' },
        { label: 'shoutrrr', value: shoutrrrGeneric(c.url ?? ''), hint: 'shoutrrrGeneric' },
        {
          label: 'test',
          value: `curl -X POST ${c.url} -H "Content-Type: application/json" -d '{"title":"Hello","message":"First message","priority":"info"}'`,
          multiline: true,
          hint: 'curlTest',
        },
      ]
    case 'homeassistant':
      return [
        { label: 'server', value: c.server ?? '' },
        { label: 'topic', value: c.topic ?? '' },
      ]
    case 'ntfy':
      return [
        { label: 'server', value: c.server ?? '' },
        { label: 'topic', value: c.topic ?? '' },
        { label: 'test', value: `curl -d "Hello from ntfy" ${c.url}`, hint: 'curlTest' },
      ]
    case 'gotify':
      return [
        { label: 'server', value: c.server ?? '' },
        { label: 'token', value: c.token },
        { label: 'test', value: `curl "${c.server}/message?token=${c.token}" -F "title=Hello" -F "message=First message" -F "priority=5"`, hint: 'curlTest' },
      ]
    case 'discord':
      return [{ label: 'webhookUrl', value: c.url ?? '', hint: 'discordUrl' }]
    case 'synology':
      // DSM 7.2's own webhook (Notification, Webhooks, provider Custom). Not the mail: the mail sender in DSM is
      // one global setting, and pointing it at nexsift would take away the operator's working mail.
      return [
        { label: 'url', value: c.url ?? '' },
        { label: 'method', value: 'POST' },
        { label: 'contentType', value: 'application/json', hint: 'synologyBody' },
      ]
    case 'ups':
    case 'email':
      return [
        { label: 'smtpServer', value: c.server ?? '', hint: 'noAuth' },
        { label: 'smtpPort', value: String(c.port ?? 25) },
        { label: 'recipient', value: c.recipient ?? '', hint: 'recipient' },
        { label: 'sender', value: `nexsift@${c.host}`, hint: 'sender' },
      ]
    case 'syslog':
      return [
        { label: 'syslogServer', value: c.server ?? '' },
        { label: 'syslogPort', value: `${c.port ?? 514} (UDP)` },
        { label: 'syslogHostname', value: c.hostname ?? '', hint: 'syslogHostname' },
      ]
    default:
      return []
  }
}

/** Which preset a source came from, as far as the setup hint is concerned. */
export function presetOf(kind: string, protocol: string): string {
  if (kind !== 'generic') return kind
  return { gotify: 'gotify', ntfy: 'ntfy', discord: 'discord', webhook: 'webhook', smtp: 'email', syslog: 'syslog' }[protocol] ?? 'webhook'
}
