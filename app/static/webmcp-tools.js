/**
 * PaperPilot — webmcp-tools.js
 *
 * The ONLY substantial JS file in the project. Business logic lives in Python.
 * This file only:
 *   1. Feature-detects WebMCP
 *   2. Registers imperative tools (thin fetch() wrappers)
 *   3. Annotates <form> elements for declarative tools (done in HTML templates)
 *   4. Updates the DOM with tool responses
 *
 * All tool registrations use one AbortController per tool for clean lifecycle
 * management (Chrome 150+ recommended pattern, works on Chrome 153+ without
 * cancelling in-flight executions on abort).
 *
 * Character budgets (per Chrome guidance):
 *   tool name   ≤ 30 chars
 *   description ≤ 500 chars
 *   param desc  ≤ 150 chars
 *   output      ≤ 1500 chars
 */

(function () {
  'use strict';

  // -------------------------------------------------------------------
  // 1. Feature detection
  // -------------------------------------------------------------------
  const mc = document.modelContext;

  if (!mc) {
    console.warn(
      '[PaperPilot] WebMCP not available in this browser. ' +
      'To enable: use Chrome 149+ with chrome://flags/#enable-webmcp-testing ' +
      'or join the origin trial. Human-only form path works without it.'
    );
    return; // Non-WebMCP browsers still get a fully working form (INSTRUCTIONS.md rule #1)
  }

  console.info('[PaperPilot] WebMCP detected. Registering tools...');

  // -------------------------------------------------------------------
  // 2. Controller registry — one AbortController per tool
  // -------------------------------------------------------------------
  const _controllers = {};

  function registerTool(definition) {
    const controller = new AbortController();
    _controllers[definition.name] = controller;

    mc.registerTool(definition, { signal: controller.signal })
      .then(function () {
        console.info('[PaperPilot] Registered tool:', definition.name);
      })
      .catch(function (e) {
        // Surface every error type explicitly (INSTRUCTIONS.md rule #9)
        if (e.name === 'InvalidStateError') {
          console.error('[PaperPilot] InvalidStateError registering', definition.name + ':', e.message);
        } else if (e.name === 'NotAllowedError') {
          console.error('[PaperPilot] NotAllowedError — "tools" Permissions Policy is disabled for this document.');
        } else if (e.name === 'SecurityError') {
          console.error('[PaperPilot] SecurityError — non-trustworthy origin in exposedTo.');
        } else if (e.name === 'TypeError') {
          console.error('[PaperPilot] TypeError — inputSchema failed to serialize for', definition.name);
        } else {
          console.error('[PaperPilot] Unexpected error registering', definition.name, e);
        }
      });
  }

  // -------------------------------------------------------------------
  // 3. Phase 0: no tools registered yet.
  //    Imperative tools are added in Phase 3 (read-only) and Phase 4 (mutating).
  //    Declarative tools live in form_step_1.html / form_step_2.html HTML attributes.
  //
  //    Stubs below show the exact shape each tool will take when added.
  // -------------------------------------------------------------------

  /*
  // --- Phase 3: explain_field (read-only) ---
  // Justification: Replaces Googling "what is EIN" mid-form.
  //   Declarative <form> tool cannot return contextual explanations.
  registerTool({
    name: 'explain_field',
    description: 'Returns a plain-language explanation of a grant form field — what it means, why it\'s asked, and a correct answer example. Use when the applicant is confused about a field.',
    inputSchema: {
      type: 'object',
      properties: {
        field_name: {
          type: 'string',
          enum: [
            'business_name','business_type','year_founded','state','ein',
            'annual_revenue','employee_count','revenue_drop_pct',
            'use_of_funds','use_of_funds_detail','tax_return_doc',
            'bank_statement_doc','applicant_name','applicant_email','certify'
          ],
          description: 'The form field name to explain. Must be one of the 15 grant application fields.'
        }
      },
      required: ['field_name']
    },
    annotations: { readOnlyHint: true, untrustedContentHint: false },
    execute: async function ({ field_name }, { signal }) {
      const res = await fetch('/api/explain/' + encodeURIComponent(field_name), { signal });
      if (!res.ok) throw new Error('explain_field: HTTP ' + res.status);
      const data = await res.json();
      return JSON.stringify(data);
    }
  });

  // --- Phase 3: check_eligibility (read-only) ---
  // Justification: Requires reading all saved session fields and running multi-condition
  //   rules. Cannot be expressed as a <form> declarative tool.
  registerTool({
    name: 'check_eligibility',
    description: 'Runs the eligibility rules against the current session\'s saved form data. Returns pass/fail and specific disqualifying reasons. Use before submitting to flag issues early.',
    inputSchema: { type: 'object', properties: {}, required: [] },
    annotations: { readOnlyHint: true, untrustedContentHint: false },
    execute: async function (_, { signal }) {
      const res = await fetch('/api/eligibility/check', { method: 'POST', signal });
      if (!res.ok) throw new Error('check_eligibility: HTTP ' + res.status);
      const data = await res.json();
      return JSON.stringify(data);
    }
  });

  // --- Phase 3: flag_issues (read-only) ---
  // Justification: Scans all fields for inconsistencies and missing values.
  //   Multi-field, session-level check cannot be a <form> declarative tool.
  registerTool({
    name: 'flag_issues',
    description: 'Scans the session for empty fields, inconsistencies (e.g. 0 employees + payroll as use of funds), and common rejection triggers. Returns a list of field names with reasons.',
    inputSchema: { type: 'object', properties: {}, required: [] },
    annotations: { readOnlyHint: true, untrustedContentHint: false },
    execute: async function (_, { signal }) {
      const res = await fetch('/api/eligibility/flags', { signal });
      if (!res.ok) throw new Error('flag_issues: HTTP ' + res.status);
      const data = await res.json();
      return JSON.stringify(data);
    }
  });

  // --- Phase 4: propose_fields (mutating — uncommitted proposals only) ---
  // Justification: Batch-proposes values without committing. Declarative <form> tool
  //   submits directly and cannot hold uncommitted state pending human review.
  registerTool({
    name: 'propose_fields',
    description: 'Proposes field values for the human to review. NOT committed until human clicks Accept. Call after gathering info to suggest pre-fills for one or more grant application fields.',
    inputSchema: {
      type: 'object',
      properties: {
        business_name:       { type: 'string', description: 'Legal business name, max 200 chars.' },
        business_type:       { type: 'string', enum: ['sole_proprietor','llc','corporation','nonprofit'], description: 'Legal structure.' },
        year_founded:        { type: 'integer', minimum: 1800, maximum: 2025, description: 'Year business was legally established.' },
        state:               { type: 'string', description: 'Two-letter US state abbreviation.' },
        ein:                 { type: 'string', description: 'EIN in XX-XXXXXXX format. Omit if sole proprietor.' },
        annual_revenue:      { type: 'number', minimum: 0, description: 'Annual gross revenue in USD.' },
        employee_count:      { type: 'integer', minimum: 0, description: 'Full-time employee count.' },
        revenue_drop_pct:    { type: 'number', minimum: 0, maximum: 100, description: 'Revenue decline % vs prior year.' },
        use_of_funds:        { type: 'string', enum: ['payroll','rent_utilities','equipment','inventory','other'], description: 'Primary intended use of grant funds.' },
        use_of_funds_detail: { type: 'string', description: 'Required if use_of_funds is other, max 500 chars.' },
        applicant_name:      { type: 'string', description: 'Full legal name of applicant, max 200 chars.' },
        applicant_email:     { type: 'string', description: 'Applicant email address.' }
      },
      additionalProperties: false
    },
    annotations: { readOnlyHint: false, untrustedContentHint: false },
    execute: async function (fields, { signal }) {
      const res = await fetch('/api/form/propose', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fields),
        signal
      });
      if (!res.ok) throw new Error('propose_fields: HTTP ' + res.status);
      const data = await res.json();
      // Refresh the review UI if it's visible
      if (document.getElementById('review-container')) {
        window.location.reload();
      }
      return JSON.stringify(data);
    }
  });

  // --- Phase 4: save_progress (mutating — session checkpoint only) ---
  // Justification: Session-level action, not a field action. Cannot be a <form> tool.
  registerTool({
    name: 'save_progress',
    description: 'Saves the current form session so the applicant can resume later. Does not submit the application. Safe to call at any point.',
    inputSchema: { type: 'object', properties: {}, required: [] },
    annotations: { readOnlyHint: false, untrustedContentHint: false },
    execute: async function (_, { signal }) {
      const res = await fetch('/api/form/save', { method: 'POST', signal });
      if (!res.ok) throw new Error('save_progress: HTTP ' + res.status);
      return 'Progress saved.';
    }
  });

  // --- Phase 5: extract_doc (mutating — uncommitted proposals only) ---
  // Justification: Requires reading a server-side binary file and running OCR.
  //   Cannot be a declarative <form> tool.
  // untrustedContentHint: true — output is derived from user-uploaded documents.
  registerTool({
    name: 'extract_doc',
    description: 'Reads an already-uploaded tax return or bank statement and extracts field values to propose as pre-fills. Values are NOT committed — human reviews first. Use after uploading a doc on Step 3.',
    inputSchema: {
      type: 'object',
      properties: {
        document_type: {
          type: 'string',
          enum: ['tax_return', 'bank_statement'],
          description: 'Which uploaded document to extract from. Must be uploaded first on Step 3.'
        }
      },
      required: ['document_type']
    },
    annotations: { readOnlyHint: false, untrustedContentHint: true },
    execute: async function ({ document_type }, { signal }) {
      const res = await fetch('/api/documents/extract', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ document_type }),
        signal
      });
      if (!res.ok) throw new Error('extract_doc: HTTP ' + res.status);
      const data = await res.json();
      if (document.getElementById('review-container')) {
        window.location.reload();
      }
      return JSON.stringify(data);
    }
  });
  */

  console.info('[PaperPilot] Phase 0: tool stubs loaded. Imperative tools activate in Phase 3+.');

}());
