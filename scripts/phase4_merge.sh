#!/usr/bin/env bash
# Phase 4 Merge: 合并 3 个子任务的 raw JSON → YAML/MD 输出
# 纯合并，不调 LLM。前置条件：3 个 *-raw.json 已存在。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"

STATE_ROOT="${TWINBOX_CANONICAL_ROOT}"
PHASE4_DIR="${STATE_ROOT}/runtime/validation/phase-4"
DOC_DIR="${STATE_ROOT}/docs/validation"
mkdir -p "${PHASE4_DIR}" "${DOC_DIR}"

for f in urgent-pending-raw.json sla-risks-raw.json weekly-brief-raw.json; do
  if [[ ! -f "${PHASE4_DIR}/${f}" ]]; then
    echo "Missing ${f}. Run think sub-tasks first." >&2; exit 1
  fi
done

echo "Merging 3 raw outputs..."

node - <<'NODE' "${PHASE4_DIR}" "${DOC_DIR}"
const fs = require('fs');
const [p4, doc] = process.argv.slice(2);
const model = process.env.LLM_MODEL || 'unknown';
const ts = new Date().toLocaleString('sv-SE',{timeZone:'Asia/Shanghai'}).replace(' ','T')+'+08:00';

function load(f) { try { return JSON.parse(fs.readFileSync(f,'utf8')); } catch { return {}; } }

const up = load(p4+'/urgent-pending-raw.json');
const sl = load(p4+'/sla-risks-raw.json');
const br = load(p4+'/weekly-brief-raw.json');

const merged = {
  daily_urgent: up.daily_urgent || [],
  pending_replies: up.pending_replies || [],
  sla_risks: sl.sla_risks || [],
  weekly_brief: br.weekly_brief || {},
};
fs.writeFileSync(p4+'/llm-response.json', JSON.stringify(merged,null,2));

const urgent=merged.daily_urgent, pending=merged.pending_replies, risks=merged.sla_risks, brief=merged.weekly_brief;

function yamlHeader() { return `generated_at: "${ts}"\nmethod: "llm-parallel"\nmodel: "${model}"`; }

// daily-urgent.yaml
const uy = [yamlHeader(), 'daily_urgent:'];
for (const u of urgent) {
  uy.push('  - thread_key: '+JSON.stringify(u.thread_key||''));
  uy.push('    flow: '+(u.flow||'UNMODELED'));
  uy.push('    stage: '+(u.stage||'unknown'));
  uy.push('    urgency_score: '+(u.urgency_score||0));
  uy.push('    why: '+JSON.stringify(u.why||''));
  uy.push('    action_hint: '+JSON.stringify(u.action_hint||''));
  uy.push('    owner: '+JSON.stringify(u.owner||''));
  uy.push('    waiting_on: '+JSON.stringify(u.waiting_on||''));
  uy.push('    evidence_source: '+(u.evidence_source||'mail_evidence'));
}
fs.writeFileSync(p4+'/daily-urgent.yaml', uy.join('\n')+'\n');

// pending-replies.yaml
const py = [yamlHeader(), 'pending_replies:'];
for (const p of pending) {
  py.push('  - thread_key: '+JSON.stringify(p.thread_key||''));
  py.push('    flow: '+(p.flow||'UNMODELED'));
  py.push('    waiting_on_me: '+(p.waiting_on_me?'true':'false'));
  py.push('    why: '+JSON.stringify(p.why||''));
  py.push('    suggested_action: '+JSON.stringify(p.suggested_action||''));
  py.push('    evidence_source: '+(p.evidence_source||'mail_evidence'));
}
fs.writeFileSync(p4+'/pending-replies.yaml', py.join('\n')+'\n');

// sla-risks.yaml
const ry = [yamlHeader(), 'sla_risks:'];
for (const r of risks) {
  ry.push('  - thread_key: '+JSON.stringify(r.thread_key||''));
  ry.push('    flow: '+(r.flow||'UNMODELED'));
  ry.push('    risk_type: '+(r.risk_type||'unknown'));
  ry.push('    risk_description: '+JSON.stringify(r.risk_description||''));
  ry.push('    days_since_last_activity: '+(r.days_since_last_activity||0));
  ry.push('    suggested_action: '+JSON.stringify(r.suggested_action||''));
}
fs.writeFileSync(p4+'/sla-risks.yaml', ry.join('\n')+'\n');

// weekly-brief.md
const bl = ['# Weekly Brief','','Generated: '+ts,'Model: '+model,'Period: '+(brief.period||'N/A'),'','## Overview','','Total threads: '+(brief.total_threads_in_window||0),''];
if (brief.flow_summary) {
  bl.push('## Flow Summary','','| Flow | Name | Count | Highlight |','|------|------|-------|-----------|');
  for (const f of brief.flow_summary) bl.push('| '+(f.flow||'')+' | '+(f.name||'')+' | '+(f.count||0)+' | '+(f.highlight||'')+' |');
  bl.push('');
}
if (brief.top_actions) { bl.push('## Top Actions',''); for (const a of brief.top_actions) bl.push('- '+a); bl.push(''); }
if (brief.rhythm_observation) { bl.push('## Rhythm','',brief.rhythm_observation,''); }
fs.writeFileSync(p4+'/weekly-brief.md', bl.join('\n')+'\n');

// Report
const rp = ['# Phase 4 Report (Parallel Mode)','','## Method','- 3 parallel LLM calls: urgent+pending, sla-risks, weekly-brief','- Model: '+model,'','## Daily Urgent ('+urgent.length+')','','| Thread | Flow | Score | Action |','|--------|------|-------|--------|'];
for (const u of urgent.slice(0,10)) rp.push('| '+(u.thread_key||'').slice(0,30)+' | '+(u.flow||'')+' | '+(u.urgency_score||0)+' | '+(u.action_hint||'').slice(0,40)+' |');
rp.push('','## Pending ('+pending.length+')','');
for (const p of pending.slice(0,5)) rp.push('- '+(p.thread_key||'').slice(0,40)+': '+(p.why||''));
rp.push('','## SLA Risks ('+risks.length+')','');
for (const r of risks.slice(0,5)) rp.push('- ['+(r.risk_type||'')+'] '+(r.thread_key||'').slice(0,30)+': '+(r.risk_description||''));
fs.writeFileSync(doc+'/phase-4-report.md', rp.join('\n')+'\n');

console.log('Merged: '+urgent.length+' urgent, '+pending.length+' pending, '+risks.length+' risks');
NODE

echo ""
echo "Phase 4 merge complete."
echo "Outputs:"
echo "  ${PHASE4_DIR}/daily-urgent.yaml"
echo "  ${PHASE4_DIR}/pending-replies.yaml"
echo "  ${PHASE4_DIR}/sla-risks.yaml"
echo "  ${PHASE4_DIR}/weekly-brief.md"
echo "  ${DOC_DIR}/phase-4-report.md"
