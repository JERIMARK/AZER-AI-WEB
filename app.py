#!/usr/bin/env python3
# ============================================================
#   MyAI Web App - Personal AI Assistant
#   Flask Web Version with Full Features
#   Version: 3.0 (Web Edition)
# ============================================================

import os
import json
import datetime
import re
import math as _math
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string
from dotenv import load_dotenv
load_dotenv()

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

app = Flask(__name__)

# ── Paths ──────────────────────────────────────────────────
BASE   = Path("myai_data")
CFG    = BASE / "config" / "settings.json"
KB_DIR = BASE / "data" / "knowledge"
MEM    = BASE / "data" / "memory.json"
HIST   = BASE / "data" / "history.json"

for d in [KB_DIR, BASE / "config", BASE / "data"]:
    d.mkdir(parents=True, exist_ok=True)

# ── Default Config ─────────────────────────────────────────
DEFAULT_CFG = {
    "ai_name": "AZER-AI",
    "user_name": "User",
    "history_limit": 500,
    "internet_search": True,
    "search_keys": {
        "tavily": "",
        "brave": "",
        "google_key": "",
        "google_cx": ""
    },
    "groq_api_key": os.environ.get("groq_api_key", ""),
    "groq_model": "llama-3.1-8b-instant",
    "use_groq_ai": True
}

# ── Config Helpers ─────────────────────────────────────────
def load_cfg():
    if CFG.exists():
        try:
            with open(CFG) as f:
                return {**DEFAULT_CFG, **json.load(f)}
        except Exception:
            pass
    return DEFAULT_CFG.copy()

def save_cfg(cfg):
    with open(CFG, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

# ── Memory ─────────────────────────────────────────────────
def load_mem():
    if MEM.exists():
        try:
            return json.loads(MEM.read_text())
        except Exception:
            pass
    return {"last_topic": None, "facts": [], "pinned": []}

def save_mem(m):
    m["facts"]  = m.get("facts", [])[-100000:]
    m["pinned"] = m.get("pinned", [])[-20000:]
    MEM.write_text(json.dumps(m, indent=2, ensure_ascii=False))

def mem_learn(mem, question, answer):
    mem["last_topic"] = question
    fact = f"{question} -> {answer[:300]}"
    if fact not in mem["facts"]:
        mem["facts"].append(fact)

def mem_search(q, mem):
    q_lower = q.lower()
    words = [w for w in q_lower.split() if len(w) > 3]
    if not words:
        return None
    for f in reversed(mem.get("pinned", [])):
        if any(word in f.lower() for word in words):
            return f
    for f in reversed(mem.get("facts", [])):
        if any(word in f.lower() for word in words):
            return f.split(" -> ", 1)[-1]
    return None

# ── Knowledge Base ─────────────────────────────────────────
def kb_search(query):
    results = []
    if not query or len(query.strip()) < 2:
        return results
    q = query.lower()
    words = [w for w in q.split() if len(w) > 2]
    for fp in KB_DIR.glob("*.json"):
        try:
            entries = json.loads(fp.read_text())
        except Exception:
            continue
        for e in entries:
            text = (e.get("title", "") + " " + e.get("content", "")).lower()
            score = sum(1 for w in words if w in text)
            if score > 0:
                results.append({**e, "_file": fp.stem, "_score": score})
    results.sort(key=lambda x: x["_score"], reverse=True)
    return results

def kb_add(title, content, tags="", source="manual"):
    category = (
        tags.split(",")[0].strip().lower().replace(" ", "_")
        if tags else "general"
    )
    fp = KB_DIR / f"{category}.json"
    entries = []
    if fp.exists():
        try:
            entries = json.loads(fp.read_text())
        except Exception:
            entries = []
    entry = {
        "id": datetime.datetime.now().strftime("%Y%m%d%H%M%S"),
        "title": title,
        "content": content,
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
        "source": source,
        "created": datetime.datetime.now().isoformat()
    }
    entries.append(entry)
    fp.write_text(json.dumps(entries, indent=2, ensure_ascii=False))
    return entry, category

def kb_delete(keyword):
    deleted = 0
    for fp in KB_DIR.glob("*.json"):
        try:
            entries = json.loads(fp.read_text())
        except Exception:
            continue
        new = [e for e in entries
               if keyword.lower() not in e.get("title", "").lower()]
        if len(new) < len(entries):
            deleted += len(entries) - len(new)
            fp.write_text(json.dumps(new, indent=2, ensure_ascii=False))
    return deleted

def kb_list_all():
    all_entries = []
    for fp in KB_DIR.glob("*.json"):
        try:
            entries = json.loads(fp.read_text())
            for e in entries:
                all_entries.append({**e, "_cat": fp.stem})
        except Exception:
            continue
    return all_entries

def kb_stats():
    total, cats = 0, {}
    for fp in KB_DIR.glob("*.json"):
        try:
            e = json.loads(fp.read_text())
            cats[fp.stem] = len(e)
            total += len(e)
        except Exception:
            pass
    return total, cats

# ── Search Engines ─────────────────────────────────────────
def _search_tavily(query, api_key):
    try:
        r = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query,
                  "search_depth": "basic", "max_results": 3},
            timeout=10
        ).json()
        results = r.get("results", [])
        if results:
            best = results[0]
            combined = " ".join(
                x.get("content", "")[:300]
                for x in results[:3] if x.get("content")
            )
            return {"title": best.get("title", query),
                    "content": combined, "source": "Tavily",
                    "url": best.get("url", "")}
    except Exception:
        pass
    return None

def _search_brave(query, api_key):
    try:
        r = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": 3},
            headers={"Accept": "application/json",
                     "Accept-Encoding": "gzip",
                     "X-Subscription-Token": api_key},
            timeout=10
        ).json()
        items = r.get("web", {}).get("results", [])
        if items:
            best = items[0]
            combined = " ".join(
                x.get("description", "")[:300]
                for x in items[:3] if x.get("description")
            )
            return {"title": best.get("title", query),
                    "content": combined, "source": "Brave",
                    "url": best.get("url", "")}
    except Exception:
        pass
    return None

def _search_google(query, api_key, cx):
    try:
        r = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": api_key, "cx": cx, "q": query, "num": 3},
            timeout=10
        ).json()
        items = r.get("items", [])
        if items:
            best = items[0]
            combined = " ".join(
                x.get("snippet", "")[:300]
                for x in items[:3] if x.get("snippet")
            )
            return {"title": best.get("title", query),
                    "content": combined, "source": "Google",
                    "url": best.get("link", "")}
    except Exception:
        pass
    return None

def _search_duckduckgo(query):
    try:
        r = requests.get(
            f"https://api.duckduckgo.com/?q={requests.utils.quote(query)}"
            f"&format=json&no_html=1&skip_disambig=1",
            timeout=8
        ).json()
        if r.get("AbstractText"):
            return {"title": r.get("Heading", query),
                    "content": r["AbstractText"], "source": "DuckDuckGo",
                    "url": r.get("AbstractURL", "")}
        for item in r.get("RelatedTopics", []):
            if isinstance(item, dict) and "Text" in item and len(item["Text"]) > 40:
                return {"title": query, "content": item["Text"],
                        "source": "DuckDuckGo",
                        "url": item.get("FirstURL", "")}
    except Exception:
        pass
    return None

def internet_search(query, cfg=None):
    if not HAS_REQUESTS:
        return None
    keys = cfg.get("search_keys", {}) if cfg else {}
    if keys.get("tavily"):
        r = _search_tavily(query, keys["tavily"])
        if r:
            return r
    if keys.get("brave"):
        r = _search_brave(query, keys["brave"])
        if r:
            return r
    if keys.get("google_key") and keys.get("google_cx"):
        r = _search_google(query, keys["google_key"], keys["google_cx"])
        if r:
            return r
    return _search_duckduckgo(query)

# ── History ────────────────────────────────────────────────
def load_hist():
    if HIST.exists():
        try:
            return json.loads(HIST.read_text())
        except Exception:
            pass
    return []

def save_hist(h, limit=500):
    HIST.write_text(json.dumps(h[-limit:], indent=2, ensure_ascii=False))

def hist_add(h, role, message):
    h.append({
        "role": role,
        "message": message,
        "time": datetime.datetime.now().isoformat()
    })

# ── NLU ───────────────────────────────────────────────────
FILLER_WORDS = [
    r"\bano\s*(ang|ba|nga|po|kaya)?\b",
    r"\bsino\s*(ang|ba|nga|po)?\b",
    r"\bsaan\s*(ba|nga|po)?\b",
    r"\bkailan\s*(ba|nga|po)?\b",
    r"\bbakit\s*(ba|nga|po)?\b",
    r"\bpaano\s*(ba|nga|po|ang)?\b",
    r"\bmagkano\s*(ang|ba|po)?\b",
    r"\bilang\s*(ang|ba|po)?\b",
    r"\bpwede\s*(mo|ba|bang|nyo)?\b",
    r"\bsabihin\s*(mo|nyo)?\b",
    r"\bibig\s*sabihin\s*(ng|nito|noon)?\b",
    r"\bmeaning\s*(ng|of|nito)?\b",
    r"\bwhat\s*is\s*(a|an|the)?\b",
    r"\bwhat\s*are\s*(the)?\b",
    r"\bwho\s*is\s*(a|an|the)?\b",
    r"\bwhere\s*is\s*(the)?\b",
    r"\bhow\s*(to|do|does|can|is|many|much)?\b",
    r"\bwhy\s*(is|are|do|does)?\b",
    r"\bwhen\s*(is|was|did)?\b",
    r"\bcan\s*you\s*(tell\s*me|explain|define)?\b",
    r"\btell\s*me\s*(about|ang|ang\s*tungkol\s*sa)?\b",
    r"\bexplain\s*(ang|the|what|how)?\b",
    r"\bdefine\s*(ang|the)?\b",
    r"\bano\s*ang\s*kahulugan\s*(ng|nito)?\b",
    r"\btungkol\s*(sa|saan)?\b",
    r"\bpakiusap\b|\bplease\b|\bpaki\b",
    r"\bpo\b|\bho\b", r"\bnga\b", r"\bkaya\b", r"\bba\b",
]

INTENT_PATTERNS = {
    "greeting":   [r"\b(hi|hello|hey|oi|sup|hoy|kumusta|kamusta|musta|good\s*(morning|afternoon|evening|night))\b"],
    "thanks":     [r"\b(salamat|maraming\s*salamat|thanks|thank\s*you|ty|tnx|pasalamat)\b"],
    "farewell":   [r"\b(paalam|bye|goodbye|ingat|sige\s*na)\b"],
    "time":       [r"\b(anong\s*oras|what\s*time|petsa|date|araw|ngayon|today|current\s*time)\b"],
    "identity":   [r"\b(pangalan\s*mo|your\s*name|sino\s*ka|who\s*are\s*you|ikaw\s*ba)\b"],
    "math":       [r"[\d]+\s*[\+\-\*\/\%\^]\s*[\d]+",
                   r"\b(compute|calculate|solve|ilang|magkano|plus|minus|times|divided|sqrt|square\s*root|ugat|porsyento|percent|squared|cubed)\b"],
    "how_to":     [r"\b(paano|how\s*to|how\s*do|steps\s*(to|para)|paraan|tutorial|guide)\b"],
    "definition": [r"\b(ano\s*ang|what\s*is|what\s*are|ibig\s*sabihin|meaning|define|kahulugan|ipaliwanag|explain)\b"],
    "who":        [r"\b(sino\s*(si|ang|ba)|who\s*is|who\s*was|who\s*are)\b"],
    "where":      [r"\b(saan\s*(ang|ba|naroroon)|where\s*is|where\s*are|location\s*of)\b"],
    "why":        [r"\b(bakit|why\s*(is|are|do|does|did)|reason\s*(why|for))\b"],
    "when":       [r"\b(kailan|when\s*(is|was|did|will)|what\s*year|what\s*date)\b"],
    "list":       [r"\b(ilista|list\s*(mo|the|of|lahat)|enumerate|mga\s*(halimbawa|example))\b"],
}

def detect_intent(query):
    q = query.lower()
    for intent, patterns in INTENT_PATTERNS.items():
        for p in patterns:
            if re.search(p, q, re.I):
                return intent
    return "general"

def clean_query(query):
    q = query.lower().strip()
    for pattern in FILLER_WORDS:
        q = re.sub(pattern, " ", q, flags=re.I)
    q = re.sub(r"\s+", " ", q).strip()
    return q if len(q) > 2 else query.lower().strip()

# ── Math Solver ────────────────────────────────────────────
def solve_math(query):
    q = query.strip()

    pct = re.search(r"(\d+\.?\d*)\s*(%|porsyento|percent)\s*(ng|of)?\s*(\d+\.?\d*)", q, re.I)
    if pct:
        p, n = float(pct.group(1)), float(pct.group(4))
        return f"{p}% ng {n} = {(p/100)*n:,}"

    sq = re.search(r"(sqrt|square root|ugat)\s*(ng|of)?\s*(\d+\.?\d*)", q, re.I)
    if sq:
        n = float(sq.group(3))
        return f"√{n} = {_math.sqrt(n)}"

    pw = re.search(r"(\d+\.?\d*)\s*(squared|cubed|sa\s*ika-?\s*(\d+))", q, re.I)
    if pw:
        base = float(pw.group(1))
        exp  = 3 if "cubed" in q.lower() else (int(pw.group(3)) if pw.group(3) else 2)
        return f"{base}^{exp} = {base**exp:,}"

    expr = q.lower()
    for src, dst in [
        (r"(ano|what|magkano|ilang|compute|calculate|solve|=\?|\?)", ""),
        (r"saka|at|plus",    "+"), (r"minus|bawas",    "-"),
        (r"times|x\b",       "*"), (r"divided by|hati", "/"),
        (r"to the power of|\^", "**"),
    ]:
        expr = re.sub(src, dst, expr)
    expr = expr.replace(",", "").strip()

    if not re.match(r"^[\d\s\+\-\*\/\.\(\)\%\*]+$", expr):
        return None
    try:
        result = eval(expr, {"__builtins__": {}}, {})
        if isinstance(result, float) and result == int(result):
            result = int(result)
        return (f"{q.strip()} = {result:,}"
                if isinstance(result, int)
                else f"{q.strip()} = {result}")
    except Exception:
        pass
    return None

# ── Groq AI ────────────────────────────────────────────────
def ask_groq(query, mem, cfg, kb_context="", web_context=""):
    api_key = cfg.get("groq_api_key", "")
    if not api_key or not HAS_REQUESTS:
        return None

    name  = cfg["ai_name"]
    uname = cfg["user_name"]
    context_parts = []

    if kb_context:
        context_parts.append(f"Relevant knowledge:\n{kb_context}")
    if web_context:
        context_parts.append(f"Web search result:\n{web_context}")
    if mem.get("facts"):
        context_parts.append("Recent memory:\n" + "\n".join(mem["facts"][-5:]))

    context = "\n\n".join(context_parts)

    system_prompt = (
        f"Ikaw si {name}, isang matalinong AI assistant na tumutulong kay {uname}. "
        f"Sumasagot ka ng malinaw, tumpak, at kumpletong Tagalog o English depende sa tanong. "
        f"Huwag mag-ulit ng tanong. Direkta sa sagot. Walang limitasyon sa haba ng sagot."
    )
    if context:
        system_prompt += f"\n\nContext:\n{context}"

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": cfg.get("groq_model", "llama-3.1-8b-instant"),
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": query}
                ],
                "max_tokens": 2048,
                "temperature": 0.7
            },
            timeout=30
        )
        data = r.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"].strip()
        if "error" in data:
            return f"[Groq Error: {data['error'].get('message', 'Unknown error')}]"
    except Exception as e:
        return f"[Groq connection error: {e}]"
    return None

# ── Built-in Responses ─────────────────────────────────────
def builtin_response(query, intent, cfg):
    name  = cfg["ai_name"]
    uname = cfg["user_name"]
    now   = datetime.datetime.now()

    if intent == "greeting":
        hour = now.hour
        greet = "Magandang umaga" if hour < 12 else "Magandang hapon" if hour < 18 else "Magandang gabi"
        return f"{greet}, {uname}! Ako si {name}. Paano kita matutulungan?"

    if intent == "thanks":
        return "Walang anuman! Lagi akong nandito para sa iyo. 😊"

    if intent == "farewell":
        return f"Paalam, {uname}! Ingat ka lagi. 👋"

    if intent == "time":
        return f"Ngayon ay {now.strftime('%A, %B %d, %Y')} at {now.strftime('%I:%M %p')}."

    if intent == "identity":
        return (f"Ako si {name}, ang iyong personal na AI assistant! "
                f"Makakatulong ako sa mga tanong, math, paghahanap ng impormasyon, at marami pa.")

    if intent == "math":
        result = solve_math(query)
        if result:
            return f"🧮 {result}"

    return None

# ── Main AI Logic ──────────────────────────────────────────
def process_message(user_input, cfg=None):
    if cfg is None:
        cfg = load_cfg()

    mem  = load_mem()
    hist = load_hist()
    query = user_input.strip()

    if not query:
        return {"response": "Wala kang sinabi. Subukang magtanong!", "source": "system"}

    intent    = detect_intent(query)
    clean_q   = clean_query(query)
    response  = None
    source    = "builtin"

    # 1. Built-in responses (greetings, time, math, etc.)
    response = builtin_response(query, intent, cfg)
    if response:
        source = "builtin"

    # 2. Memory search
    if not response:
        mem_result = mem_search(clean_q, mem)
        if mem_result and len(mem_result) > 10:
            response = mem_result
            source   = "memory"

    # 3. Knowledge base search
    kb_context = ""
    if not response:
        kb_results = kb_search(clean_q)
        if kb_results:
            best = kb_results[0]
            kb_context = f"{best.get('title','')}: {best.get('content','')}"
            response   = best.get("content", "")
            source     = "knowledge_base"

    # 4. Internet search
    web_context = ""
    if (not response or source == "knowledge_base") and cfg.get("internet_search") and HAS_REQUESTS:
        web_result = internet_search(query, cfg)
        if web_result:
            web_context = web_result.get("content", "")
            if not response:
                response = web_context
                source   = f"web:{web_result.get('source','')}"

    # 5. Groq AI (uses all context)
    if cfg.get("use_groq_ai") and cfg.get("groq_api_key"):
        groq_ans = ask_groq(query, mem, cfg, kb_context=kb_context, web_context=web_context)
        if groq_ans and not groq_ans.startswith("[Groq"):
            response = groq_ans
            source   = "groq_ai"
        elif groq_ans and groq_ans.startswith("[Groq"):
            if not response:
                response = groq_ans

    # 6. Fallback
    if not response:
        response = (
            f"Hindi ko pa alam ang sagot sa '{query}'. "
            f"Maaari kang mag-add ng knowledge gamit ang /kb add, "
            f"o i-configure ang Groq API para mas matalino akong sumagot."
        )
        source = "fallback"

    # Save to memory and history
    mem_learn(mem, query, str(response))
    save_mem(mem)

    hist_add(hist, "user", query)
    hist_add(hist, "assistant", str(response))
    save_hist(hist, cfg.get("history_limit", 500))

    return {"response": response, "source": source, "intent": intent}

# ── HTML Template ──────────────────────────────────────────
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="tl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MyAI — Personal Assistant</title>
<style>
  :root {
    --bg: #0f0f13;
    --surface: #17171f;
    --surface2: #1e1e28;
    --border: #2a2a38;
    --accent: #7c6af7;
    --accent2: #a78bfa;
    --text: #e8e8f0;
    --muted: #6b6b80;
    --user-bubble: #1e1b3a;
    --ai-bubble: #1a2035;
    --success: #4ade80;
    --warning: #fbbf24;
    --error: #f87171;
    --radius: 16px;
    --font: 'Segoe UI', system-ui, sans-serif;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    height: 100dvh;
    display: flex;
    flex-direction: column;
  }

  /* Header */
  header {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 14px 20px;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-shrink: 0;
  }
  .logo {
    width: 40px; height: 40px;
    background: linear-gradient(135deg, var(--accent), #38bdf8);
    border-radius: 12px;
    display: flex; align-items: center; justify-content: center;
    font-size: 20px; font-weight: 900; color: white;
    letter-spacing: -1px;
  }
  .header-info h1 { font-size: 1.1rem; font-weight: 700; }
  .header-info p  { font-size: 0.75rem; color: var(--muted); }
  .status-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--success); margin-left: auto;
    box-shadow: 0 0 8px var(--success);
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0.4; }
  }
  .header-actions { display: flex; gap: 8px; }
  .icon-btn {
    background: var(--surface2); border: 1px solid var(--border);
    color: var(--muted); padding: 7px 12px;
    border-radius: 8px; cursor: pointer; font-size: 0.78rem;
    transition: all 0.2s;
  }
  .icon-btn:hover { border-color: var(--accent); color: var(--accent2); }

  /* Chat area */
  #chat {
    flex: 1; overflow-y: auto; padding: 20px;
    display: flex; flex-direction: column; gap: 16px;
    scroll-behavior: smooth;
  }
  #chat::-webkit-scrollbar { width: 4px; }
  #chat::-webkit-scrollbar-track { background: transparent; }
  #chat::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }

  .msg { display: flex; gap: 10px; animation: fadeIn 0.2s ease; }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; } }

  .msg.user { flex-direction: row-reverse; }

  .avatar {
    width: 32px; height: 32px; border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 14px; flex-shrink: 0; margin-top: 2px;
  }
  .msg.user .avatar    { background: linear-gradient(135deg, #3b82f6, #8b5cf6); }
  .msg.ai .avatar      { background: linear-gradient(135deg, var(--accent), #38bdf8); }

  .bubble {
    max-width: 75%; padding: 12px 16px;
    border-radius: var(--radius); line-height: 1.6;
    font-size: 0.92rem;
  }
  .msg.user .bubble {
    background: var(--user-bubble);
    border: 1px solid #3b2d8a;
    border-top-right-radius: 4px;
  }
  .msg.ai .bubble {
    background: var(--ai-bubble);
    border: 1px solid var(--border);
    border-top-left-radius: 4px;
  }
  .bubble .source-tag {
    display: inline-block; font-size: 0.68rem;
    padding: 2px 7px; border-radius: 20px;
    margin-top: 8px; opacity: 0.7;
  }
  .source-groq_ai    { background: #2e1065; color: var(--accent2); }
  .source-knowledge_base { background: #1a3a1a; color: var(--success); }
  .source-memory     { background: #2a1a3a; color: #c4b5fd; }
  .source-web        { background: #1a2a3a; color: #60a5fa; }
  .source-builtin    { background: #2a2a1a; color: var(--warning); }
  .source-fallback   { background: #3a1a1a; color: var(--error); }

  .typing {
    display: flex; gap: 4px; align-items: center;
    padding: 12px 16px;
  }
  .typing span {
    width: 7px; height: 7px; border-radius: 50%;
    background: var(--accent); animation: bounce 0.9s infinite;
  }
  .typing span:nth-child(2) { animation-delay: 0.15s; }
  .typing span:nth-child(3) { animation-delay: 0.30s; }
  @keyframes bounce {
    0%, 60%, 100% { transform: translateY(0); }
    30%           { transform: translateY(-6px); }
  }

  /* Input area */
  .input-area {
    padding: 14px 20px;
    background: var(--surface);
    border-top: 1px solid var(--border);
    flex-shrink: 0;
  }
  .input-row {
    display: flex; gap: 10px; align-items: flex-end;
  }
  #input {
    flex: 1; background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 12px; color: var(--text);
    padding: 12px 16px; font-size: 0.92rem;
    font-family: var(--font); resize: none;
    max-height: 120px; line-height: 1.5;
    transition: border-color 0.2s;
    outline: none;
  }
  #input:focus   { border-color: var(--accent); }
  #input::placeholder { color: var(--muted); }

  #send-btn {
    background: linear-gradient(135deg, var(--accent), #38bdf8);
    border: none; border-radius: 12px; padding: 12px 18px;
    cursor: pointer; color: white; font-size: 1.1rem;
    transition: opacity 0.2s; flex-shrink: 0;
  }
  #send-btn:hover    { opacity: 0.85; }
  #send-btn:disabled { opacity: 0.4; cursor: not-allowed; }

  .quick-btns {
    display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px;
  }
  .quick-btn {
    background: var(--surface2); border: 1px solid var(--border);
    color: var(--muted); padding: 5px 12px;
    border-radius: 20px; cursor: pointer; font-size: 0.78rem;
    transition: all 0.2s;
  }
  .quick-btn:hover { border-color: var(--accent); color: var(--accent2); }

  /* Panels */
  .panel {
    position: fixed; top: 0; right: -420px; width: 400px;
    height: 100%; background: var(--surface);
    border-left: 1px solid var(--border);
    transition: right 0.3s ease; z-index: 100;
    display: flex; flex-direction: column;
    overflow: hidden;
  }
  .panel.open { right: 0; }
  .panel-header {
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center;
    justify-content: space-between; flex-shrink: 0;
  }
  .panel-header h2 { font-size: 1rem; }
  .panel-close {
    background: none; border: none; color: var(--muted);
    cursor: pointer; font-size: 1.2rem;
  }
  .panel-body { flex: 1; overflow-y: auto; padding: 16px; }
  .panel-body::-webkit-scrollbar { width: 4px; }
  .panel-body::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }

  /* KB / Memory items */
  .item-card {
    background: var(--surface2); border: 1px solid var(--border);
    border-radius: 10px; padding: 12px; margin-bottom: 10px;
  }
  .item-card h4 { font-size: 0.88rem; color: var(--accent2); margin-bottom: 4px; }
  .item-card p  { font-size: 0.8rem; color: var(--muted); line-height: 1.5; }
  .item-card .tag {
    display: inline-block; font-size: 0.7rem; padding: 2px 8px;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 20px; margin-top: 6px; margin-right: 4px;
    color: var(--muted);
  }

  /* KB Add form */
  .form-group { margin-bottom: 12px; }
  .form-group label { display: block; font-size: 0.8rem; color: var(--muted); margin-bottom: 5px; }
  .form-group input, .form-group textarea {
    width: 100%; background: var(--surface2);
    border: 1px solid var(--border); border-radius: 8px;
    color: var(--text); padding: 8px 12px; font-size: 0.85rem;
    font-family: var(--font); outline: none;
  }
  .form-group input:focus, .form-group textarea:focus { border-color: var(--accent); }
  .form-group textarea { resize: vertical; min-height: 80px; }
  .btn-primary {
    background: var(--accent); border: none; border-radius: 8px;
    color: white; padding: 9px 18px; cursor: pointer; font-size: 0.85rem;
    width: 100%; transition: opacity 0.2s;
  }
  .btn-primary:hover { opacity: 0.85; }

  /* Settings */
  .setting-row {
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 0; border-bottom: 1px solid var(--border);
  }
  .setting-row label { font-size: 0.85rem; }
  .setting-row input[type=text], .setting-row select {
    background: var(--surface2); border: 1px solid var(--border);
    border-radius: 6px; color: var(--text); padding: 5px 10px;
    font-size: 0.82rem; outline: none; width: 180px;
  }
  .toggle {
    width: 38px; height: 22px; background: var(--border);
    border-radius: 11px; cursor: pointer; position: relative;
    transition: background 0.2s; border: none;
  }
  .toggle.on { background: var(--accent); }
  .toggle::after {
    content: ""; position: absolute; width: 16px; height: 16px;
    background: white; border-radius: 50%; top: 3px; left: 3px;
    transition: left 0.2s;
  }
  .toggle.on::after { left: 19px; }

  /* Overlay */
  .overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.5);
    z-index: 99; display: none;
  }
  .overlay.visible { display: block; }

  /* Welcome message */
  .welcome {
    text-align: center; padding: 40px 20px; color: var(--muted);
  }
  .welcome .big-icon { font-size: 3rem; margin-bottom: 12px; }
  .welcome h2 { font-size: 1.3rem; color: var(--text); margin-bottom: 8px; }
  .welcome p  { font-size: 0.88rem; line-height: 1.6; }

  @media (max-width: 600px) {
    .panel { width: 100%; }
    .bubble { max-width: 90%; }
  }
</style>
</head>
<body>

<!-- Header -->
<header>
  <div class="logo">AZER</div>
  <div class="header-info">
    <h1>AZER AI</h1>
    <p>Personal Assistant v3.0</p>
  </div>
  <div class="status-dot"></div>
  <div class="header-actions">
    <button class="icon-btn" onclick="openPanel('kb-panel')">📚 KB</button>
    <button class="icon-btn" onclick="openPanel('mem-panel')">🧠 Memory</button>
    <button class="icon-btn" onclick="openPanel('hist-panel')">📜 History</button>
    <button class="icon-btn" onclick="openPanel('cfg-panel')">⚙️</button>
  </div>
</header>

<!-- Chat -->
<div id="chat">
  <div class="welcome">
    <div class="big-icon">🤖</div>
    <h2>Kumusta! Ako si AZER-AI.</h2>
    <p>Magtanong ka ng kahit ano — Tagalog o English.<br>
       May knowledge base, memory, internet search, at Groq AI ako.</p>
  </div>
</div>

<!-- Input -->
<div class="input-area">
  <div class="quick-btns">
    <button class="quick-btn" onclick="quickSend('Kumusta ka?')">👋 Kumusta</button>
    <button class="quick-btn" onclick="quickSend('Anong oras na?')">🕐 Oras</button>
    <button class="quick-btn" onclick="quickSend('Ano ang AI?')">💡 AI</button>
    <button class="quick-btn" onclick="quickSend('25% ng 200')">🧮 Math</button>
    <button class="quick-btn" onclick="quickSend('Sino si Rizal?')">📖 History</button>
  </div>
  <div class="input-row">
    <textarea id="input" placeholder="Magtanong ka dito..." rows="1"
      onkeydown="handleKey(event)" oninput="autoResize(this)"></textarea>
    <button id="send-btn" onclick="sendMsg()">➤</button>
  </div>
</div>

<!-- Overlay -->
<div class="overlay" id="overlay" onclick="closeAllPanels()"></div>

<!-- KB Panel -->
<div class="panel" id="kb-panel">
  <div class="panel-header">
    <h2>📚 Knowledge Base</h2>
    <button class="panel-close" onclick="closeAllPanels()">✕</button>
  </div>
  <div class="panel-body">
    <div class="form-group">
      <label>🔍 Maghanap</label>
      <input type="text" id="kb-search" placeholder="Hilahin ang keyword..." oninput="searchKB()">
    </div>
    <hr style="border-color:var(--border);margin:12px 0">
    <details>
      <summary style="cursor:pointer;font-size:0.88rem;color:var(--accent2);margin-bottom:12px">
        ➕ Magdagdag ng Knowledge
      </summary>
      <div style="margin-top:12px">
        <div class="form-group">
          <label>Pamagat</label>
          <input type="text" id="kb-title" placeholder="Halimbawa: Python basics">
        </div>
        <div class="form-group">
          <label>Nilalaman</label>
          <textarea id="kb-content" placeholder="Ilagay ang impormasyon dito..."></textarea>
        </div>
        <div class="form-group">
          <label>Tags (hiwalay ng kuwit)</label>
          <input type="text" id="kb-tags" placeholder="programming, python, coding">
        </div>
        <button class="btn-primary" onclick="addKB()">💾 I-save</button>
      </div>
    </details>
    <hr style="border-color:var(--border);margin:12px 0">
    <div id="kb-list">
      <p style="color:var(--muted);font-size:0.85rem">I-load ang KB...</p>
    </div>
  </div>
</div>

<!-- Memory Panel -->
<div class="panel" id="mem-panel">
  <div class="panel-header">
    <h2>🧠 Memory Bank</h2>
    <button class="panel-close" onclick="closeAllPanels()">✕</button>
  </div>
  <div class="panel-body" id="mem-list">
    <p style="color:var(--muted);font-size:0.85rem">I-load ang memories...</p>
  </div>
</div>

<!-- History Panel -->
<div class="panel" id="hist-panel">
  <div class="panel-header">
    <h2>📜 Chat History</h2>
    <button class="panel-close" onclick="closeAllPanels()">✕</button>
  </div>
  <div class="panel-body" id="hist-list">
    <p style="color:var(--muted);font-size:0.85rem">I-load ang history...</p>
  </div>
</div>

<!-- Config Panel -->
<div class="panel" id="cfg-panel">
  <div class="panel-header">
    <h2>⚙️ Settings</h2>
    <button class="panel-close" onclick="closeAllPanels()">✕</button>
  </div>
  <div class="panel-body" id="cfg-body">
    <p style="color:var(--muted);font-size:0.85rem">I-load ang settings...</p>
  </div>
</div>

<script>
// ── State ────────────────────────────────────────────────
let cfg = {};

// ── Chat ─────────────────────────────────────────────────
function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMsg();
  }
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

function quickSend(text) {
  document.getElementById('input').value = text;
  sendMsg();
}

async function sendMsg() {
  const inp = document.getElementById('input');
  const msg = inp.value.trim();
  if (!msg) return;

  inp.value = '';
  inp.style.height = 'auto';
  document.getElementById('send-btn').disabled = true;

  appendMsg('user', msg);

  // Typing indicator
  const typingId = appendTyping();

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({message: msg})
    });
    const data = await res.json();
    removeTyping(typingId);
    appendMsg('ai', data.response, data.source);
  } catch(e) {
    removeTyping(typingId);
    appendMsg('ai', 'May error sa pagkonekta sa server. Subukan muli.', 'error');
  }

  document.getElementById('send-btn').disabled = false;
}

function appendMsg(role, text, source='') {
  const chat = document.getElementById('chat');

  // Remove welcome if first message
  const welcome = chat.querySelector('.welcome');
  if (welcome) welcome.remove();

  const div = document.createElement('div');
  div.className = `msg ${role === 'user' ? 'user' : 'ai'}`;

  const sourceKey = (source || '').split(':')[0];
  const sourceLbl = {
    'groq_ai': '🤖 AZER AI',
    'knowledge_base': '📚 Knowledge Base',
    'memory': '🧠 Memory',
    'web': '🌐 ' + (source.split(':')[1] || 'Web'),
    'builtin': '⚡ Built-in',
    'fallback': '❓ Fallback'
  }[sourceKey] || '';

  div.innerHTML = `
    <div class="avatar">${role === 'user' ? '👤' : '🤖'}</div>
    <div class="bubble">
      ${escHtml(text).replace(/\\n/g,'<br>')}
      ${sourceLbl ? `<div><span class="source-tag source-${sourceKey}">${sourceLbl}</span></div>` : ''}
    </div>`;

  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function appendTyping() {
  const chat = document.getElementById('chat');
  const id = 'typing-' + Date.now();
  const div = document.createElement('div');
  div.className = 'msg ai'; div.id = id;
  div.innerHTML = `
    <div class="avatar">🤖</div>
    <div class="bubble">
      <div class="typing"><span></span><span></span><span></span></div>
    </div>`;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return id;
}

function removeTyping(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;')
            .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Panels ───────────────────────────────────────────────
function openPanel(id) {
  closeAllPanels();
  document.getElementById(id).classList.add('open');
  document.getElementById('overlay').classList.add('visible');
  if (id === 'kb-panel')   loadKB();
  if (id === 'mem-panel')  loadMemory();
  if (id === 'hist-panel') loadHistory();
  if (id === 'cfg-panel')  loadConfig();
}

function closeAllPanels() {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('open'));
  document.getElementById('overlay').classList.remove('visible');
}

// ── KB ───────────────────────────────────────────────────
async function loadKB(keyword='') {
  const res  = await fetch('/api/kb' + (keyword ? `?q=${encodeURIComponent(keyword)}` : ''));
  const data = await res.json();
  const el   = document.getElementById('kb-list');

  if (!data.entries || !data.entries.length) {
    el.innerHTML = '<p style="color:var(--muted);font-size:0.85rem">Walang entries pa.</p>';
    return;
  }

  el.innerHTML = data.entries.map(e => `
    <div class="item-card">
      <h4>${escHtml(e.title || 'Untitled')}</h4>
      <p>${escHtml((e.content || '').substring(0,200))}${e.content && e.content.length>200 ? '...' : ''}</p>
      ${(e.tags||[]).map(t => `<span class="tag">${escHtml(t)}</span>`).join('')}
      <div style="margin-top:8px">
        <button onclick="deleteKB('${escHtml(e.title||'')}','${e.id||''}')"
          style="background:none;border:1px solid var(--error);color:var(--error);padding:3px 10px;
          border-radius:6px;cursor:pointer;font-size:0.75rem">🗑 Delete</button>
      </div>
    </div>`).join('');
}

async function searchKB() {
  const kw = document.getElementById('kb-search').value;
  await loadKB(kw);
}

async function addKB() {
  const title   = document.getElementById('kb-title').value.trim();
  const content = document.getElementById('kb-content').value.trim();
  const tags    = document.getElementById('kb-tags').value.trim();
  if (!title || !content) { alert('Kailangan ang pamagat at nilalaman!'); return; }

  await fetch('/api/kb', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({title, content, tags})
  });

  document.getElementById('kb-title').value   = '';
  document.getElementById('kb-content').value = '';
  document.getElementById('kb-tags').value    = '';
  loadKB();
}

async function deleteKB(title) {
  if (!confirm(`I-delete ang "${title}"?`)) return;
  await fetch('/api/kb', {
    method: 'DELETE',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({keyword: title})
  });
  loadKB();
}

// ── Memory ───────────────────────────────────────────────
async function loadMemory() {
  const res  = await fetch('/api/memory');
  const data = await res.json();
  const el   = document.getElementById('mem-list');

  let html = '';
  if (data.pinned && data.pinned.length) {
    html += `<p style="color:var(--warning);font-size:0.82rem;margin-bottom:8px">
               📌 PINNED (${data.pinned.length})</p>`;
    html += data.pinned.map(p => `
      <div class="item-card"><p>${escHtml(p)}</p></div>`).join('');
    html += '<hr style="border-color:var(--border);margin:12px 0">';
  }

  if (data.facts && data.facts.length) {
    html += `<p style="color:var(--muted);font-size:0.82rem;margin-bottom:8px">
               🗂 RECENT (${data.facts.length} total)</p>`;
    html += [...data.facts].reverse().slice(0,30).map(f => {
      const parts = f.split(' -> ');
      return `<div class="item-card">
        <h4>${escHtml(parts[0].substring(0,60))}</h4>
        ${parts[1] ? `<p>${escHtml(parts[1].substring(0,120))}${parts[1].length>120?'...':''}</p>` : ''}
      </div>`;
    }).join('');
  }

  if (!html) html = '<p style="color:var(--muted);font-size:0.85rem">Walang memories pa.</p>';
  el.innerHTML = html;
}

// ── History ──────────────────────────────────────────────
async function loadHistory() {
  const res  = await fetch('/api/history');
  const data = await res.json();
  const el   = document.getElementById('hist-list');

  if (!data.history || !data.history.length) {
    el.innerHTML = '<p style="color:var(--muted);font-size:0.85rem">Walang history pa.</p>';
    return;
  }

  el.innerHTML = [...data.history].reverse().slice(0,50).map(h => `
    <div class="item-card">
      <h4 style="color:${h.role==='user'?'#60a5fa':'var(--accent2)'}">${h.role==='user'?'👤 Ikaw':'🤖 AI'}</h4>
      <p>${escHtml((h.message||'').substring(0,150))}${(h.message||'').length>150?'...':''}</p>
      <span style="font-size:0.7rem;color:var(--muted)">${(h.time||'').substring(0,16)}</span>
    </div>`).join('');
}

// ── Config ───────────────────────────────────────────────
async function loadConfig() {
  const res  = await fetch('/api/config');
  cfg        = await res.json();
  const el   = document.getElementById('cfg-body');

  el.innerHTML = `
    <div class="setting-row">
      <label>AI Name</label>
      <input type="text" id="cfg-ai_name" value="${escHtml(cfg.ai_name||'MyAI')}">
    </div>
    <div class="setting-row">
      <label>User Name</label>
      <input type="text" id="cfg-user_name" value="${escHtml(cfg.user_name||'User')}">
    </div>
    <div style="visibility: hidden;" class="setting-row"> 
      <label>API Key</label>
      <input type="text" id="cfg-groq_key" placeholder="gsk_..." value="${escHtml(cfg.groq_api_key||'')}">
    </div>
    <div class="setting-row">
      <label>Model</label>
      <select id="cfg-groq_model">
        ${['llama-3.1-8b-instant','llama3-70b-8192','mixtral-8x7b-32768','gemma2-9b-it'].map(m =>
          `<option value="${m}" ${cfg.groq_model===m?'selected':''}>${m}</option>`
        ).join('')}
      </select>
    </div>
    <div class="setting-row">
      <label>Gamitin ang Online AI</label>
      <button class="toggle ${cfg.use_groq_ai?'on':''}" id="toggle-groq"
        onclick="toggleCfg('use_groq_ai','toggle-groq')"></button>
    </div>
    <div class="setting-row">
      <label>Internet Search</label>
      <button class="toggle ${cfg.internet_search?'on':''}" id="toggle-search"
        onclick="toggleCfg('internet_search','toggle-search')"></button>
    </div>
    <hr style="border-color:var(--border);margin:16px 0">
    <p style="font-size:0.8rem;color:var(--muted);margin-bottom:10px">Search API Keys (optional)</p>
    <div class="form-group">
      <label>Tavily API Key</label>
      <input type="text" id="cfg-tavily" placeholder="tvly-..." value="${escHtml((cfg.search_keys||{}).tavily||'')}">
    </div>
    <div class="form-group">
      <label>Brave API Key</label>
      <input type="text" id="cfg-brave" value="${escHtml((cfg.search_keys||{}).brave||'')}">
    </div>
    <button class="btn-primary" style="margin-top:8px" onclick="saveConfig()">💾 I-save ang Settings</button>
  `;
}

function toggleCfg(key, btnId) {
  cfg[key] = !cfg[key];
  const btn = document.getElementById(btnId);
  btn.classList.toggle('on', cfg[key]);
}

async function saveConfig() {
  const payload = {
    ai_name:       document.getElementById('cfg-ai_name').value,
    user_name:     document.getElementById('cfg-user_name').value,
    groq_api_key:  document.getElementById('cfg-groq_key').value,
    groq_model:    document.getElementById('cfg-groq_model').value,
    use_groq_ai:   cfg.use_groq_ai,
    internet_search: cfg.internet_search,
    search_keys: {
      tavily: document.getElementById('cfg-tavily').value,
      brave:  document.getElementById('cfg-brave').value,
      google_key: (cfg.search_keys||{}).google_key || '',
      google_cx:  (cfg.search_keys||{}).google_cx  || ''
    }
  };
  await fetch('/api/config', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(payload)
  });
  alert('✅ Na-save ang settings!');
  closeAllPanels();
}

// ── Init ─────────────────────────────────────────────────
window.onload = () => {
  document.getElementById('input').focus();
};
</script>
</body>
</html>
"""

# ── Flask Routes ───────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/api/chat", methods=["POST"])
def chat():
    data      = request.get_json()
    user_msg  = (data or {}).get("message", "").strip()
    cfg       = load_cfg()
    result    = process_message(user_msg, cfg)
    return jsonify(result)

@app.route("/api/kb", methods=["GET"])
def kb_get():
    keyword = request.args.get("q", "")
    if keyword:
        entries = kb_search(keyword)
    else:
        entries = kb_list_all()
    total, cats = kb_stats()
    return jsonify({"entries": entries, "total": total, "categories": cats})

@app.route("/api/kb", methods=["POST"])
def kb_post():
    data    = request.get_json()
    title   = (data or {}).get("title", "")
    content = (data or {}).get("content", "")
    tags    = (data or {}).get("tags", "")
    if not title or not content:
        return jsonify({"error": "Title and content required"}), 400
    entry, cat = kb_add(title, content, tags)
    return jsonify({"success": True, "entry": entry, "category": cat})

@app.route("/api/kb", methods=["DELETE"])
def kb_del():
    data    = request.get_json()
    keyword = (data or {}).get("keyword", "")
    deleted = kb_delete(keyword)
    return jsonify({"success": True, "deleted": deleted})

@app.route("/api/memory", methods=["GET"])
def memory_get():
    mem = load_mem()
    return jsonify({
        "facts":      mem.get("facts", [])[-50:],
        "pinned":     mem.get("pinned", []),
        "last_topic": mem.get("last_topic")
    })

@app.route("/api/memory", methods=["DELETE"])
def memory_clear():
    save_mem({"last_topic": None, "facts": [], "pinned": []})
    return jsonify({"success": True})

@app.route("/api/history", methods=["GET"])
def history_get():
    return jsonify({"history": load_hist()})

@app.route("/api/history", methods=["DELETE"])
def history_clear():
    save_hist([])
    return jsonify({"success": True})

@app.route("/api/config", methods=["GET"])
def config_get():
    return jsonify(load_cfg())

@app.route("/api/config", methods=["POST"])
def config_post():
    data = request.get_json()
    cfg  = load_cfg()
    cfg.update(data or {})
    save_cfg(cfg)
    return jsonify({"success": True})

@app.route("/api/status", methods=["GET"])
def status():
    cfg        = load_cfg()
    total, _   = kb_stats()
    mem        = load_mem()
    return jsonify({
        "status":   "online",
        "ai_name":  cfg["ai_name"],
        "kb_total": total,
        "memories": len(mem.get("facts", [])),
        "groq":     bool(cfg.get("groq_api_key")),
        "search":   cfg.get("internet_search", False)
    })

# ── Run ────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  MyAI Web App v3.0 — Running on http://0.0.0.0:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
