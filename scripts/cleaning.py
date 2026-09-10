"""编码/去广告/规范化/去重/分章 的核心函数，供 pipeline.py 调用。"""
import hashlib
import random
import re
from difflib import SequenceMatcher
from pathlib import Path

try:
    import chardet
except ImportError:
    chardet = None

FALLBACK_ENCODINGS = ["utf-8", "gb18030", "big5", "utf-16"]

ZERO_WIDTH_RE = re.compile(r"[﻿​‌‍]")
BLANK_LINES_RE = re.compile(r"\n{3,}")
TRAILING_WS_RE = re.compile(r"[ \t]+\n")

CHAPTER_RE = re.compile(
    r"^[\s☆★●○◆♦•·\-—、.]{0,8}("
    r"第\s*[0-9〇零一二三四五六七八九十百千两萬万]+\s*[章节回卷集].{0,40}"  # 原有：第X章
    r"|Chapter\s*\d+.*"  # 新增：Chapter3
    r"|CHAPTER\s*\d+.*"  # 新增：CHAPTER3
    r")\s*$")
# 兜底：少数站点导出的文件不用"第X章"，整章标题就是一行纯数字（比如"01"）。
# 只有当整本书一次 CHAPTER_RE 都没匹配到时才会用这个，避免把正文里偶尔出现的
# 孤立数字行（页码之类）误判成章节标题。
FALLBACK_CHAPTER_RE = re.compile(r"^\s*(\d{1,4})\s*$")


def read_text_auto_encoding(path: Path) -> str:
    raw = path.read_bytes()
    if chardet is not None:
        detected = chardet.detect(raw)
        guess, confidence = detected["encoding"], detected["confidence"]
        # 低置信度的猜测比瞎猜好不了多少（比如把中文小说猜成 koi8-u），
        # 不如直接走下面按优先级试解码的 fallback 列表。
        if guess and confidence >= 0.7:
            try:
                return raw.decode(guess)
            except (UnicodeDecodeError, LookupError):
                pass
    for enc in FALLBACK_ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def load_ad_patterns(path: Path) -> list[re.Pattern]:
    patterns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(re.compile(line))
    return patterns


def remove_ads(text: str, patterns: list[re.Pattern]) -> str:
    kept_lines = []
    for line in text.split("\n"):
        if any(p.match(line) for p in patterns):
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines)


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = ZERO_WIDTH_RE.sub("", text)
    text = TRAILING_WS_RE.sub("\n", text)
    text = BLANK_LINES_RE.sub("\n\n", text)
    return text.strip("\n")


def split_chapters(text: str) -> tuple[str, list[tuple[str, str]], bool]:
    """按 “第X章” 一类的标题行切分。返回 (synopsis, [(标题, 正文), ...], used_fallback)。

    第一个章节标题之前的内容通常是站点导出时带的"文案/简介/标签/编辑推荐"，
    不是正文，所以单独作为 synopsis 返回，不当成一章——这类内容本来就该用来
    帮书级 world/tags 起草，而不是被当成"正文"喂给模型学怎么写故事。
    如果整本书一次 CHAPTER_RE 都没匹配到（比如只用"01""02"这种纯数字做章节标题），
    改用 FALLBACK_CHAPTER_RE 再切一遍——used_fallback 告诉调用方这本书用的是
    兜底规则，值得标一下建议人工抽查（纯数字标题误判的风险比"第X章"更高）。
    """
    lines = text.split("\n")
    used_fallback = not any(CHAPTER_RE.match(line) for line in lines)
    pattern = FALLBACK_CHAPTER_RE if used_fallback else CHAPTER_RE

    chapters: list[tuple[str, str]] = []
    synopsis = ""
    current_title = None
    current_body: list[str] = []

    def flush():
        nonlocal synopsis
        body = "\n".join(current_body).strip("\n")
        if current_title is not None:
            if body:
                chapters.append((current_title, body))
        elif body:
            synopsis = body

    for line in lines:
        m = pattern.match(line)
        if m:
            flush()
            current_title = m.group(1).strip()
            current_body = []
        else:
            current_body.append(line)
    flush()
    return synopsis, chapters, used_fallback


def remove_intra_duplicate_blocks(
    body: str, window: int = 4, min_span_chars: int = 120, line_similarity: float = 0.6
) -> tuple[str, list[str]]:
    """有些站点导出的正文里，整段内容被原样/略微改写地粘贴了两遍（实测过，见
    _clean_run 里的案例）。这里在同一章内找"连续 N 行几乎和前面某处一样"的片段，
    删掉后一次出现，保留第一次。返回 (处理后的正文, 被删片段预览列表)。

    只在窗口内至少 `window` 行都命中（相同或高相似度）、且删除片段总长度
    达到 min_span_chars 时才动手，避免把"顾远。\\n顾远……"这类作者故意重复的
    短句式误删。
    """
    lines = body.split("\n")
    n = len(lines)
    norm = [l.strip() for l in lines]

    def window_key(i: int) -> str | None:
        chunk = norm[i : i + window]
        if any(len(x) < 2 for x in chunk):
            return None
        return "".join(chunk)

    seen: dict[str, int] = {}
    to_remove = [False] * n
    previews: list[str] = []

    i = 0
    while i <= n - window:
        if to_remove[i]:
            i += 1
            continue
        key = window_key(i)
        if key is None:
            i += 1
            continue
        if key not in seen:
            seen[key] = i
            i += 1
            continue

        earlier_start = seen[key]
        later_start = i
        la, lb = later_start, earlier_start
        miss_streak = 0
        while la < n and lb < later_start:
            same = norm[la] == norm[lb] or (
                norm[la] and norm[lb] and SequenceMatcher(None, norm[la], norm[lb]).ratio() >= line_similarity
            )
            if same:
                miss_streak = 0
            else:
                miss_streak += 1
                if miss_streak >= 3:
                    break
            la += 1
            lb += 1
        span_end = la - miss_streak
        span_text = "\n".join(lines[later_start:span_end])

        if len(span_text) >= min_span_chars:
            for k in range(later_start, span_end):
                to_remove[k] = True
            previews.append(span_text[:80].replace("\n", " "))
            i = span_end
        else:
            i += 1

    kept_lines = [line for idx, line in enumerate(lines) if not to_remove[idx]]
    return "\n".join(kept_lines), previews


# 固定种子：同一份文本每次算出来的签名必须一致，去重结果才可复现。
_MINHASH_SALTS = [random.Random(42).getrandbits(64) for _ in range(64)]
_MASK64 = (1 << 64) - 1


def minhash_signature(text: str, shingle_size: int = 12, stride: int = 3) -> list[int]:
    """整本书级别的近似去重签名。用 12 字字符片段（而不是逐字 4-gram 频次加权）
    是因为之前试过 4-gram + 频次加权的 simhash，在几十万字的长文本上会被高频虚词/
    标点"洗平"，导致完全不相关的两本书被判成近似重复（实测过，误判过一次）。
    这里改成"去重后的片段集合 + MinHash 估计 Jaccard 相似度"，长文档上更稳。
    """
    if len(text) < shingle_size:
        shingles = {text} if text else set()
    else:
        shingles = {text[i : i + shingle_size] for i in range(0, len(text) - shingle_size + 1, stride)}
    if not shingles:
        shingles = {""}
    hashes = [int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "big") for s in shingles]
    return [min((h ^ salt) & _MASK64 for h in hashes) for salt in _MINHASH_SALTS]


def signature_similarity(a: list[int], b: list[int]) -> float:
    return sum(1 for x, y in zip(a, b) if x == y) / len(a)


def exact_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()
