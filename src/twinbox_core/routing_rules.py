"""Phase 3.5 Routing Rules Engine (Semantic Triage)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from twinbox_core.llm import call_llm, clean_json_text, resolve_backend


@dataclass(frozen=True)
class RuleAction:
    set_state: str | None = None
    set_waiting_on: str | None = None
    add_tags: list[str] | None = None
    skip_phase4: bool = False


@dataclass(frozen=True)
class RuleCondition:
    match_all: list[dict[str, object]] | None = None
    match_any: list[dict[str, object]] | None = None


@dataclass(frozen=True)
class RoutingRule:
    id: str
    name: str
    active: bool
    conditions: RuleCondition
    actions: RuleAction


def load_rules_raw(config_path: Path) -> dict[str, object]:
    if not config_path.is_file():
        return {"rules": []}
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"rules": []}
    except Exception:
        return {"rules": []}


def save_rules_raw(config_path: Path, data: dict[str, object]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def load_rules(config_path: Path) -> list[RoutingRule]:
    if not config_path.is_file():
        return []
    
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "rules" not in data:
            return []
            
        rules = []
        for r in data.get("rules", []):
            if not r.get("active", True):
                continue
                
            cond_data = r.get("conditions", {})
            conditions = RuleCondition(
                match_all=cond_data.get("match_all"),
                match_any=cond_data.get("match_any"),
            )
            
            act_data = r.get("actions", {})
            actions = RuleAction(
                set_state=act_data.get("set_state"),
                set_waiting_on=act_data.get("set_waiting_on"),
                add_tags=act_data.get("add_tags", []),
                skip_phase4=act_data.get("skip_phase4", False),
            )
            
            rules.append(RoutingRule(
                id=r.get("id", ""),
                name=r.get("name", ""),
                active=True,
                conditions=conditions,
                actions=actions,
            ))
        return rules
    except Exception as e:
        print(f"Warning: failed to load routing rules from {config_path}: {e}")
        return []


def _evaluate_hard_condition(field: str, operator: str, value: object, thread: dict[str, object]) -> bool:
    thread_val = str(thread.get(field, "") or "").lower()
    
    if operator == "in" and isinstance(value, list):
        return thread_val in [str(v).lower() for v in value]
    if operator == "not_in" and isinstance(value, list):
        return thread_val not in [str(v).lower() for v in value]
    if operator == "equals":
        return thread_val == str(value).lower()
    if operator == "contains":
        return str(value).lower() in thread_val
        
    return False


def _evaluate_semantic_condition(
    intent_desc: str, 
    thread: dict[str, object], 
    env_file: Path | None = None
) -> bool:
    """Use a lightweight LLM call to evaluate semantic match."""
    prompt = f"""You are a routing rule engine. Evaluate if the following email thread matches the user's intent description.
    
Intent Description: {intent_desc}

Thread Subject: {thread.get('latest_subject', '')}
Thread Excerpt: {str(thread.get('body_excerpt', ''))[:500]}

Reply with a JSON object:
{{"matches": true/false, "reason": "brief explanation"}}
"""
    try:
        backend = resolve_backend(env_file=env_file)
        if not backend.model:
            return False
        # Prefer a faster/cheaper model if available, but fallback to default
        response_text = call_llm(prompt, max_tokens=128, env_file=env_file)
        # Handle cases where LLM returns a markdown code block or just true/false
        cleaned = clean_json_text(response_text)
        if cleaned.lower() == "true":
            return True
        if cleaned.lower() == "false":
            return False
            
        parsed = json.loads(cleaned)
        return bool(parsed.get("matches", False))
    except Exception as e:
        print(f"Warning: semantic evaluation failed: {e}")
        return False


def evaluate_rule(
    rule: RoutingRule, 
    thread: dict[str, object], 
    env_file: Path | None = None
) -> bool:
    """Evaluate if a thread matches a rule."""
    
    def eval_cond_list(conds: list[dict[str, object]]) -> list[bool]:
        results = []
        for c in conds:
            field = str(c.get("field", ""))
            operator = str(c.get("operator", ""))
            value = c.get("value")
            
            if field == "semantic_intent":
                if operator == "is_true":
                    results.append(_evaluate_semantic_condition(str(value), thread, env_file))
                elif operator == "is_false":
                    results.append(not _evaluate_semantic_condition(str(value), thread, env_file))
                else:
                    results.append(False)
            else:
                results.append(_evaluate_hard_condition(field, operator, value, thread))
        return results

    if rule.conditions.match_all:
        if not all(eval_cond_list(rule.conditions.match_all)):
            return False
            
    if rule.conditions.match_any:
        if not any(eval_cond_list(rule.conditions.match_any)):
            return False
            
    return True


def apply_routing_rules(
    context_pack_path: Path, 
    rules_path: Path, 
    output_path: Path,
    env_file: Path | None = None
) -> None:
    """Phase 3.5: Apply routing rules to context pack threads."""
    rules = load_rules(rules_path)
    if not rules:
        print("No active routing rules found. Skipping Phase 3.5.")
        # Just copy the file
        output_path.write_text(context_pack_path.read_text(encoding="utf-8"), encoding="utf-8")
        return
        
    context = json.loads(context_pack_path.read_text(encoding="utf-8"))
    threads = context.get("threads", context.get("top_threads", []))
    
    applied_count = 0
    for thread in threads:
        for rule in rules:
            if evaluate_rule(rule, thread, env_file):
                print(f"Thread '{thread.get('thread_key')}' matched rule '{rule.name}'")
                
                # Apply actions
                if rule.actions.set_state:
                    thread["routing_state"] = rule.actions.set_state
                if rule.actions.set_waiting_on is not None:
                    thread["routing_waiting_on"] = rule.actions.set_waiting_on
                if rule.actions.add_tags:
                    tags = thread.get("tags", [])
                    tags.extend(rule.actions.add_tags)
                    thread["tags"] = list(set(tags))
                if rule.actions.skip_phase4:
                    thread["skip_phase4"] = True
                    
                thread["matched_rule"] = rule.id
                applied_count += 1
                break # Only apply the first matching rule
                
    # Re-assign threads to context to ensure changes are saved
    context["threads"] = threads
    output_path.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Phase 3.5 complete. Applied rules to {applied_count} threads.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--context-pack", required=True)
    parser.add_argument("--rules", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--env-file")
    args = parser.parse_args()
    
    apply_routing_rules(
        Path(args.context_pack),
        Path(args.rules),
        Path(args.output),
        Path(args.env_file) if args.env_file else None
    )
