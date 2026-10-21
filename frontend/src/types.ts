export type ResourceAction = { type: 'view_document' | 'view_policy' | 'create_ticket' | 'open_tickets' | 'view_ticket' | 'open_policies' | 'open_activities'; label: string; resource_id?: string }
export type Resource = {
  id: string; kind: 'knowledge' | 'policy' | 'service' | 'activity' | 'ticket'; title: string; description: string
  chunk_id?: string; source_url?: string; is_demo?: boolean
  steps?: string[]; materials?: string[]; source?: string; updated_at?: string; meta?: string; action: ResourceAction
}
