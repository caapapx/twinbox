#!/usr/bin/env bash
# llm_common.sh — 公共 LLM 调用函数，供所有 thinking 脚本 source
# 用法: source scripts/llm_common.sh

init_llm_backend() {
  local env_file="${1:-.env}"
  [[ -f "${env_file}" ]] && { set -a; source "${env_file}"; set +a; }

  LLM_BACKEND=""
  if [[ -n "${LLM_API_KEY:-}" ]]; then
    LLM_BACKEND="openai"
    LLM_URL="${LLM_API_URL:-https://coding.dashscope.aliyuncs.com/v1/chat/completions}"
    LLM_MODEL_NAME="${LLM_MODEL:-kimi-k2.5}"
    echo "LLM backend: OpenAI-compatible (${LLM_MODEL_NAME})"
  elif [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
    LLM_BACKEND="anthropic"
    echo "LLM backend: Anthropic API"
  else
    echo "No LLM backend. Set LLM_API_KEY in .env." >&2
    return 1
  fi
}

call_llm() {
  local prompt="$1"
  local max_tokens="${2:-4096}"
  local timeout="${LLM_TIMEOUT:-180}"
  local retries="${LLM_RETRIES:-2}"
  if [[ "${LLM_BACKEND}" == "openai" ]]; then
    local body
    body=$(node -e '
      console.log(JSON.stringify({
        model: process.argv[2],
        messages: [{ role: "user", content: process.argv[1] }],
        temperature: 0.15,
        max_tokens: Number(process.argv[3]),
      }));
    ' "${prompt}" "${LLM_MODEL_NAME}" "${max_tokens}")
    local attempt=0 result=""
    while [[ $attempt -le $retries ]]; do
      result=$(curl -s --max-time "${timeout}" -X POST "${LLM_URL}" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${LLM_API_KEY}" \
        -d "${body}" 2>/dev/null)
      if [[ -n "${result}" && "${result}" != "" ]]; then break; fi
      attempt=$((attempt+1))
      [[ $attempt -le $retries ]] && echo "Retry ${attempt}/${retries}..." >&2 && sleep 5
    done
    echo "${result}" | node -e '
      const c=[]; process.stdin.on("data",d=>c.push(d));
      process.stdin.on("end",()=>{
        try {
          const r=JSON.parse(Buffer.concat(c).toString("utf8"));
          if(r.error){process.stderr.write("API error: "+JSON.stringify(r.error)+"\n");process.stdout.write("{}");return;}
          process.stdout.write(r.choices?.[0]?.message?.content||"{}");
        } catch(e){process.stderr.write("Parse error: "+e.message+"\n");process.stdout.write("{}");}
      });'
  elif [[ "${LLM_BACKEND}" == "anthropic" ]]; then
    local api_url="${ANTHROPIC_BASE_URL:-https://api.anthropic.com}/v1/messages"
    local model="${ANTHROPIC_MODEL:-claude-sonnet-4-20250514}"
    local body
    body=$(node -e '
      console.log(JSON.stringify({
        model: process.argv[2], max_tokens: Number(process.argv[3]),
        messages: [{ role: "user", content: process.argv[1] }]
      }));
    ' "${prompt}" "${model}" "${max_tokens}")
    local attempt=0 result=""
    while [[ $attempt -le $retries ]]; do
      result=$(curl -s --max-time "${timeout}" -X POST "${api_url}" \
        -H "Content-Type: application/json" \
        -H "x-api-key: ${ANTHROPIC_API_KEY}" \
        -H "anthropic-version: 2023-06-01" \
        -d "${body}" 2>/dev/null)
      if [[ -n "${result}" && "${result}" != "" ]]; then break; fi
      attempt=$((attempt+1))
      [[ $attempt -le $retries ]] && echo "Retry ${attempt}/${retries}..." >&2 && sleep 5
    done
    echo "${result}" | node -e '
      const c=[]; process.stdin.on("data",d=>c.push(d));
      process.stdin.on("end",()=>{
        try {
          const r=JSON.parse(Buffer.concat(c).toString("utf8"));
          if(r.error){process.stderr.write("API error\n");process.stdout.write("{}");return;}
          process.stdout.write((r.content||[]).map(c=>c.text||"").join(""));
        } catch(e){process.stdout.write("{}");}
      });'
  fi
}

# 清理 LLM 返回的 markdown 包裹，提取纯 JSON
clean_json() {
  node -e '
    const chunks = [];

    function stripFences(text) {
      const fenced = text.match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
      if (fenced) return fenced[1].trim();
      return text
        .replace(/^```(?:json)?\s*/i, "")
        .replace(/\s*```$/, "")
        .trim();
    }

    function findJsonStart(text) {
      const obj = text.indexOf("{");
      const arr = text.indexOf("[");
      if (obj === -1) return arr;
      if (arr === -1) return obj;
      return Math.min(obj, arr);
    }

    function extractBalancedPrefix(text) {
      const start = findJsonStart(text);
      if (start === -1) return text;

      let inString = false;
      let escaped = false;
      const stack = [];
      let lastBalanced = -1;

      for (let i = start; i < text.length; i++) {
        const ch = text[i];
        if (inString) {
          if (escaped) {
            escaped = false;
          } else if (ch === "\\\\") {
            escaped = true;
          } else if (ch === "\"") {
            inString = false;
          }
          continue;
        }

        if (ch === "\"") {
          inString = true;
          continue;
        }
        if (ch === "{" || ch === "[") {
          stack.push(ch);
          continue;
        }
        if (ch === "}" || ch === "]") {
          const last = stack[stack.length - 1];
          if ((ch === "}" && last === "{") || (ch === "]" && last === "[")) {
            stack.pop();
            if (stack.length === 0) lastBalanced = i;
          }
        }
      }

      if (lastBalanced !== -1) return text.slice(start, lastBalanced + 1).trim();
      return text.slice(start).trim();
    }

    function removeTrailingCommas(text) {
      return text.replace(/,\s*([}\]])/g, "$1");
    }

    function closeDanglingString(text) {
      let inString = false;
      let escaped = false;
      for (const ch of text) {
        if (inString) {
          if (escaped) {
            escaped = false;
          } else if (ch === "\\\\") {
            escaped = true;
          } else if (ch === "\"") {
            inString = false;
          }
        } else if (ch === "\"") {
          inString = true;
        }
      }
      return inString ? text + "\"" : text;
    }

    function balanceClosers(text) {
      let inString = false;
      let escaped = false;
      const stack = [];

      for (const ch of text) {
        if (inString) {
          if (escaped) {
            escaped = false;
          } else if (ch === "\\\\") {
            escaped = true;
          } else if (ch === "\"") {
            inString = false;
          }
          continue;
        }

        if (ch === "\"") {
          inString = true;
        } else if (ch === "{" || ch === "[") {
          stack.push(ch);
        } else if (ch === "}" || ch === "]") {
          const last = stack[stack.length - 1];
          if ((ch === "}" && last === "{") || (ch === "]" && last === "[")) {
            stack.pop();
          }
        }
      }

      let suffix = "";
      for (let i = stack.length - 1; i >= 0; i--) {
        suffix += stack[i] === "{" ? "}" : "]";
      }
      return text + suffix;
    }

    function candidates(raw) {
      const base = raw.replace(/^\uFEFF/, "").trim();
      const out = [];
      const seen = new Set();
      const push = (value) => {
        const normalized = value.trim();
        if (!normalized || seen.has(normalized)) return;
        seen.add(normalized);
        out.push(normalized);
      };

      const fenced = stripFences(base);
      const extracted = extractBalancedPrefix(fenced);

      push(base);
      push(fenced);
      push(extracted);
      push(removeTrailingCommas(extracted));
      push(balanceClosers(closeDanglingString(removeTrailingCommas(extracted))));

      return out;
    }

    function parseFirst(raw) {
      let lastError = "unknown";
      for (const candidate of candidates(raw)) {
        try {
          return JSON.stringify(JSON.parse(candidate), null, 2);
        } catch (err) {
          lastError = err.message;
        }
      }
      throw new Error(lastError);
    }

    process.stdin.on("data", d => chunks.push(d));
    process.stdin.on("end", () => {
      const raw = Buffer.concat(chunks).toString("utf8");
      try {
        process.stdout.write(parseFirst(raw));
      } catch (err) {
        const preview = raw.replace(/\s+/g, " ").trim().slice(0, 500);
        process.stderr.write("JSON parse failed after repair attempts: " + err.message + "\n");
        if (preview) process.stderr.write("Raw (first 500): " + preview + "\n");
        process.stdout.write("{}");
      }
    });'
}
