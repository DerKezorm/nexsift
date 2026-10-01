/** The shapes the server delivers. Names follow the backend (snake_case), so nothing gets lost in translation. */

export type Priority = 'crit' | 'warn' | 'info'
export type Protocol = 'gotify' | 'ntfy' | 'discord' | 'webhook' | 'smtp' | 'syslog'
export type ThreadState = 'unread' | 'read' | 'archived'
export type View = 'inbox' | 'unread' | 'crit' | 'archived'
export type PushMode = 'immediate' | 'window' | 'single' | 'never'

export interface Account {
  id: number
  name: string
  email: string
  oidc_linked: boolean
  prefs: Record<string, unknown>
}

export interface Link {
  label: string
  url: string
}

export interface Source {
  id: number
  name: string
  kind: string
  protocol: Protocol
  created_at: string
  last_seen_at: string | null
  count_total: number
  muted_until: string | null
  unrecognized_streak: number
  last_unrecognized_at: string | null
}

export interface Connection {
  host: string
  /** Where the host came from: the sender address in Settings, the public address, or the request. */
  host_from: 'sender' | 'public' | 'request'
  ports: Record<string, number>
  token: string
  server?: string
  shoutrrr?: string
  topic?: string
  url?: string
  port?: number
  recipient?: string
  hostname?: string
}

export type SourceWithConnection = Source & { connection: Connection }

export interface Preset {
  key: string
  kind: string
  protocol: Protocol
  name: string
}

export interface Stranger {
  protocol: 'smtp' | 'syslog' | 'ntfy'
  key: string
  count: number
  first_at: string
  last_at: string
  sample: string
  peer: string
}

export interface ThreadSummary {
  id: number
  source_id: number
  title: string
  priority: Priority
  state: ThreadState
  event_count: number
  first_at: string
  last_at: string
  resolved_at: string | null
  resolved_by: string
  throttled_count: number
  pushed: boolean
  /** A source's routine: different info messages in one line, titled by their count. */
  routine: boolean
  preview: string
  links: Link[]
}

export interface NsEvent {
  id: number
  received_at: string
  title: string
  body: string
  priority: Priority
  links: Link[]
  raw: string
  recognized: boolean
}

export interface DeliveryInfo {
  id: number
  target: string
  target_kind: string
  kind: 'first' | 'followup' | 'allclear' | 'storm' | 'test'
  status: 'pending' | 'sent' | 'failed'
  attempts: number
  created_at: string
  sent_at: string | null
  last_error: string
}

export interface ThreadDetail extends ThreadSummary {
  rule_names: string[]
  push_mode: string
  window_until: string | null
  events: NsEvent[]
  deliveries: DeliveryInfo[]
}

export interface Counts {
  views: Record<View, number>
  unread_by_source: Record<string, number>
}

export interface Condition {
  field: 'any' | 'title' | 'body'
  op: 'word' | 'contains' | 'regex'
  value: string
}

export interface RuleActions {
  priority?: Priority
  group_key?: string
  title_template?: string
  resolves?: string
  push?: PushMode
  drop?: boolean
}

export interface Rule {
  id: number
  position: number
  name: string
  enabled: boolean
  source_id: number | null
  conditions: Condition[]
  actions: RuleActions
  built_in: string
}

export type TargetKind = 'ntfy' | 'gotify' | 'telegram' | 'apprise' | 'webhook'

export interface Target {
  id: number
  kind: TargetKind
  name: string
  url: string
  chat_id: string
  has_token: boolean
  min_priority: Priority
  quiet_from: string
  quiet_to: string
  enabled: boolean
  last_ok_at: string | null
  last_error: string
}

export interface Settings {
  password_login: boolean
  public_url: string
  sender_host: string
  push_mode: PushMode
  bundle_minutes: number
  throttle_per_minute: number
  storm_enabled: boolean
  storm_count: number
  storm_minutes: number
  retention_days: number
  archive_days: number
  raw_days: number
}

export interface About {
  version: string
  ports: Record<string, number>
  doors: Record<string, boolean>
}
