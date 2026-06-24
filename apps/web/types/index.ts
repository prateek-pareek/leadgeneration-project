// ============================================================
// ProspectOS — Core TypeScript types
// ============================================================

export type UUID = string;
export type ISODate = string;

// ── Auth ──────────────────────────────────────────────────────

export type UserRole = "owner" | "admin" | "member" | "viewer";

export interface User {
  id: UUID;
  orgId: UUID;
  email: string;
  name: string;
  avatarUrl: string | null;
  role: UserRole;
  lastLoginAt: ISODate | null;
  createdAt: ISODate;
}

export interface AuthTokens {
  accessToken: string;
  refreshToken: string;
  expiresAt: ISODate;
  user: User;
}

// ── Organization ──────────────────────────────────────────────

export interface Organization {
  id: UUID;
  name: string;
  slug: string;
  plan: string;
  settings: Record<string, unknown>;
  createdAt: ISODate;
}

// ── Sources ───────────────────────────────────────────────────

export type SourceType =
  | "hackernews"
  | "reddit"
  | "x"
  | "producthunt"
  | "indiehackers"
  | "github"
  | "manual";

export interface Source {
  id: UUID;
  orgId: UUID;
  name: string;
  type: SourceType;
  config: Record<string, unknown>;
  isActive: boolean;
  lastRunAt: ISODate | null;
  nextRunAt: ISODate | null;
  createdAt: ISODate;
}

// ── Posts ─────────────────────────────────────────────────────

export interface PostEngagement {
  upvotes?: number;
  comments?: number;
  likes?: number;
  shares?: number;
  points?: number;
}

export interface Post {
  id: UUID;
  orgId: UUID;
  sourceId: UUID | null;
  authorId: UUID | null;
  externalId: string | null;
  platform: SourceType;
  url: string;
  text: string;
  title: string | null;
  postedAt: ISODate | null;
  engagement: PostEngagement;
  language: string;
  sourceConfidence: number | null;
  isProcessed: boolean;
  discoveredAt: ISODate;
}

// ── Authors ───────────────────────────────────────────────────

export interface Author {
  id: UUID;
  platform: string;
  handle: string;
  displayName: string | null;
  profileUrl: string | null;
  bio: string | null;
  followersCount: number | null;
  website: string | null;
}

// ── Companies ─────────────────────────────────────────────────

export type CompanyStage =
  | "idea"
  | "pre-seed"
  | "seed"
  | "early"
  | "growth"
  | "unknown";

export interface Company {
  id: UUID;
  name: string;
  website: string | null;
  domain: string | null;
  description: string | null;
  stage: CompanyStage | null;
  sizeEstimate: string | null;
  industry: string | null;
  linkedinUrl: string | null;
  twitterHandle: string | null;
}

// ── Leads ─────────────────────────────────────────────────────

export type PipelineStage =
  | "Discovered"
  | "Qualified"
  | "Researched"
  | "Comment Drafted"
  | "Comment Posted"
  | "Replied"
  | "Connection Sent"
  | "DM Drafted"
  | "Email Drafted"
  | "Email Sent"
  | "Meeting Booked"
  | "Proposal Sent"
  | "Won"
  | "Lost"
  | "Nurture";

export const PIPELINE_STAGES: PipelineStage[] = [
  "Discovered",
  "Qualified",
  "Researched",
  "Comment Drafted",
  "Comment Posted",
  "Replied",
  "Connection Sent",
  "DM Drafted",
  "Email Drafted",
  "Email Sent",
  "Meeting Booked",
  "Proposal Sent",
  "Won",
  "Lost",
  "Nurture",
];

export interface Lead {
  id: UUID;
  orgId: UUID;
  authorId: UUID | null;
  companyId: UUID | null;
  postId: UUID | null;
  source: string;
  status: string;
  pipelineStage: PipelineStage;
  ownerId: UUID | null;
  tags: string[];
  nextAction: string | null;
  nextActionAt: ISODate | null;
  lastContactAt: ISODate | null;
  isSuppressed: boolean;
  createdAt: ISODate;
  updatedAt: ISODate;
  // Joined fields
  author?: Author;
  company?: Company;
  post?: Post;
  latestScore?: LeadScore;
  latestResearch?: ResearchBrief;
}

// ── Research ──────────────────────────────────────────────────

export interface ResearchBrief {
  id: UUID;
  leadId: UUID;
  companyName: string | null;
  companyDescription: string;
  companyStage: string;
  companySize: string;
  founderConfidence: number;
  isDecisionMaker: boolean | null;
  painPoints: string[];
  budgetSignal: string;
  techMaturity: string;
  serviceFit: string[];
  engagementAngle: string;
  briefText: string;
  confidenceOverall: number;
  uncertainFields: string[];
  sourcesUsed: string[];
  modelUsed: string;
  createdAt: ISODate;
}

// ── Scoring ───────────────────────────────────────────────────

export type ScoreBucket = "hot" | "warm" | "cold" | "ignore";

export interface DimensionScores {
  buying_intent: number;
  decision_maker: number;
  recency: number;
  service_fit: number;
  company_legitimacy: number;
  urgency: number;
  engagement: number;
  reply_likelihood: number;
}

export interface LeadScore {
  id: UUID;
  leadId: UUID;
  score: number;
  bucket: ScoreBucket;
  scoreVersion: string;
  dimensionScores: DimensionScores;
  topSignals: string[];
  explanation: string;
  recommendedAction: string;
  scoredAt: ISODate;
}

// ── Comments ──────────────────────────────────────────────────

export type CommentVariantType = "concise" | "insightful" | "founder_friendly";

export interface CommentVariant {
  type: CommentVariantType;
  text: string;
  tone: string;
}

export type CommentDraftStatus =
  | "pending_approval"
  | "approved"
  | "rejected"
  | "posted"
  | "cancelled";

export interface CommentDraft {
  id: UUID;
  leadId: UUID;
  postId: UUID | null;
  variants: CommentVariant[];
  selectedVariant: CommentVariant | null;
  contextUsed: string;
  status: CommentDraftStatus;
  approvedBy: UUID | null;
  approvedAt: ISODate | null;
  postedAt: ISODate | null;
  postedUrl: string | null;
  rejectionReason: string | null;
  createdAt: ISODate;
}

// ── Approvals ─────────────────────────────────────────────────

export type ApprovalType = "comment_draft" | "outreach_draft";
export type ApprovalStatus = "pending" | "approved" | "rejected";

export interface Approval {
  id: UUID;
  orgId: UUID;
  type: ApprovalType;
  refId: UUID;
  leadId: UUID | null;
  status: ApprovalStatus;
  assignedTo: UUID | null;
  decidedBy: UUID | null;
  decisionAt: ISODate | null;
  decisionNotes: string | null;
  createdAt: ISODate;
  // Joined
  lead?: Lead;
  commentDraft?: CommentDraft;
}

// ── Email Health ──────────────────────────────────────────────

export interface Domain {
  id: UUID;
  domain: string;
  isPrimary: boolean;
  healthScore: number | null;
  lastCheckedAt: ISODate | null;
  createdAt: ISODate;
}

export interface DomainCheck {
  id: UUID;
  domainId: UUID;
  spfValid: boolean | null;
  spfRecord: string | null;
  dkimValid: boolean | null;
  dkimSelectors: string[];
  dmarcValid: boolean | null;
  dmarcPolicy: string | null;
  mxRecords: string[];
  blacklistsHit: string[];
  blacklistClean: boolean | null;
  healthScore: number | null;
  checkedAt: ISODate;
}

// ── Tasks ─────────────────────────────────────────────────────

export type TaskPriority = "low" | "medium" | "high";
export type TaskStatus = "open" | "done" | "cancelled";

export interface Task {
  id: UUID;
  leadId: UUID | null;
  assignedTo: UUID | null;
  title: string;
  description: string | null;
  dueAt: ISODate | null;
  priority: TaskPriority;
  status: TaskStatus;
  completedAt: ISODate | null;
  createdAt: ISODate;
}

// ── Analytics ─────────────────────────────────────────────────

export interface AnalyticsOverview {
  leadsDiscovered: number;
  hotLeads: number;
  commentsDrafted: number;
  commentsPosted: number;
  repliesReceived: number;
  emailsSent: number;
  meetingsBooked: number;
  conversionRate: number;
}

// ── Pagination ────────────────────────────────────────────────

export interface PaginatedResponse<T> {
  data: T[];
  total: number;
  limit: number;
  offset: number;
}

// ── Alerts ────────────────────────────────────────────────────

export type AlertSeverity = "info" | "warning" | "critical";

export interface Alert {
  id: UUID;
  type: string;
  severity: AlertSeverity;
  title: string;
  description: string | null;
  resourceType: string | null;
  resourceId: UUID | null;
  isRead: boolean;
  resolvedAt: ISODate | null;
  createdAt: ISODate;
}
