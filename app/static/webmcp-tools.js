/**
 * PaperPilot — webmcp-tools.js
 *
 * The ONLY substantial JS file in the project. Business logic lives in Python.
 * This file only:
 *   1. Feature-detects WebMCP
 *   2. Registers imperative tools (thin fetch() wrappers)
 *   3. Binds declarative <form> tools so agent POSTs receive JSON, not HTML
 *
 * Character budgets (per Chrome guidance):
 *   tool name   ≤ 30 chars
 *   description ≤ 500 chars
 *   param desc  ≤ 150 chars
 *   output      ≤ 1500 chars
 */

(function () {
  'use strict';

  // Nested documents (iframes) must NEVER register WebMCP tools.
  // Doing so duplicates every tool (_0_ and _1310_) and the Inspector
  // then errors with "Could not establish connection. Receiving end does not exist."
  if (window.top !== window) return;

  function toolSignal(extras) {
    if (!extras) return undefined;
    if (extras.signal) return extras.signal;
    if (typeof extras.aborted === 'boolean') return extras;
    return undefined;
  }

  async function toolFetch(url, options) {
    try {
      const opts = Object.assign({ credentials: 'same-origin' }, options || {});
      opts.headers = Object.assign({ Accept: 'application/json' }, opts.headers || {});
      const res = await fetch(url, opts);
      const text = await res.text();
      var data;
      try {
        data = JSON.parse(text);
      } catch (parseErr) {
        return JSON.stringify({
          error: 'Server returned HTML instead of JSON (HTTP ' + res.status + '). Reload the page and try again.',
          status: res.status
        });
      }
      if (!res.ok) {
        var detail = data && (data.detail || data.error || data.message);
        return JSON.stringify({ error: detail || ('HTTP ' + res.status), status: res.status });
      }
      return JSON.stringify(data);
    } catch (err) {
      return JSON.stringify({ error: err.message || String(err) });
    }
  }

  /**
   * Declarative form tools (submit_biz_details / submit_fin_details) POST the
   * real form. Humans get a 303 HTML redirect. Agents must ask for JSON or
   * fetch() follows the redirect and tries to parse <!DOCTYPE html>.
   */
  window.paperpilotBindAgentForm = function (form) {
    if (!form || form.dataset.webmcpBound === '1') return;
    form.dataset.webmcpBound = '1';
    form.addEventListener('submit', function (e) {
      if (!e.agentInvoked) return;
      e.preventDefault();

      var params = e.toolParams || e.params || null;
      if (params && typeof params === 'object') {
        Object.keys(params).forEach(function (name) {
          if (params[name] == null) return;
          var el = form.elements.namedItem(name);
          if (el && 'value' in el) el.value = String(params[name]);
        });
      }

      e.respondWith(
        fetch(form.action, {
          method: 'POST',
          body: new FormData(form),
          credentials: 'same-origin',
          headers: { Accept: 'application/json', 'X-WebMCP-Agent': '1' }
        }).then(function (r) { return r.text().then(function (text) { return { r: r, text: text }; }); })
          .then(function (pack) {
            var data;
            try {
              data = JSON.parse(pack.text);
            } catch (parseErr) {
              return { error: 'Server returned HTML instead of JSON (HTTP ' + pack.r.status + ').' };
            }
            return data;
          })
          .catch(function (err) {
            return { error: err.message || String(err) };
          })
      );
    });
  };

  document.addEventListener('DOMContentLoaded', function () {
    var step1 = document.getElementById('step1-form');
    var step2 = document.getElementById('step2-form');
    if (step1) window.paperpilotBindAgentForm(step1);
    if (step2) window.paperpilotBindAgentForm(step2);
  });

  function showSavedNotice(step) {
    var el = document.getElementById('pp-agent-status');
    if (!el) {
      el = document.createElement('div');
      el.id = 'pp-agent-status';
      document.body.appendChild(el);
    }
    var text = {
      1: 'Business details saved. The assistant is still working in this tab.',
      2: 'Financials saved. The assistant is still working in this tab.',
      3: 'Application saved.'
    }[step] || 'Saved.';
    el.innerHTML = text +
      (step === 3
        ? ' <a href="/form/review" target="_blank" rel="noopener">Open review</a>' +
          ' · <a href="/dashboard" target="_blank" rel="noopener">Open dashboard</a>'
        : '');
  }

  const mc = (document.modelContext || navigator.modelContext);

  if (!mc || typeof mc.registerTool !== 'function') {
    console.warn(
      '[PaperPilot] WebMCP not available in this browser. ' +
      'To enable: use Chrome 149+ with chrome://flags/#enable-webmcp-testing ' +
      'or the Model Context Tool Inspector extension. Human-only form path works without it.'
    );
    return;
  }

  console.info('[PaperPilot] WebMCP detected. Registering tools...');

  const _controllers = {};

  function registerTool(definition) {
    const controller = new AbortController();
    _controllers[definition.name] = controller;

    mc.registerTool(definition, { signal: controller.signal })
      .then(function () {
        console.info('[PaperPilot] Registered tool:', definition.name);
      })
      .catch(function (e) {
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
    execute: async function (input, extras) {
      var field_name = input && input.field_name;
      if (!field_name) return JSON.stringify({ error: 'field_name is required.' });
      return toolFetch('/api/explain/' + encodeURIComponent(field_name), { signal: toolSignal(extras) });
    }
  });

  registerTool({
    name: 'check_eligibility',
    description: 'Runs the eligibility rules against the current session\'s saved form data. Returns pass/fail and specific disqualifying reasons. Use before submitting to flag issues early.',
    inputSchema: { type: 'object', properties: {}, required: [] },
    annotations: { readOnlyHint: true, untrustedContentHint: false },
    execute: async function (_input, extras) {
      return toolFetch('/api/eligibility/check', { method: 'POST', signal: toolSignal(extras) });
    }
  });

  registerTool({
    name: 'flag_issues',
    description: 'Scans the session for empty fields, inconsistencies (e.g. 0 employees + payroll as use of funds), and common rejection triggers. Returns a list of field names with reasons.',
    inputSchema: { type: 'object', properties: {}, required: [] },
    annotations: { readOnlyHint: true, untrustedContentHint: false },
    execute: async function (_input, extras) {
      return toolFetch('/api/eligibility/flags', { signal: toolSignal(extras) });
    }
  });

  function applyFieldsToPage(fields) {
    if (!fields || typeof fields !== 'object') return;
    Object.keys(fields).forEach(function (name) {
      if (fields[name] == null) return;
      var el = document.getElementById(name) || document.querySelector('[name="' + name + '"]');
      if (el && 'value' in el) el.value = String(fields[name]);
    });
  }

  async function submitStepAndGo(step, fields, extras) {
    applyFieldsToPage(fields);
    const raw = await toolFetch('/api/form/submit-step/' + step, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(fields || {}),
      signal: toolSignal(extras)
    });
    try {
      const data = JSON.parse(raw);
      if (data && data.ok) showSavedNotice(step);
    } catch (e) { /* keep raw */ }
    return raw;
  }

  if (!document.getElementById('step1-form')) {
    registerTool({
      name: 'submit_biz_details',
      description: 'SAVE business name, type, year founded, state, and EIN. Does not reload this tab. After success, immediately call submit_fin_details if the user also gave financials. Do NOT use propose_fields.',
      inputSchema: {
        type: 'object',
        properties: {
          business_name: { type: 'string', description: 'Legal registered name of the business.' },
          business_type: { type: 'string', enum: ['sole_proprietor', 'llc', 'corporation', 'nonprofit'], description: 'Legal structure.' },
          year_founded: { type: 'integer', minimum: 1800, maximum: 2025, description: 'Year legally established. At least 1 year ago.' },
          state: { type: 'string', description: 'Two-letter US state abbreviation.' },
          ein: { type: 'string', description: 'EIN as XX-XXXXXXX. Optional for sole proprietors.' }
        },
        required: ['business_name', 'business_type', 'year_founded', 'state']
      },
      annotations: { readOnlyHint: false, untrustedContentHint: false },
      execute: async function (fields, extras) {
        return submitStepAndGo(1, fields, extras);
      }
    });
  }

  if (!document.getElementById('step2-form')) {
    registerTool({
      name: 'submit_fin_details',
      description: 'SAVE annual revenue, employee count, revenue drop %, and use of funds. Does not change the page. After success, immediately call submit_applicant if the user also gave a name and email. Do NOT use propose_fields.',
      inputSchema: {
        type: 'object',
        properties: {
          annual_revenue: { type: 'number', minimum: 0, description: 'Annual gross revenue in USD. Max 5,000,000.' },
          employee_count: { type: 'integer', minimum: 0, description: 'Full-time employees. Max 500.' },
          revenue_drop_pct: { type: 'number', minimum: 0, maximum: 100, description: 'Revenue decline %. Min 15 to qualify.' },
          use_of_funds: { type: 'string', enum: ['payroll', 'rent_utilities', 'equipment', 'inventory', 'other'], description: 'Primary use of grant funds.' },
          use_of_funds_detail: { type: 'string', description: 'Required if use_of_funds is other.' }
        },
        required: ['annual_revenue', 'employee_count', 'revenue_drop_pct', 'use_of_funds']
      },
      annotations: { readOnlyHint: false, untrustedContentHint: false },
      execute: async function (fields, extras) {
        return submitStepAndGo(2, fields, extras);
      }
    });
  }

  registerTool({
    name: 'submit_applicant',
    description: 'SAVE applicant name, email, and certification. Last save when completing the application. Does not reload this tab. Do NOT use propose_fields.',
    inputSchema: {
      type: 'object',
      properties: {
        applicant_name: { type: 'string', description: 'Full legal name of the applicant.' },
        applicant_email: { type: 'string', description: 'Applicant email address.' },
        certify: { type: 'string', enum: ['true'], description: 'Must be true — applicant certifies the information is accurate.' }
      },
      required: ['applicant_name', 'applicant_email', 'certify']
    },
    annotations: { readOnlyHint: false, untrustedContentHint: false },
    execute: async function (fields, extras) {
      return submitStepAndGo(3, fields, extras);
    }
  });

  registerTool({
    name: 'go_to_step',
    description: 'Does not change this tab. Returns the URL for a form step, review, or dashboard. The applicant can open it after saves finish.',
    inputSchema: {
      type: 'object',
      properties: {
        step: { type: 'string', enum: ['1', '2', '3', 'review', 'dashboard'], description: 'Destination: 1 business, 2 financials, 3 documents, review, or dashboard.' }
      },
      required: ['step']
    },
    annotations: { readOnlyHint: true, untrustedContentHint: false },
    execute: async function (input) {
      var dest = {
        '1': '/form/step/1',
        '2': '/form/step/2',
        '3': '/form/step/3',
        review: '/form/review',
        dashboard: '/dashboard'
      }[(input && input.step) || ''];
      if (!dest) return JSON.stringify({ error: 'Unknown step.' });
      showSavedNotice(3);
      var bar = document.getElementById('pp-agent-status');
      if (bar) {
        bar.innerHTML = 'Ready. <a href="' + dest + '" target="_blank" rel="noopener">Open ' + dest + '</a>';
      }
      return JSON.stringify({ ok: true, url: dest, hint: 'Open the link in a new tab. Do not reload this Inspector tab.' });
    }
  });

  registerTool({
    name: 'propose_fields',
    description: 'Suggest uncommitted pre-fills only. Does NOT save the step, does NOT click Continue, and does NOT change the page. If the user asked to submit or continue, call submit_biz_details or submit_fin_details instead.',
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
    execute: async function (fields, extras) {
      applyFieldsToPage(fields);
      const raw = await toolFetch('/api/form/propose', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(fields || {}),
        signal: toolSignal(extras)
      });
      try {
        const data = JSON.parse(raw);
        if (data && data.proposed && document.getElementById('review-container')) {
          window.location.reload();
        }
      } catch (e) { /* keep raw string */ }
      return raw;
    }
  });

  registerTool({
    name: 'save_progress',
    description: 'Saves the current form session so the applicant can resume later. Does not submit the application. Safe to call at any point.',
    inputSchema: { type: 'object', properties: {}, required: [] },
    annotations: { readOnlyHint: false, untrustedContentHint: false },
    execute: async function (_input, extras) {
      return toolFetch('/api/form/save', { method: 'POST', signal: toolSignal(extras) });
    }
  });

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
    execute: async function (input, extras) {
      const document_type = input && input.document_type;
      if (!document_type) return JSON.stringify({ error: 'document_type is required.' });
      const raw = await toolFetch('/api/documents/extract', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ document_type: document_type }),
        signal: toolSignal(extras)
      });
      try {
        const data = JSON.parse(raw);
        if (data && data.proposed && document.getElementById('review-container')) {
          window.location.reload();
        }
      } catch (e) { /* keep raw string */ }
      return raw;
    }
  });

  registerTool({
    name: 'estimate_award',
    description: 'Returns a tiered award estimate for the current session based on revenue, revenue drop, and employee count. Use when the applicant asks how much they might receive.',
    inputSchema: { type: 'object', properties: {}, required: [] },
    annotations: { readOnlyHint: true, untrustedContentHint: false },
    execute: async function (_input, extras) {
      return toolFetch('/api/eligibility/estimate', { signal: toolSignal(extras) });
    }
  });

  registerTool({
    name: 'get_checklist',
    description: 'Returns required-field completion status, missing fields, and overall completion percentage for the current application session.',
    inputSchema: { type: 'object', properties: {}, required: [] },
    annotations: { readOnlyHint: true, untrustedContentHint: false },
    execute: async function (_input, extras) {
      return toolFetch('/api/eligibility/checklist', { signal: toolSignal(extras) });
    }
  });

  console.info('[PaperPilot] All tools registered — submit_biz_details, submit_fin_details, explain_field, check_eligibility, flag_issues, propose_fields, save_progress, extract_doc, estimate_award, get_checklist.');

}());
