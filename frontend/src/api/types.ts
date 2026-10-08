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
  /** `dashboard-icons/<name>`, `selfhst/<name>` or an own address; empty: two letters. */
  icon: string
  /** Where the interface loads the icon from (through nexsift); null without one. */
  icon_url: string | null
  /** What tapping a push to ntfy opens: the message's link, or the line in nexsift. */
  tap: 'link' | 'nexsift'
  /** The targets its pushes go to; empty: all of them. */
  targets: number[]
  /** The lowest priority pushed from it, in place of each target's minimum; empty: as each target says. */
  min_priority: Priority | ''
}

export interface Connection {
  host: string
  /** Where the host came from: the sender address in Settings, the public address, or the request. */
  host_from: 'sender' | 'public' | 'request'
  /** The internet address the host name leads to, when it leads out instead of home; empty otherwise. */
  host_outside: string
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
  /** The logo a new source of this kind starts with. */
  icon?: string
}

/** One logo of dashboard-icons or selfh.st, as the picker lists it. */
export interface IconName {
  name: string
  icon: string
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
  /** Text keys of the newest event when nexsift worded it; `title_from_texts`: the line's title came from them. */
  texts: Texts | null
  title_from_texts: boolean
  /** The icon a rule gave this line (several apps behind one source); null: show the source's. */
  icon_url: string | null
}

export type TextSegment = { key: string; args: Record<string, string | number> } | { text: string }
/** Words nexsift wrote itself, as text keys; lines of segments joined with " · ". See services/texts.py. */
export interface Texts {
  title?: TextSegment
  body?: TextSegment[][]
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
  texts: Texts | null
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
  /** A logo of the collections or an own address, for the lines this rule matches. */
  icon?: string
  /** The targets the lines this rule matches go to, before the source's choice. */
  targets?: number[]
  /** The lowest priority pushed for these lines, before the source's level and the targets' minimum. */
  min_priority?: Priority
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

export type TargetKind = 'webpush' | 'ntfy' | 'gotify' | 'telegram' | 'pushover' | 'apprise' | 'webhook'

export interface Target {
  id: number
  kind: TargetKind
  name: string
  /** Web Push only: a fingerprint of the device's push address, to recognize this browser. */
  device?: string
  url: string
  chat_id: string
  /** Pushover only: the user or group key. */
  user: string
  has_token: boolean
  min_priority: Priority
  quiet_from: string
  quiet_to: string
  enabled: boolean
  last_ok_at: string | null
  last_error: string
  /** The sources and rules that chose this target, by name (in the list only). */
  chosen_by?: { sources: string[]; rules: string[] }
}

export interface Settings {
  password_login: boolean
  public_url: string
  sender_host: string
  webpush_enabled: boolean
  push_mode: PushMode
  push_language: 'en' | 'de'
  bundle_minutes: number
  throttle_per_minute: number
  storm_enabled: boolean
  storm_count: number
  storm_minutes: number
  retention_days: number
  archive_days: number
  raw_days: number
  backup_schedule: BackupSchedule
  backup_keep: number
  api_keys_allowed: boolean
  /** May nexsift fetch logos from dashboard-icons and selfh.st (from GitHub)? */
  icons_from_web: boolean
  /** Pushes to ntfy carry the source's logo instead of nexsift's. */
  push_source_icons: boolean
}

export type BackupSchedule = 'off' | 'daily' | 'weekly' | 'monthly'
export type BackupKind = 'manual' | 'auto' | 'update'

export interface Backup {
  name: string
  size: number
  created: string
  kind: BackupKind
  note: string
  version: string
  compatible: boolean
  reason: 'ok' | 'backup_newer' | 'unknown_version'
}

export interface BackupList {
  entries: Backup[]
  folder: string
  schedule: BackupSchedule
  keep: number
}

export interface BackupCounts {
  sources: number
  rules: number
  targets: number
  threads: number
  events: number
}

export interface BackupBrief {
  version: string
  created: string
  kind: BackupKind
  note: string
  counts: BackupCounts
  key_in_archive: boolean
  key_from_env: boolean
  compatible: boolean
  reason: Backup['reason']
}

export type LogMode = 'quiet' | 'normal' | 'detailed' | 'trace'

export interface LogModeState {
  mode: LogMode
  until: string | null
  fixed_by_env: boolean
  modes: LogMode[]
  durations: number[]
}

export interface LogEntry {
  time: string
  level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL'
  logger: string
  message: string
  request_id: string | null
  user: string | null
}

export interface ApiKey {
  id: number
  name: string
  prefix: string
  created_at: string
  last_used_at: string | null
}

export interface ApiKeyList {
  allowed: boolean
  keys: ApiKey[]
}

export interface ApiKeyCreated extends ApiKey {
  key: string
}

export interface About {
  version: string
  license: string
  repo_url: string
  releases_url: string
  /** Empty while nexsift has no project page. */
  project_url: string
  ports: Record<string, number>
  doors: Record<string, boolean>
}

/** Whether a newer nexsift is out; asked once a day unless switched off. */
export interface Updates {
  update_check: boolean
  checked: boolean
  latest: string | null
  newer: boolean
  checked_at: string | null
  release_url: string | null
}
