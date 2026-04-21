Amazingtools_clientcentric

Remake Amazing tools to Client Centric Platform AI PowerHouse

# AmazingTools — Customer-Centric Platform Rebuild

## Master Coding Prompt for AI-Coder / Dev Team

You are a senior full-stack engineer, product architect, and AI systems designer. Your job is to rebuild **AmazingTools** from a tool-centric dashboard into a **customer-centric operating system** for SEO and AI-driven marketing service delivery.

This document is the complete implementation specification. Everything below is in scope. Do not skip sections. Do not simplify the data model. Do not collapse advisory/full service into a cosmetic flag.

-----

## 0. Context & Non-Negotiables

**Current state**: The app is a grid of independent tools (AI Visibility Tracker, SEO Crawler, QueryMatch, IPR Sandbox, Page Simulator, Marketing Agents). Each tool asks the user to re-enter customer info. Outputs are siloed. Chat (“MEVO”) is global and context-less.

**Target state**: The platform’s primary entity is the **Customer**. The first screen is a customer list. Everything else — tools, agents, insights, tasks, reports, chat — is scoped to a customer. Customer context is shared across all modules.

**Hard rules:**

1. The first action in the app is **select or create a customer**. Tools are never the landing page.
1. Customer context (domain, goals, competitors, integrations, history) is entered **once** and shared across every module.
1. Every module output becomes a **structured record** (Insight, Recommendation, Task, Deliverable) attached to the customer — not a raw text blob.
1. **Service mode** (Advisory vs Full service) is a behavioral switch, not cosmetic. It alters what agents are allowed to do, what executes vs. suggests, and what requires approval.
1. **MEVO (the chat assistant)** has persistent per-customer chat history and automatic access to the customer’s full context, modules, runs, insights, and tasks.
1. **Consultant comments/notes** are a first-class entity — attachable to a customer, a module, a specific insight, a task, a run, or a report.
1. All external data (GA4, Search Console, Ads, Ahrefs, crawler output, etc.) flows through a **unified ingestion layer** and is rendered in normalized views, never raw dumps.

-----

## 1. Tech Stack

**Frontend**

- Next.js 14+ (App Router), TypeScript, React Server Components where appropriate
- Tailwind CSS + shadcn/ui for primitives
- TanStack Query for client-side data fetching
- Zustand for local UI state (mode toggles, panel state)
- Recharts for dashboards, D3 for IPR graph visualizations
- Framer Motion for transitions

**Backend**

- Node.js + Fastify (or NestJS if team prefers)
- PostgreSQL 15+ as primary store
- Prisma ORM
- Redis for caching, rate limits, and job queue (BullMQ)
- S3-compatible object storage for reports, exports, crawl artifacts
- Pinecone or pgvector for semantic search over customer context + MEVO memory
- Temporal or BullMQ workflows for long-running agent runs

**AI layer**

- Anthropic Claude API (via the Messages endpoint) as primary LLM
- Per-customer memory layer backed by pgvector
- Tool-use / function-calling for agent actions (create task, approve, run module, fetch metric)

**Integrations**

- Google Analytics 4 (Data API)
- Google Search Console API
- Google Ads API
- Meta Ads API
- Ahrefs API (or DataForSEO as alternative)
- Generic webhook + CMS bridge (WordPress, Shopify, Sanity)

**Auth**

- NextAuth or Clerk, with org/team support and role-based permissions

-----

## 2. Data Model (Prisma schema skeleton)

Implement every entity below. Do not collapse related entities into JSON blobs — they must be queryable.

```prisma
// ===== Core identity =====
model User {
  id        String   @id @default(cuid())
  email     String   @unique
  name      String
  role      UserRole @default(CONSULTANT)
  orgId     String
  org       Org      @relation(fields: [orgId], references: [id])
  ownedCustomers Customer[] @relation("CustomerOwner")
  comments  Comment[]
  createdAt DateTime @default(now())
}

enum UserRole { OWNER ADMIN CONSULTANT VIEWER }

model Org {
  id        String    @id @default(cuid())
  name      String
  users     User[]
  customers Customer[]
  blueprints ServiceBlueprint[]
}

// ===== Customer core =====
model Customer {
  id              String            @id @default(cuid())
  orgId           String
  org             Org               @relation(fields: [orgId], references: [id])
  companyName     String
  primaryDomain   String
  secondaryDomains String[]
  industry        String?
  markets         String[]          // ["SE", "NO", "DK"]
  languages       String[]
  ownerId         String
  owner           User              @relation("CustomerOwner", fields: [ownerId], references: [id])
  serviceMode     ServiceMode       @default(ADVISORY)
  status          CustomerStatus    @default(ONBOARDING)
  blueprintId     String?
  blueprint       ServiceBlueprint? @relation(fields: [blueprintId], references: [id])
  goals           Goal[]
  competitors     Competitor[]
  stakeholders    Stakeholder[]
  integrations    Integration[]
  moduleAssignments ModuleAssignment[]
  insights        Insight[]
  recommendations Recommendation[]
  tasks           Task[]
  approvals       Approval[]
  runs            AgentRun[]
  deliverables    Deliverable[]
  reports         Report[]
  conversations   Conversation[]
  comments        Comment[]
  knowledgeEntries KnowledgeEntry[]
  metrics         MetricSnapshot[]
  auditLog        AuditEvent[]
  createdAt       DateTime          @default(now())
  updatedAt       DateTime          @updatedAt
}

enum ServiceMode   { ADVISORY FULL_SERVICE }
enum CustomerStatus { ONBOARDING ACTIVE PAUSED ARCHIVED }

model Goal {
  id         String   @id @default(cuid())
  customerId String
  customer   Customer @relation(fields: [customerId], references: [id])
  title      String
  kpi        String?
  targetValue String?
  deadline   DateTime?
  status     String   @default("active")
}

model Competitor {
  id         String   @id @default(cuid())
  customerId String
  customer   Customer @relation(fields: [customerId], references: [id])
  name       String
  domain     String
  isPrimary  Boolean  @default(false)
}

model Stakeholder {
  id         String   @id @default(cuid())
  customerId String
  customer   Customer @relation(fields: [customerId], references: [id])
  name       String
  email      String?
  role       String?   // "CMO", "Content lead", etc.
  isApprover Boolean  @default(false)
}

// ===== Modules & blueprints =====
model Module {
  id          String   @id   // "ai-visibility-tracker", "seo-crawler", etc.
  name        String
  category    ModuleCategory
  description String
  capabilities Json     // what it produces, what it needs
  defaultCadence String?  // "daily", "weekly", "on-demand"
  requiresIntegrations String[]
  assignments ModuleAssignment[]
}

enum ModuleCategory { VISIBILITY TECHNICAL_SEO SEMANTIC_CONTENT INTERNAL_LINKING MARKETING_OPS }

model ModuleAssignment {
  id          String   @id @default(cuid())
  customerId  String
  customer    Customer @relation(fields: [customerId], references: [id])
  moduleId    String
  module      Module   @relation(fields: [moduleId], references: [id])
  enabled     Boolean  @default(true)
  cadence     String?   // overrides module default
  config      Json     // per-customer settings
  permissions Json     // what it's allowed to execute in full-service mode
  enabledAt   DateTime @default(now())
  @@unique([customerId, moduleId])
}

model ServiceBlueprint {
  id        String   @id @default(cuid())
  orgId     String
  org       Org      @relation(fields: [orgId], references: [id])
  name      String   // "E-commerce Growth", "Local SEO", etc.
  moduleIds String[]
  defaultMode ServiceMode
  defaultPermissions Json
  customers Customer[]
}

// ===== Outputs: the structured-record rule =====
model Insight {
  id          String   @id @default(cuid())
  customerId  String
  customer    Customer @relation(fields: [customerId], references: [id])
  moduleId    String   // which module produced it
  runId       String?
  run         AgentRun? @relation(fields: [runId], references: [id])
  title       String
  body        String   @db.Text
  severity    Severity
  category    String   // "technical", "content", "architecture", "visibility"
  impactScore Int?     // 0-100
  confidence  Int?     // 0-100
  evidence    Json     // structured links to URLs, metrics, screenshots
  status      InsightStatus @default(OPEN)
  dismissedAt DateTime?
  comments    Comment[]
  recommendations Recommendation[]
  createdAt   DateTime @default(now())
}

enum Severity { HIGH MEDIUM LOW }
enum InsightStatus { OPEN IN_PROGRESS RESOLVED DISMISSED }

model Recommendation {
  id          String   @id @default(cuid())
  customerId  String
  customer    Customer @relation(fields: [customerId], references: [id])
  insightId   String?
  insight     Insight? @relation(fields: [insightId], references: [id])
  title       String
  rationale   String   @db.Text
  projectedImpact Json // {metric: "pagerank", delta: "+0.23", confidence: 74}
  effort      String   // "low", "medium", "high"
  playbook    Json?    // steps to execute
  tasks       Task[]
  createdAt   DateTime @default(now())
}

model Task {
  id              String   @id @default(cuid())
  customerId      String
  customer        Customer @relation(fields: [customerId], references: [id])
  recommendationId String?
  recommendation  Recommendation? @relation(fields: [recommendationId], references: [id])
  title           String
  description     String?  @db.Text
  ownerUserId     String?
  ownerType       OwnerType @default(HUMAN)
  status          TaskStatus @default(OPEN)
  impact          Severity
  dueDate         DateTime?
  requiresApproval Boolean @default(false)
  approvalId      String?
  approval        Approval? @relation(fields: [approvalId], references: [id])
  comments        Comment[]
  auditEvents     AuditEvent[]
  createdAt       DateTime @default(now())
  completedAt     DateTime?
}

enum OwnerType  { HUMAN AI }
enum TaskStatus { OPEN IN_PROGRESS BLOCKED DONE CANCELLED }

model Approval {
  id          String   @id @default(cuid())
  customerId  String
  customer    Customer @relation(fields: [customerId], references: [id])
  proposedAction Json  // describes what will happen if approved
  requesterType OwnerType  // HUMAN or AI
  requesterId String
  approverId  String?
  status      ApprovalStatus @default(PENDING)
  riskLevel   Severity
  tasks       Task[]
  createdAt   DateTime @default(now())
  decidedAt   DateTime?
}

enum ApprovalStatus { PENDING APPROVED REJECTED }

model AgentRun {
  id          String   @id @default(cuid())
  customerId  String
  customer    Customer @relation(fields: [customerId], references: [id])
  moduleId    String
  status      RunStatus @default(QUEUED)
  triggeredBy OwnerType  // HUMAN or AI (scheduled)
  triggeredById String?
  input       Json
  output      Json?
  logs        String?   @db.Text
  insights    Insight[]
  startedAt   DateTime?
  finishedAt  DateTime?
  createdAt   DateTime @default(now())
}

enum RunStatus { QUEUED RUNNING SUCCESS FAILED CANCELLED }

model Deliverable {
  id         String   @id @default(cuid())
  customerId String
  customer   Customer @relation(fields: [customerId], references: [id])
  type       String   // "strategy-doc", "audit-report", "content-brief", "ad-copy-set"
  title      String
  storageUrl String   // S3 path
  metadata   Json
  createdAt  DateTime @default(now())
}

model Report {
  id         String   @id @default(cuid())
  customerId String
  customer   Customer @relation(fields: [customerId], references: [id])
  title      String
  period     String   // "2026-Q1"
  sections   Json     // structured sections
  generatedAt DateTime @default(now())
}

// ===== MEVO: chat + per-customer memory =====
model Conversation {
  id         String   @id @default(cuid())
  customerId String?  // nullable for global/portfolio-level chats
  customer   Customer? @relation(fields: [customerId], references: [id])
  userId     String   // the consultant
  title      String?   // auto-generated or user-set
  scope      ConversationScope
  messages   Message[]
  createdAt  DateTime @default(now())
  updatedAt  DateTime @updatedAt
}

enum ConversationScope { CUSTOMER GLOBAL PORTFOLIO }

model Message {
  id             String   @id @default(cuid())
  conversationId String
  conversation   Conversation @relation(fields: [conversationId], references: [id])
  role           MessageRole
  content        String   @db.Text
  // Structured tool calls, so we can render them as rich blocks
  toolCalls      Json?    // [{name, input, output}, ...]
  // Every message can link back to the entities it referenced/created
  referencedEntityIds Json? // [{type:"insight", id:"..."}, {type:"task", id:"..."}]
  createdAt      DateTime @default(now())
}

enum MessageRole { USER ASSISTANT SYSTEM TOOL }

model MemoryEntry {
  id         String   @id @default(cuid())
  customerId String
  kind       MemoryKind
  content    String   @db.Text
  embedding  Unsupported("vector(1536)")?  // pgvector
  source     String   // "chat", "run-output", "manual", "deliverable"
  sourceId   String?
  createdAt  DateTime @default(now())
  @@index([customerId, kind])
}

enum MemoryKind { FACT DECISION PREFERENCE HISTORY OUTCOME }

// ===== Comments (consultant notes) =====
model Comment {
  id            String   @id @default(cuid())
  authorId      String
  author        User     @relation(fields: [authorId], references: [id])
  body          String   @db.Text
  // Polymorphic: exactly one target
  customerId    String?
  customer      Customer? @relation(fields: [customerId], references: [id])
  insightId     String?
  insight       Insight?  @relation(fields: [insightId], references: [id])
  taskId        String?
  task          Task?     @relation(fields: [taskId], references: [id])
  runId         String?
  reportId      String?
  moduleAssignmentId String?
  pinned        Boolean  @default(false)
  mentions      String[]  // user ids mentioned with @
  reactions     Json?     // {"👍": ["userId1", "userId2"]}
  createdAt     DateTime @default(now())
  updatedAt     DateTime @updatedAt
}

// ===== Knowledge entries (strategic context) =====
model KnowledgeEntry {
  id         String   @id @default(cuid())
  customerId String
  customer   Customer @relation(fields: [customerId], references: [id])
  kind       String   // "brand-notes", "approved-copy", "meeting-notes", "constraint"
  title      String
  body       String   @db.Text
  authorId   String
  tags       String[]
  embedding  Unsupported("vector(1536)")?
  createdAt  DateTime @default(now())
  updatedAt  DateTime @updatedAt
}

// ===== Integrations =====
model Integration {
  id          String   @id @default(cuid())
  customerId  String
  customer    Customer @relation(fields: [customerId], references: [id])
  provider    IntegrationProvider
  status      String   // "connected", "error", "pending"
  credentials Json     // encrypted
  config      Json     // property IDs, account IDs, etc.
  lastSyncAt  DateTime?
  createdAt   DateTime @default(now())
}

enum IntegrationProvider { GA4 SEARCH_CONSOLE GOOGLE_ADS META_ADS AHREFS DATAFORSEO WORDPRESS SHOPIFY SANITY WEBHOOK }

// ===== Metric snapshots (normalized data from integrations) =====
model MetricSnapshot {
  id          String   @id @default(cuid())
  customerId  String
  customer    Customer @relation(fields: [customerId], references: [id])
  source      IntegrationProvider
  metric      String   // "organic_sessions", "impressions", "cpc", "share_of_voice"
  dimension   Json?    // {page: "/kategori/soffor", country: "SE", query: "modulsoffa"}
  value       Float
  unit        String?
  periodStart DateTime
  periodEnd   DateTime
  capturedAt  DateTime @default(now())
  @@index([customerId, source, metric, periodStart])
}

// ===== Audit =====
model AuditEvent {
  id         String   @id @default(cuid())
  customerId String?
  customer   Customer? @relation(fields: [customerId], references: [id])
  actorType  OwnerType
  actorId    String
  action     String   // "task.created", "run.started", "approval.granted", "integration.synced"
  targetType String?
  targetId   String?
  payload    Json?
  taskId     String?
  task       Task?    @relation(fields: [taskId], references: [id])
  createdAt  DateTime @default(now())
}
```

-----

## 3. Information Architecture & Routing

Organize the app around `customerId` as the root context. Use Next.js App Router.

```
/app
  /page.tsx                          → redirect to /customers
  /customers/page.tsx                → customer list (primary landing)
  /customers/new/page.tsx            → onboarding wizard
  /customers/[id]
    /layout.tsx                      → customer-scoped shell (loads context once)
    /page.tsx                        → redirect to overview
    /overview/page.tsx
    /modules/page.tsx
    /modules/[moduleId]/page.tsx     → module detail within customer
    /insights/page.tsx
    /insights/[insightId]/page.tsx
    /tasks/page.tsx
    /runs/page.tsx
    /runs/[runId]/page.tsx
    /reports/page.tsx
    /knowledge/page.tsx
    /settings/page.tsx
  /portfolio/page.tsx                → cross-customer table
  /tasks/page.tsx                    → team-wide task queue
  /reports/page.tsx                  → deliverables library
  /blueprints/page.tsx               → reusable service templates
  /integrations/page.tsx             → org-level integration catalog
  /admin/page.tsx
```

The `/customers/[id]/layout.tsx` MUST load and provide customer context to every child page via a React Context so modules never re-fetch or re-request basic customer info.

-----

## 4. Service Mode — Behavioral Implementation

This is the #1 rule the team tends to get wrong. Implement these as server-enforced behaviors, not UI hints.

**Advisory mode** (`ServiceMode.ADVISORY`):

- Agent runs may produce Insights, Recommendations, and Task drafts.
- Agents MUST NOT call execution tools (e.g. `publishCanonicalTag`, `pushAdCopy`, `writeSitemap`).
- Tasks created by agents default to `ownerType = HUMAN` with a suggested assignee.
- `requiresApproval` is irrelevant because nothing executes.
- Reports framed as “recommendations” rather than “work completed”.

**Full service mode** (`ServiceMode.FULL_SERVICE`):

- Agents MAY call execution tools if the specific `ModuleAssignment.permissions` allow it.
- Tasks can be created with `ownerType = AI` and auto-progressed.
- Risky actions (classified by `riskLevel`) create an `Approval` record and pause until decided.
- Every execution writes an `AuditEvent` with before/after payload.

**Implementation**: build a server-side guard:

```ts
// lib/serviceMode.ts
export async function assertCanExecute(
  customerId: string,
  moduleId: string,
  action: string,
  riskLevel: Severity
): Promise<{ allowed: boolean; requiresApproval: boolean; reason?: string }> {
  const customer = await db.customer.findUnique({ where: { id: customerId } });
  if (customer.serviceMode === 'ADVISORY') {
    return { allowed: false, requiresApproval: false, reason: 'Customer is in advisory mode' };
  }
  const assignment = await db.moduleAssignment.findUnique({
    where: { customerId_moduleId: { customerId, moduleId } }
  });
  const permissions = assignment.permissions as { allowedActions: string[]; autoExecuteBelow: Severity };
  if (!permissions.allowedActions.includes(action)) {
    return { allowed: false, requiresApproval: false, reason: 'Action not permitted for this module' };
  }
  const requiresApproval = severityRank(riskLevel) > severityRank(permissions.autoExecuteBelow);
  return { allowed: true, requiresApproval };
}
```

Every agent tool-use handler calls `assertCanExecute` before touching any external system. If `requiresApproval` is true, the agent creates an `Approval` record and stops.

-----

## 5. MEVO — Chat & Per-Customer Memory

This is a significant expansion over the current floating chat. MEVO must feel like a colleague who remembers everything about every customer.

### 5.1 Behavioral requirements

- Inside a customer workspace, MEVO **automatically** has:
  - The full customer record (goals, markets, competitors, stakeholders, service mode).
  - Enabled modules with their configs.
  - The last 30 days of runs, the last 50 open insights, all open tasks, pending approvals.
  - The last 20 messages of prior conversations with this customer.
  - Semantically relevant memory entries (see 5.3).
- Outside a customer workspace (Portfolio, global), MEVO asks or infers which customer is being discussed and loads that context before answering.
- MEVO never acts as a generic chatbot. Every answer grounds in customer data or admits it needs to fetch.
- MEVO can execute tools: create tasks, draft briefs, trigger runs, request approvals, fetch metrics. These go through the same `assertCanExecute` guard as any other agent.

### 5.2 Chat persistence

Every conversation is stored in `Conversation` + `Message`. A customer can have many conversations. The sidebar of the chat UI shows a thread list like an email client:

```
[Customer: Nordika Furniture]
  ◉ This week's status (active)
  ◦ Canonical tag batch plan
  ◦ April competitor review
  ◦ Content brief: bäddsoffa
  + New conversation
```

When the user switches customers, the conversation list swaps. Opening a conversation restores the full message history.

### 5.3 Per-customer memory layer

MEVO doesn’t just re-read the whole conversation. It builds a **summarized, embedded memory** per customer.

- On every assistant message containing a decision, outcome, or fact, a background job writes a `MemoryEntry` with kind `DECISION`, `OUTCOME`, `FACT`, or `PREFERENCE` and embeds it.
- When starting a new MEVO turn, do a pgvector similarity search over `MemoryEntry` for this customer against the current user query, and inject the top 8 results into the system prompt as “What you remember about this customer”.
- Also inject a deterministic snapshot: current goals, active modules, recent insights, open approvals. This ensures MEVO never hallucinates the basics.

### 5.4 System prompt skeleton for MEVO

```
You are MEVO, the AI colleague inside AmazingTools. You are embedded in the workspace of customer {{customer.companyName}} ({{customer.primaryDomain}}).

## Customer snapshot
- Markets: {{markets}}
- Service mode: {{serviceMode}}
- Goals: {{goals}}
- Top competitors: {{competitors}}
- Enabled modules: {{moduleList}}

## What you remember
{{memoryEntries | format}}

## Recent activity (last 14 days)
- Runs: {{recentRuns | summarize}}
- High-severity insights: {{highSeverityInsights | summarize}}
- Open tasks: {{openTasks | count}}
- Pending approvals: {{pendingApprovals | summarize}}

## Available tools
You may call: createTask, draftContentBrief, triggerRun, fetchMetric, proposeApproval, addComment, searchKnowledge, summarizeReport.

## Mode-bound behavior
{{#if serviceMode == ADVISORY}}
You can propose and draft. You CANNOT execute changes to external systems. Frame every suggestion as "I recommend..." and always create tasks for the consultant to own.
{{else}}
You can execute approved workflows. Actions classified as HIGH severity require human approval — create an Approval record and stop. Actions below that threshold auto-execute and log AuditEvents.
{{/if}}

## Style
Concise, grounded in the customer's actual data. Cite the run id or insight id when referencing findings. Never invent metrics. If data is missing, say so and offer to fetch it.
```

### 5.5 Tool definitions

```ts
const mevoTools = [
  {
    name: "createTask",
    description: "Create a task attached to this customer. In advisory mode, task owner defaults to the consultant.",
    input_schema: {
      type: "object",
      properties: {
        title: { type: "string" },
        description: { type: "string" },
        impact: { enum: ["HIGH", "MEDIUM", "LOW"] },
        dueDate: { type: "string", format: "date" },
        linkedInsightId: { type: "string" }
      },
      required: ["title", "impact"]
    }
  },
  {
    name: "triggerRun",
    description: "Queue a new run of a module for this customer.",
    input_schema: {
      type: "object",
      properties: {
        moduleId: { type: "string" },
        input: { type: "object" }
      },
      required: ["moduleId"]
    }
  },
  {
    name: "fetchMetric",
    description: "Retrieve a normalized metric from the customer's integrations.",
    input_schema: {
      type: "object",
      properties: {
        metric: { type: "string" },
        source: { enum: ["GA4", "SEARCH_CONSOLE", "GOOGLE_ADS", "META_ADS", "AHREFS"] },
        periodStart: { type: "string", format: "date" },
        periodEnd: { type: "string", format: "date" },
        dimension: { type: "object" }
      },
      required: ["metric", "source", "periodStart", "periodEnd"]
    }
  },
  {
    name: "proposeApproval",
    description: "Create an Approval request for an action that requires human sign-off.",
    input_schema: { /* ... */ }
  },
  {
    name: "addComment",
    description: "Leave a note on a customer, task, or insight.",
    input_schema: { /* ... */ }
  },
  {
    name: "searchKnowledge",
    description: "Semantic search over the customer's knowledge entries and past deliverables.",
    input_schema: { /* ... */ }
  }
];
```

### 5.6 Chat UI requirements

- Floating panel, expandable to full-screen.
- Left rail: conversation list for the current customer.
- Main: message thread with rich blocks — insights, tasks, metrics, and approvals render as inline cards, not plain text.
- Slash commands: `/run seo-crawler`, `/insight-summary`, `/draft-email cmo`, `/compare-competitors`.
- Context indicator chip at the top: “Context: Nordika Furniture · Full service · 6 modules”.
- Messages that create entities show a footer: “Created Task #T-482” with a link.

-----

## 6. Consultant Comments — First-Class Entity

Consultants and MEVO both write to the same `Comment` table. Comments are polymorphic — they attach to exactly one of: Customer, Insight, Task, Run, Report, ModuleAssignment.

### 6.1 Where comments appear

- **Customer overview**: a pinned-comments panel + a general activity thread.
- **Insight detail**: inline discussion below the insight body.
- **Task detail**: threaded discussion with the task.
- **Run detail**: post-mortem notes.
- **Report detail**: feedback from the consultant before sending to customer.
- **Module assignment page**: configuration notes (“we lowered cadence because the client prefers weekly updates”).

### 6.2 Comment features

- Markdown support.
- `@mentions` of other users in the org (triggers notification).
- Reactions (emoji).
- Pinning (pinned comments surface at the top of the customer overview).
- Edit history (retain previous versions).
- MEVO can read and write comments. When MEVO writes, the `authorId` points to a special system user flagged `ownerType = AI` in the UI.
- Threaded replies (optional phase 2) — or flat thread with quoting.

### 6.3 Feed integration

The customer overview’s “Recent activity” feed merges comments with runs, insights, task state changes, and approvals into a single chronological timeline, each with a distinct icon.

-----

## 7. Data Ingestion & Display — SEO, Ads, Analytics

All external data flows through a unified ingestion pipeline. No module reads directly from a third-party API at render time.

### 7.1 Ingestion architecture

```
Integration (GA4, SC, Ads, etc.)
        │
        ▼
Connector (per-provider, handles auth + pagination + rate limits)
        │
        ▼
Normalizer (maps provider schema → MetricSnapshot records)
        │
        ▼
Postgres (MetricSnapshot table, indexed by customer+metric+period)
        │
        ▼
Query layer (typed service functions)
        │
        ▼
UI components (charts, tables, KPI tiles)
```

### 7.2 Connector contract

Every connector implements:

```ts
interface Connector {
  provider: IntegrationProvider;
  testConnection(integration: Integration): Promise<{ ok: boolean; error?: string }>;
  sync(integration: Integration, range: { start: Date; end: Date }): Promise<SyncResult>;
  capabilities(): MetricDefinition[];
}

interface MetricDefinition {
  key: string;                 // "organic_sessions"
  unit: string;
  dimensions: string[];        // ["page", "country", "query"]
  supportsRealtime: boolean;
}
```

### 7.3 Scheduled syncs

- BullMQ job per customer per connector, default cadence daily at 03:00 customer-local time.
- On-demand sync button on the integrations page and per module.
- Failures write to `AuditEvent` and bubble up as a banner on the customer overview.

### 7.4 Display patterns

**KPI tiles** (customer overview): latest value + MoM delta + sparkline. Pull from `MetricSnapshot` with a single aggregated query — never loop.

**Metric explorer** (module detail): date range picker, dimension breakdown, source comparison. Use Recharts with our design tokens (no default chart colors).

**Trend cards** (insights): when an insight references a metric, render an inline 30-day sparkline sourced from the same `MetricSnapshot` table. This keeps the visual language consistent everywhere.

**Cross-source joins**: the portfolio health score combines GA4 (traffic), SC (impressions), and Ads (spend efficiency). Implement as a materialized view refreshed hourly.

### 7.5 Specific integration deliverables

**GA4**: sessions, users, engaged sessions, conversions, event counts — all dimensioned by landing page, source/medium, country, device.

**Search Console**: impressions, clicks, CTR, average position — dimensioned by query, page, country. Handle the 16-month limit by snapshotting.

**Google Ads**: impressions, clicks, cost, conversions, ROAS — dimensioned by campaign, ad group, keyword.

**Meta Ads**: equivalent coverage.

**Ahrefs**: domain rating, organic keywords, referring domains, top pages, backlink gains/losses — snapshot weekly.

**SEO Crawler (internal)**: every crawled URL writes a row in `CrawlResult` (add this table) with status code, title, H1, meta description, canonical, word count, internal links in/out. This is the fuel for SEO Crawler insights and IPR Sandbox.

-----

## 8. Module Runtime

Every module is an independent worker that:

1. Reads its input from an `AgentRun` record.
1. Has access to the customer context (goals, competitors, integrations, knowledge).
1. Produces structured outputs (`Insight`, `Recommendation`, `Deliverable`) — never raw markdown blobs as the primary output.
1. Writes logs into the run record.
1. Honors service mode via `assertCanExecute`.

Implement a module base class so adding a new module is 1 file + 1 Prisma row.

```ts
abstract class ModuleRunner {
  abstract id: string;
  abstract category: ModuleCategory;
  abstract run(run: AgentRun, ctx: CustomerContext): Promise<ModuleRunOutput>;
}

interface ModuleRunOutput {
  insights: InsightDraft[];
  recommendations: RecommendationDraft[];
  deliverables?: DeliverableDraft[];
  metrics?: MetricSnapshot[];
  logs: string;
}
```

-----

## 9. Onboarding Wizard (6 steps)

Implement as a multi-step form with saved progress (a customer in `ONBOARDING` status can be resumed):

1. **Profile** — company name, primary domain, secondary domains, markets, languages, industry, owner.
1. **Context** — goals (1..n), primary competitors (up to 5), strategic notes, brand tone, audience.
1. **Integrations** — OAuth flows for GA4, SC, Ads, Ahrefs. Skip allowed; can complete later.
1. **Mode** — Advisory or Full service. Include a plain-language comparison.
1. **Modules** — show grouped module catalog (A–E). Offer blueprint templates (“E-commerce Growth”, “Local SEO”, “Enterprise B2B”) and a custom option.
1. **Review** — summary, then “Create workspace” button flips status to `ACTIVE`.

On completion, auto-enqueue initial runs for every enabled module.

-----

## 10. Portfolio View

Cross-customer table for team leads. Columns: Customer, Mode, Owner, Modules enabled/total, Health score, Open tasks, Pending approvals, Last run. Sort and filter by any column. Row click opens the customer workspace.

Also implement a “Needs attention” auto-filter: customers with health score < 60, or no run in 7 days, or approvals pending > 48 hours.

-----

## 11. Permissions & Roles

- **Owner** — full org-level control including billing.
- **Admin** — manage users, customers, blueprints, integrations.
- **Consultant** — full access to their assigned customers; read-only for others (configurable).
- **Viewer** — read-only on everything, no tool execution.

Enforce in API middleware AND in UI (don’t rely on UI alone).

-----

## 12. Notifications

Events that notify:

- Pending approval for an assigned stakeholder.
- Comment `@mention`.
- Run failure.
- Integration disconnected/expired.
- Task due within 24 hours.

Channels: in-app bell, email digest (daily), optional Slack webhook.

-----

## 13. Audit & Compliance

Every mutation writes an `AuditEvent`. The customer Settings page has an audit log tab showing:

- Who (human or AI) did what, when.
- Before/after for approvals and executed actions.
- Filterable by actor, action type, date range.

This is non-optional for full-service mode credibility.

-----

## 14. Migration from Current Product

Do not delete existing tools. Map them into the new architecture:

|Current tool                   |New module id                            |Category        |
|-------------------------------|-----------------------------------------|----------------|
|AI Visibility Tracker          |`ai-visibility-tracker`                  |VISIBILITY      |
|SEO Crawler                    |`seo-crawler`                            |TECHNICAL_SEO   |
|QueryMatch                     |`query-match`                            |SEMANTIC_CONTENT|
|IPR Sandbox                    |`ipr-sandbox`                            |INTERNAL_LINKING|
|Page Simulator                 |`page-simulator`                         |INTERNAL_LINKING|
|Marketing Agents (7 sub-agents)|`marketing-agents` with sub-agent configs|MARKETING_OPS   |

Migration script:

1. For every historic tool run in the old system, create a placeholder `Customer` (or link to a real one by domain) and attach the historic output as an `AgentRun` + derived `Insight`/`Recommendation` records.
1. Deprecate the old `/tools/*` routes with 301 redirects to the matching customer + module path once a customer is chosen.

-----

## 15. Design System

Match the mockup (already delivered). Key tokens:

```css
--bg: #f4f1ea;          /* warm off-white */
--bg-card: #fbfaf6;
--ink: #0f1111;
--ink-mute: #6b6e6e;
--teal: #0fa6a0;         /* primary accent, preserved from current brand */
--teal-deep: #0b7a76;
--amber: #c67b1a;        /* advisory mode */
--rose: #b34a4a;         /* high severity */
--ok: #2f7a4d;
```

Typography: Fraunces (display serif), Inter Tight (UI), JetBrains Mono (code/meta).

Every page uses the customer workspace shell when inside a customer context. Top bar shows breadcrumb: `Customers / Nordika Furniture`.

-----

## 16. Phased Roadmap

**Phase 1 — Foundation (weeks 1–3)**

- Data model + migrations.
- Auth, orgs, users, customers CRUD.
- Customer list + onboarding wizard.
- Customer workspace shell with Overview + Settings tabs.
- Service mode toggle (UI only, enforcement in phase 2).

**Phase 2 — Modules & runs (weeks 4–6)**

- Module registry, ModuleAssignment, ServiceBlueprint.
- AgentRun lifecycle + BullMQ workers.
- Port SEO Crawler, QueryMatch, AI Visibility Tracker to the new runner.
- Structured Insight + Recommendation output.
- Modules tab in workspace.

**Phase 3 — Ingestion & display (weeks 7–8)**

- Connectors for GA4, SC, Google Ads.
- MetricSnapshot table + scheduled syncs.
- KPI tiles, metric explorer, trend cards.

**Phase 4 — Tasks, approvals, comments (weeks 9–10)**

- Task + Approval tables + UI.
- Service mode enforcement (`assertCanExecute`).
- Comments system — polymorphic, mentions, pinning, reactions.

**Phase 5 — MEVO (weeks 11–13)**

- Conversation + Message persistence.
- Memory layer (pgvector).
- Tool-use handlers.
- Context injection + customer-aware system prompt.
- Chat UI with conversation list and rich inline cards.

**Phase 6 — Portfolio, reports, polish (weeks 14–15)**

- Portfolio view with health scores.
- Report generator.
- Audit log UI.
- Notifications.

**Phase 7 — Migrate remaining modules + launch (weeks 16–17)**

- IPR Sandbox, Page Simulator, Marketing Agents.
- Data migration from the old system.
- Deprecate old tool routes.

-----

## 17. Acceptance Criteria (Definition of Done)

Ship nothing until all of these pass:

1. The landing screen is a customer list. There is no path to a tool without first choosing a customer.
1. A new customer is created via the 6-step wizard. Every field in the data model is captured.
1. Opening a customer workspace loads the full context once; sub-pages read from a React Context, never re-fetch basic customer info.
1. Service mode toggling changes server-enforced behavior: advisory-mode agents cannot call execution tools — verify with a test.
1. Every module produces structured `Insight` and `Recommendation` records. A raw text blob is never the primary output.
1. MEVO inside a customer workspace answers “What’s the biggest issue right now?” by citing actual insight ids from the database, not fabrications.
1. MEVO’s conversation history persists per customer and can be reopened days later with full context.
1. The memory layer surfaces relevant past decisions in a new MEVO turn (validate with a seeded test case).
1. Consultants can leave comments on customers, insights, tasks, runs, and reports. `@mentions` trigger a notification.
1. GA4, Search Console, and Google Ads connectors sync daily and populate `MetricSnapshot`. KPI tiles render from those records.
1. The Portfolio page shows every customer with health, open tasks, pending approvals.
1. Every executed action in full-service mode writes an `AuditEvent` with before/after payload.
1. Service Blueprints can be created, applied to new customers during onboarding, and updated across existing customers.
1. Old tool URLs 301 redirect into the new customer-scoped paths (or to the customer list if no customer is in scope).

-----

## 18. Anti-Patterns — Do Not Do These

- Do not build “a dashboard with a customer selector at the top”. The customer must be the root of the route tree.
- Do not let modules read third-party APIs at render time. Everything goes through `MetricSnapshot`.
- Do not store agent outputs as markdown blobs. Structured records first, rendering second.
- Do not make service mode a boolean that only changes button labels. It must gate execution server-side.
- Do not build MEVO as a generic chat wrapper. It must load customer context, persist per-customer history, and write back memory entries.
- Do not let comments be strings on the customer record. They are their own entity, polymorphic, queryable.
- Do not skip the audit log. Full-service mode without auditing is not shippable.

-----

## 19. Deliverables Checklist

- [ ] Prisma schema covering every entity in section 2.
- [ ] Migration scripts + seed data for development.
- [ ] Next.js App Router structure per section 3.
- [ ] Connector implementations for GA4, Search Console, Google Ads.
- [ ] Module runner base class + ports for SEO Crawler, QueryMatch, AI Visibility Tracker.
- [ ] `assertCanExecute` guard with tests covering advisory vs full service.
- [ ] Comments system with mentions, pinning, reactions.
- [ ] MEVO: Conversation + Message persistence, memory layer, tool-use handlers, customer-aware system prompt.
- [ ] 6-step onboarding wizard with resumable progress.
- [ ] Portfolio view with health score.
- [ ] Audit log UI per customer.
- [ ] Design tokens + Tailwind theme matching the delivered mockup.
- [ ] End-to-end tests for: onboarding, running a module, MEVO tool-use, approval flow, service mode enforcement.

Jag ska skriva en omfattande, produktionsredo kodningsprompt som kan ges till en AI-kodare eller utvecklarteam. Den ska täcka hela arkitekturen inklusive MEVO:s per-kund-minne, konsultkommentarer, och dataintegrationer.​​​​​​​​​​​​​​​​

Klar. Prompten är skriven som en komplett implementationsspec som en AI-kodare eller dev-team kan följa end-to-end.

**Vad som är täckt (utöver grundarkitekturen):**

- **Sektion 5 — MEVO med per-kund-minne**: Conversation- och Message-tabeller för persistent chathistorik per kund, en MemoryEntry-tabell med pgvector för semantiskt minne (kind: FACT, DECISION, PREFERENCE, HISTORY, OUTCOME), systemprompt-skelett, och tool-use-definitioner för `createTask`, `triggerRun`, `fetchMetric`, `proposeApproval`, `addComment`. Konversationslista i chat-UI:n fungerar som en e-postklient — byt kund, byt trådar.
- **Sektion 6 — Konsultkommentarer**: Polymorft Comment-entity som kan kopplas till Customer, Insight, Task, Run, Report eller ModuleAssignment. Stöd för markdown, @mentions (med notis), pinning, reactions, redigeringshistorik. MEVO kan läsa OCH skriva kommentarer som systemanvändare.
- **Sektion 7 — Dataingestion för SEO/Ads/Analytics**: Unified ingestion pipeline där ingen modul läser tredjepart-API:er vid render time. Connector-kontrakt, schemalagda syncs via BullMQ, MetricSnapshot-tabell som enda källa, och konkreta deliverables för GA4, Search Console, Google Ads, Meta Ads, Ahrefs och en intern SEO Crawler.
- **Sektion 4 — Service mode som faktisk guard**: `assertCanExecute`-funktion som server-enforced kontrollerar Advisory vs Full service. Advisory mode *får inte* anropa execution-tools. Full service kan, men high-risk-actions skapar Approval-records.
- **Sektion 16 — 7-fasers roadmap** från datamodell → moduler → ingestion → tasks/approvals/kommentarer → MEVO → portfölj → migrering.
- **Sektion 17 — 14 acceptance criteria** som måste passera innan release. Bland annat: MEVO måste citera riktiga insight-id:n från databasen (ej hallucinera), minneslagret ska surfaca relevanta tidigare beslut, och gamla tool-URL:er ska 301-redirecta.
- **Sektion 18 — Anti-patterns** som explicit säger *“gör inte en dashboard med en customer-selector överst”* eftersom det är den vanligaste felvägen teamet lär hamna i.

Ge hela filen till din AI-kodare i ett svep — den är skriven för att konsumeras som en enda master-prompt. Om du vill att jag ska splittra upp den i epics/user stories med Jira-kompatibelt format, eller skriva en separat, djupare spec för någon enskild sektion (t.ex. bara MEVO:s memory layer, eller bara ingestion pipeline med faktisk TypeScript-kod), säg till.​​​​​​​​​​​​​​​​

-----

**Final instruction to the implementer**: Build this as a real product, not a demo. Prioritize the data model and the customer context layer in week 1 — if those are right, everything else composes. If you’re tempted to take a shortcut, reread section 18.


The screenshot makes the core problem very clear: the landing page is a grid of tools, so the user is forced into the wrong question first — “Which tool should I open?” — instead of “Which customer am I working on?”

That is the architectural shift you want.

Strategic reframing

AmazingTools should stop being a toolbox and become a customer operating system.

The top-level entity must be the customer account.
Every tool, agent, and module should become a capability attached to that customer.

So the new mental model becomes:

Customer → Workspace → Service mode → Selected modules → Runs, insights, tasks, approvals, deliverables

Not:

Tool → enter customer details again → run isolated analysis

⸻

Copy-paste master prompt for your AI coder

You are a senior product architect, UX strategist, CRM designer, AI workflow designer, and full-stack SaaS engineer.

Your task is to redesign our platform “AmazingTools” from first principles.

## 1. Current state

Today AmazingTools is tool-centric. The user lands on a dashboard showing independent tools and agents such as:

- AI Visibility Tracker
- Marketing Agents
- SEO Crawler
- QueryMatch
- IPR Sandbox
- Page Simulator
- and related modules

The current flow is:
1. Open the platform
2. Choose a tool
3. Enter customer information inside that tool
4. Run the analysis or agent
5. Repeat in other tools

This architecture is wrong for the business we want to build because it fragments customer context, duplicates input, isolates outputs, and makes the product feel like a toolbox instead of a service platform.

## 2. New product thesis

We want to rebuild AmazingTools as a CUSTOMER-CENTRIC platform, not a TOOL-CENTRIC platform.

The primary object of the system must be the CUSTOMER.

The first thing a user should do after entering the platform is:
- select an existing customer, or
- create a new customer

The platform should feel like a CRM + service operations workspace for SEO and AI-driven marketing delivery.

Tools, agents, and modules should no longer be the top-level navigation. They should become service capabilities inside each customer workspace.

## 3. Core design principles (non-negotiable)

1. Customer-first entry point
   - The home screen must show customers, not tools.
   - Users must begin by selecting or creating a customer.

2. Persistent customer context
   - Every customer must have a persistent profile and memory layer.
   - Tools and agents must read from a shared customer context instead of asking for the same information repeatedly.

3. Service blueprint per customer
   - For each customer, the user must be able to choose exactly which tools, agents, and modules are enabled.
   - This should work like assigning a service package or delivery blueprint to that customer.

4. Two service modes
   - Advisory mode: agents analyze, diagnose, prioritize, and recommend. The consultant executes the work.
   - Full service mode: agents perform the work end-to-end where permissions and integrations allow it.
   - The system architecture should support a customer-level default mode and ideally allow module-level overrides later.

5. Unified outputs
   - All outputs from all modules must flow back into the customer workspace as structured objects:
     - insights
     - recommendations
     - tasks
     - simulations
     - reports
     - content drafts
     - change logs
     - approvals
     - deliverables

6. Customer workspace over tool silos
   - The user should experience a single customer workspace with multiple capabilities, not separate disconnected tools.

7. Modular platform architecture
   - Each tool/agent/module should be implemented as a modular capability that plugs into the customer workspace and orchestration engine.

## 4. What the new UX should feel like

AmazingTools should feel like an account-centric operating system for consultants and AI agents working together on customer growth.

The first screen should be a Customers view, similar to a CRM:
- search customers
- filter customers
- sort customers
- create new customer
- open recent customers
- see ownership/status/service mode at a glance

Each customer should have a customer card and a dedicated workspace.

## 5. Top-level information architecture

Design a new information architecture with these primary sections:

- Customers
- Portfolio / Operations Overview
- Tasks & Approvals
- Reports & Deliverables
- Templates / Service Blueprints
- Integrations
- Settings / Admin

The product must NOT lead with tools anymore.

## 6. Required customer data model

Create a core customer object with at minimum:

- customer_id
- company_name
- primary_domain
- secondary_domains
- industry / niche
- target markets / countries / languages
- assigned consultant / owner
- service mode (advisory or full service)
- service status (active, onboarding, paused, archived)
- goals / KPIs
- competitors
- notes / strategic context
- connected integrations
- enabled modules
- activity history
- run history
- deliverables history
- permissions / approval rules

Also define related entities such as:

- Customer
- Workspace
- Domain
- Competitor
- Goal
- Integration
- Module
- ModuleAssignment
- ServiceBlueprint
- AgentRun
- Insight
- Recommendation
- Task
- Approval
- Deliverable
- Report
- Conversation
- AuditLog
- User / Role

## 7. New first-run experience

Design an onboarding flow where the user creates a customer through a structured wizard:

Step 1: Basic customer profile
- company name
- domain
- owner
- market / language
- status

Step 2: Strategic context
- customer goals
- business priorities
- target audience
- key pages
- competitors
- tone / positioning / brand notes

Step 3: Data and integrations
- analytics
- search console
- crawl sources
- CMS
- ad platforms
- other relevant sources

Step 4: Choose service mode
- Advisory
- Full service

Step 5: Choose customer modules
- Show all available tools, agents, and their submodules
- Group them by capability or service area
- Allow the user to check which ones this customer should have
- Allow choosing templates or custom configuration

Step 6: Review and create workspace

## 8. Module catalog design

All existing tools must be reclassified as capabilities/modules inside the customer workspace.

Example grouping:

A. Visibility & market intelligence
- AI Visibility Tracker
- competitor / market analysis modules

B. Technical SEO
- SEO Crawler
- CWV / technical audit modules

C. Semantic relevance & content
- QueryMatch
- content / landing page review modules

D. Internal linking & architecture
- IPR Sandbox
- Page Simulator
- related internal linking modules

E. Marketing / conversion operations
- ad copy writer
- UTM builder
- conversion debugger
- lead qualification-related modules

The user must be able to:
- browse all modules
- understand what each does
- see prerequisites/integrations
- enable or disable them per customer
- configure cadence, permissions, and expected outputs

Tools should be visually demoted from “main destination” to “capabilities inside the customer account”.

## 9. Customer workspace design

For each customer, create a full workspace with tabs or sections such as:

### Overview
- customer summary
- active modules
- service mode
- key metrics / KPI snapshot
- recent findings
- open tasks
- pending approvals
- recent deliverables
- latest runs

### Modules / Service Blueprint
- full catalog of enabled and available modules
- grouped by capability
- ability to add/remove/configure modules for this customer

### Insights
- unified feed of findings, issues, opportunities, and recommendations across all modules

### Tasks & Actions
- generated tasks
- consultant-owned tasks
- AI-owned tasks
- status, owner, impact, due date
- approval flow

### Runs / Jobs
- background jobs
- run history
- current status
- logs
- rerun / schedule

### Reports & Deliverables
- strategy documents
- presentations
- audit summaries
- customer-facing reports
- exportable outputs

### Knowledge / Context
- strategic notes
- meeting notes
- business context
- brand constraints
- approved copy
- historical decisions

### Settings
- integrations
- service mode
- module permissions
- customer-specific preferences
- stakeholder contacts

## 10. Advisory mode vs Full service mode

Design clear behavioral differences.

### Advisory mode
The agents should:
- analyze data
- identify issues/opportunities
- prioritize actions
- estimate impact/effort/confidence
- generate recommendations, task suggestions, drafts, and playbooks
- stop before execution unless explicitly approved

The consultant should:
- review recommendations
- decide what to implement
- execute externally or manually
- mark completion and outcomes

### Full service mode
The agents should:
- run analyses automatically
- generate tasks and action plans
- execute approved workflows where integrations allow
- produce reports and follow-up actions
- maintain logs and change history
- escalate only when approval is needed or risk thresholds are crossed

Important:
Even in full service mode, the system should support approval gates for risky or customer-facing actions.

## 11. AI assistant behavior

There may still be a chat assistant, but it must become CUSTOMER-AWARE.

Rules:
- A chat assistant inside a customer workspace must automatically know:
  - which customer is selected
  - their goals
  - their modules
  - service mode
  - historical findings
  - current tasks
  - recent deliverables
- A global assistant outside a customer workspace must first ask or infer which customer is being discussed
- The assistant should never act like a disconnected generic chatbot

## 12. Portfolio / consultant operations layer

Besides customer workspaces, create a cross-customer portfolio view for consultants and managers.

This view should show:
- all customers
- service mode
- active modules
- health/risk indicators
- pending tasks
- pending approvals
- latest runs
- overdue deliverables
- customers needing attention

This is important because the platform is not only a customer workspace but also an internal operating system for the team.

## 13. Key UI components to design

Design reusable components such as:
- customer cards
- module cards
- service mode toggle
- onboarding wizard
- module selector with grouped categories
- insight cards
- recommendation cards
- task cards
- approval queue
- deliverable cards
- run status cards
- customer timeline / activity feed

Each component should have clear states:
- empty
- loading
- active
- disabled
- pending approval
- error
- completed
- scheduled

## 14. Technical architecture requirements

Design the system architecture so it is scalable and modular.

Must include:
- a CRM/customer core
- a shared customer context layer / memory layer
- a module registry
- a workflow/orchestration engine
- a run/job queue
- structured output storage
- audit logs
- role-based permissions
- integration layer
- notification layer

Important system principle:
Outputs should be stored as structured entities first, and rendered as UI/report/chat content second.

Do NOT design this as a set of isolated tool pages with light wrappers around them.

## 15. Routing / frontend structure

Propose a route structure like:

- /customers
- /customers/:customerId
- /customers/:customerId/overview
- /customers/:customerId/modules
- /customers/:customerId/insights
- /customers/:customerId/tasks
- /customers/:customerId/runs
- /customers/:customerId/reports
- /customers/:customerId/knowledge
- /customers/:customerId/settings
- /portfolio
- /templates
- /integrations
- /admin

The product must be organized around the customerId as the root context.

## 16. Migration requirements

We already have existing tools and modules. Do not throw away their functionality.

Instead:
- map every existing tool into the new module architecture
- preserve current business logic where useful
- reframe old tools as customer-attached capabilities
- avoid duplicate input forms across tools
- preserve historical outputs by attaching them to the relevant customer if possible

## 17. Required output from you

I do NOT want a vague redesign suggestion.

I want a concrete product/system specification with these sections:

1. Executive summary of the redesign
2. New product philosophy and mental model
3. New information architecture
4. Detailed user journeys
5. Screen-by-screen UX specification
6. Customer data model / entity model
7. Module architecture and taxonomy
8. Advisory vs Full service behavior design
9. AI assistant behavior design
10. Backend architecture
11. Frontend/component architecture
12. API / data flow proposal
13. Migration strategy from current product
14. Risks / edge cases
15. Phased implementation roadmap
16. Acceptance criteria / definition of done

## 18. Acceptance criteria

Your solution will only be accepted if:
- the first action in the product is selecting or creating a customer
- tools are no longer the primary landing structure
- customer context is persistent and shared across modules
- modules can be selected per customer
- advisory and full service modes are clearly implemented
- outputs from modules converge into one customer workspace
- the consultant can manage both individual customers and a multi-customer portfolio
- the platform feels like a CRM/workspace for customer delivery, not a toolbox

## 19. Important constraint

Do not merely reskin the current dashboard.

This requires a foundational redesign of:
- navigation
- information architecture
- data model
- user workflows
- permissions
- AI orchestration
- module activation logic
- reporting and task management

The result should be a customer-centric operating system for SEO and AI service delivery.


⸻

My strongest product recommendation

Do not make “full service” vs “advisory” a shallow cosmetic switch.

It should alter:
	•	what agents are allowed to do
	•	whether tasks are only suggested or actually executed
	•	whether approvals are required
	•	what gets logged
	•	what is shown in the workspace
	•	how reports are framed

That distinction should be part of the platform’s operating logic, not just its wording.

⸻

Four architectural decisions worth insisting on

1. Customer memory must be shared across all modules

A customer should only need to be defined once.
Everything else should inherit that context.

2. Outputs should become structured records

Do not let modules only produce raw text blobs.
They should generate objects like:
	•	finding
	•	recommendation
	•	task
	•	simulation
	•	report
	•	approval request
	•	deliverable

That makes the whole system composable.

3. Module selection should live in a “Service Blueprint”

This is the cleanest way to express what the customer has bought, what is active, and how the AI should behave.

4. Chat must be contextual

The floating assistant should not be generic. It should operate inside the selected customer context and understand the customer’s enabled modules, goals, and history.

⸻

A sharper one-sentence positioning

You could describe the redesign internally like this:

“AmazingTools is no longer a library of SEO tools; it is a customer-centric AI operating system for planning, executing, and managing SEO and marketing services.”

Next step could be turning this into a proper PRD with epics, user stories, and acceptance criteria for your AI coder or dev team.

<!DOCTYPE html>

<html lang="sv">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AmazingTools — Customer OS (Mockup)</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300;0,9..144,400;0,9..144,500;0,9..144,600;1,9..144,400&family=Inter+Tight:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #f4f1ea;
  --bg-card: #fbfaf6;
  --bg-panel: #ffffff;
  --ink: #0f1111;
  --ink-soft: #3a3d3d;
  --ink-mute: #6b6e6e;
  --line: #d9d4c6;
  --line-soft: #e8e3d4;
  --teal: #0fa6a0;
  --teal-deep: #0b7a76;
  --teal-soft: #d4ece9;
  --amber: #c67b1a;
  --amber-soft: #f5e6cd;
  --rose: #b34a4a;
  --rose-soft: #f0d9d9;
  --ok: #2f7a4d;
  --ok-soft: #d4e8dc;
  --shadow: 0 1px 0 rgba(15,17,17,0.04), 0 12px 32px -12px rgba(15,17,17,0.08);
  --shadow-lift: 0 2px 0 rgba(15,17,17,0.05), 0 24px 48px -18px rgba(15,17,17,0.18);
}

- { box-sizing: border-box; margin: 0; padding: 0; }

html, body {
background: var(–bg);
color: var(–ink);
font-family: ‘Inter Tight’, sans-serif;
font-size: 14px;
line-height: 1.5;
-webkit-font-smoothing: antialiased;
min-height: 100vh;
}

body {
background-image:
radial-gradient(circle at 12% 8%, rgba(15,166,160,0.06) 0%, transparent 42%),
radial-gradient(circle at 88% 92%, rgba(198,123,26,0.05) 0%, transparent 40%);
}

.serif { font-family: ‘Fraunces’, serif; font-weight: 400; letter-spacing: -0.01em; }
.mono { font-family: ‘JetBrains Mono’, monospace; }

/* ===== Layout shell ===== */
.app {
display: grid;
grid-template-columns: 240px 1fr;
min-height: 100vh;
max-width: 1600px;
margin: 0 auto;
}

/* ===== Sidebar ===== */
.sidebar {
background: var(–bg);
border-right: 1px solid var(–line);
padding: 28px 20px;
display: flex;
flex-direction: column;
gap: 28px;
position: sticky;
top: 0;
height: 100vh;
overflow-y: auto;
}

.brand {
display: flex;
align-items: baseline;
gap: 8px;
}
.brand-mark {
font-family: ‘Fraunces’, serif;
font-weight: 500;
font-size: 22px;
letter-spacing: -0.02em;
}
.brand-mark i { font-style: italic; color: var(–teal-deep); }
.brand-tag {
font-size: 10px;
letter-spacing: 0.12em;
text-transform: uppercase;
color: var(–ink-mute);
font-family: ‘JetBrains Mono’, monospace;
}

.nav-section {
display: flex;
flex-direction: column;
gap: 2px;
}
.nav-label {
font-size: 10px;
letter-spacing: 0.14em;
text-transform: uppercase;
color: var(–ink-mute);
padding: 0 10px;
margin-bottom: 8px;
font-weight: 600;
}
.nav-item {
display: flex;
align-items: center;
gap: 10px;
padding: 8px 10px;
border-radius: 6px;
cursor: pointer;
color: var(–ink-soft);
font-weight: 500;
font-size: 13.5px;
transition: all 0.15s ease;
border: 1px solid transparent;
}
.nav-item:hover { background: rgba(15,17,17,0.04); color: var(–ink); }
.nav-item.active {
background: var(–bg-panel);
color: var(–ink);
border-color: var(–line);
box-shadow: 0 1px 0 rgba(15,17,17,0.03);
}
.nav-item .dot {
width: 6px; height: 6px; border-radius: 50%;
background: var(–ink-mute);
flex-shrink: 0;
}
.nav-item.active .dot { background: var(–teal); }
.nav-item .badge {
margin-left: auto;
font-size: 10px;
background: var(–line-soft);
padding: 1px 6px;
border-radius: 8px;
font-weight: 600;
color: var(–ink-soft);
}

.sidebar-foot {
margin-top: auto;
padding: 14px;
background: var(–bg-panel);
border: 1px solid var(–line);
border-radius: 8px;
font-size: 12px;
}
.sidebar-foot .who { font-weight: 600; margin-bottom: 2px; }
.sidebar-foot .role { color: var(–ink-mute); font-size: 11px; }

/* ===== Main ===== */
.main {
padding: 0;
position: relative;
min-height: 100vh;
}

.topbar {
display: flex;
align-items: center;
gap: 16px;
padding: 18px 40px;
border-bottom: 1px solid var(–line);
background: rgba(244,241,234,0.85);
backdrop-filter: blur(12px);
position: sticky;
top: 0;
z-index: 20;
}
.crumb {
font-family: ‘JetBrains Mono’, monospace;
font-size: 12px;
color: var(–ink-mute);
letter-spacing: 0.02em;
}
.crumb b { color: var(–ink); font-weight: 500; }
.crumb .sep { margin: 0 8px; opacity: 0.4; }

.search {
margin-left: auto;
display: flex;
align-items: center;
gap: 8px;
padding: 6px 12px;
background: var(–bg-panel);
border: 1px solid var(–line);
border-radius: 6px;
font-size: 12px;
color: var(–ink-mute);
min-width: 280px;
}
.search .k { font-family: ‘JetBrains Mono’, monospace; font-size: 10px; background: var(–line-soft); padding: 1px 5px; border-radius: 3px; margin-left: auto; }

.btn {
display: inline-flex;
align-items: center;
gap: 6px;
padding: 7px 14px;
border-radius: 6px;
border: 1px solid var(–line);
background: var(–bg-panel);
color: var(–ink);
font-family: inherit;
font-size: 13px;
font-weight: 500;
cursor: pointer;
transition: all 0.15s;
}
.btn:hover { background: var(–line-soft); }
.btn-primary {
background: var(–ink);
color: var(–bg);
border-color: var(–ink);
}
.btn-primary:hover { background: var(–teal-deep); border-color: var(–teal-deep); }
.btn-ghost { background: transparent; border-color: transparent; }
.btn-ghost:hover { background: rgba(15,17,17,0.05); }

/* ===== View container ===== */
.view {
padding: 32px 40px 120px;
display: none;
animation: fadeIn 0.3s ease;
}
.view.active { display: block; }
@keyframes fadeIn {
from { opacity: 0; transform: translateY(4px); }
to { opacity: 1; transform: translateY(0); }
}

/* ===== Page headers ===== */
.page-head {
display: flex;
align-items: flex-end;
gap: 24px;
margin-bottom: 32px;
padding-bottom: 24px;
border-bottom: 1px solid var(–line-soft);
}
.page-head h1 {
font-family: ‘Fraunces’, serif;
font-weight: 400;
font-size: 44px;
line-height: 1;
letter-spacing: -0.02em;
}
.page-head h1 i { color: var(–teal-deep); font-weight: 300; }
.page-head .sub {
color: var(–ink-mute);
font-size: 14px;
max-width: 500px;
margin-top: 6px;
}
.page-head .actions { margin-left: auto; display: flex; gap: 8px; }

/* ===== Customers grid ===== */
.filter-row {
display: flex;
align-items: center;
gap: 8px;
margin-bottom: 20px;
flex-wrap: wrap;
}
.chip {
padding: 5px 11px;
background: var(–bg-panel);
border: 1px solid var(–line);
border-radius: 16px;
font-size: 12px;
color: var(–ink-soft);
cursor: pointer;
font-weight: 500;
transition: all 0.15s;
}
.chip:hover { border-color: var(–ink); }
.chip.on { background: var(–ink); color: var(–bg); border-color: var(–ink); }
.chip-count { opacity: 0.6; margin-left: 4px; }

.customers-grid {
display: grid;
grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
gap: 16px;
}
.cust-card {
background: var(–bg-card);
border: 1px solid var(–line);
border-radius: 10px;
padding: 20px;
cursor: pointer;
transition: all 0.2s;
position: relative;
overflow: hidden;
}
.cust-card::before {
content: ‘’;
position: absolute;
top: 0; left: 0; right: 0;
height: 3px;
background: var(–teal);
transform: translateY(-3px);
transition: transform 0.2s;
}
.cust-card:hover {
box-shadow: var(–shadow-lift);
border-color: var(–ink);
transform: translateY(-2px);
}
.cust-card:hover::before { transform: translateY(0); }
.cust-card.new-card {
border-style: dashed;
background: transparent;
display: flex;
flex-direction: column;
align-items: center;
justify-content: center;
text-align: center;
min-height: 200px;
color: var(–ink-mute);
}
.cust-card.new-card:hover { border-color: var(–teal-deep); color: var(–teal-deep); }
.cust-card.new-card .plus {
font-family: ‘Fraunces’, serif;
font-size: 40px;
line-height: 1;
font-weight: 300;
margin-bottom: 10px;
}

.cust-head {
display: flex;
align-items: flex-start;
gap: 12px;
margin-bottom: 14px;
}
.cust-logo {
width: 40px; height: 40px;
border-radius: 8px;
background: var(–ink);
color: var(–bg);
display: flex;
align-items: center;
justify-content: center;
font-family: ‘Fraunces’, serif;
font-weight: 500;
font-size: 18px;
flex-shrink: 0;
}
.cust-logo.c2 { background: var(–teal-deep); }
.cust-logo.c3 { background: var(–amber); }
.cust-logo.c4 { background: var(–rose); }
.cust-logo.c5 { background: #4a5d4c; }
.cust-logo.c6 { background: #5a4a6d; }

.cust-name { font-weight: 600; font-size: 15px; margin-bottom: 2px; }
.cust-domain { font-family: ‘JetBrains Mono’, monospace; font-size: 11px; color: var(–ink-mute); }

.cust-mode {
display: inline-flex;
align-items: center;
gap: 5px;
padding: 2px 8px;
border-radius: 12px;
font-size: 10.5px;
font-weight: 600;
letter-spacing: 0.04em;
text-transform: uppercase;
margin-top: 10px;
}
.mode-advisory { background: var(–amber-soft); color: var(–amber); }
.mode-full { background: var(–teal-soft); color: var(–teal-deep); }
.mode-onboard { background: var(–line-soft); color: var(–ink-soft); }

.cust-meta {
display: grid;
grid-template-columns: 1fr 1fr;
gap: 10px;
margin-top: 14px;
padding-top: 14px;
border-top: 1px dashed var(–line);
}
.meta-item .label {
font-size: 10px;
color: var(–ink-mute);
text-transform: uppercase;
letter-spacing: 0.08em;
margin-bottom: 2px;
}
.meta-item .val {
font-size: 13px;
font-weight: 500;
}
.meta-item .val.alert { color: var(–rose); }
.meta-item .val.ok { color: var(–ok); }

.cust-mods {
display: flex;
gap: 3px;
margin-top: 12px;
flex-wrap: wrap;
}
.mod-pip {
width: 22px; height: 22px;
border-radius: 4px;
background: var(–line-soft);
display: flex;
align-items: center;
justify-content: center;
font-size: 10px;
font-weight: 700;
color: var(–ink-soft);
}
.mod-pip.on { background: var(–teal); color: white; }
.mod-pip.on-amber { background: var(–amber); color: white; }

/* ===== Workspace ===== */
.ws-header {
display: flex;
align-items: flex-start;
gap: 20px;
margin-bottom: 0;
padding-bottom: 20px;
}
.ws-logo {
width: 60px; height: 60px;
border-radius: 12px;
background: var(–teal-deep);
color: white;
display: flex;
align-items: center;
justify-content: center;
font-family: ‘Fraunces’, serif;
font-weight: 500;
font-size: 28px;
flex-shrink: 0;
}
.ws-title h1 {
font-family: ‘Fraunces’, serif;
font-weight: 400;
font-size: 34px;
letter-spacing: -0.02em;
line-height: 1.1;
margin-bottom: 4px;
}
.ws-title .ws-domain {
font-family: ‘JetBrains Mono’, monospace;
font-size: 12px;
color: var(–ink-mute);
}
.ws-title .ws-tags { margin-top: 10px; display: flex; gap: 6px; flex-wrap: wrap; }
.tag {
font-size: 11px;
padding: 2px 9px;
background: var(–line-soft);
border-radius: 10px;
color: var(–ink-soft);
font-weight: 500;
}

.mode-toggle {
margin-left: auto;
display: flex;
flex-direction: column;
gap: 6px;
align-items: flex-end;
}
.mode-toggle .label {
font-size: 10px;
letter-spacing: 0.14em;
text-transform: uppercase;
color: var(–ink-mute);
font-weight: 600;
}
.toggle {
display: inline-flex;
background: var(–bg-panel);
border: 1px solid var(–line);
border-radius: 8px;
padding: 3px;
}
.toggle button {
padding: 6px 12px;
border: none;
background: transparent;
font-family: inherit;
font-size: 12px;
font-weight: 600;
cursor: pointer;
border-radius: 5px;
color: var(–ink-mute);
transition: all 0.15s;
}
.toggle button.on {
background: var(–ink);
color: var(–bg);
}
.toggle button.on.advisory { background: var(–amber); color: white; }

/* Tabs */
.tabs {
display: flex;
gap: 0;
border-bottom: 1px solid var(–line);
margin-bottom: 28px;
overflow-x: auto;
}
.tab {
padding: 12px 18px;
background: transparent;
border: none;
border-bottom: 2px solid transparent;
font-family: inherit;
font-size: 13.5px;
font-weight: 500;
color: var(–ink-mute);
cursor: pointer;
white-space: nowrap;
transition: all 0.15s;
margin-bottom: -1px;
}
.tab:hover { color: var(–ink); }
.tab.active {
color: var(–ink);
border-bottom-color: var(–teal);
}
.tab .tab-count {
font-family: ‘JetBrains Mono’, monospace;
font-size: 10px;
background: var(–line-soft);
padding: 1px 6px;
border-radius: 8px;
margin-left: 6px;
font-weight: 600;
}

/* Tab panes */
.pane { display: none; }
.pane.active { display: block; animation: fadeIn 0.25s ease; }

/* Overview grid */
.ov-grid {
display: grid;
grid-template-columns: 2fr 1fr;
gap: 20px;
}
.ov-col { display: flex; flex-direction: column; gap: 20px; }

.panel {
background: var(–bg-card);
border: 1px solid var(–line);
border-radius: 10px;
overflow: hidden;
}
.panel-head {
padding: 14px 18px;
display: flex;
align-items: center;
gap: 10px;
border-bottom: 1px solid var(–line-soft);
}
.panel-head h3 {
font-family: ‘Fraunces’, serif;
font-weight: 500;
font-size: 17px;
letter-spacing: -0.01em;
}
.panel-head .meta-mini {
font-size: 11px;
color: var(–ink-mute);
margin-left: auto;
font-family: ‘JetBrains Mono’, monospace;
}
.panel-body { padding: 18px; }
.panel-body.tight { padding: 0; }

/* KPI strip */
.kpi-strip {
display: grid;
grid-template-columns: repeat(4, 1fr);
gap: 1px;
background: var(–line-soft);
}
.kpi {
background: var(–bg-card);
padding: 16px 18px;
}
.kpi .k-label {
font-size: 10.5px;
letter-spacing: 0.1em;
text-transform: uppercase;
color: var(–ink-mute);
font-weight: 600;
margin-bottom: 6px;
}
.kpi .k-val {
font-family: ‘Fraunces’, serif;
font-size: 26px;
font-weight: 400;
letter-spacing: -0.02em;
line-height: 1;
}
.kpi .k-delta {
font-size: 11px;
font-weight: 600;
margin-top: 4px;
font-family: ‘JetBrains Mono’, monospace;
}
.k-delta.up { color: var(–ok); }
.k-delta.down { color: var(–rose); }

/* Feed */
.feed-item {
display: grid;
grid-template-columns: auto 1fr auto;
gap: 14px;
padding: 14px 18px;
border-bottom: 1px solid var(–line-soft);
align-items: flex-start;
cursor: pointer;
transition: background 0.15s;
}
.feed-item:last-child { border-bottom: none; }
.feed-item:hover { background: rgba(15,17,17,0.02); }
.feed-icon {
width: 32px; height: 32px;
border-radius: 7px;
background: var(–line-soft);
display: flex;
align-items: center;
justify-content: center;
font-family: ‘Fraunces’, serif;
font-weight: 500;
font-size: 14px;
flex-shrink: 0;
}
.feed-icon.insight { background: var(–teal-soft); color: var(–teal-deep); }
.feed-icon.task { background: var(–amber-soft); color: var(–amber); }
.feed-icon.approval { background: var(–rose-soft); color: var(–rose); }
.feed-icon.deliverable { background: #e8e0f0; color: #5a4a6d; }
.feed-icon.run { background: var(–ok-soft); color: var(–ok); }
.feed-title { font-weight: 600; font-size: 13.5px; margin-bottom: 2px; }
.feed-desc { font-size: 12.5px; color: var(–ink-mute); }
.feed-time {
font-family: ‘JetBrains Mono’, monospace;
font-size: 10.5px;
color: var(–ink-mute);
white-space: nowrap;
}

/* Task row */
.task-row {
display: grid;
grid-template-columns: auto 1fr auto auto;
gap: 12px;
padding: 12px 18px;
border-bottom: 1px solid var(–line-soft);
align-items: center;
font-size: 13px;
}
.task-row:last-child { border-bottom: none; }
.check {
width: 16px; height: 16px;
border: 1.5px solid var(–line);
border-radius: 4px;
background: white;
cursor: pointer;
}
.task-title { font-weight: 500; }
.task-meta { font-size: 11px; color: var(–ink-mute); margin-top: 2px; }
.task-impact {
font-size: 10px;
font-weight: 700;
padding: 2px 7px;
border-radius: 10px;
letter-spacing: 0.04em;
}
.impact-high { background: var(–rose-soft); color: var(–rose); }
.impact-med { background: var(–amber-soft); color: var(–amber); }
.impact-low { background: var(–line-soft); color: var(–ink-mute); }
.task-owner {
font-size: 11px;
font-family: ‘JetBrains Mono’, monospace;
color: var(–ink-mute);
}
.task-owner.ai { color: var(–teal-deep); }

/* Advisory / full service notice */
.mode-notice {
display: flex;
align-items: flex-start;
gap: 12px;
padding: 14px 16px;
border-radius: 8px;
margin-bottom: 20px;
font-size: 13px;
}
.mode-notice.advisory {
background: var(–amber-soft);
border: 1px solid rgba(198,123,26,0.25);
color: #6b4511;
}
.mode-notice.full {
background: var(–teal-soft);
border: 1px solid rgba(15,166,160,0.25);
color: #0a5f5c;
}
.mode-notice .icon {
font-family: ‘Fraunces’, serif;
font-size: 22px;
line-height: 1;
font-weight: 500;
}
.mode-notice b { font-weight: 600; }

/* Modules pane */
.module-group {
margin-bottom: 28px;
}
.module-group h4 {
font-family: ‘Fraunces’, serif;
font-weight: 500;
font-size: 19px;
letter-spacing: -0.01em;
margin-bottom: 4px;
}
.module-group .group-sub {
font-size: 12px;
color: var(–ink-mute);
margin-bottom: 14px;
}

.mod-grid {
display: grid;
grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
gap: 12px;
}
.mod-card {
background: var(–bg-card);
border: 1px solid var(–line);
border-radius: 8px;
padding: 16px;
position: relative;
cursor: pointer;
transition: all 0.15s;
}
.mod-card:hover { border-color: var(–ink); }
.mod-card.enabled {
background: var(–bg-card);
border-color: var(–teal);
box-shadow: inset 0 0 0 1px var(–teal);
}
.mod-card .mod-head {
display: flex;
align-items: center;
gap: 8px;
margin-bottom: 8px;
}
.mod-card .mod-icon {
width: 28px; height: 28px;
border-radius: 6px;
background: var(–line-soft);
display: flex;
align-items: center;
justify-content: center;
font-family: ‘JetBrains Mono’, monospace;
font-weight: 700;
font-size: 11px;
color: var(–ink-soft);
}
.mod-card.enabled .mod-icon { background: var(–teal); color: white; }
.mod-card .mod-name { font-weight: 600; font-size: 13.5px; flex: 1; }
.mod-card .mod-switch {
width: 32px; height: 18px;
background: var(–line);
border-radius: 10px;
position: relative;
transition: all 0.2s;
}
.mod-card .mod-switch::after {
content: ‘’;
position: absolute;
width: 14px; height: 14px;
background: white;
border-radius: 50%;
top: 2px; left: 2px;
transition: all 0.2s;
box-shadow: 0 1px 2px rgba(0,0,0,0.2);
}
.mod-card.enabled .mod-switch { background: var(–teal); }
.mod-card.enabled .mod-switch::after { left: 16px; }
.mod-card .mod-desc { font-size: 12px; color: var(–ink-mute); line-height: 1.45; }
.mod-card .mod-foot {
display: flex;
gap: 6px;
margin-top: 10px;
font-size: 10.5px;
color: var(–ink-mute);
font-family: ‘JetBrains Mono’, monospace;
}

/* ===== Contextual chat ===== */
.chat {
position: fixed;
right: 24px;
bottom: 24px;
width: 360px;
background: var(–bg-panel);
border: 1px solid var(–line);
border-radius: 12px;
box-shadow: var(–shadow-lift);
overflow: hidden;
z-index: 50;
display: none;
flex-direction: column;
max-height: 520px;
}
.chat.open { display: flex; }
.chat-head {
padding: 14px 16px;
border-bottom: 1px solid var(–line-soft);
display: flex;
align-items: center;
gap: 10px;
background: var(–bg-card);
}
.chat-avatar {
width: 32px; height: 32px;
border-radius: 50%;
background: var(–teal-deep);
color: white;
display: flex;
align-items: center;
justify-content: center;
font-family: ‘Fraunces’, serif;
font-weight: 500;
font-size: 14px;
position: relative;
}
.chat-avatar::after {
content: ‘’;
width: 8px; height: 8px;
background: var(–ok);
border: 2px solid var(–bg-panel);
border-radius: 50%;
position: absolute;
bottom: -2px; right: -2px;
}
.chat-title { font-weight: 600; font-size: 13.5px; }
.chat-ctx { font-size: 11px; color: var(–ink-mute); font-family: ‘JetBrains Mono’, monospace; }
.chat-close {
margin-left: auto;
background: none;
border: none;
cursor: pointer;
color: var(–ink-mute);
font-size: 18px;
padding: 4px;
}
.chat-body {
padding: 14px;
flex: 1;
overflow-y: auto;
display: flex;
flex-direction: column;
gap: 10px;
}
.msg {
padding: 10px 12px;
border-radius: 10px;
font-size: 13px;
max-width: 88%;
line-height: 1.45;
}
.msg.bot {
background: var(–bg-card);
border: 1px solid var(–line-soft);
align-self: flex-start;
border-bottom-left-radius: 2px;
}
.msg.user {
background: var(–ink);
color: var(–bg);
align-self: flex-end;
border-bottom-right-radius: 2px;
}
.msg .ctx-pill {
display: inline-block;
font-size: 10px;
font-family: ‘JetBrains Mono’, monospace;
background: var(–teal-soft);
color: var(–teal-deep);
padding: 1px 6px;
border-radius: 8px;
margin-bottom: 6px;
font-weight: 600;
}
.chat-input {
display: flex;
padding: 10px;
gap: 8px;
border-top: 1px solid var(–line-soft);
}
.chat-input input {
flex: 1;
border: 1px solid var(–line);
border-radius: 6px;
padding: 8px 10px;
font-family: inherit;
font-size: 13px;
outline: none;
}
.chat-input input:focus { border-color: var(–ink); }
.chat-input button {
padding: 0 14px;
background: var(–ink);
color: var(–bg);
border: none;
border-radius: 6px;
font-weight: 600;
cursor: pointer;
font-family: inherit;
font-size: 13px;
}

.chat-fab {
position: fixed;
right: 24px;
bottom: 24px;
width: 52px; height: 52px;
background: var(–ink);
color: var(–bg);
border: none;
border-radius: 50%;
cursor: pointer;
box-shadow: var(–shadow-lift);
z-index: 49;
display: flex;
align-items: center;
justify-content: center;
font-family: ‘Fraunces’, serif;
font-size: 22px;
font-weight: 500;
transition: transform 0.2s;
}
.chat-fab:hover { transform: scale(1.05); }
.chat-fab.hidden { display: none; }

/* Wizard */
.wizard-overlay {
position: fixed;
inset: 0;
background: rgba(15,17,17,0.45);
backdrop-filter: blur(4px);
z-index: 100;
display: none;
align-items: center;
justify-content: center;
padding: 40px;
}
.wizard-overlay.open { display: flex; }
.wizard {
background: var(–bg);
border-radius: 14px;
max-width: 720px;
width: 100%;
max-height: 90vh;
overflow: hidden;
display: flex;
flex-direction: column;
box-shadow: 0 40px 80px -20px rgba(0,0,0,0.4);
}
.wiz-head {
padding: 24px 28px 20px;
border-bottom: 1px solid var(–line);
display: flex;
align-items: flex-start;
gap: 16px;
}
.wiz-head h2 {
font-family: ‘Fraunces’, serif;
font-weight: 400;
font-size: 26px;
letter-spacing: -0.02em;
line-height: 1.1;
}
.wiz-head .wiz-sub { color: var(–ink-mute); font-size: 13px; margin-top: 4px; }
.wiz-close {
margin-left: auto;
background: none;
border: none;
cursor: pointer;
font-size: 22px;
color: var(–ink-mute);
}
.wiz-steps {
display: flex;
padding: 0 28px;
gap: 4px;
border-bottom: 1px solid var(–line);
background: var(–bg);
}
.wiz-step {
padding: 14px 0 14px;
flex: 1;
font-size: 11px;
color: var(–ink-mute);
border-bottom: 2px solid transparent;
display: flex;
align-items: center;
gap: 8px;
font-weight: 600;
text-transform: uppercase;
letter-spacing: 0.05em;
}
.wiz-step .n {
width: 20px; height: 20px;
border-radius: 50%;
background: var(–line-soft);
color: var(–ink-mute);
display: flex;
align-items: center;
justify-content: center;
font-size: 11px;
font-family: ‘JetBrains Mono’, monospace;
}
.wiz-step.done .n { background: var(–ok); color: white; }
.wiz-step.active { color: var(–ink); border-bottom-color: var(–teal); }
.wiz-step.active .n { background: var(–ink); color: white; }

.wiz-body {
padding: 28px;
overflow-y: auto;
flex: 1;
}
.wiz-foot {
padding: 16px 28px;
border-top: 1px solid var(–line);
display: flex;
justify-content: space-between;
background: var(–bg-card);
}

.form-row {
display: grid;
grid-template-columns: 1fr 1fr;
gap: 16px;
margin-bottom: 14px;
}
.form-group { display: flex; flex-direction: column; gap: 6px; }
.form-group.full { grid-column: 1 / -1; }
.form-group label {
font-size: 11px;
font-weight: 600;
color: var(–ink-soft);
text-transform: uppercase;
letter-spacing: 0.06em;
}
.form-group input, .form-group select, .form-group textarea {
padding: 10px 12px;
border: 1px solid var(–line);
border-radius: 6px;
font-family: inherit;
font-size: 13.5px;
background: var(–bg-panel);
outline: none;
transition: border 0.15s;
}
.form-group input:focus, .form-group select:focus, .form-group textarea:focus { border-color: var(–ink); }

.mode-picker {
display: grid;
grid-template-columns: 1fr 1fr;
gap: 12px;
margin-top: 8px;
}
.mode-option {
padding: 18px;
border: 1px solid var(–line);
border-radius: 10px;
cursor: pointer;
background: var(–bg-panel);
transition: all 0.15s;
}
.mode-option.sel {
border-color: var(–ink);
box-shadow: inset 0 0 0 1px var(–ink);
}
.mode-option .mo-head {
font-family: ‘Fraunces’, serif;
font-weight: 500;
font-size: 17px;
margin-bottom: 4px;
display: flex;
align-items: center;
gap: 8px;
}
.mode-option .mo-desc {
font-size: 12.5px;
color: var(–ink-mute);
line-height: 1.5;
}
.mode-option .mo-tag {
margin-top: 10px;
display: inline-block;
font-size: 10px;
font-weight: 700;
padding: 2px 7px;
border-radius: 10px;
letter-spacing: 0.04em;
text-transform: uppercase;
}

/* Portfolio table */
.table-wrap {
background: var(–bg-card);
border: 1px solid var(–line);
border-radius: 10px;
overflow: hidden;
}
table.portfolio {
width: 100%;
border-collapse: collapse;
font-size: 13px;
}
table.portfolio th {
text-align: left;
padding: 12px 16px;
font-size: 10.5px;
font-weight: 600;
letter-spacing: 0.08em;
text-transform: uppercase;
color: var(–ink-mute);
border-bottom: 1px solid var(–line);
background: var(–bg-card);
}
table.portfolio td {
padding: 14px 16px;
border-bottom: 1px solid var(–line-soft);
}
table.portfolio tr:hover td { background: rgba(15,17,17,0.015); cursor: pointer; }
table.portfolio tr:last-child td { border-bottom: none; }

.health-bar {
width: 60px;
height: 6px;
background: var(–line-soft);
border-radius: 3px;
overflow: hidden;
display: inline-block;
vertical-align: middle;
}
.health-bar span {
display: block;
height: 100%;
border-radius: 3px;
}
.health-good { background: var(–ok); }
.health-warn { background: var(–amber); }
.health-bad { background: var(–rose); }

/* Insight cards */
.insight {
display: grid;
grid-template-columns: auto 1fr auto;
gap: 14px;
padding: 16px 18px;
border-bottom: 1px solid var(–line-soft);
align-items: flex-start;
}
.insight:last-child { border-bottom: none; }
.insight .ins-marker {
width: 4px;
align-self: stretch;
border-radius: 2px;
}
.insight.sev-high .ins-marker { background: var(–rose); }
.insight.sev-med .ins-marker { background: var(–amber); }
.insight.sev-low .ins-marker { background: var(–teal); }
.insight .ins-title { font-weight: 600; font-size: 14px; margin-bottom: 4px; }
.insight .ins-body { font-size: 13px; color: var(–ink-soft); margin-bottom: 8px; line-height: 1.5; }
.insight .ins-meta { display: flex; gap: 8px; font-size: 11px; color: var(–ink-mute); font-family: ‘JetBrains Mono’, monospace; align-items: center; }
.insight .ins-source { padding: 1px 6px; background: var(–line-soft); border-radius: 4px; }
.insight .ins-actions { display: flex; flex-direction: column; gap: 6px; }

.empty-hint {
padding: 40px 20px;
text-align: center;
color: var(–ink-mute);
font-size: 13px;
}
.empty-hint .em {
font-family: ‘Fraunces’, serif;
font-size: 28px;
font-weight: 400;
color: var(–ink-soft);
margin-bottom: 6px;
}

/* Old vs New marker banner */
.shift-banner {
background: linear-gradient(90deg, var(–ink) 0%, #2a2d2d 100%);
color: var(–bg);
padding: 14px 20px;
border-radius: 10px;
display: flex;
align-items: center;
gap: 16px;
margin-bottom: 24px;
font-size: 13px;
}
.shift-banner .left {
font-family: ‘Fraunces’, serif;
font-weight: 500;
font-size: 18px;
letter-spacing: -0.01em;
}
.shift-banner .arrow {
font-family: ‘Fraunces’, serif;
font-size: 22px;
color: var(–teal);
}
.shift-banner .right {
font-family: ‘Fraunces’, serif;
font-weight: 500;
font-size: 18px;
color: var(–teal-soft);
letter-spacing: -0.01em;
}
.shift-banner .tag-old, .shift-banner .tag-new {
font-size: 10px;
font-family: ‘JetBrains Mono’, monospace;
letter-spacing: 0.08em;
text-transform: uppercase;
opacity: 0.7;
margin-right: 8px;
}

@media (max-width: 900px) {
.app { grid-template-columns: 1fr; }
.sidebar { position: static; height: auto; }
.ov-grid { grid-template-columns: 1fr; }
.view { padding: 20px; }
}
</style>

</head>
<body>

<div class="app">

  <!-- SIDEBAR -->

  <aside class="sidebar">
    <div class="brand">
      <div class="brand-mark">Amazing<i>Tools</i></div>
    </div>
    <div class="brand-tag">Customer OS · v2</div>

```
<div class="nav-section">
  <div class="nav-label">Primary</div>
  <div class="nav-item active" data-view="customers"><span class="dot"></span>Customers<span class="badge">14</span></div>
  <div class="nav-item" data-view="portfolio"><span class="dot"></span>Portfolio</div>
  <div class="nav-item" data-view="tasks"><span class="dot"></span>Tasks &amp; Approvals<span class="badge">7</span></div>
  <div class="nav-item" data-view="reports"><span class="dot"></span>Reports</div>
</div>

<div class="nav-section">
  <div class="nav-label">Configuration</div>
  <div class="nav-item" data-view="templates"><span class="dot"></span>Service Blueprints</div>
  <div class="nav-item" data-view="integrations"><span class="dot"></span>Integrations</div>
  <div class="nav-item" data-view="admin"><span class="dot"></span>Admin</div>
</div>

<div class="sidebar-foot">
  <div class="who">Anna Lindqvist</div>
  <div class="role">Senior SEO Consultant</div>
</div>
```

  </aside>

  <!-- MAIN -->

  <main class="main">

```
<!-- TOPBAR -->
<div class="topbar">
  <div class="crumb" id="crumb">
    <b>Customers</b>
  </div>
  <div class="search">
    <span>⌕  Search customers, modules, insights…</span>
    <span class="k">⌘K</span>
  </div>
  <button class="btn btn-ghost">Notifications</button>
</div>

<!-- ============ VIEW: CUSTOMERS ============ -->
<section class="view active" id="view-customers">
  <div class="shift-banner">
    <span class="tag-old">Före</span>
    <span class="left">Tool-centric dashboard</span>
    <span class="arrow">→</span>
    <span class="tag-new">Nu</span>
    <span class="right">Customer-centric operating system</span>
  </div>

  <div class="page-head">
    <div>
      <h1>Customers<i>.</i></h1>
      <div class="sub">Börja alltid här. Välj en kund för att öppna deras workspace — eller skapa en ny.</div>
    </div>
    <div class="actions">
      <button class="btn">Import</button>
      <button class="btn btn-primary" onclick="openWizard()">＋ New customer</button>
    </div>
  </div>

  <div class="filter-row">
    <span class="chip on">All <span class="chip-count">14</span></span>
    <span class="chip">Active <span class="chip-count">11</span></span>
    <span class="chip">Onboarding <span class="chip-count">2</span></span>
    <span class="chip">Paused <span class="chip-count">1</span></span>
    <span class="chip">My customers</span>
    <span class="chip">Needs attention</span>
    <span style="margin-left:auto;font-size:12px;color:var(--ink-mute);">Sort: Recent activity</span>
  </div>

  <div class="customers-grid">

    <div class="cust-card" onclick="openWorkspace('nordika')">
      <div class="cust-head">
        <div class="cust-logo">N</div>
        <div>
          <div class="cust-name">Nordika Furniture</div>
          <div class="cust-domain">nordika.se</div>
          <span class="cust-mode mode-full">● Full service</span>
        </div>
      </div>
      <div class="cust-meta">
        <div class="meta-item"><div class="label">Owner</div><div class="val">Anna L.</div></div>
        <div class="meta-item"><div class="label">Open tasks</div><div class="val alert">6</div></div>
        <div class="meta-item"><div class="label">Markets</div><div class="val">SE · NO · DK</div></div>
        <div class="meta-item"><div class="label">Last run</div><div class="val">2 h ago</div></div>
      </div>
      <div class="cust-mods">
        <div class="mod-pip on">VT</div>
        <div class="mod-pip on">SC</div>
        <div class="mod-pip on">QM</div>
        <div class="mod-pip on">IPR</div>
        <div class="mod-pip on-amber">MA</div>
        <div class="mod-pip">PS</div>
      </div>
    </div>

    <div class="cust-card" onclick="openWorkspace('brinkens')">
      <div class="cust-head">
        <div class="cust-logo c2">B</div>
        <div>
          <div class="cust-name">Brinkens Bryggeri</div>
          <div class="cust-domain">brinkens.se</div>
          <span class="cust-mode mode-advisory">● Advisory</span>
        </div>
      </div>
      <div class="cust-meta">
        <div class="meta-item"><div class="label">Owner</div><div class="val">Anna L.</div></div>
        <div class="meta-item"><div class="label">Open tasks</div><div class="val">3</div></div>
        <div class="meta-item"><div class="label">Markets</div><div class="val">SE</div></div>
        <div class="meta-item"><div class="label">Last run</div><div class="val">Yesterday</div></div>
      </div>
      <div class="cust-mods">
        <div class="mod-pip on">VT</div>
        <div class="mod-pip on">SC</div>
        <div class="mod-pip on">QM</div>
        <div class="mod-pip">IPR</div>
        <div class="mod-pip">MA</div>
        <div class="mod-pip">PS</div>
      </div>
    </div>

    <div class="cust-card" onclick="openWorkspace('otium')">
      <div class="cust-head">
        <div class="cust-logo c3">O</div>
        <div>
          <div class="cust-name">Otium Wellness</div>
          <div class="cust-domain">otium.health</div>
          <span class="cust-mode mode-full">● Full service</span>
        </div>
      </div>
      <div class="cust-meta">
        <div class="meta-item"><div class="label">Owner</div><div class="val">Marcus B.</div></div>
        <div class="meta-item"><div class="label">Open tasks</div><div class="val">2</div></div>
        <div class="meta-item"><div class="label">Markets</div><div class="val">SE · FI · DE</div></div>
        <div class="meta-item"><div class="label">Last run</div><div class="val">6 h ago</div></div>
      </div>
      <div class="cust-mods">
        <div class="mod-pip on">VT</div>
        <div class="mod-pip on">SC</div>
        <div class="mod-pip on">QM</div>
        <div class="mod-pip on">IPR</div>
        <div class="mod-pip on">MA</div>
        <div class="mod-pip on">PS</div>
      </div>
    </div>

    <div class="cust-card" onclick="openWorkspace('kairo')">
      <div class="cust-head">
        <div class="cust-logo c4">K</div>
        <div>
          <div class="cust-name">Kairo Legal</div>
          <div class="cust-domain">kairolegal.com</div>
          <span class="cust-mode mode-advisory">● Advisory</span>
        </div>
      </div>
      <div class="cust-meta">
        <div class="meta-item"><div class="label">Owner</div><div class="val">Elin S.</div></div>
        <div class="meta-item"><div class="label">Open tasks</div><div class="val alert">9</div></div>
        <div class="meta-item"><div class="label">Markets</div><div class="val">EU</div></div>
        <div class="meta-item"><div class="label">Last run</div><div class="val">3 d ago</div></div>
      </div>
      <div class="cust-mods">
        <div class="mod-pip on">VT</div>
        <div class="mod-pip on">SC</div>
        <div class="mod-pip on">QM</div>
        <div class="mod-pip">IPR</div>
        <div class="mod-pip on-amber">MA</div>
        <div class="mod-pip">PS</div>
      </div>
    </div>

    <div class="cust-card" onclick="openWorkspace('voro')">
      <div class="cust-head">
        <div class="cust-logo c5">V</div>
        <div>
          <div class="cust-name">Voro Outdoors</div>
          <div class="cust-domain">voro.outdoors</div>
          <span class="cust-mode mode-onboard">● Onboarding</span>
        </div>
      </div>
      <div class="cust-meta">
        <div class="meta-item"><div class="label">Owner</div><div class="val">Anna L.</div></div>
        <div class="meta-item"><div class="label">Open tasks</div><div class="val">—</div></div>
        <div class="meta-item"><div class="label">Markets</div><div class="val">SE · NO</div></div>
        <div class="meta-item"><div class="label">Progress</div><div class="val">Step 3/6</div></div>
      </div>
      <div class="cust-mods">
        <div class="mod-pip">VT</div>
        <div class="mod-pip">SC</div>
        <div class="mod-pip">QM</div>
        <div class="mod-pip">IPR</div>
        <div class="mod-pip">MA</div>
        <div class="mod-pip">PS</div>
      </div>
    </div>

    <div class="cust-card" onclick="openWorkspace('helix')">
      <div class="cust-head">
        <div class="cust-logo c6">H</div>
        <div>
          <div class="cust-name">Helix Studios</div>
          <div class="cust-domain">helixstudios.io</div>
          <span class="cust-mode mode-full">● Full service</span>
        </div>
      </div>
      <div class="cust-meta">
        <div class="meta-item"><div class="label">Owner</div><div class="val">Marcus B.</div></div>
        <div class="meta-item"><div class="label">Open tasks</div><div class="val">4</div></div>
        <div class="meta-item"><div class="label">Markets</div><div class="val">Global</div></div>
        <div class="meta-item"><div class="label">Last run</div><div class="val">30 min ago</div></div>
      </div>
      <div class="cust-mods">
        <div class="mod-pip on">VT</div>
        <div class="mod-pip on">SC</div>
        <div class="mod-pip on">QM</div>
        <div class="mod-pip on">IPR</div>
        <div class="mod-pip on">MA</div>
        <div class="mod-pip on">PS</div>
      </div>
    </div>

    <div class="cust-card new-card" onclick="openWizard()">
      <div class="plus">＋</div>
      <div style="font-weight:600;color:var(--ink);">Add new customer</div>
      <div style="font-size:12px;margin-top:4px;">Start onboarding wizard →</div>
    </div>

  </div>
</section>

<!-- ============ VIEW: WORKSPACE ============ -->
<section class="view" id="view-workspace">
  <div class="ws-header">
    <div class="ws-logo" id="ws-logo">N</div>
    <div class="ws-title">
      <h1 id="ws-name">Nordika Furniture</h1>
      <div class="ws-domain" id="ws-domain">nordika.se · primary</div>
      <div class="ws-tags">
        <span class="tag">E-commerce</span>
        <span class="tag">SE · NO · DK</span>
        <span class="tag">Owner: Anna L.</span>
        <span class="tag">Since Mar 2025</span>
      </div>
    </div>
    <div class="mode-toggle">
      <span class="label">Service mode</span>
      <div class="toggle" id="mode-toggle">
        <button class="advisory" onclick="setMode('advisory')">Advisory</button>
        <button class="on" onclick="setMode('full')">Full service</button>
      </div>
      <span style="font-size:10.5px;color:var(--ink-mute);font-family:'JetBrains Mono',monospace;">Alters agent behavior</span>
    </div>
  </div>

  <!-- Tabs -->
  <div class="tabs">
    <button class="tab active" onclick="openTab('overview', this)">Overview</button>
    <button class="tab" onclick="openTab('modules', this)">Modules <span class="tab-count">6 of 12</span></button>
    <button class="tab" onclick="openTab('insights', this)">Insights <span class="tab-count">23</span></button>
    <button class="tab" onclick="openTab('tasks', this)">Tasks &amp; Approvals <span class="tab-count">6</span></button>
    <button class="tab" onclick="openTab('runs', this)">Runs</button>
    <button class="tab" onclick="openTab('reports', this)">Reports</button>
    <button class="tab" onclick="openTab('knowledge', this)">Knowledge</button>
    <button class="tab" onclick="openTab('settings', this)">Settings</button>
  </div>

  <!-- OVERVIEW PANE -->
  <div class="pane active" id="pane-overview">

    <div class="mode-notice full" id="mode-notice">
      <span class="icon">◎</span>
      <div>
        <b>Full service mode is active.</b> Agents analyze, generate tasks, and execute approved workflows autonomously. High-risk actions still require your approval.
      </div>
    </div>

    <div class="panel" style="margin-bottom:20px;">
      <div class="kpi-strip">
        <div class="kpi">
          <div class="k-label">AI Visibility</div>
          <div class="k-val">34.2<span style="font-size:16px;color:var(--ink-mute);">%</span></div>
          <div class="k-delta up">↑ 4.1 pt · 30d</div>
        </div>
        <div class="kpi">
          <div class="k-label">Organic sessions</div>
          <div class="k-val">128k</div>
          <div class="k-delta up">↑ 12% · MoM</div>
        </div>
        <div class="kpi">
          <div class="k-label">Internal PageRank Δ</div>
          <div class="k-val">+0.18</div>
          <div class="k-delta up">since re-link</div>
        </div>
        <div class="kpi">
          <div class="k-label">Open issues</div>
          <div class="k-val">14</div>
          <div class="k-delta down">3 high severity</div>
        </div>
      </div>
    </div>

    <div class="ov-grid">
      <div class="ov-col">

        <div class="panel">
          <div class="panel-head">
            <h3>Recent activity</h3>
            <span class="meta-mini">Unified across all modules</span>
          </div>
          <div class="panel-body tight">
            <div class="feed-item">
              <div class="feed-icon insight">◐</div>
              <div>
                <div class="feed-title">SEO Crawler flagged 12 pages with missing canonical tags</div>
                <div class="feed-desc">/kategori/soffor and 11 sub-pages. Suggested fix drafted. <b style="color:var(--teal-deep)">MEVO</b> recommends batch remediation.</div>
              </div>
              <div class="feed-time">2h ago</div>
            </div>
            <div class="feed-item">
              <div class="feed-icon approval">!</div>
              <div>
                <div class="feed-title">Approval requested · Internal link restructure</div>
                <div class="feed-desc">IPR Sandbox simulation projects +0.23 PageRank to /categories. 47 link changes.</div>
              </div>
              <div class="feed-time">5h ago</div>
            </div>
            <div class="feed-item">
              <div class="feed-icon deliverable">◼</div>
              <div>
                <div class="feed-title">Report generated · April competitive landscape</div>
                <div class="feed-desc">AI Visibility Tracker — share of voice vs. 4 competitors, 38 pages.</div>
              </div>
              <div class="feed-time">Yesterday</div>
            </div>
            <div class="feed-item">
              <div class="feed-icon run">▶</div>
              <div>
                <div class="feed-title">Full crawl completed</div>
                <div class="feed-desc">2,847 URLs · 23 new issues · 8 resolved since last run</div>
              </div>
              <div class="feed-time">Yesterday</div>
            </div>
            <div class="feed-item">
              <div class="feed-icon task">◆</div>
              <div>
                <div class="feed-title">Ad copy variants published to Google Ads</div>
                <div class="feed-desc">Marketing Agents · Ad Copy Writer · 6 variants A/B live</div>
              </div>
              <div class="feed-time">2d ago</div>
            </div>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h3>Top recommendations</h3>
            <span class="meta-mini">Ranked by impact × confidence</span>
          </div>
          <div class="panel-body tight">
            <div class="insight sev-high">
              <div class="ins-marker"></div>
              <div>
                <div class="ins-title">Consolidate duplicate sofa category pages</div>
                <div class="ins-body">SEO Crawler + QueryMatch detected 3 category pages competing for the same query cluster ("modulsoffa"). Merging them is projected to lift rankings on 28 keywords.</div>
                <div class="ins-meta">
                  <span class="ins-source">seo-crawler</span>
                  <span class="ins-source">querymatch</span>
                  <span>Impact: +12 positions avg · Confidence 82%</span>
                </div>
              </div>
              <div class="ins-actions">
                <button class="btn btn-primary" style="font-size:11px;padding:5px 10px;">Plan</button>
                <button class="btn" style="font-size:11px;padding:5px 10px;">Dismiss</button>
              </div>
            </div>
            <div class="insight sev-med">
              <div class="ins-marker"></div>
              <div>
                <div class="ins-title">Add internal links from /blogg to commercial pages</div>
                <div class="ins-body">IPR Sandbox simulation: adding 18 contextual links lifts PageRank to priority pages by +0.23.</div>
                <div class="ins-meta">
                  <span class="ins-source">ipr-sandbox</span>
                  <span>Impact: moderate · Confidence 74%</span>
                </div>
              </div>
              <div class="ins-actions">
                <button class="btn btn-primary" style="font-size:11px;padding:5px 10px;">Plan</button>
              </div>
            </div>
          </div>
        </div>

      </div>

      <div class="ov-col">

        <div class="panel">
          <div class="panel-head">
            <h3>Enabled modules</h3>
            <span class="meta-mini">6 of 12</span>
          </div>
          <div class="panel-body">
            <div style="display:flex;flex-direction:column;gap:8px;font-size:13px;">
              <div style="display:flex;align-items:center;gap:8px;"><div class="mod-pip on">VT</div><span>AI Visibility Tracker</span><span style="margin-left:auto;font-size:11px;color:var(--ink-mute);">Weekly</span></div>
              <div style="display:flex;align-items:center;gap:8px;"><div class="mod-pip on">SC</div><span>SEO Crawler</span><span style="margin-left:auto;font-size:11px;color:var(--ink-mute);">Daily</span></div>
              <div style="display:flex;align-items:center;gap:8px;"><div class="mod-pip on">QM</div><span>QueryMatch</span><span style="margin-left:auto;font-size:11px;color:var(--ink-mute);">On-demand</span></div>
              <div style="display:flex;align-items:center;gap:8px;"><div class="mod-pip on">IPR</div><span>IPR Sandbox</span><span style="margin-left:auto;font-size:11px;color:var(--ink-mute);">On-demand</span></div>
              <div style="display:flex;align-items:center;gap:8px;"><div class="mod-pip on-amber">MA</div><span>Marketing Agents</span><span style="margin-left:auto;font-size:11px;color:var(--ink-mute);">Advisory</span></div>
              <div style="display:flex;align-items:center;gap:8px;"><div class="mod-pip">PS</div><span style="color:var(--ink-mute);">Page Simulator</span><span style="margin-left:auto;font-size:11px;color:var(--ink-mute);">Off</span></div>
            </div>
            <button class="btn" style="margin-top:12px;width:100%;font-size:12px;" onclick="openTab('modules', document.querySelectorAll('.tab')[1])">Manage modules →</button>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h3>Goals &amp; KPIs</h3>
          </div>
          <div class="panel-body">
            <div style="font-size:13px;margin-bottom:8px;"><b>Q2:</b> +20% organic sessions on category pages</div>
            <div style="font-size:13px;margin-bottom:8px;"><b>Q2:</b> Top 3 for "modulsoffa" in SE/NO</div>
            <div style="font-size:13px;"><b>Q2:</b> Reach 45% AI visibility on bedroom queries</div>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h3>Stakeholders</h3>
          </div>
          <div class="panel-body" style="font-size:13px;">
            <div style="display:flex;justify-content:space-between;margin-bottom:6px;"><span>Lisa Hagström</span><span style="color:var(--ink-mute);font-size:11px;">CMO · Approver</span></div>
            <div style="display:flex;justify-content:space-between;margin-bottom:6px;"><span>Johan Berg</span><span style="color:var(--ink-mute);font-size:11px;">E-com lead</span></div>
            <div style="display:flex;justify-content:space-between;"><span>Ida Ek</span><span style="color:var(--ink-mute);font-size:11px;">Content</span></div>
          </div>
        </div>

      </div>
    </div>
  </div>

  <!-- MODULES PANE -->
  <div class="pane" id="pane-modules">
    <p style="font-size:13.5px;color:var(--ink-mute);max-width:640px;margin-bottom:24px;">
      Configure this customer's <b style="color:var(--ink);">Service Blueprint</b>. Every enabled module runs on the shared customer context — no re-entering of domains, goals, or competitors.
    </p>

    <div class="module-group">
      <h4>A. Visibility &amp; market intelligence</h4>
      <div class="group-sub">How visible is the brand? Where does it compete?</div>
      <div class="mod-grid">
        <div class="mod-card enabled">
          <div class="mod-head">
            <div class="mod-icon">VT</div>
            <div class="mod-name">AI Visibility Tracker</div>
            <div class="mod-switch"></div>
          </div>
          <div class="mod-desc">Mention rate and Share of Voice on ChatGPT-answered queries vs. competitors.</div>
          <div class="mod-foot"><span>Weekly</span><span>· Needs: competitor list</span></div>
        </div>
        <div class="mod-card">
          <div class="mod-head">
            <div class="mod-icon">CA</div>
            <div class="mod-name">Competitor Analyst</div>
            <div class="mod-switch"></div>
          </div>
          <div class="mod-desc">Deep dive into 4 primary competitors — content, structure, backlinks.</div>
          <div class="mod-foot"><span>On-demand</span></div>
        </div>
      </div>
    </div>

    <div class="module-group">
      <h4>B. Technical SEO</h4>
      <div class="group-sub">Crawlability, health, Core Web Vitals.</div>
      <div class="mod-grid">
        <div class="mod-card enabled">
          <div class="mod-head">
            <div class="mod-icon">SC</div>
            <div class="mod-name">SEO Crawler</div>
            <div class="mod-switch"></div>
          </div>
          <div class="mod-desc">Full technical audit + up to 5 competitor sites. Titles, H1s, status codes, canonicals.</div>
          <div class="mod-foot"><span>Daily</span></div>
        </div>
        <div class="mod-card">
          <div class="mod-head">
            <div class="mod-icon">CWV</div>
            <div class="mod-name">CWV Auditor</div>
            <div class="mod-switch"></div>
          </div>
          <div class="mod-desc">Core Web Vitals monitoring with field data + remediation playbooks.</div>
          <div class="mod-foot"><span>Needs: Search Console</span></div>
        </div>
      </div>
    </div>

    <div class="module-group">
      <h4>C. Semantic relevance &amp; content</h4>
      <div class="group-sub">Does each page actually answer the query?</div>
      <div class="mod-grid">
        <div class="mod-card enabled">
          <div class="mod-head">
            <div class="mod-icon">QM</div>
            <div class="mod-name">QueryMatch</div>
            <div class="mod-switch"></div>
          </div>
          <div class="mod-desc">Semantic relevance of any URL vs. target keyword — per section.</div>
          <div class="mod-foot"><span>On-demand</span></div>
        </div>
        <div class="mod-card">
          <div class="mod-head">
            <div class="mod-icon">LR</div>
            <div class="mod-name">Landing Page Reviewer</div>
            <div class="mod-switch"></div>
          </div>
          <div class="mod-desc">AI agent reviews landing pages for clarity, CTA, trust signals.</div>
          <div class="mod-foot"><span>On-demand</span></div>
        </div>
      </div>
    </div>

    <div class="module-group">
      <h4>D. Internal linking &amp; architecture</h4>
      <div class="group-sub">Distribute authority where it matters.</div>
      <div class="mod-grid">
        <div class="mod-card enabled">
          <div class="mod-head">
            <div class="mod-icon">IPR</div>
            <div class="mod-name">IPR Sandbox</div>
            <div class="mod-switch"></div>
          </div>
          <div class="mod-desc">Simulate internal linking changes and see PageRank impact live.</div>
          <div class="mod-foot"><span>On-demand</span></div>
        </div>
        <div class="mod-card">
          <div class="mod-head">
            <div class="mod-icon">PS</div>
            <div class="mod-name">Page Simulator</div>
            <div class="mod-switch"></div>
          </div>
          <div class="mod-desc">Zoom in on one page — measure inbound/outbound link impact.</div>
          <div class="mod-foot"><span>On-demand</span></div>
        </div>
      </div>
    </div>

    <div class="module-group">
      <h4>E. Marketing &amp; conversion operations</h4>
      <div class="group-sub">AI-driven execution across paid + landing pages.</div>
      <div class="mod-grid">
        <div class="mod-card enabled">
          <div class="mod-head">
            <div class="mod-icon">MA</div>
            <div class="mod-name">Marketing Agents</div>
            <div class="mod-switch"></div>
          </div>
          <div class="mod-desc">Ad Copy Writer, UTM Builder, Conversion Debugger, Lead Qualifier.</div>
          <div class="mod-foot"><span>Per-agent config</span></div>
        </div>
        <div class="mod-card">
          <div class="mod-head">
            <div class="mod-icon">CD</div>
            <div class="mod-name">Conversion Debugger</div>
            <div class="mod-switch"></div>
          </div>
          <div class="mod-desc">Diagnose drop-off on key funnels. Suggests tests.</div>
          <div class="mod-foot"><span>Needs: GA4</span></div>
        </div>
      </div>
    </div>
  </div>

  <!-- INSIGHTS PANE -->
  <div class="pane" id="pane-insights">
    <div class="filter-row">
      <span class="chip on">All <span class="chip-count">23</span></span>
      <span class="chip">High severity <span class="chip-count">3</span></span>
      <span class="chip">Technical</span>
      <span class="chip">Content</span>
      <span class="chip">Architecture</span>
      <span class="chip">Visibility</span>
    </div>
    <div class="panel">
      <div class="panel-body tight">
        <div class="insight sev-high">
          <div class="ins-marker"></div>
          <div>
            <div class="ins-title">12 category pages missing canonical tags</div>
            <div class="ins-body">Duplicate-content risk on /kategori/soffor hierarchy. Recommended canonical pattern drafted; safe to batch-apply.</div>
            <div class="ins-meta">
              <span class="ins-source">seo-crawler</span>
              <span>Severity: high</span>
              <span>Detected 2h ago</span>
            </div>
          </div>
          <div class="ins-actions">
            <button class="btn btn-primary" style="font-size:11px;padding:5px 10px;">Create task</button>
            <button class="btn" style="font-size:11px;padding:5px 10px;">View →</button>
          </div>
        </div>
        <div class="insight sev-high">
          <div class="ins-marker"></div>
          <div>
            <div class="ins-title">Competitor gaining AI visibility on "bäddsoffa"</div>
            <div class="ins-body">IKEA mention rate up +8pp on ChatGPT answers in SE market. Content gap identified on /guider/baddsoffa.</div>
            <div class="ins-meta">
              <span class="ins-source">ai-visibility-tracker</span>
              <span>Severity: high</span>
            </div>
          </div>
          <div class="ins-actions">
            <button class="btn btn-primary" style="font-size:11px;padding:5px 10px;">Brief content</button>
          </div>
        </div>
        <div class="insight sev-med">
          <div class="ins-marker"></div>
          <div>
            <div class="ins-title">Internal link opportunity from /blogg → /kategori</div>
            <div class="ins-body">Simulated +0.23 PageRank shift toward priority commercial pages with 18 contextual links.</div>
            <div class="ins-meta">
              <span class="ins-source">ipr-sandbox</span>
              <span>Severity: medium</span>
            </div>
          </div>
          <div class="ins-actions">
            <button class="btn" style="font-size:11px;padding:5px 10px;">Simulate</button>
          </div>
        </div>
        <div class="insight sev-low">
          <div class="ins-marker"></div>
          <div>
            <div class="ins-title">H1 mismatch on 7 product pages</div>
            <div class="ins-body">Title tags strong but H1 omits primary query. Auto-fix available.</div>
            <div class="ins-meta">
              <span class="ins-source">seo-crawler</span>
              <span>Severity: low</span>
            </div>
          </div>
          <div class="ins-actions">
            <button class="btn btn-primary" style="font-size:11px;padding:5px 10px;">Auto-fix</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- TASKS PANE -->
  <div class="pane" id="pane-tasks">
    <div class="mode-notice advisory" id="advisory-notice" style="display:none;">
      <span class="icon">◉</span>
      <div>
        <b>Advisory mode.</b> Agents generate recommendations and task drafts. Nothing executes until you mark it done — approval gates are disabled, but no external systems are touched.
      </div>
    </div>

    <div class="panel">
      <div class="panel-head">
        <h3>Open tasks</h3>
        <span class="meta-mini">6 open · 2 pending approval</span>
      </div>
      <div class="panel-body tight">
        <div class="task-row">
          <div class="check"></div>
          <div>
            <div class="task-title">Batch-apply canonical tags to /kategori/soffor hierarchy</div>
            <div class="task-meta">From SEO Crawler insight · Due in 3 days</div>
          </div>
          <div class="task-impact impact-high">HIGH</div>
          <div class="task-owner ai">🤖 AI</div>
        </div>
        <div class="task-row">
          <div class="check"></div>
          <div>
            <div class="task-title">Write content brief for "bäddsoffa" guide</div>
            <div class="task-meta">From AI Visibility gap · Assigned: Ida Ek</div>
          </div>
          <div class="task-impact impact-high">HIGH</div>
          <div class="task-owner">Ida</div>
        </div>
        <div class="task-row">
          <div class="check"></div>
          <div>
            <div class="task-title">Review IPR simulation — approve link restructure</div>
            <div class="task-meta">Pending approval from CMO · 47 link changes</div>
          </div>
          <div class="task-impact impact-med">MED</div>
          <div class="task-owner">Anna</div>
        </div>
        <div class="task-row">
          <div class="check"></div>
          <div>
            <div class="task-title">Fix H1 tags on 7 product pages</div>
            <div class="task-meta">Auto-fix available · From SEO Crawler</div>
          </div>
          <div class="task-impact impact-low">LOW</div>
          <div class="task-owner ai">🤖 AI</div>
        </div>
        <div class="task-row">
          <div class="check"></div>
          <div>
            <div class="task-title">Launch ad copy A/B test on Google Ads "modulsoffa"</div>
            <div class="task-meta">6 variants ready · Budget approved</div>
          </div>
          <div class="task-impact impact-med">MED</div>
          <div class="task-owner ai">🤖 AI</div>
        </div>
      </div>
    </div>
  </div>

  <!-- RUNS PANE -->
  <div class="pane" id="pane-runs">
    <div class="empty-hint">
      <div class="em">Runs &amp; jobs</div>
      All background jobs, schedules, logs, and rerun controls — per module, all in one timeline.
    </div>
  </div>

  <!-- REPORTS PANE -->
  <div class="pane" id="pane-reports">
    <div class="empty-hint">
      <div class="em">Reports &amp; deliverables</div>
      Strategy docs, audit summaries, customer-facing PDFs, and exports.
    </div>
  </div>

  <!-- KNOWLEDGE PANE -->
  <div class="pane" id="pane-knowledge">
    <div class="empty-hint">
      <div class="em">Customer knowledge</div>
      Strategic notes, meeting notes, brand constraints, approved copy. Every agent reads from here.
    </div>
  </div>

  <!-- SETTINGS PANE -->
  <div class="pane" id="pane-settings">
    <div class="empty-hint">
      <div class="em">Customer settings</div>
      Integrations, service mode, approval rules, permissions, stakeholders.
    </div>
  </div>
</section>

<!-- ============ VIEW: PORTFOLIO ============ -->
<section class="view" id="view-portfolio">
  <div class="page-head">
    <div>
      <h1>Portfolio<i>.</i></h1>
      <div class="sub">Every customer, across the team. Spot risks, pending approvals, and customers needing attention.</div>
    </div>
    <div class="actions">
      <button class="btn">Export</button>
      <button class="btn">Filters</button>
    </div>
  </div>

  <div class="table-wrap">
    <table class="portfolio">
      <thead>
        <tr>
          <th>Customer</th>
          <th>Mode</th>
          <th>Owner</th>
          <th>Modules</th>
          <th>Health</th>
          <th>Open tasks</th>
          <th>Pending approvals</th>
          <th>Last run</th>
        </tr>
      </thead>
      <tbody>
        <tr onclick="openWorkspace('nordika')">
          <td><b>Nordika Furniture</b><div style="font-size:11px;color:var(--ink-mute);font-family:'JetBrains Mono',monospace;">nordika.se</div></td>
          <td><span class="cust-mode mode-full" style="margin-top:0;">Full</span></td>
          <td>Anna L.</td>
          <td><b>6</b>/12</td>
          <td><span class="health-bar"><span class="health-good" style="width:78%;"></span></span> 78</td>
          <td>6</td>
          <td><b style="color:var(--rose);">2</b></td>
          <td>2 h</td>
        </tr>
        <tr onclick="openWorkspace('brinkens')">
          <td><b>Brinkens Bryggeri</b><div style="font-size:11px;color:var(--ink-mute);font-family:'JetBrains Mono',monospace;">brinkens.se</div></td>
          <td><span class="cust-mode mode-advisory" style="margin-top:0;">Advisory</span></td>
          <td>Anna L.</td>
          <td><b>3</b>/12</td>
          <td><span class="health-bar"><span class="health-good" style="width:84%;"></span></span> 84</td>
          <td>3</td>
          <td>0</td>
          <td>1 d</td>
        </tr>
        <tr onclick="openWorkspace('otium')">
          <td><b>Otium Wellness</b><div style="font-size:11px;color:var(--ink-mute);font-family:'JetBrains Mono',monospace;">otium.health</div></td>
          <td><span class="cust-mode mode-full" style="margin-top:0;">Full</span></td>
          <td>Marcus B.</td>
          <td><b>6</b>/12</td>
          <td><span class="health-bar"><span class="health-good" style="width:91%;"></span></span> 91</td>
          <td>2</td>
          <td>1</td>
          <td>6 h</td>
        </tr>
        <tr onclick="openWorkspace('kairo')">
          <td><b>Kairo Legal</b><div style="font-size:11px;color:var(--ink-mute);font-family:'JetBrains Mono',monospace;">kairolegal.com</div></td>
          <td><span class="cust-mode mode-advisory" style="margin-top:0;">Advisory</span></td>
          <td>Elin S.</td>
          <td><b>4</b>/12</td>
          <td><span class="health-bar"><span class="health-warn" style="width:52%;"></span></span> 52</td>
          <td><b style="color:var(--rose);">9</b></td>
          <td>0</td>
          <td>3 d</td>
        </tr>
        <tr onclick="openWorkspace('voro')">
          <td><b>Voro Outdoors</b><div style="font-size:11px;color:var(--ink-mute);font-family:'JetBrains Mono',monospace;">voro.outdoors</div></td>
          <td><span class="cust-mode mode-onboard" style="margin-top:0;">Onboarding</span></td>
          <td>Anna L.</td>
          <td>—</td>
          <td><span class="health-bar"><span class="health-warn" style="width:30%;"></span></span> —</td>
          <td>—</td>
          <td>—</td>
          <td>Setup</td>
        </tr>
        <tr onclick="openWorkspace('helix')">
          <td><b>Helix Studios</b><div style="font-size:11px;color:var(--ink-mute);font-family:'JetBrains Mono',monospace;">helixstudios.io</div></td>
          <td><span class="cust-mode mode-full" style="margin-top:0;">Full</span></td>
          <td>Marcus B.</td>
          <td><b>6</b>/12</td>
          <td><span class="health-bar"><span class="health-good" style="width:88%;"></span></span> 88</td>
          <td>4</td>
          <td>0</td>
          <td>30 m</td>
        </tr>
      </tbody>
    </table>
  </div>
</section>

<!-- Placeholder views -->
<section class="view" id="view-tasks">
  <div class="page-head"><div><h1>Tasks &amp; Approvals<i>.</i></h1><div class="sub">Cross-customer queue for the whole team.</div></div></div>
  <div class="empty-hint"><div class="em">Team task queue</div>Every open task, every pending approval — across every customer.</div>
</section>
<section class="view" id="view-reports">
  <div class="page-head"><div><h1>Reports<i>.</i></h1></div></div>
  <div class="empty-hint"><div class="em">Deliverables library</div>Every generated report, grouped by customer and module.</div>
</section>
<section class="view" id="view-templates">
  <div class="page-head"><div><h1>Service Blueprints<i>.</i></h1><div class="sub">Reusable bundles of modules + cadence + approval rules. Apply to new customers in one click.</div></div></div>
  <div class="empty-hint"><div class="em">Blueprint templates</div>"E-commerce Growth", "Enterprise B2B", "Local SEO", etc.</div>
</section>
<section class="view" id="view-integrations">
  <div class="page-head"><div><h1>Integrations<i>.</i></h1></div></div>
  <div class="empty-hint"><div class="em">Connected sources</div>GA4, Search Console, Ahrefs, CMS, ad platforms.</div>
</section>
<section class="view" id="view-admin">
  <div class="page-head"><div><h1>Admin<i>.</i></h1></div></div>
  <div class="empty-hint"><div class="em">Workspace settings</div>Team, permissions, billing.</div>
</section>
```

  </main>
</div>

<!-- ========= CONTEXTUAL CHAT ========= -->

<button class="chat-fab" id="chat-fab" onclick="toggleChat()">M</button>

<div class="chat" id="chat">
  <div class="chat-head">
    <div class="chat-avatar">M</div>
    <div>
      <div class="chat-title">MEVO</div>
      <div class="chat-ctx" id="chat-ctx">Context: Customers view</div>
    </div>
    <button class="chat-close" onclick="toggleChat()">×</button>
  </div>
  <div class="chat-body" id="chat-body">
    <div class="msg bot">
      <div class="ctx-pill" id="chat-pill">Global scope</div>
      Hi Anna — which customer are we working on today? I can also pull up your portfolio overview or open tasks.
    </div>
    <div class="msg bot">
      Try: <i>"Show Nordika's top 3 issues"</i> or <i>"What needs my approval?"</i>
    </div>
  </div>
  <div class="chat-input">
    <input type="text" placeholder="Ask MEVO…" id="chat-input">
    <button onclick="sendChat()">Send</button>
  </div>
</div>

<!-- ========= ONBOARDING WIZARD ========= -->

<div class="wizard-overlay" id="wizard">
  <div class="wizard">
    <div class="wiz-head">
      <div>
        <h2>Create new customer</h2>
        <div class="wiz-sub">This becomes the single source of truth. Every module will read from this context — no more re-entering domains and goals.</div>
      </div>
      <button class="wiz-close" onclick="closeWizard()">×</button>
    </div>
    <div class="wiz-steps">
      <div class="wiz-step active" data-step="1"><span class="n">1</span>Profile</div>
      <div class="wiz-step" data-step="2"><span class="n">2</span>Context</div>
      <div class="wiz-step" data-step="3"><span class="n">3</span>Integrations</div>
      <div class="wiz-step" data-step="4"><span class="n">4</span>Mode</div>
      <div class="wiz-step" data-step="5"><span class="n">5</span>Modules</div>
      <div class="wiz-step" data-step="6"><span class="n">6</span>Review</div>
    </div>
    <div class="wiz-body" id="wiz-body">

```
  <!-- Step 1 visible by default -->
  <div class="wiz-pane" data-pane="1">
    <div class="form-row">
      <div class="form-group full">
        <label>Company name</label>
        <input type="text" placeholder="e.g. Nordika Furniture AB">
      </div>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>Primary domain</label>
        <input type="text" placeholder="nordika.se">
      </div>
      <div class="form-group">
        <label>Owner</label>
        <select><option>Anna Lindqvist</option><option>Marcus Berg</option><option>Elin Svensson</option></select>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>Markets / Languages</label>
        <input type="text" placeholder="SE, NO, DK">
      </div>
      <div class="form-group">
        <label>Industry</label>
        <input type="text" placeholder="E-commerce · Home &amp; furniture">
      </div>
    </div>
  </div>

  <div class="wiz-pane" data-pane="2" style="display:none;">
    <div class="form-row">
      <div class="form-group full">
        <label>Business goals &amp; KPIs</label>
        <textarea rows="3" placeholder="What should we move the needle on?"></textarea>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group full">
        <label>Primary competitors (up to 5)</label>
        <input type="text" placeholder="ikea.com, mio.se, jotex.se">
      </div>
    </div>
    <div class="form-row">
      <div class="form-group full">
        <label>Strategic notes / brand positioning</label>
        <textarea rows="3" placeholder="Tone, audience, what makes them different…"></textarea>
      </div>
    </div>
  </div>

  <div class="wiz-pane" data-pane="3" style="display:none;">
    <p style="color:var(--ink-mute);font-size:13px;margin-bottom:16px;">Connect the data sources agents will use. You can skip and add these later.</p>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
      <div class="mod-card"><div class="mod-head"><div class="mod-icon">GA</div><div class="mod-name">Google Analytics 4</div><button class="btn" style="font-size:11px;padding:4px 10px;">Connect</button></div></div>
      <div class="mod-card"><div class="mod-head"><div class="mod-icon">SC</div><div class="mod-name">Search Console</div><button class="btn" style="font-size:11px;padding:4px 10px;">Connect</button></div></div>
      <div class="mod-card"><div class="mod-head"><div class="mod-icon">AH</div><div class="mod-name">Ahrefs</div><button class="btn" style="font-size:11px;padding:4px 10px;">Connect</button></div></div>
      <div class="mod-card"><div class="mod-head"><div class="mod-icon">CMS</div><div class="mod-name">CMS / Webhook</div><button class="btn" style="font-size:11px;padding:4px 10px;">Connect</button></div></div>
    </div>
  </div>

  <div class="wiz-pane" data-pane="4" style="display:none;">
    <p style="color:var(--ink-mute);font-size:13px;margin-bottom:6px;">This isn't cosmetic. It changes what agents are allowed to do, what gets executed vs. suggested, and what requires approval.</p>
    <div class="mode-picker">
      <div class="mode-option" onclick="selectMode(this,'advisory')">
        <div class="mo-head"><span style="color:var(--amber);">◉</span> Advisory</div>
        <div class="mo-desc">Agents analyze, prioritize, and recommend. Drafts tasks and playbooks. <b>Never executes.</b> Consultant owns all implementation.</div>
        <span class="mo-tag mode-advisory">Low-risk · high control</span>
      </div>
      <div class="mode-option sel" onclick="selectMode(this,'full')">
        <div class="mo-head"><span style="color:var(--teal-deep);">◎</span> Full service</div>
        <div class="mo-desc">Agents run analyses, generate tasks, and <b>execute approved workflows</b> via integrations. Risky actions still gate on approval.</div>
        <span class="mo-tag mode-full">Higher autonomy · audited</span>
      </div>
    </div>
  </div>

  <div class="wiz-pane" data-pane="5" style="display:none;">
    <p style="color:var(--ink-mute);font-size:13px;margin-bottom:16px;">Pick the modules this customer has in their Service Blueprint. Start from a template or go custom.</p>
    <div style="margin-bottom:12px;"><button class="btn">Apply template: E-commerce Growth</button></div>
    <div class="mod-grid">
      <div class="mod-card enabled"><div class="mod-head"><div class="mod-icon">VT</div><div class="mod-name">AI Visibility Tracker</div><div class="mod-switch"></div></div><div class="mod-desc">Share of voice on ChatGPT answers.</div></div>
      <div class="mod-card enabled"><div class="mod-head"><div class="mod-icon">SC</div><div class="mod-name">SEO Crawler</div><div class="mod-switch"></div></div><div class="mod-desc">Technical audit + competitors.</div></div>
      <div class="mod-card enabled"><div class="mod-head"><div class="mod-icon">QM</div><div class="mod-name">QueryMatch</div><div class="mod-switch"></div></div><div class="mod-desc">Semantic relevance per section.</div></div>
      <div class="mod-card"><div class="mod-head"><div class="mod-icon">IPR</div><div class="mod-name">IPR Sandbox</div><div class="mod-switch"></div></div><div class="mod-desc">Internal PageRank simulation.</div></div>
      <div class="mod-card"><div class="mod-head"><div class="mod-icon">MA</div><div class="mod-name">Marketing Agents</div><div class="mod-switch"></div></div><div class="mod-desc">7 agents: ad copy, UTM, CWV, etc.</div></div>
      <div class="mod-card"><div class="mod-head"><div class="mod-icon">PS</div><div class="mod-name">Page Simulator</div><div class="mod-switch"></div></div><div class="mod-desc">Single-page link impact.</div></div>
    </div>
  </div>

  <div class="wiz-pane" data-pane="6" style="display:none;">
    <div style="background:var(--bg-card);border:1px solid var(--line);border-radius:10px;padding:20px;">
      <div style="font-family:'Fraunces',serif;font-size:20px;font-weight:500;margin-bottom:14px;">Ready to create workspace</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;font-size:13px;">
        <div><b>Company</b><div style="color:var(--ink-mute);">Voro Outdoors AB</div></div>
        <div><b>Domain</b><div style="color:var(--ink-mute);font-family:'JetBrains Mono',monospace;">voro.outdoors</div></div>
        <div><b>Markets</b><div style="color:var(--ink-mute);">SE, NO</div></div>
        <div><b>Owner</b><div style="color:var(--ink-mute);">Anna Lindqvist</div></div>
        <div><b>Service mode</b><div style="color:var(--teal-deep);">Full service</div></div>
        <div><b>Modules enabled</b><div style="color:var(--ink-mute);">VT, SC, QM (3)</div></div>
      </div>
    </div>
  </div>

</div>
<div class="wiz-foot">
  <button class="btn btn-ghost" onclick="closeWizard()">Cancel</button>
  <div style="display:flex;gap:8px;">
    <button class="btn" id="wiz-back" onclick="wizStep(-1)">← Back</button>
    <button class="btn btn-primary" id="wiz-next" onclick="wizStep(1)">Continue →</button>
  </div>
</div>
```

  </div>
</div>

<script>
// Nav
document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', () => {
    const v = item.dataset.view;
    if (!v) return;
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    item.classList.add('active');
    document.querySelectorAll('.view').forEach(s => s.classList.remove('active'));
    const target = document.getElementById('view-' + v);
    if (target) target.classList.add('active');
    updateCrumb(v);
    updateChatContext(v);
  });
});

function updateCrumb(v, extra) {
  const labels = {
    customers: 'Customers',
    workspace: 'Customers <span class="sep">/</span> <b>Nordika Furniture</b>',
    portfolio: '<b>Portfolio</b>',
    tasks: '<b>Tasks &amp; Approvals</b>',
    reports: '<b>Reports</b>',
    templates: '<b>Service Blueprints</b>',
    integrations: '<b>Integrations</b>',
    admin: '<b>Admin</b>'
  };
  const el = document.getElementById('crumb');
  if (v === 'customers') el.innerHTML = '<b>Customers</b>';
  else if (v === 'workspace') el.innerHTML = 'Customers <span class="sep">/</span> <b id="crumb-name">' + (extra || 'Nordika Furniture') + '</b>';
  else el.innerHTML = labels[v] || '';
}

// Customer data
const customers = {
  nordika: { name: 'Nordika Furniture', domain: 'nordika.se · primary', logo: 'N', bg: 'var(--teal-deep)' },
  brinkens: { name: 'Brinkens Bryggeri', domain: 'brinkens.se · primary', logo: 'B', bg: 'var(--teal-deep)' },
  otium: { name: 'Otium Wellness', domain: 'otium.health · primary', logo: 'O', bg: 'var(--amber)' },
  kairo: { name: 'Kairo Legal', domain: 'kairolegal.com · primary', logo: 'K', bg: 'var(--rose)' },
  voro: { name: 'Voro Outdoors', domain: 'voro.outdoors · primary', logo: 'V', bg: '#4a5d4c' },
  helix: { name: 'Helix Studios', domain: 'helixstudios.io · primary', logo: 'H', bg: '#5a4a6d' }
};

function openWorkspace(id) {
  const c = customers[id] || customers.nordika;
  document.getElementById('ws-name').textContent = c.name;
  document.getElementById('ws-domain').textContent = c.domain;
  const logo = document.getElementById('ws-logo');
  logo.textContent = c.logo;
  logo.style.background = c.bg;
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.querySelectorAll('.view').forEach(s => s.classList.remove('active'));
  document.getElementById('view-workspace').classList.add('active');
  updateCrumb('workspace', c.name);
  updateChatContext('workspace', c.name);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// Tabs
function openTab(name, btn) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.pane').forEach(p => p.classList.remove('active'));
  document.getElementById('pane-' + name).classList.add('active');
}

// Service mode
function setMode(mode) {
  const buttons = document.querySelectorAll('#mode-toggle button');
  buttons.forEach(b => b.classList.remove('on'));
  if (mode === 'advisory') {
    buttons[0].classList.add('on');
    document.getElementById('mode-notice').style.display = 'none';
    document.getElementById('advisory-notice').style.display = 'flex';
    // Flip the overview notice too
    showAdvisoryNotice();
  } else {
    buttons[1].classList.add('on');
    document.getElementById('mode-notice').style.display = 'flex';
    document.getElementById('advisory-notice').style.display = 'none';
    showFullNotice();
  }
}

function showAdvisoryNotice() {
  const n = document.getElementById('mode-notice');
  n.className = 'mode-notice advisory';
  n.style.display = 'flex';
  n.innerHTML = '<span class="icon">◉</span><div><b>Advisory mode is active.</b> Agents analyze and recommend. Tasks are drafted for your review — <b>nothing executes automatically.</b> Good for sensitive customers and approval-heavy workflows.</div>';
}
function showFullNotice() {
  const n = document.getElementById('mode-notice');
  n.className = 'mode-notice full';
  n.style.display = 'flex';
  n.innerHTML = '<span class="icon">◎</span><div><b>Full service mode is active.</b> Agents analyze, generate tasks, and execute approved workflows autonomously. High-risk actions still require your approval.</div>';
}

// Chat
function toggleChat() {
  document.getElementById('chat').classList.toggle('open');
  document.getElementById('chat-fab').classList.toggle('hidden');
}
function updateChatContext(view, name) {
  const ctx = document.getElementById('chat-ctx');
  const pill = document.getElementById('chat-pill');
  const body = document.getElementById('chat-body');
  if (view === 'workspace') {
    ctx.textContent = 'Context: ' + (name || 'Nordika Furniture');
    // Replace initial messages with customer-aware greeting
    body.innerHTML = `
      <div class="msg bot">
        <div class="ctx-pill">Context: ${name || 'Nordika Furniture'}</div>
        I've got full context on ${name || 'Nordika'} — their goals, modules, competitors, and recent runs. No need to re-explain.
      </div>
      <div class="msg bot">
        Want me to walk through the 3 high-severity issues from today's crawl, or draft this week's status email for the CMO?
      </div>
    `;
  } else {
    ctx.textContent = 'Context: ' + (view || 'Global');
  }
}
function sendChat() {
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text) return;
  const body = document.getElementById('chat-body');
  const userMsg = document.createElement('div');
  userMsg.className = 'msg user';
  userMsg.textContent = text;
  body.appendChild(userMsg);
  input.value = '';
  body.scrollTop = body.scrollHeight;
  setTimeout(() => {
    const bot = document.createElement('div');
    bot.className = 'msg bot';
    bot.innerHTML = 'Got it — I\'ll pull that from the customer context and ping you shortly.';
    body.appendChild(bot);
    body.scrollTop = body.scrollHeight;
  }, 600);
}
document.getElementById('chat-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') sendChat();
});

// Wizard
let wizCur = 1;
function openWizard() {
  document.getElementById('wizard').classList.add('open');
  wizCur = 1;
  renderWizStep();
}
function closeWizard() {
  document.getElementById('wizard').classList.remove('open');
}
function wizStep(delta) {
  wizCur = Math.max(1, Math.min(6, wizCur + delta));
  renderWizStep();
  if (wizCur === 6 && delta > 0) {
    document.getElementById('wiz-next').textContent = 'Create workspace →';
  } else if (wizCur < 6) {
    document.getElementById('wiz-next').textContent = 'Continue →';
  }
}
function renderWizStep() {
  document.querySelectorAll('.wiz-step').forEach(s => {
    const n = parseInt(s.dataset.step);
    s.classList.remove('active', 'done');
    if (n === wizCur) s.classList.add('active');
    else if (n < wizCur) s.classList.add('done');
  });
  document.querySelectorAll('.wiz-pane').forEach(p => {
    p.style.display = (parseInt(p.dataset.pane) === wizCur) ? 'block' : 'none';
  });
  document.getElementById('wiz-back').disabled = wizCur === 1;
  document.getElementById('wiz-back').style.opacity = wizCur === 1 ? 0.3 : 1;
}
function selectMode(el, mode) {
  document.querySelectorAll('.mode-option').forEach(o => o.classList.remove('sel'));
  el.classList.add('sel');
}

// Module toggle (visual)
document.querySelectorAll('.mod-card').forEach(card => {
  card.addEventListener('click', (e) => {
    if (e.target.closest('.btn')) return;
    card.classList.toggle('enabled');
  });
});
</script>

</body>
</html>
amazingtools-mockup.html
