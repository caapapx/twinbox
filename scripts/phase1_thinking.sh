#!/usr/bin/env bash
# Phase 1 Thinking: LLM batch intent classification
# Input:  runtime/context/phase1-context.json
# Output: runtime/validation/phase-1/intent-classification.json
#         runtime/validation/phase-1/intent-report.md
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"

STATE_ROOT="${TWINBOX_CANONICAL_ROOT}"
ENV_FILE="${STATE_ROOT}/.env"
CONTEXT_PACK="${STATE_ROOT}/runtime/context/phase1-context.json"
OUTPUT_DIR="${STATE_ROOT}/runtime/validation/phase-1"
BATCH_SIZE=15
MODEL="${TWINBOX_LLM_MODEL:-claude-sonnet-4-20250514}"

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/phase1_thinking.sh [options]

Reads phase1-context.json, calls LLM for batch intent classification.
Requires: ANTHROPIC_API_KEY in .env or environment.

Options:
  --context <path>    Override context-pack path
  --batch-size <n>    Envelopes per LLM call (default: 15)
  --model <name>      LLM model (default: claude-sonnet-4-20250514)
  --dry-run           Print prompts without calling API
  -h, --help          Show this help
USAGE
}

DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --context) CONTEXT_PACK="${2:-}"; shift 2 ;;
    --batch-size) BATCH_SIZE="${2:-}"; shift 2 ;;
    --model) MODEL="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 1 ;;
  esac
done

# --- load env for API key ---
if [[ -f "${ENV_FILE}" ]]; then
  set -a; source "${ENV_FILE}"; set +a
fi

if [[ -n "${LLM_API_KEY:-}" ]]; then
  LLM_BACKEND="openai"
  LLM_URL="${LLM_API_URL:-https://coding.dashscope.aliyuncs.com/v1/chat/completions}"
  LLM_MODEL_NAME="${LLM_MODEL:-kimi-k2.5}"
  API_KEY="${LLM_API_KEY}"
  MODEL="${LLM_MODEL_NAME}"
  echo "LLM backend: OpenAI-compatible API (${LLM_MODEL_NAME})"
elif [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  LLM_BACKEND="anthropic"
  LLM_URL="https://api.anthropic.com/v1/messages"
  API_KEY="${ANTHROPIC_API_KEY}"
  echo "LLM backend: Anthropic API"
else
  echo "Error: LLM_API_KEY or ANTHROPIC_API_KEY not set (add to .env or export)"
  exit 1
fi

if [[ ! -f "${CONTEXT_PACK}" ]]; then
  echo "Error: context-pack not found at ${CONTEXT_PACK}"
  echo "Run scripts/phase1_loading.sh first."
  exit 1
fi

mkdir -p "${OUTPUT_DIR}"

echo "Phase 1 Thinking: LLM intent classification"
echo "  Model: ${MODEL}"
echo "  Context: ${CONTEXT_PACK}"
echo "  Batch size: ${BATCH_SIZE}"

# --- build batches and classify ---
node - <<'CLASSIFY' "${CONTEXT_PACK}" "${OUTPUT_DIR}" "${BATCH_SIZE}" "${MODEL}" "${API_KEY}" "${DRY_RUN}" "${LLM_BACKEND}" "${LLM_URL}"
const fs = require('fs');
const https = require('https');
const http = require('http');

const [contextPath, outputDir, batchSizeRaw, model, apiKey, dryRun, backend, llmUrl] =
  process.argv.slice(2);
const BATCH_SIZE = Number(batchSizeRaw);
const isDryRun = dryRun === 'true';

const ctx = JSON.parse(fs.readFileSync(contextPath, 'utf8'));
const envelopes = ctx.envelopes || [];
const bodyMap = ctx.sampled_bodies || {};

// Intent taxonomy for the LLM
const SYSTEM_PROMPT = `You are an email intent classifier for a business mailbox.

Classify each email into exactly ONE intent from this taxonomy:
- support: customer support, bug reports, tickets, troubleshooting
- finance: invoices, payments, budgets, contracts, reimbursements
- recruiting: job postings, interviews, candidates, offers, HR
- scheduling: meetings, calendar invites, time coordination
- receipt: delivery confirmations, read receipts, acknowledgments
- newsletter: newsletters, digests, event announcements, marketing
- internal_update: company notices, policy updates, compliance, training
- collaboration: project discussions, code reviews, shared docs, teamwork
- escalation: urgent requests, complaints, SLA breaches
- human: personal/social messages that need human judgment

For each email, provide:
1. intent: one of the above categories
2. confidence: 0.0-1.0 (how certain you are)
3. evidence: 1-3 short reasons supporting your classification

Respond with valid JSON only. No markdown fences.`;

function buildBatchPrompt(batch) {
  const items = batch.map((e, i) => {
    const body = bodyMap[e.id] ? bodyMap[e.id].body || '' : '';
    const bodySnippet = body.slice(0, 500);
    return `[${i}] id=${e.id} folder=${e.folder}
  from: ${e.from_name} <${e.from_addr}>
  subject: ${e.subject}
  date: ${e.date}
  has_attachment: ${e.has_attachment}
  body_preview: ${bodySnippet || '(no body sampled)'}`;
  });

  return `Classify these ${batch.length} emails. Return a JSON array where each element has: {"id": "...", "intent": "...", "confidence": 0.X, "evidence": ["...", "..."]}

${items.join('\n\n')}`;
}

function callLLM(systemPrompt, userPrompt) {
  return new Promise((resolve, reject) => {
    const url = new URL(llmUrl);
    let payload, headers;

    if (backend === 'openai') {
      payload = JSON.stringify({
        model,
        max_tokens: 4096,
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: userPrompt },
        ],
      });
      headers = {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`,
      };
    } else {
      payload = JSON.stringify({
        model,
        max_tokens: 4096,
        system: systemPrompt,
        messages: [{ role: 'user', content: userPrompt }],
      });
      headers = {
        'Content-Type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
      };
    }

    const options = {
      hostname: url.hostname,
      port: url.port || (url.protocol === 'https:' ? 443 : 80),
      path: url.pathname,
      method: 'POST',
      headers,
    };

    const transport = url.protocol === 'https:' ? https : http;
    const req = transport.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => (data += chunk));
      res.on('end', () => {
        if (res.statusCode !== 200) {
          reject(new Error(`API ${res.statusCode}: ${data.slice(0, 300)}`));
          return;
        }
        try {
          const body = JSON.parse(data);
          let text;
          if (backend === 'openai') {
            text = body.choices?.[0]?.message?.content || '';
          } else {
            text = body.content?.[0]?.text || '';
          }
          resolve(text);
        } catch (e) {
          reject(new Error(`Parse error: ${e.message}`));
        }
      });
    });
    req.on('error', reject);
    req.write(payload);
    req.end();
  });
}

async function main() {
  // Build batches
  const batches = [];
  for (let i = 0; i < envelopes.length; i += BATCH_SIZE) {
    batches.push(envelopes.slice(i, i + BATCH_SIZE));
  }

  console.log(`Processing ${envelopes.length} envelopes in ${batches.length} batch(es)...`);

  const allClassifications = [];

  for (let bi = 0; bi < batches.length; bi++) {
    const batch = batches[bi];
    const prompt = buildBatchPrompt(batch);

    if (isDryRun) {
      console.log(`\n--- Batch ${bi + 1}/${batches.length} (${batch.length} items) ---`);
      console.log(prompt.slice(0, 500) + '...\n');
      // Generate placeholder classifications for dry-run
      for (const e of batch) {
        allClassifications.push({
          id: e.id, intent: 'human', confidence: 0.0,
          evidence: ['dry-run placeholder'],
        });
      }
      continue;
    }

    console.log(`Batch ${bi + 1}/${batches.length} (${batch.length} items)...`);

    try {
      const response = await callLLM(SYSTEM_PROMPT, prompt);
      // Extract JSON array from response
      const jsonMatch = response.match(/\[[\s\S]*\]/);
      if (!jsonMatch) {
        console.error(`  Warn: no JSON array in response, marking as human`);
        for (const e of batch) {
          allClassifications.push({
            id: e.id, intent: 'human', confidence: 0.0,
            evidence: ['LLM response parse failure'],
          });
        }
        continue;
      }

      const results = JSON.parse(jsonMatch[0]);
      for (const r of results) {
        allClassifications.push({
          id: String(r.id),
          intent: r.intent || 'human',
          confidence: Number(r.confidence) || 0.5,
          evidence: Array.isArray(r.evidence) ? r.evidence : [],
        });
      }
      console.log(`  Classified ${results.length} items`);
    } catch (err) {
      console.error(`  Error: ${err.message}`);
      for (const e of batch) {
        allClassifications.push({
          id: e.id, intent: 'human', confidence: 0.0,
          evidence: [`API error: ${err.message}`],
        });
      }
    }

    // Rate limit courtesy: 500ms between batches
    if (bi < batches.length - 1) {
      await new Promise(r => setTimeout(r, 500));
    }
  }

  // --- Build distribution ---
  const distribution = {};
  for (const c of allClassifications) {
    distribution[c.intent] = (distribution[c.intent] || 0) + 1;
  }

  const output = {
    generated_at: new Date().toLocaleString('sv-SE', {timeZone:'Asia/Shanghai'}).replace(' ','T') + '+08:00',
    model,
    dry_run: isDryRun,
    stats: {
      total_classified: allClassifications.length,
      total_envelopes: envelopes.length,
      batches: batches.length,
    },
    distribution,
    classifications: allClassifications,
  };

  const outPath = `${outputDir}/intent-classification.json`;
  fs.writeFileSync(outPath, JSON.stringify(output, null, 2));
  console.log(`\nClassification written: ${outPath}`);

  // --- Build report ---
  const sorted = Object.entries(distribution)
    .sort((a, b) => b[1] - a[1]);
  const total = allClassifications.length;

  const highConf = allClassifications.filter(c => c.confidence >= 0.8).length;
  const lowConf = allClassifications.filter(c => c.confidence < 0.5).length;

  let report = `# Phase 1 Intent Classification Report\n\n`;
  report += `Generated: ${output.generated_at}\n`;
  report += `Model: ${model}\n`;
  report += `Total classified: ${total}\n\n`;
  report += `## Distribution\n\n`;
  report += `| Intent | Count | Ratio |\n|--------|-------|-------|\n`;
  for (const [intent, count] of sorted) {
    report += `| ${intent} | ${count} | ${(count / total * 100).toFixed(1)}% |\n`;
  }
  report += `\n## Confidence\n\n`;
  report += `- High confidence (>=0.8): ${highConf} (${(highConf/total*100).toFixed(1)}%)\n`;
  report += `- Low confidence (<0.5): ${lowConf} (${(lowConf/total*100).toFixed(1)}%)\n`;
  report += `\n## Notes\n\n`;
  report += `- Each classification includes an evidence chain for auditability\n`;
  report += `- Low-confidence items should be reviewed manually before downstream use\n`;
  report += `- Distribution informs Phase 2 profile inference priorities\n`;

  const reportPath = `${outputDir}/intent-report.md`;
  fs.writeFileSync(reportPath, report);
  console.log(`Report written: ${reportPath}`);
}

main().catch(err => {
  console.error(`Fatal: ${err.message}`);
  process.exit(1);
});
CLASSIFY

echo ""
echo "Phase 1 Thinking complete."
echo "  Output: runtime/validation/phase-1/intent-classification.json"
echo "  Report: runtime/validation/phase-1/intent-report.md"
