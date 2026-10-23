"""House style learned from the channel owner's feedback.

A note on a finished video ("the joke in beat 2 was too corny", "never open with a question", "less stock footage of
people typing") is turned by the script AI (DeepSeek) into one to three short standing rules, merged with the rules
already there (a new rule that contradicts or repeats an old one replaces it), and kept in style_rules.json next to the
jobs folder. Every script, rewrite and visual prompt after that gets them, so the same mistake is not made twice.
The rules can be listed, added by hand and removed (Newsroom page or /api/style)."""
import json
import re
import threading
import time
import uuid
from pathlib import Path

AREAS = ("script", "humor", "visuals", "voice", "general")
MAX_RULES = 40
_lock = threading.Lock()

LEARN = """You keep the house style guide for a YouTube news channel (Shorts and explainers written by AI from news alerts).
The channel owner just gave this feedback on a finished video:
"{note}"
About the video: {context}

Current house rules (id: [area] rule):
{rules}

Turn the feedback into at most 3 short, general, standing rules a script writer or visual editor can follow on ANY future
video (not just this one). Areas: script, humor, visuals, voice, general. Keep the owner's intent and wording where you can;
no rules about things the feedback does not mention. If a new rule repeats or contradicts a current rule, list that old
rule's id in "replaces". If the feedback is only about this one video and teaches nothing general, return no rules.
Reply with JSON only: {{"rules": [{{"area": "...", "rule": "...", "replaces": ["id", ...]}}]}}"""


def path(cfg):
    return Path(cfg.get("style_rules_file") or (Path(cfg.get("jobs_dir") or ".").parent / "style_rules.json"))


def load(cfg):
    try: return json.loads(path(cfg).read_text(encoding="utf-8")).get("rules", [])
    except (OSError, ValueError): return []


def _save(cfg, rules):
    p = path(cfg); p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps({"rules": rules[-MAX_RULES:]}, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def text(cfg, areas=AREAS):
    """The prompt block: '' when there are no rules (prompts stay exactly as before)."""
    rs = [r for r in load(cfg) if r.get("area") in areas and r.get("rule")]
    if not rs: return ""
    return ("\nHOUSE STYLE (rules from the channel owner's feedback; follow them unless they conflict with the facts):\n"
            + "\n".join(f"- [{r['area']}] {r['rule']}" for r in rs))


def add(cfg, rule, area="general", note="", job=""):
    rule = " ".join(str(rule).split())[:300]
    if not rule: raise ValueError("empty rule")
    area = area if area in AREAS else "general"
    with _lock:
        rs = load(cfg)
        r = {"id": uuid.uuid4().hex[:8], "area": area, "rule": rule, "note": note[:500], "job": job, "at": time.time()}
        rs.append(r); _save(cfg, rs)
    return r


def remove(cfg, rid):
    with _lock:
        rs = load(cfg); keep = [r for r in rs if r.get("id") != rid]
        if len(keep) == len(rs): return False
        _save(cfg, keep); return True


def replace_all(cfg, rules):
    """The laptop worker gets the PC's rules before a job (same list, same ids)."""
    with _lock: _save(cfg, [r for r in rules if isinstance(r, dict) and r.get("rule")])


def learn(cfg, note, context, job="", log=print):
    """Feedback -> rules (via the script AI). -> {"added": [...], "replaced": [...]}"""
    note = " ".join(str(note).split())[:1500]
    if not note: raise ValueError("empty feedback")
    from .llm import LLM
    cur = load(cfg)
    listing = "\n".join(f"{r['id']}: [{r['area']}] {r['rule']}" for r in cur) or "(none yet)"
    def ok(j):
        if not isinstance(j.get("rules"), list): return "rules must be a list"
        return None
    with LLM(dict(cfg), log, lambda: False) as llm:
        j = llm.chat_json("You turn feedback into short house-style rules. Reply with JSON only.",
                          LEARN.format(note=note.replace('"', "'"), context=str(context)[:600], rules=listing), max_tokens=600, check=ok)
    added, replaced = [], []
    with _lock:
        rs = load(cfg)
        for x in (j.get("rules") or [])[:3]:
            rule = " ".join(str(x.get("rule", "")).split())[:300]
            if not rule: continue
            for rid in x.get("replaces") or []:
                if any(r["id"] == rid for r in rs): rs = [r for r in rs if r["id"] != rid]; replaced.append(rid)
            r = {"id": uuid.uuid4().hex[:8], "area": x.get("area") if x.get("area") in AREAS else "general", "rule": rule,
                 "note": note[:500], "job": re.sub(r"[^\w-]", "", str(job))[:40], "at": time.time()}
            rs.append(r); added.append(r)
        _save(cfg, rs)
    log(f"House style: {len(added)} rule(s) learned" + (f", {len(replaced)} replaced" if replaced else "") + "".join(f"\n  + [{r['area']}] {r['rule']}" for r in added))
    return {"added": added, "replaced": replaced}
