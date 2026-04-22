# Cursor Rules — How to Trigger Each Rule

## How Cursor applies rules

- **`alwaysApply: true`** — The rule is **always** included in context (you don’t need to do anything; the AI has it).
- **`alwaysApply: false`** + **`globs`** — The rule is included when you have **files matching the globs** open or in context (or when you @-mention them).
- **Explicit ask** — Saying the right phrase in chat makes the AI **act** on the rule (run the skill, run the script, etc.).

---

## 0. Trust but verify (`trust-but-verify.mdc`) — Golden rule

| How it’s applied | **Always** (`alwaysApply: true`). |
|------------------|-----------------------------------|
| **What it does** | Before applying any change: **verify scope** (which system/template/file), **target** (exact names, WHERE clauses, paths), and **effect** (no unintended edits). Do not change the wrong thing. Especially for production (migrations, config, templates). |

---

## 1. Feature / Kanban (`feature-kanban.mdc`)

| How it’s applied | `globs` only — when `FEATURES_AND_IDEAS.md` or any file in `_docs/product/kaban/` is open or in context. |
|-----------------|----------------------------------------------------------------------------------------------------------|
| **How to trigger the behavior** | Say one of: **"Do feature X"**, **"Do FEAT-042"**, **"Implement FEAT-058"**, **"Go ahead and implement [feature]"**, **"I'm picking FEAT-042"**, **"Starting work on [feature name]"**, **"Refresh the kanban"**, **"Re-run the parse script"**. Or open `_docs/product/FEATURES_AND_IDEAS.md` and ask to refresh the board. |
| **What happens** | **"Do / implement feature X" or "Do FEAT-XXX":** **First thing** (before any implementation): (1) Update that feature to **IN-PROGRESS** in FEATURES_AND_IDEAS.md (heading + Status line). (2) Run parse script (real-time Kanban view). (3) **If the feature block has an Analysis: link**, read that analysis document under `_docs/product/analysis/` and use it to guide implementation. (4) Then proceed with the ticket. **When feature is completed:** (1) Set status to **COMPLETED**, add **Completed:** date. (2) Move the feature block to the "Completed Features" section at the bottom. (3) Run parse script. **"Refresh the kanban":** Run parse script only. |

**Tip:** Open `_docs/product/FEATURES_AND_IDEAS.md` or a file in `_docs/product/kaban/` before asking, so the rule is in context.

**Latest features not showing on the Kanban?** The board uses **embedded JSON** inside `kanban.html` (or falls back to `features.json`). That data is **only updated when you run the parse script**. After adding or editing features/bugs in FEATURES_AND_IDEAS.md, run: `python3 _docs/product/kaban/parse_features_md.py` (from repo root). Then open **`kanban.html`** (not `kanban_template.html`) in the browser; hard-refresh if you still see old data.

---

## 1b. Feature & Bug Block Format (`feature-format.mdc`)

| How it's applied | **Globs** — when `_docs/product/FEATURES_AND_IDEAS.md` is open or in context. |
|-----------------|-------------------------------------------------------------------------------|
| **How to trigger the behavior** | Add or edit any feature or bug block in FEATURES_AND_IDEAS.md; the rule is in context when the file is open. |
| **What happens** | The AI ensures every block follows the **required pattern**: (1) Heading `### [STATUS] [PRIORITY] FEAT-XXX: Title` or `### [STATUS] [PRIORITY] BUG-XXX: Title`; (2) **Mandatory** line `**Feature ID:** \`FEAT-XXX\` or **Bug ID:** \`BUG-XXX\` (with backticks) — without this the Kanban parser skips the block; (3) **Description:**; (4) optional **Related:**, **Analysis:**, **Complexity:**, **Business Value:**. **Completed Features** blocks must use the **canonical order**: metadata line → blank line → **Description:** (no **Complexity:** / **Business Value:** between metadata and **Description:**), so the parser and dashboard treat all completed items the same. After edits, run the parse script so the Kanban updates. |

**Tip:** Open FEATURES_AND_IDEAS.md when creating or editing features so the format rule is applied and new entries show on the Kanban.

---

## 1c. Feature/Bug Creation Date Required (`feature-creation-date-mandatory.mdc`)

| How it's applied | **Globs** — when `_docs/product/FEATURES_AND_IDEAS.md` is open or in context. |
|------------------|-------------------------------------------------------------------------------|
| **What it does** | When **creating** a new feature or bug, the **Added:** YYYY-MM-DD field (the **date the feature got created**) is **mandatory**. Never omit it — use the actual date of creation (today when adding the entry). Ensures traceability and correct Kanban behaviour. |

**Related:** `create-feature-documentation.mdc`, `feature-format.mdc`.

---

## 2. Marketing Feature List (`marketing-feature-list.mdc`)

| How it's applied | **Globs** — when `FEATURES_AND_IDEAS.md`, `MARKETING_FEATURE_LIST.md`, or any file in `_docs/product/kaban/` is open or in context. |
|------------------|--------------------------------------------------------------------------------------------------------------------------------------|
| **How to trigger the behavior** | When **closing a feature** (marking it COMPLETED and moving to Completed Features per the feature-kanban rule). The feature-kanban rule already includes step 4: add the feature to the marketing list. |
| **What happens** | After the feature is set to COMPLETED and moved to Completed Features, add an entry to `_docs/product/MARKETING_FEATURE_LIST.md` in the appropriate section, with **Description:** and **Key Features:** in marketing/sales style. Update the Table of Contents if you add a new section. |

**Tip:** When you say "close FEAT-XXX" or "mark FEAT-XXX complete", both feature-kanban and marketing-feature-list apply: update backlog, run parse, **and** add to MARKETING_FEATURE_LIST.md **and** add/update www user-manual docs (see section 2a).

---

## 2a. WWW Documentation — User Manual for docs.liliflow.ai (`www-documentation.mdc`)

| How it's applied | **Globs** — when any file under `_docs/www/**/*.md` is open or in context; or when closing a feature (per marketing-feature-list and feature-kanban). |
|------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------|
| **How to trigger the behavior** | When **closing a feature** (marking COMPLETED and adding to marketing list), the marketing-feature-list rule requires you to **also** create or update the corresponding **user-manual style** doc in `_docs/www/`. Or open a file in `_docs/www/` and ask to add/update docs for a feature. |
| **What happens** | Create or update a doc under `_docs/www/` (or `_docs/www/Getting Started/` for high-level UX) so the feature is documented on **https://www.liliflow.ai/docs** (e.g. [workflow-builder](https://www.liliflow.ai/docs?article=workflow-builder)). Use **user-manual style**: Overview, **Last Updated:** YYYY-MM-DD, how to access, core features (step-by-step), tables for parameters, examples. New major capability → new file; sub-feature → add section to existing file. |

**Tip:** When you complete a feature, the flow is: COMPLETED + move to Completed Features → add to MARKETING_FEATURE_LIST.md (with **Completed:** date) → **create or update** the www doc in `_docs/www/` so the docs site has user-manual coverage.

---

## 3. Security Review (`security-review.mdc`)

| How it’s applied | **Always** (`alwaysApply: true`). |
|-----------------|------------------------------------|
| **How to trigger the behavior** | Say one of: **"Security review"**, **"Audit this"**, **"Is this secure?"**, or ask to review code that touches auth, payments, APIs, webhooks, or integrations. |
| **What happens** | AI reads `workflow/micro-services/workflow-engine/docs/going_into_prod/standards/SKILL-SECURITY-REVIEW.md` and follows its full procedure and output format (Summary → Critical/High/Medium/Low → Checklist → Verdict). **Results are written to** `_docs/product/analysis/security/pentest-audits/PENTEST_YYYY-MM-DD.md` (or `PENTEST_<scope>_YYYY-MM-DD.md`). |

---

## 3a. Pentest → Feature Entry (`pentest-feature-documentation.mdc`)

| How it's applied | **Always** (`alwaysApply: true`). |
|-----------------|------------------------------------|
| **How to trigger the behavior** | Runs **automatically** whenever a pentest is executed (per Security Review rule above). No separate phrase needed. |
| **What happens** | After writing the pentest report to `pentest-audits/`, the AI **also** creates or updates a **feature/bug entry** in **`_docs/product/FEATURES_AND_IDEAS.md`** that details the pentest: next BUG-XXX ID, scope, date, findings summary (Critical/High/Medium/Low), link to the pentest file, and optional analysis doc. Follows the same format as BUG-004. Optionally adds a row to the value/incomplete tables. |

**Tip:** Every pentest is then tracked as a concrete backlog item (BUG-XXX) with a direct link to the full audit.

---

## 3a (continued). Pentest — Ask to Fix (`pentest-ask-fix.mdc`)

| How it's applied | **Always** (`alwaysApply: true`). |
|-----------------|------------------------------------|
| **How to trigger the behavior** | Runs **automatically** after a pentest is complete (report written + BUG-XXX entry created/updated). |
| **What happens** | Before ending the turn, the AI **asks the user** whether they want to fix the findings (e.g. "Do you want to start fixing these now? I can work through Critical and High first, or a specific BUG-XXX."). If yes → proceed with remediation (e.g. set BUG to IN-PROGRESS and fix). If no → acknowledge and stop. |

---

## 3b. Production Readiness / Periodic Security Audit (`security-audit-production-readiness.mdc`)

| How it's applied | **Globs** — when `workflow/promp-code-analysis.md` is open or in context; or **explicit ask**. |
|------------------|--------------------------------------------------------------------------------------------------|
| **How to trigger the behavior** | Say one of: **"Run a production readiness audit"**, **"Full security audit"**, **"Periodic security audit"**, **"Is this app production ready?"**, **"Release readiness review"**. Or open `workflow/promp-code-analysis.md` and ask for an audit. |
| **What happens** | AI uses the template in `workflow/promp-code-analysis.md`: Executive Verdict → Release Blockers → Security (threat model + findings) → Code Quality → Reliability → Observability → Deployment → Action Plan → Scoring. Use when you want a **broad** audit (quality + security + ops), not just a focused security review. |

**Tip:** For a **narrow** security pass on code/PR, use **"Security review"** (rule above). For a **full** or **periodic** production-readiness audit, use this rule.

---

## 4. Code Review (`code-review.mdc`)

| How it’s applied | **Always** (`alwaysApply: true`). |
|-----------------|------------------------------------|
| **How to trigger the behavior** | Say one of: **"Code review"**, **"Review this code"**, **"PR review"**, or ask to review a PR, refactor, new feature, or architecture. |
| **What happens** | AI reads `.cursor/skills/skillcodereview/SKILL.md` and follows its full procedure and output format (Summary → Critical → Important → Optional → Overall Recommendation). |

---

## 5. API Endpoints & Capabilities (`api-endpoints-capabilities.mdc`)

| How it's applied | **Globs** — when any Java file under `workflow/**/src/main/java/**/controllers/**/*.java` is open or in context. |
|------------------|-------------------------------------------------------------------------------------------------------------------|
| **How to trigger the behavior** | Add or modify an API endpoint (e.g. new `@GetMapping`, `@PostMapping`, etc.) in a controller, or say: **"Add capability to this endpoint"**, **"Protect this API"**. |
| **What happens** | When you add or change endpoints, the AI ensures: (1) Each new endpoint has `@HasCapability("...")` with an existing or new capability. (2) If a new capability is needed, it is added in `CapabilityService` and assigned to the right roles (ADMIN, USER, VIEWER). (3) Documentation (e.g. FEATURES_AND_IDEAS.md) notes the capability and that it applies to admin and user where appropriate. New endpoints must not be shipped without a capability check. |

**Tip:** Open the controller file you are editing so the rule is in context when adding new endpoints.

---

## 5a. API response XSS prevention (`api-response-xss-prevention.mdc`)

| How it's applied | **Globs** — when any `*Controller*.java`, `*Controller*.ts(x)`, or file under `**/controllers/**` is open or in context. |
|------------------|--------------------------------------------------------------------------------------------------------------------------|
| **How to trigger the behavior** | Generate or edit code that returns HTTP response bodies (JSON, CSV, etc.). The rule is in context when you work on controllers. |
| **What happens** | The AI **never** returns user-controllable or external data (params, DB, upstream APIs, exception messages) in response bodies without encoding. Use `HtmlEncoder` (Java) or safe DOM APIs (frontend) so XSS payloads are neutralized. Success bodies, error maps, and CSV/export content must encode string values. Add tests that assert XSS payloads appear encoded (e.g. `&lt;script&gt;`) and never raw. |

**Tip:** Prevents the recurring mistake of exposing XSS via API responses. Reference: workflow-engine, document-service, crawler-service controllers and their tests.

---

## 6. Java Tests (`java-tests.mdc`)

| How it's applied | **Globs** — when any Java file under `workflow/**/src/main/java/**/*.java` is open or in context. |
|------------------|---------------------------------------------------------------------------------------------------|
| **How to trigger the behavior** | Modify or add Java code under `src/main/java`, or say: **"Add tests for this"**, **"Generate tests"**, **"Write unit tests for X"**. |
| **What happens** | When you add or change production Java code, the AI also adds or updates the relevant tests (unit and, when appropriate, integration). Tests follow best practices: JUnit 5, clear naming, Arrange–Act–Assert, mocks for dependencies, coverage of main paths and edge cases. Test classes live under `src/test/java` with the same package structure (e.g. `FooService.java` → `FooServiceTest.java`). |

**Tip:** Open the Java file you are changing so the rule is in context; the AI will then include test generation as part of the change.

---

## 7. Flyway Migrations (`flyway-migrations.mdc`)

| How it's applied | **Globs** — when any file under `workflow/**/db/migration/*.sql` is open or in context. |
|------------------|-------------------------------------------------------------------------------------------|
| **How to trigger the behavior** | Create or edit a Flyway SQL migration under `db/migration/`. |
| **What happens** | The AI follows idempotent DDL best practices: (1) Table/index/constraint renames are conditional (only when source exists and target does not). (2) Uses `DO $$ ... END $$` and `pg_tables` / `pg_indexes` / `pg_constraint` for existence checks. (3) Avoids `CREATE INDEX CONCURRENTLY` in transactional migrations; uses `CREATE INDEX IF NOT EXISTS`. (4) INSERTs use explicit columns and values for NOT NULL/default columns. (5) COMMENT and other DDL guarded when the object might not exist. This avoids "relation already exists", "relation does not exist", and "null value in column" on partial runs or JPA-influenced databases. |

**Tip:** Open the migration file you are creating or editing so the rule is in context; new scripts will follow the safe-check patterns.

---

## 8. New Step or Integration — Mandatory Rules (follow both 8 and 8b)

When you add a **new workflow step** or **new integration** that adds steps to the designer, you **must** follow **both** rules below so the step is visible, configurable, has Output Variables where it produces output, and has a Test button where it can be validated.

**How to trigger:** Say **"new step"**, **"new integration"**, **"add step X"**, or **"add integration X"**, and open at least one of: `Sidebar.tsx`, `PropertiesPanel.tsx`, `step-type-reference.json`, or `_docs/product/guides/HOW_TO_ADD_A_STEP_TO_THE_LEFT_SIDEBAR.md` / `HOW_TO_ADD_A_CUSTOM_INTEGRATION.md`. That loads the rules so the AI follows the full checklist.

---

## 8a. New Steps — Output Variables & Test Button (`new-steps-output-variables-and-test.mdc`)

| How it's applied | **Globs** — when `PropertiesPanel.tsx`, `Sidebar.tsx`, `stepOutputVariables.ts`, or the step/integration guides are open or in context. |
|------------------|-------------------------------------------------------------------------------------------------------------------------------------------|
| **How to trigger the behavior** | Add or modify a **new workflow step type** or **custom integration** (new step in Sidebar, Properties panel, backend executor). |
| **What happens** | The AI **must** implement: (1) **Output Variables** — collapsible section in Properties panel + entry in `stepOutputVariables.ts` when the step produces context or outputData. (2) **Test button** — backend test endpoint and frontend Test button + result UI when the step can be validated in isolation. Pattern: DOCUMENT_LOAD, OCR_EXTRACT, CRAWL_START. |

**Tip:** Open `PropertiesPanel.tsx` or the relevant guide when adding a new step so this rule is in context.

---

## 8a1. Previous Variables UI — Step Name Once, Variable Names Only (`previous-variables-ui.mdc`)

| How it's applied | **Globs** — when `PropertiesPanel.tsx` is open or in context. |
|------------------|----------------------------------------------------------------|
| **How to trigger the behavior** | Add or edit a **"Variables you can use in this step"** block (upstream steps + workflow globals) for any step that accepts template/expression input (e.g. URL, body, passphrase). |
| **What happens** | The AI **must** follow: show **step name once** as heading, then list only the **actual variable names** (e.g. `outputData.text`, `myVar`), not the full `{{stepId.outputData.text}}` in the UI. Copy and tooltip use the full `{{...}}` value. Use **`variableDisplayLabel(v)`** for display. Pattern: CHOICE, HTTP, ENCRYPT_DECRYPT. |

**Tip:** When adding "Variables you can use" to a new step, follow **previous-variables-ui.mdc** so the list is scannable (no repeated step id in every chip).

---

## 8b. New Workflow Step or Integration — Full Checklist (`new-workflow-step-left-menu-checklist.mdc`)

| How it's applied | **Globs** — when `Sidebar.tsx`, `configStore.ts`, `workflow.ts`, `WorkflowNode.tsx`, `PropertiesPanel.tsx`, `ApplicationSettingsPanel.tsx`, `stepOutputVariables.ts`, `step-type-reference.json`, or the step/integration guides are open or in context. |
|------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **How to trigger the behavior** | Add or modify a **new workflow step type** or **new integration** (backend enum, new executor, or new step in the designer). Say **"Add new step X"**, **"New workflow step"**, **"New integration"**, or open one of the glob files. |
| **What happens** | The AI follows the **mandatory 11-point checklist**: (1) step-type-reference.json, (2) StepType, (3) Sidebar, (4) configStore + migration, (5) WorkflowNode icons/colors, (6) PropertiesPanel config block, (7) ApplicationSettingsPanel step visibility, (8) validator, (9) backend enum + executor + wiring, (10) **Output Variables** (required when step produces output), (11) **Test the step** (required when step can be validated). Prevents "backend-only" steps and missing Output Variables/Test. |

**Tip:** When adding a new step or integration, open `Sidebar.tsx` or `step-type-reference.json` so this rule is in context; then the full checklist is applied. **All step property labels, descriptions, and help text must be professional, error-free, and free of spelling mistakes** — see **Step properties user copy** (section 8c).

---

## 8c. Step Properties — Professional, Error-Free User Copy (`step-properties-user-copy.mdc`)

| How it's applied | **Globs** — when `step-type-reference.json`, `PropertiesPanel.tsx`, or step docs under `_docs/www/` are open or in context. |
|------------------|-------------------------------------------------------------------------------------------------------------------------------|
| **How to trigger the behavior** | Add or edit a workflow step (new step or changing properties), or edit user-facing text in step-type-reference, PropertiesPanel, or www step documentation. |
| **What happens** | All user-facing text (labels, descriptions, placeholders, help text, parameter descriptions) must be **professional**, **error-free**, and **free of spelling mistakes**. Review and fix spelling and grammar before shipping. Applies to step-type-reference.json, PropertiesPanel config blocks and Output Variables, and _docs/www/ step docs. |

**Tip:** When a step has many properties, double-check every label and description; follow this rule together with the new-step checklist (8, 8a, 8b).

---

## 8d. Step Type Look-and-Feel — Never Lose Custom Step Appearance (`step-type-look-and-feel.mdc`)

| How it's applied | **Globs** — when `workflowStore.ts` or `WorkflowNode.tsx` is open or in context. |
|------------------|----------------------------------------------------------------------------------------|
| **How to trigger the behavior** | Change how steps are loaded, saved, or updated (e.g. load workflow from API, updateNode, paste steps, import). Or when a step "loses its look" and appears as a generic task. |
| **What happens** | Step type must **never** be lost: (1) When building a node from a step, read type from both `step.type` and `step.stepType` and set `data.stepType`. (2) In **updateNode**, never overwrite `stepType` with undefined—preserve existing. (3) Use **normalizeStepType** for variants and aliases (e.g. AGENTIC_RAG, UNIFIED_OUTPUT, RENDER_EMAIL_TEMPLATE / MAIL_MERGE). (4) New custom step types: add to stepIcons, stepColors, and normalizeStepType (canonical + any aliases). Ensures compound nodes and special icons never collapse to a basic task after load/reload. |

**Tip:** If a step suddenly looks like a generic task after load/save/paste, check that the step type is set on the node and preserved in updateNode; follow this rule.

---

## 9. Create Feature — Documentation First (`create-feature-documentation.mdc`)

| How it's applied | **Always** (`alwaysApply: true`). |
|------------------|------------------------------------|
| **How to trigger the behavior** | Say **"create a feature"**, **"add a feature"**, or similar (e.g. "I want a feature that…", "Implement a feature for…"). |
| **What happens** | **First:** Add or update a feature entry in **`_docs/product/FEATURES_AND_IDEAS.md`** (new FEAT-XXX in Features & Ideas with Description, status, priority; or if retroactive, add COMPLETED block + full entry in Completed Features). **Then:** Proceed with implementation. Keeps the backlog as single source of truth when creating new features. |

**Tip:** For working on an **existing** FEAT-XXX (e.g. "Do FEAT-042"), use the **Feature/Kanban** rule (section 1) instead.

---

## 9a. Build a LiliFlow App (`build-liliapp.mdc`)

| How it's applied | **Always** (`alwaysApply: true`). |
|------------------|------------------------------------|
| **How to trigger the behavior** | Say **"build an app"**, **"create an app"**, **"add a LiliFlow app"**, **"new Lili app"**, or similar (e.g. "I want an app for X", "Create an app that does Y"). |
| **What happens** | The AI **reads and follows** **`_docs/product/guides/LILIFLOW_APP_BUILD_PATTERN.md`**: (1) Add FEAT entry + analysis doc (ERD, tables, workflows, forms; cross-tenant note). (2) New migration: INSERT **app_definition** (fixed UUID, slug, version, name, description, icon, **package_json** with dataTables [parent first; reference columns], workflows [inline steps], forms, optional navigation). (3) Optional separate migration: create **dashboard** + **dashboard_widget** per tenant with app installed (app_id = tenant_app.id). (4) Obey **liliflow-apps-best-practices.mdc**, **flyway-golden-rule.mdc**, **cross-tenant-compliance.mdc**. Deliver: feature entry, analysis doc, migrations, tests. |

**Tip:** Full checklist and schema details are in **`_docs/product/guides/LILIFLOW_APP_BUILD_PATTERN.md`**. Example apps: Expense Tracker (V1091, V1114), CRM Pro (V1098, V1101).

---

## 10. Feature Relationships (`feature-relationships.mdc`)

| How it's applied | **Globs** — when `FEATURES_AND_IDEAS.md`, any file in `_docs/product/kaban/`, or any file in `_docs/product/analysis/` is open or in context. |
|------------------|--------------------------------------------------------------------------------------------------------------------------------------------------|
| **How to trigger the behavior** | Add a **new feature** (new FEAT-XXX block) or **significantly edit** an existing feature (scope, dependencies, analysis). |
| **What happens** | The AI **must** work out relationships to other features (depends on, complements, extends, related) and add a **Related:** line in the feature block (e.g. `**Related:** FEAT-033 (workflow sharing), FEAT-002 (approval for production).`). Optionally update the **Related** line of existing features to reference the new one. If no relationships exist, add `**Related:** None (standalone).` After changes, run the parse script so the Kanban stays in sync. |

**Tip:** When you say "add a new feature" or edit FEATURES_AND_IDEAS.md with a new FEAT-XXX, the rule ensures relationships are documented so tickets stay traceable.

---

## 11. Local Workflows Path (`local-workflows-path.mdc`)

| How it's applied | **Globs** — when any file under `workflow/micro-services/workflow-engine/src/main/resources/workflows/` is open or in context. |
|------------------|----------------------------------------------------------------------------------------------------------------------------------|
| **How to trigger the behavior** | Add or edit a **local workflow** that the engine should load at runtime (e.g. demos, tests, default workflows). |
| **What happens** | The AI ensures workflow definition files are **YAML** and live **only** in `workflow/micro-services/workflow-engine/src/main/resources/workflows/`. Do not put engine-loadable workflows in `docs/workflows/` or as JSON for loading — use the resources workflow directory so they are on the classpath and picked up by `workflow.definitions.path` (`workflows/**/*.yaml`). |

**Tip:** Open a file in `.../src/main/resources/workflows/` when creating or moving a local workflow so the rule is in context.

---

## 12. Backend Recompile — Force Clean Compile After Java Changes (`backend-recompile.mdc`)

| How it's applied | **Globs** — when any `.java` file under `workflow-engine/src/main/java/` or `pom.xml` is open or in context. |
|------------------|--------------------------------------------------------------------------------------------------------------|
| **How to trigger the behavior** | Modify any Java source file under `workflow-engine/src/main/java/` — the rule applies via globs. Or when debugging "works in frontend but not in backend" issues. |
| **What happens** | After modifying Java source files, you **must** run `mvn clean compile -DskipTests -q` from the `workflow-engine/` directory before restarting the backend. Maven's incremental compiler can silently use stale bytecode from `target/classes/`, causing new enum values (e.g. `RENDER_EMAIL_TEMPLATE`), new classes, or changed logic to be ignored at runtime. After clean compile, optionally verify with `javap` that the change is in the compiled bytecode. Then restart the backend. |

**Tip:** If a new step type or enum value "works on the frontend but reverts on save/load", the first thing to check is whether the backend was clean-compiled. Run `mvn clean compile` and restart.

---

## Quick reference

| Rule            | To trigger it, say or do… |
|-----------------|---------------------------|
| **Feature/Kanban** | Open backlog/kanban file, then: *"Do feature X"* / *"Do FEAT-042"* (sets IN-PROGRESS, runs parse, **loads linked analysis if present**, then works on ticket). When done, say feature is complete → AI sets COMPLETED, moves to Completed section, runs parse, **adds to MARKETING_FEATURE_LIST.md** and **creates/updates www user-manual doc** in `_docs/www/`. Or: *"Refresh the kanban"* (runs parse only). |
| **Marketing feature list** | When closing a feature (COMPLETED) → add entry to `MARKETING_FEATURE_LIST.md` with **Completed:** date, Description + Key Features (marketing style). Triggered as part of "close FEAT-XXX". |
| **WWW documentation (user manual)** | When closing a feature (COMPLETED) → create or update user-manual style doc in `_docs/www/` so the feature is on https://www.liliflow.ai/docs. See `www-documentation.mdc`. Triggered as part of "close FEAT-XXX"; or open `_docs/www/` and ask to document a feature. |
| **Security review** | *"Security review"*, *"Audit this"*, *"Is this secure?"* — output written to `_docs/product/analysis/security/pentest-audits/PENTEST_YYYY-MM-DD.md`. |
| **Pentest → feature entry** | Runs automatically when a pentest is run — creates/updates a BUG-XXX entry in FEATURES_AND_IDEAS.md detailing scope, date, findings, and link to pentest file. |
| **Pentest → ask to fix** | After pentest + feature entry, AI asks: "Do you want to fix these findings?" (Critical/High first or specific BUG-XXX). |
| **Code review**    | *"Code review"*, *"Review this code"*, *"PR review"* |
| **API endpoints & capabilities** | Add/modify endpoints in a controller (rule applies via globs), or: *"Add capability to this endpoint"*, *"Protect this API"* — ensure `@HasCapability` and capability in `CapabilityService` for admin/user. |
| **Java tests**     | Modify/add Java under `src/main/java` (rule applies via globs), or: *"Add tests for this"*, *"Generate tests"* |
| **Flyway migrations** | Create/edit any `workflow/**/db/migration/*.sql` (rule applies via globs) — use idempotent renames, existence checks, `IF NOT EXISTS`, explicit INSERT columns. |
| **Create feature (doc first)** | *"Create a feature"*, *"Add a feature"* — add/update entry in FEATURES_AND_IDEAS.md first (new FEAT-XXX or COMPLETED block), then implement. |
| **Build LiliFlow app** | *"Build an app"*, *"Create an app"*, *"Add a LiliFlow app"* — follow **`_docs/product/guides/LILIFLOW_APP_BUILD_PATTERN.md`**: FEAT + analysis doc, migration(s) for app_definition + optional dashboard, package_json (dataTables, workflows, forms, navigation), tests. See **build-liliapp.mdc**. |
| **Feature format** | When FEATURES_AND_IDEAS.md is open and you add/edit a block — use heading `### [STATUS] [PRIORITY] FEAT-XXX: Title`, **Feature ID:** \`FEAT-XXX\` or **Bug ID:** \`BUG-XXX\` (required for parser), **Description:**, optional **Related:** / **Analysis:**. Run parse script after. |
| **Feature relationships** | Add or significantly edit a feature in FEATURES_AND_IDEAS.md (rule applies via globs) — work out and add **Related:** FEAT-XXX (relationship type); run parse script after. |
| **Local workflows path** | When adding or editing a **local workflow** (engine-loadable): put **YAML** files only in `workflow/micro-services/workflow-engine/src/main/resources/workflows/`. Do not use `docs/workflows/` or JSON for engine loading. See `local-workflows-path.mdc`. |
| **New step or integration** | When adding a **new workflow step** or **new integration**: open Sidebar, PropertiesPanel, step-type-reference.json, or the step/integration guide so the rules apply. Then follow **both** (1) **new-workflow-step-left-menu-checklist.mdc** — full checklist (visibility, left menu, configStore, PropertiesPanel, **Previous variables** when step has template/expression inputs — **previous-variables-ui.mdc**, Output Variables, Test button, backend), and (2) **new-steps-output-variables-and-test.mdc** — Output Variables + Test button pattern. **Previous variables:** When the step has parameters that accept `{{variable}}`, add "Variables you can use in this step" and follow **previous-variables-ui.mdc** (step name once, variable names only). **Step properties user copy:** All labels, descriptions, and help text must be professional, error-free, and free of spelling mistakes (**step-properties-user-copy.mdc**). **Step type look-and-feel:** When changing load/save/update of steps, preserve step type so custom steps never collapse to a generic task (**step-type-look-and-feel.mdc**). Do not ship without completing every applicable item. |
|| **Backend recompile** | After modifying **any Java source file** under `workflow-engine/src/main/java/`: run `mvn clean compile -DskipTests -q` from `workflow-engine/` **before** restarting the backend. Maven's incremental compiler can silently skip recompilation and use stale bytecode. If a new enum value or class "works in frontend but not backend", this is the first thing to check. See **backend-recompile.mdc**. |
