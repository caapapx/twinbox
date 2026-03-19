#!/usr/bin/env bash
set -euo pipefail

# Phase 1 Thinking: LLM batch intent classification
# Input:  runtime/context/phase1-context.json
# Output: runtime/validation/phase-1/ (intent JSON + report)

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
CONTEXT_FILE="${ROOT_DIR}/runtime/context/phase1-context.json"
PHASE_DIR="${ROOT_DIR}/runtime/validation/phase-1"
DOC_DIR="${ROOT_DIR}/docs/validation"
BATCH_SIZE=20

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/phase1_thinking.sh [options]

Options:
  --context <path>    Override context-pack path
  --batch-size <n>    Envelopes per LLM batch (default: 20)
  --dry-run           Print prompts without calling LLM
  -h, --help          Show this help
USAGE
}

DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --context)    CONTEXT_FILE="${2:-}"; shift 2 ;;
    --batch-size) BATCH_SIZE="${2:-}"; shift 2 ;;
    --dry-run)    DRY_RUN=true; shift ;;
    -h|--help)    usage; exit 0 ;;
    *)            echo "Unknown option: $1"; usage; exit 1 ;;
  esac
done

mkdir -p "${PHASE_DIR}" "${DOC_DIR}"

# --- validate inputs ---
if [[ ! -f "${CONTEXT_FILE}" ]]; then
  echo "Context-pack not found: ${CONTEXT_FILE}"
  echo "Run phase1_loading.sh first."
  exit 1
fi

# Load .env for optional ANTHROPIC_API_KEY
if [[ -f "${ENV_FILE}" ]]; then
  set -a; source "${ENV_FILE}"; set +a
fi

ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
if [[ -z "${ANTHROPIC_API_KEY}" && "${DRY_RUN}" == "false" ]]; then
  echo "ANTHROPIC_API_KEY not set in .env or environment."
  echo "Use --dry-run to preview prompts without calling the API."
  exit 1
fi

echo "[thinking] Reading context-pack: ${CONTEXT_FILE}"
echo "[thinking] Batch size: ${BATCH_SIZE}"

# --- LLM batch classification ---
node - <<'NODE' "${CONTEXT_FILE}" "${PHASE_DIR}" "${DOC_DIR}" "${BATCH_SIZE}" "${DRY_RUN}" "${ANTHROPIC_API_KEY}"
const fs = require('fs');
const https = require('https');

const [ctxPath, phaseDir, docDir, batchSizeRaw, dryRunRaw, apiKey] =
  process.argv.slice(2);
const BATCH_SIZE = Number(batchSizeRaw);
const DRY_RUN = dryRunRaw === 'true';

const ctx = JSON.parse(fs.readFileSync(ctxPath, 'utf8'));
const envelopes = ctx.envelopes || [];
const bodyMap = new Map(
  (ctx.sampled_bodies || []).map(b => [String(b.id), b.body || ''])
);

const INTENTS = [
  'human_conversation',
  'support_ticket',
  'finance_invoice',
  'recruiting_hr',
  'scheduling_meeting',
  'receipt_confirmation',
  'newsletter_marketing',
  'internal_update',
  'notification_automated',
  'spam_junk',
];

function buildPrompt(batch) {
  const items = batch.map((e, i) => {
    const body = bodyMap.get(String(e.id)) || '';
    const bodySnippet = body.slice(0, 500);
    return [
      `[${i}]`,
      `  folder: ${e.folder}`,
      `  from: ${e.from_name} <${e.from_addr}>`,
      `  date: ${e.date}`,
      `  subject: ${e.subject}`,
      `  has_attachment: ${e.has_attachment}`,
      bodySnippet ? `  body_preview: ${bodySnippet}` : '',
    ].filter(Boolean).join('\n');
  }).join('\n\n');

  return `You are an email intent classifier. Classify each email into exactly one intent category.

Available intents: ${INTENTS.join(', ')}

For each email, respond with a JSON array. Each element must have:
- "index": the [N] index from the input
- "intent": one of the available intents
- "confidence": a number 0.0-1.0
- "evidence": a brief explanation (1 sentence) of why this intent was chosen

Respond ONLY with the JSON array, no other text.

Emails to classify:

${items}`;
}

async function callClaude(prompt) {
  const body = JSON.stringify({
    model: 'claude-haiku-4-5-20251001',
    max_tokens: 4096,
    messages: [{ role: 'user', content: prompt }],
  });

  return new Promise((resolve, reject) => {
    const req = https.request({
      hostname: 'api.anthropic.com',
      path: '/v1/messages',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
      },
    }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        if (res.statusCode !== 200) {
          reject(new Error(`API ${res.statusCode}: ${data}`));
          return;
        }
        try {
          const parsed = JSON.parse(data);
          const text = parsed.content?.[0]?.text || '';
          resolve(text);
        } catch (e) {
          reject(new Error(`Parse error: ${e.message}`));
        }
      });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

function parseResponse(text) {
  // Extract JSON array from response (handle markdown fences)
  const cleaned = text.replace(/```json\n?/g, '').replace(/```\n?/g, '').trim();
  try {
    return JSON.parse(cleaned);
  } catch {
    console.error('[thinking] Failed to parse LLM response:', text.slice(0, 200));
    return [];
  }
}

async function main() {
  const batches = [];
  for (let i = 0; i < envelopes.length; i += BATCH_SIZE) {
    batches.push(envelopes.slice(i, i + BATCH_SIZE));
  }

  console.log(`[thinking] ${envelopes.length} envelopes → ${batches.length} batches`);

  const allResults = [];

  for (let bi = 0; bi < batches.length; bi++) {
    const batch = batches[bi];
    const prompt = buildPrompt(batch);

    if (DRY_RUN) {
      console.log(`\n--- Batch ${bi + 1}/${batches.length} (${batch.length} items) ---`);
      console.log(prompt.slice(0, 500) + '...\n');
      // Generate mock results for dry-run
      for (let j = 0; j < batch.length; j++) {
        allResults.push({
          id: batch[j].id,
          folder: batch[j].folder,
          subject: batch[j].subject,
          from_addr: batch[j].from_addr,
          intent: 'human_conversation',
          confidence: 0.5,
          evidence: '[dry-run] No LLM call made',
        });
      }
      continue;
    }

    console.log(`[thinking] Batch ${bi + 1}/${batches.length} (${batch.length} items)...`);
    try {
      const raw = await callClaude(prompt);
      const parsed = parseResponse(raw);
      for (const item of parsed) {
        const idx = item.index;
        if (idx >= 0 && idx < batch.length) {
          allResults.push({
            id: batch[idx].id,
            folder: batch[idx].folder,
            subject: batch[idx].subject,
            from_addr: batch[idx].from_addr,
            intent: item.intent || 'unknown',
            confidence: item.confidence || 0,
            evidence: item.evidence || '',
          });
        }
      }
    } catch (err) {
      console.error(`[thinking] Batch ${bi + 1} failed: ${err.message}`);
      // Mark batch items as failed
      for (const e of batch) {
        allResults.push({
          id: e.id, folder: e.folder, subject: e.subject,
          from_addr: e.from_addr,
          intent: 'error', confidence: 0,
          evidence: `LLM call failed: ${err.message}`,
        });
      }
    }
  }

  // --- Write intent classification results ---
  const intentDist = {};
  let classified = 0, errors = 0;
  for (const r of allResults) {
    if (r.intent === 'error') { errors++; continue; }
    classified++;
    intentDist[r.intent] = (intentDist[r.intent] || 0) + 1;
  }

  const output = {
    version: 1,
    generated_at: new Date().toISOString(),
    dry_run: DRY_RUN,
    stats: {
      total: allResults.length,
      classified,
      errors,
      intent_distribution: intentDist,
    },
    classifications: allResults,
  };

  const outPath = `${phaseDir}/intent-classification.json`;
  fs.writeFileSync(outPath, JSON.stringify(output, null, 2));
  console.log(`[thinking] Results: ${outPath}`);

  // --- Write human-readable report ---
  const sorted = Object.entries(intentDist)
    .sort((a, b) => b[1] - a[1]);
  const total = classified || 1;

  let report = `# Phase 1 Intent Classification Report\n\n`;
  report += `Generated: ${output.generated_at}\n`;
  report += `Mode: ${DRY_RUN ? 'dry-run (no LLM)' : 'LLM (claude-haiku-4-5)'}\n\n`;
  report += `## Summary\n\n`;
  report += `| Metric | Value |\n|--------|-------|\n`;
  report += `| Total envelopes | ${allResults.length} |\n`;
  report += `| Classified | ${classified} |\n`;
  report += `| Errors | ${errors} |\n\n`;
  report += `## Intent Distribution\n\n`;
  report += `| Intent | Count | Ratio |\n|--------|-------|-------|\n`;
  for (const [intent, count] of sorted) {
    report += `| ${intent} | ${count} | ${(count / total * 100).toFixed(1)}% |\n`;
  }

  // High-confidence samples per intent
  report += `\n## High-Confidence Samples\n\n`;
  for (const [intent] of sorted.slice(0, 5)) {
    const samples = allResults
      .filter(r => r.intent === intent && r.confidence >= 0.8)
      .slice(0, 3);
    if (samples.length === 0) continue;
    report += `### ${intent}\n\n`;
    for (const s of samples) {
      report += `- **${s.subject}** (from: ${s.from_addr}, conf: ${s.confidence})\n`;
      report += `  Evidence: ${s.evidence}\n`;
    }
    report += '\n';
  }

  const reportPath = `${docDir}/phase-1-intent-report.md`;
  fs.writeFileSync(reportPath, report);
  console.log(`[thinking] Report: ${reportPath}`);
}

main().catch(err => {
  console.error(`[thinking] Fatal: ${err.message}`);
  process.exit(1);
});
NODE

echo ""
echo "Phase 1 Thinking complete."
echo "  Results: ${PHASE_DIR}/intent-classification.json"
echo "  Report:  ${DOC_DIR}/phase-1-intent-report.md"
