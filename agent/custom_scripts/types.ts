// Spec-first shared contracts for the future email-bot runtime.
// These interfaces intentionally describe the extension surface before a full runtime exists.

export type EvidenceSourceType =
  | "mail_evidence"
  | "material_evidence"
  | "user_declared_rule"
  | "user_confirmed_fact"
  | "agent_inference";

export type ListenerEventType =
  | "thread_entered_state"
  | "thread_sla_risk"
  | "daily_digest_time"
  | "context_updated"
  | "confidence_below_threshold";

export type ActionRiskLevel = "low" | "medium" | "high";
export type PhaseGate = "preflight" | "phase-1" | "phase-2" | "phase-3" | "phase-4" | "phase-5" | "phase-6" | "phase-7";

export interface EvidenceRef {
  sourceType: EvidenceSourceType;
  ref: string;
  note?: string;
}

export interface ContextRef {
  contextId: string;
  factType: string;
  sourceType: EvidenceSourceType;
}

export interface ThreadSnapshot {
  threadKey: string;
  workflowType?: string;
  state?: string;
  stateConfidence?: number;
  ownerGuess?: string;
  waitingOn?: string;
  dueHint?: string;
  riskFlags: string[];
  evidenceRefs: EvidenceRef[];
  contextRefs: ContextRef[];
}

export interface ListenerContext {
  eventType: ListenerEventType;
  phase: PhaseGate;
  occurredAt: string;
  thread?: ThreadSnapshot;
  attentionBudgetRef?: string;
}

export interface ListenerDefinition {
  id: string;
  name: string;
  eventTypes: ListenerEventType[];
  enabledByDefault: boolean;
  minimumPhase: PhaseGate;
  riskLevel: ActionRiskLevel;
  inputRequirements: string[];
  outputTypes: string[];
}

export interface ActionTemplate {
  id: string;
  name: string;
  description: string;
  minimumPhase: PhaseGate;
  riskLevel: ActionRiskLevel;
  requiresHumanReview: boolean;
  requiredThreadFields: string[];
  requiredContextTypes: string[];
  resultSchemaRef?: string;
}

export interface ActionInstance {
  instanceId: string;
  templateId: string;
  threadKey: string;
  workflowType?: string;
  state?: string;
  why: string;
  confidence: number;
  riskLevel: ActionRiskLevel;
  dueHint?: string;
  evidenceRefs: EvidenceRef[];
  contextRefs: ContextRef[];
  proposedPayload: Record<string, unknown>;
  requiresReview: boolean;
  phaseGate: PhaseGate;
}

export interface ActionContext {
  phase: PhaseGate;
  template: ActionTemplate;
  instance: ActionInstance;
  thread: ThreadSnapshot;
}

export interface ActionResult {
  status: "proposed" | "executed" | "rejected" | "failed";
  message: string;
  outputRef?: string;
}

export interface AuditRecord {
  recordId: string;
  recordType: "listener" | "action" | "review";
  occurredAt: string;
  phase: PhaseGate;
  actor: string;
  listenerId?: string;
  templateId?: string;
  instanceId?: string;
  threadKey?: string;
  decision?: string;
  result?: string;
  evidenceRefs: EvidenceRef[];
  contextRefs: ContextRef[];
}
