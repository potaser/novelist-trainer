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


def call_local_llm(base_url: str, model: str, system_prompt: str, user_prompt: str, 
                   timeout: int = 300, api_key: str = None) -> dict:
    """调用 OpenAI 兼容的 API（支持本地和远程）"""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    
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
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    content = result["choices"][0]["message"]["content"]
    return json.loads(strip_code_fence(content))

BOOK_META_SYSTEM_PROMPT = """你是专业的网络小说编辑，擅长分析耽美小说的整体设定。

根据书名、标签和正文节选，请起草这本书的：

1. **world**：一句话世界观设定（必须包含以下要素）
   - 时代背景（现代/古代/未来等）
   - 特殊设定（如ABO、娱乐圈、商战等）
   - 整体氛围（甜宠/虐心/轻松等）
   示例："现代都市，娱乐圈背景，轻松甜宠"

2. **style_template**：这本书的整体写作风格特点
   - 叙事风格（如"细腻心理描写"、"快节奏对话"等）
   - 语言特点（如"轻松幽默"、"文艺唯美"等）

3. **banned_terms**：这个世界观下不该出现的词汇（如果有）

**输出格式（严格 JSON）：**
{{"world": "...", "style_template": [...], "banned_terms": [...]}}
"""

CHAPTER_DRAFT_SYSTEM_PROMPT_TMPL = """你是专业的网络小说编辑，擅长分析耽美小说的情节和人物关系。

已知这本书的世界观：{world}

请仔细阅读以下章节内容，然后进行详细标注。

**标注要求：**

1. **scene**：一句话描述本章主要场景（时间、地点、主要事件）

2. **emotion**：本章的情感基调（如"暧昧、试探"、"虐心、误会"、"甜蜜温馨"等）

3. **plot**：本章核心剧情，用一句话概括（不超过50字）

4. **style**：本章的写作风格特点（如"心理描写细腻"、"对话节奏快"、"场景渲染丰富"等）

5. **characters**：列出本章出现的**所有有台词或重要动作的角色**（不仅限于主角）
   - **name**：角色名称
   - **role**：角色定位（攻/受/配角/炮灰等）
   - **state**：该角色在本章中的状态（情绪、目的、行为倾向）
   - **speech**：该角色的说话风格特点
   - **importance**：重要性（main/supporting/minor）
   - **function**：如果是不重要角色，一句话说明其在剧情中的作用（如"推动误会加深"、"提供关键信息"）

6. **pov**：本章的视角人物（如果有明确视角）

7. **word_count**：本章大致字数（可以为 null）

**特别注意：**
- 不要混淆角色，仔细区分每个人物
- 即使是不重要的配角也要列出，说明其作用
- 准确理解人物关系和事件因果关系
- 所有字符串使用双引号，避免使用特殊字符

**输出格式（严格 JSON）：**
{{"scene": "...", "emotion": "...", "plot": "...", "style": "...", "characters": [{{"name": "...", "role": "...", "state": "...", "speech": "...", "importance": "...", "function": "..."}}], "pov": "...", "word_count": null}}
"""


def draft_book_meta(base_url: str, model: str, title: str, tags: list[str], 
                    sample_text: str, api_key: str = None) -> dict:
    user_prompt = f"书名：{title}\n标签：{'、'.join(tags) if tags else '（无）'}\n正文节选：\n{sample_text[:3000]}"
    return call_local_llm(base_url, model, BOOK_META_SYSTEM_PROMPT, user_prompt, api_key=api_key)

def draft_chapter(base_url: str, model: str, world: str, chapter_title: str, 
                  chapter_body: str, api_key: str = None) -> dict:
    system_prompt = CHAPTER_DRAFT_SYSTEM_PROMPT_TMPL.format(world=world or "（未知，请从正文推断）")
    user_prompt = f"章节标题：{chapter_title}\n正文：\n{chapter_body[:4000]}"
    return call_local_llm(base_url, model, system_prompt, user_prompt, api_key=api_key)