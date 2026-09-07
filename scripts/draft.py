"""本地大模型辅助起草：书级 world/style_template/banned_terms，章节级详细标注。

只产出草稿，不覆盖已经非空的字段——人工填过/改过的内容重跑 draft 不会被冲掉。
"""
import json
import re
import urllib.request
from pathlib import Path

FILENAME_PATTERNS = [
    re.compile(r"^(?P<title>.+?)[-_](?P<author>[^-_]{1,20})$"),
    re.compile(r"^(?P<title>.+?)[（(](?P<author>[^)）]{1,20})[)）]$"),
]


def parse_filename(stem: str) -> tuple[str, str | None]:
    for pat in FILENAME_PATTERNS:
        m = pat.match(stem)
        if m:
            return m.group("title").strip(), m.group("author").strip()
    return stem.strip(), None


def load_tag_line_patterns(configs_dir: Path) -> list[re.Pattern]:
    patterns = []
    for line in (configs_dir / "tag_line_patterns.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(re.compile(line))
    return patterns


def extract_tags(text: str, patterns: list[re.Pattern], head_lines: int = 30) -> list[str]:
    tags: list[str] = []
    for line in text.split("\n")[:head_lines]:
        for p in patterns:
            m = p.match(line)
            if m:
                tag_str = m.group(2)
                tags.extend(t for t in re.split(r"[，,、/\s]+", tag_str) if t)
    return tags


def strip_code_fence(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\n", "", content)
        content = re.sub(r"\n```$", "", content)
    return content.strip()


def call_local_llm(base_url: str, model: str, system_prompt: str, user_prompt: str, timeout: int = 300) -> dict:
    """调用 OpenAI 兼容的 /chat/completions（Ollama / vLLM 本地服务通用）。"""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    content = result["choices"][0]["message"]["content"]
    return json.loads(strip_code_fence(content))


BOOK_META_SYSTEM_PROMPT = """你是网络小说数据标注助手。根据书名、标签和正文节选，起草这本书的：
1. world：一句话世界观设定（例如"古代架空，主角是现代穿越者"、"快穿，星际ABO背景"）
2. style_template：数组，每项 {"role": 角色/旁白类别, "instruction": 这类角色的说话/叙事风格要点}，
   至少包含"旁白"和主角对话；如果能看出有明显不同说话方式的配角群体（比如"系统提示"、
   "皇帝及大臣"），也列出来
3. banned_terms：如果这本书的世界观里有明显不该出现的词汇（比如古代背景不该出现"手机"），
   列出来；没有就空数组

严格输出 JSON，不要输出多余文字，格式：
{"world": "...", "style_template": [{"role": "...", "instruction": "..."}], "banned_terms": ["..."]}
"""

CHAPTER_DRAFT_SYSTEM_PROMPT_TMPL = """你是网络小说数据标注助手。已知这本书的世界观是：{world}

根据这一章的正文，起草详细标注：
1. scene：一两句话描述这一章"当前场景"（谁在哪里做什么）
2. emotion：这一章的情感基调（如"暧昧、试探"、"虐心、误会"等）
3. plot：这一章的核心剧情，一句话概括
4. style：这一章的写作风格指令（如"心理描写细腻，对话含蓄，节奏舒缓"）
5. characters：数组，每个角色包含 name/role/state/speech 四个字段
   - name：角色名
   - role：攻/受/配角等
   - state：当前章节下该角色的状态（情绪、心态、行为倾向）
   - speech：该角色的说话风格
6. pov：这一章的视角人物（如果有明确视角）
7. word_count：这一章的大致字数（可选）

严格输出 JSON，不要输出多余文字，格式：
{{"scene": "...", "emotion": "...", "plot": "...", "style": "...", "characters": [{{"name": "...", "role": "...", "state": "...", "speech": "..."}}], "pov": "...", "word_count": null}}
"""


def draft_book_meta(base_url: str, model: str, title: str, tags: list[str], sample_text: str) -> dict:
    user_prompt = f"书名：{title}\n标签：{'、'.join(tags) if tags else '（无）'}\n正文节选：\n{sample_text[:3000]}"
    return call_local_llm(base_url, model, BOOK_META_SYSTEM_PROMPT, user_prompt)


def draft_chapter(base_url: str, model: str, world: str, chapter_title: str, chapter_body: str) -> dict:
    system_prompt = CHAPTER_DRAFT_SYSTEM_PROMPT_TMPL.format(world=world or "（未知，请从正文推断）")
    user_prompt = f"章节标题：{chapter_title}\n正文：\n{chapter_body[:5000]}"
    return call_local_llm(base_url, model, system_prompt, user_prompt)