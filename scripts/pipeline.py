"""
清洗流水线 CLI（统一语料，不再按题材分 LoRA）。

用法示例（在 noval 目录下执行）：
  python scripts/pipeline.py clean                       # raw/*.txt -> cleaned/<book>/...（增量，跳过已清洗的书）
  python scripts/pipeline.py clean --force                # 连已清洗过的书也重新处理一遍
  python scripts/pipeline.py draft --scope book           # 起草缺 world 的书级 meta
  python scripts/pipeline.py draft --scope chapters       # 起草缺 scene/plot_outline 的章节
  python scripts/pipeline.py draft --scope all            # 两者都做
  python scripts/pipeline.py flags                        # 列出所有自动检测/人工标注的待核查标记
  python scripts/pipeline.py export --out export/train.jsonl

clean 阶段：raw/*.txt -> 编码修复+去广告+规范化 -> 去重（整本书级别，含跟已清洗老书的比较）
            -> 按章切分 -> 写到 cleaned/<book>/0001.md + cleaned/<book>/_book_meta.yaml。
            靠 cleaned/_corpus_index.jsonl 记录哪些书已经处理过，重跑只处理 raw/ 里的新文件，
            不会碰已经清洗好（可能已经人工标注过）的老书，除非加 --force。
            过程中发现的可疑情况（章节数异常少、用了兜底分章规则、疑似重复段落、编码可能
            丢字等）会自动写进 flags 字段；`flags` 子命令能把所有待核查项集中列出来，
            你也可以直接手写 flags（比如"这本书文笔差/机翻感重，先不用"）。
draft 阶段：调用本地大模型（Ollama/vLLM 的 OpenAI 兼容接口）起草 world/style_template/
            banned_terms（书级）和 scene/plot_outline（章节级）。只填空字段，
            不会覆盖已经人工确认过的内容，可以反复重跑、增量处理新书。
export 阶段：合并 书级 meta + 章节 frontmatter，渲染成
            [世界观]/[当前场景]/[语言风格指令]/[剧情骨架] 的 user 提示 + 正文 assistant 回复，
            写成 messages 格式的 jsonl（兼容 LLaMA-Factory / ms-swift / unsloth 等主流微调框架，
            训练时由框架自己套 ChatML 模板，不需要在数据里手写 <|im_start|> 之类的token）。
            默认带 flags 的内容也会导出（只是打印提示），加 --skip-flagged 可以先排除。
"""
import argparse
import json
from pathlib import Path

import yaml

import draft
from cleaning import (
    exact_hash,
    load_ad_patterns,
    minhash_signature,
    normalize_text,
    read_text_auto_encoding,
    remove_ads,
    remove_intra_duplicate_blocks,
    signature_similarity,
    split_chapters,
)

NEAR_DUP_SIMILARITY_THRESHOLD = 0.8

ROOT = Path(__file__).resolve().parent.parent
CONFIGS = ROOT / "configs"
RAW_DIR = ROOT / "raw"
CLEANED_DIR = ROOT / "cleaned"


def resolve_under_root(relative: str) -> Path:
    """把用户传的相对路径钉死在 noval/ 目录下，防止 --out/--manifest 里带 ".."
    之类的写法把文件写到项目目录外面（真的发生过，教训）。"""
    resolved = (ROOT / relative).resolve()
    if ROOT not in resolved.parents and resolved != ROOT:
        raise SystemExit(f"拒绝写到 noval 目录之外：{resolved}")
    return resolved


def _is_near_dup(a: dict, b: dict) -> bool:
    len_ratio = min(a["char_count"], b["char_count"]) / max(a["char_count"], b["char_count"])
    if len_ratio < 0.85:
        return False
    return signature_similarity(a["fp"], b["fp"]) >= NEAR_DUP_SIMILARITY_THRESHOLD


def dedup_books(new_books: list[dict], cached_books: list[dict]) -> tuple[list[dict], list[dict]]:
    """new_books/cached_books 都需要 book/hash/fp/char_count 字段。

    cached_books 是已经清洗定型（可能已经人工标注过）的老书签名，只用来比较，
    永远不会被丢弃或改动——去重只会丢新书，不会因为新加的书"更完整"就反过来
    动老书已经清洗好的产出，避免悄悄销毁人工标注成果。
    返回 (保留的新书, 丢弃的新书)，丢弃项带 reason/duplicate_of(书名) 字段。
    """
    dropped: list[dict] = []
    remaining: list[dict] = []

    for b in new_books:
        dup = next((c for c in cached_books if b["hash"] == c["hash"] or _is_near_dup(b, c)), None)
        if dup:
            reason = "exact_duplicate" if b["hash"] == dup["hash"] else "near_duplicate"
            dropped.append({**b, "reason": reason, "duplicate_of": dup["book"]})
        else:
            remaining.append(b)

    seen_hashes: dict[str, dict] = {}
    for b in remaining:
        if b["hash"] in seen_hashes:
            dropped.append({**b, "reason": "exact_duplicate", "duplicate_of": seen_hashes[b["hash"]]["book"]})
            continue
        seen_hashes[b["hash"]] = b

    uniques = list(seen_hashes.values())
    dropped_books: set[str] = set()
    for i in range(len(uniques)):
        if uniques[i]["book"] in dropped_books:
            continue
        for j in range(i + 1, len(uniques)):
            if uniques[j]["book"] in dropped_books:
                continue
            a, b = uniques[i], uniques[j]
            if _is_near_dup(a, b):
                shorter = a if a["char_count"] <= b["char_count"] else b
                longer = b if shorter is a else a
                dropped_books.add(shorter["book"])
                dropped.append({**shorter, "reason": "near_duplicate", "duplicate_of": longer["book"]})

    kept = [b for b in uniques if b["book"] not in dropped_books]
    return kept, dropped


def load_corpus_index() -> dict[str, dict]:
    index_path = CLEANED_DIR / "_corpus_index.jsonl"
    index: dict[str, dict] = {}
    if index_path.exists():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                index[rec["book"]] = rec
    return index


def save_corpus_index(index: dict[str, dict]):
    index_path = CLEANED_DIR / "_corpus_index.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as f:
        for rec in index.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def write_book_meta_stub(book_dir: Path, book: str, tags: list[str], synopsis: str, source_file: str, flags: list[str]):
    meta_path = book_dir / "_book_meta.yaml"
    if meta_path.exists():
        return  # 已经存在（可能已被人工/draft 填过），不覆盖
    meta = {
        "book": book,
        "source_file": source_file,
        "tags": tags,
        "synopsis": synopsis,  # 站点导出时自带的文案/简介，起草 world 用的参考材料，不算正文
        "world": "",
        "style_template": [],
        "banned_terms": [],
        # 自动检测出的可疑情况 + 你自己想标注的("这本书文笔差/机翻感重"之类都可以手写加进来)，
        # 用 `python pipeline.py flags` 能看到所有非空 flags 的书/章节，方便集中人工核查。
        "flags": flags,
    }
    book_dir.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8")


def write_chapter_md(out_dir: Path, index: int, title: str, body: str, meta: dict, flags: list[str]):
    out_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        # 新增的标注字段，初始为空，等待 draft 或人工填充
        "world": "",  # 世界观（书级，从 _book_meta.yaml 继承，但这里也保留便于单独使用）
        "scene": "",  # 当前场景，一句话
        "emotion": "",  # 情感基调
        "plot": "",  # 本章核心剧情，一句话
        "style": "",  # 写作风格指令
        "characters": [],  # 人物状态列表
        "pov": "",  # 视角
        "word_count": None,  # 目标字数（可选）
        "style_overrides": [],  # 保留用于特殊情况
    }
    content = "---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False) + "---\n\n" + body + "\n"
    (out_dir / f"{index:04d}.md").write_text(content, encoding="utf-8")

def migrate_chapter_meta(chap_meta: dict) -> dict:
    """将旧的 plot_outline 格式迁移到新的 plot 格式"""
    if "plot_outline" in chap_meta and "plot" not in chap_meta:
        chap_meta["plot"] = chap_meta.pop("plot_outline")
    # 确保所有新字段都存在
    for field, default in [
        ("emotion", ""),
        ("style", ""),
        ("characters", []),
        ("pov", ""),
        ("word_count", None),
        ("world", ""),
    ]:
        if field not in chap_meta:
            chap_meta[field] = default
    return chap_meta

def read_md(path: Path) -> tuple[dict, str]:
    raw = path.read_text(encoding="utf-8")
    _, fm_text, body = raw.split("---", 2)
    meta = yaml.safe_load(fm_text)
    meta = migrate_chapter_meta(meta)
    return meta, body.strip("\n")


def write_md(path: Path, meta: dict, body: str):
    content = "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n\n" + body + "\n"
    path.write_text(content, encoding="utf-8")


def cmd_clean(args):
    ad_patterns = load_ad_patterns(CONFIGS / "ad_patterns.txt")
    tag_patterns = draft.load_tag_line_patterns(CONFIGS)

    if not RAW_DIR.exists():
        raise SystemExit(f"找不到 {RAW_DIR}")

    index = load_corpus_index()
    all_raw = sorted(RAW_DIR.glob("*.txt"))

    new_books = []
    skipped = 0
    for txt_path in all_raw:
        book_name, _author = draft.parse_filename(txt_path.stem)
        # 已经处理过的书（不管当时是清洗成功还是判定为重复丢弃）默认跳过，
        # 不重新读取/解码/去重比较——大规模语料下这是省时间的关键。
        # 想强制重新清洗某本书：加 --force，或者手动删掉它在 index 里的记录/cleaned/ 目录。
        if not args.force and book_name in index:
            skipped += 1
            continue

        raw_text = read_text_auto_encoding(txt_path)
        book_flags = []
        if "�" in raw_text:
            book_flags.append("编码解析可能丢字（正文里出现了 U+FFFD 替换字符），建议人工确认原始文件编码")
        tags = draft.extract_tags(raw_text, tag_patterns)
        text = normalize_text(raw_text)
        text = remove_ads(text, ad_patterns)
        text = normalize_text(text)
        new_books.append(
            {
                "book": book_name,
                "path": txt_path,
                "text": text,
                "tags": tags,
                "flags": book_flags,
                "hash": exact_hash(text),
                "fp": minhash_signature(text),
                "char_count": len(text),
            }
        )

    print(f"raw/ 共 {len(all_raw)} 个文件，跳过已处理 {skipped} 个，本次新处理 {len(new_books)} 个")
    if not new_books:
        print("没有需要新处理的书（都已经清洗过；想强制重新跑就加 --force）")
        return

    cached_books = [rec for rec in index.values() if rec.get("status") == "cleaned"]
    kept, dropped = dedup_books(new_books, cached_books)
    print(f"新书内部+跟已清洗老书去重后，保留 {len(kept)} 本，丢弃 {len(dropped)} 本（重复）")

    if dropped:
        log_path = CLEANED_DIR / "_dedup_log.csv"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            for d in dropped:
                f.write(f"{d['book']},{d['reason']},{d['duplicate_of']}\n")
        print(f"去重明细已追加到 {log_path}")
        for d in dropped:
            index[d["book"]] = {
                "book": d["book"],
                "status": "duplicate",
                "duplicate_of": d["duplicate_of"],
                "source_file": str(d["path"].relative_to(ROOT)),
            }

    total_chapters = 0
    intra_dedup_log: list[str] = []
    for b in kept:
        book_dir = CLEANED_DIR / b["book"]
        source_file = str(b["path"].relative_to(ROOT))

        synopsis, chapters, used_fallback = split_chapters(b["text"])
        book_flags = list(b["flags"])
        if len(chapters) <= 1:
            book_flags.append("只切出了 1 章，章节标题格式大概率没识别，建议人工检查/补充 CHAPTER_RE 规则")
        if used_fallback:
            book_flags.append("没找到\"第X章\"格式，用的是纯数字兜底规则切的章节，建议抽查分章是否准确")
        write_book_meta_stub(book_dir, b["book"], b["tags"], synopsis, source_file, book_flags)

        meta = {"book": b["book"], "source_file": source_file}
        for idx, (title, body) in enumerate(chapters, start=1):
            cleaned_body, previews = remove_intra_duplicate_blocks(body)
            chapter_flags = []
            if previews:
                chapter_flags.append("检测到疑似重复段落并自动删除，建议核实没有误删")
            for p in previews:
                intra_dedup_log.append(f"{b['book']} / {title}: {p}")
            write_chapter_md(book_dir, idx, title, cleaned_body, meta, chapter_flags)
        total_chapters += len(chapters)
        print(f"  {b['book']}: {len(chapters)} 章 -> {book_dir}")

        index[b["book"]] = {
            "book": b["book"],
            "status": "cleaned",
            "source_file": source_file,
            "char_count": b["char_count"],
            "hash": b["hash"],
            "fp": b["fp"],
        }

    save_corpus_index(index)

    if intra_dedup_log:
        log_path = CLEANED_DIR / "_intra_dedup_log.txt"
        with open(log_path, "a", encoding="utf-8") as f:
            for line in intra_dedup_log:
                f.write(line + "\n")
        print(f"发现 {len(intra_dedup_log)} 处章节内重复段落，已删除后一次出现，明细见 {log_path}")

    print(f"完成，共写出 {total_chapters} 章 .md 文件到 {CLEANED_DIR}")


def cmd_draft(args):
    if not CLEANED_DIR.exists():
        raise SystemExit(f"找不到 {CLEANED_DIR}，先跑 clean")

    book_dirs = [CLEANED_DIR / args.book] if args.book else [d for d in CLEANED_DIR.iterdir() if d.is_dir()]

    for book_dir in book_dirs:
        meta_path = book_dir / "_book_meta.yaml"
        if not meta_path.exists():
            continue
        meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
        chapter_paths = sorted(book_dir.glob("*.md"))

        # 书级起草（保持不变）
        if args.scope in ("book", "all") and not meta.get("world"):
            sample_body = meta.get("synopsis") or ""
            if not sample_body and chapter_paths:
                _, sample_body = read_md(chapter_paths[0])
            if not sample_body:
                print(f"[book] {book_dir.name}: 没有简介也没有章节，跳过")
            else:
                try:
                    result = draft.draft_book_meta(
                        args.llm_base_url, args.llm_model, meta["book"], meta.get("tags", []), sample_body
                    )
                    meta["world"] = result.get("world", "")
                    meta["style_template"] = result.get("style_template", [])
                    meta["banned_terms"] = result.get("banned_terms", [])
                    meta_path.write_text(yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8")
                    print(f"[book] {book_dir.name}: 起草完成，world={meta['world']!r}")
                except Exception as e:
                    print(f"[book] {book_dir.name}: 起草失败 - {e}")

        # 章节级起草（修改部分）
        if args.scope in ("chapters", "all"):
            world = meta.get("world", "")
            for md_path in chapter_paths:
                chap_meta, body = read_md(md_path)
                # 检查是否有新字段需要起草
                needs_draft = not all([
                    chap_meta.get("scene"),
                    chap_meta.get("emotion"),
                    chap_meta.get("plot"),
                    chap_meta.get("style"),
                    chap_meta.get("characters"),
                ])
                if not needs_draft:
                    continue
                try:
                    result = draft.draft_chapter(
                        args.llm_base_url, args.llm_model, world, chap_meta.get("chapter_title", ""), body
                    )
                    # 只填充空字段
                    chap_meta["scene"] = chap_meta.get("scene") or result.get("scene", "")
                    chap_meta["emotion"] = chap_meta.get("emotion") or result.get("emotion", "")
                    chap_meta["plot"] = chap_meta.get("plot") or result.get("plot", "")
                    chap_meta["style"] = chap_meta.get("style") or result.get("style", "")
                    chap_meta["characters"] = chap_meta.get("characters") or result.get("characters", [])
                    chap_meta["pov"] = chap_meta.get("pov") or result.get("pov", "")
                    if chap_meta.get("word_count") is None:
                        chap_meta["word_count"] = result.get("word_count")
                    write_md(md_path, chap_meta, body)
                    print(f"  {md_path.relative_to(ROOT)}: 起草完成")
                except Exception as e:
                    print(f"  {md_path.relative_to(ROOT)}: 起草失败 - {e}")
def cmd_flags(args):
    """把所有非空 flags（自动检测出的 + 你手动写进 yaml/md 里的）列出来，
    方便集中做人工核查，而不用一本本翻。"""
    if not CLEANED_DIR.exists():
        raise SystemExit(f"找不到 {CLEANED_DIR}，先跑 clean")

    found = 0
    for book_dir in sorted(d for d in CLEANED_DIR.iterdir() if d.is_dir()):
        meta_path = book_dir / "_book_meta.yaml"
        if not meta_path.exists():
            continue
        meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
        for flag in meta.get("flags", []) or []:
            print(f"[book] {book_dir.name}: {flag}")
            found += 1
        for md_path in sorted(book_dir.glob("*.md")):
            chap_meta, _body = read_md(md_path)
            for flag in chap_meta.get("flags", []) or []:
                print(f"[chapter] {md_path.relative_to(ROOT)}: {flag}")
                found += 1

    print(f"共 {found} 条待核查标记" if found else "没有发现任何标记，暂时不用特别核查")


def merge_style(base: list[dict], overrides: list[dict]) -> list[dict]:
    merged = {item["role"]: item["instruction"] for item in base}
    for item in overrides:
        merged[item["role"]] = item["instruction"]
    return [{"role": r, "instruction": i} for r, i in merged.items()]


def render_user_block(book_meta: dict, chap_meta: dict) -> str:
    """根据新的标注格式渲染 user prompt"""
    lines = []
    
    # 世界观
    world = chap_meta.get("world") or book_meta.get("world", "")
    if world:
        lines.append(f"[世界观] {world}")
    
    # 当前场景
    scene = chap_meta.get("scene", "")
    if scene:
        lines.append(f"[当前场景] {scene}")
    
    # 情感基调
    emotion = chap_meta.get("emotion", "")
    if emotion:
        lines.append(f"[情感基调] {emotion}")
    
    # 剧情要点
    plot = chap_meta.get("plot", "")
    if plot:
        lines.append(f"[剧情要点] {plot}")
    
    # 写作风格
    style = chap_meta.get("style", "")
    if style:
        lines.append(f"[写作风格] {style}")
    
    # 人物状态
    characters = chap_meta.get("characters", [])
    if characters:
        lines.append("[人物状态]")
        for char in characters:
            char_info = f"- {char.get('name', '')}"
            if char.get('role'):
                char_info += f"（{char['role']}）"
            if char.get('state'):
                char_info += f"：{char['state']}"
            if char.get('speech'):
                char_info += f"；说话风格：{char['speech']}"
            lines.append(char_info)
    
    # 视角
    pov = chap_meta.get("pov", "")
    if pov:
        lines.append(f"[视角] {pov}")
    
    return "\n".join(lines)


def cmd_export(args):
    if not CLEANED_DIR.exists():
        raise SystemExit(f"找不到 {CLEANED_DIR}，先跑 clean")

    out_path = resolve_under_root(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    incomplete = 0
    flagged_included = 0
    flagged_skipped = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for book_dir in sorted(d for d in CLEANED_DIR.iterdir() if d.is_dir()):
            meta_path = book_dir / "_book_meta.yaml"
            if not meta_path.exists():
                continue
            book_meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
            book_flagged = bool(book_meta.get("flags"))
            if book_flagged and args.skip_flagged:
                flagged_skipped += len(list(book_dir.glob("*.md")))
                continue

            for md_path in sorted(book_dir.glob("*.md")):
                chap_meta, body = read_md(md_path)
                chapter_flagged = book_flagged or bool(chap_meta.get("flags"))
                if chapter_flagged and args.skip_flagged:
                    flagged_skipped += 1
                    continue
                if chapter_flagged:
                    flagged_included += 1

                # 检查必需字段是否完整
                required_fields = ["scene", "emotion", "plot", "characters"]
                missing_fields = [field for field in required_fields if not chap_meta.get(field)]
                if missing_fields:
                    incomplete += 1
                
                user_block = render_user_block(book_meta, chap_meta)
                record = {
                    "messages": [
                        {"role": "user", "content": user_block},
                        {"role": "assistant", "content": body},
                    ],
                    "book": book_meta.get("book"),
                    "chapter_index": chap_meta.get("chapter_index"),
                    "chapter_title": chap_meta.get("chapter_title"),
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                total += 1

    print(f"导出 {total} 条到 {out_path}")
    if incomplete:
        print(f"注意：其中 {incomplete} 条还缺少必需字段，建议先跑 draft 或人工补全")
    if flagged_included:
        print(f"注意：其中 {flagged_included} 条带有 flags 标记但仍被导出了（用 --skip-flagged 可以排除）")
    if flagged_skipped:
        print(f"已跳过 {flagged_skipped} 条带 flags 标记的内容（--skip-flagged）")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_clean = sub.add_parser("clean")
    p_clean.add_argument(
        "--force", action="store_true", help="连已经在 cleaned/_corpus_index.jsonl 里登记过的书也重新清洗"
    )
    p_clean.set_defaults(func=cmd_clean)

    p_draft = sub.add_parser("draft")
    p_draft.add_argument("--scope", choices=["book", "chapters", "all"], default="all")
    p_draft.add_argument("--book", default=None, help="只处理 cleaned/ 下的某一本书")
    p_draft.add_argument("--llm-base-url", default="http://localhost:11434/v1")
    p_draft.add_argument("--llm-model", default="qwen3:8b")
    p_draft.set_defaults(func=cmd_draft)

    p_export = sub.add_parser("export")
    p_export.add_argument("--out", default="export/train.jsonl")
    p_export.add_argument("--skip-flagged", action="store_true", help="跳过带 flags 标记（自动检测/人工标注）的书和章节")
    p_export.set_defaults(func=cmd_export)

    p_flags = sub.add_parser("flags")
    p_flags.set_defaults(func=cmd_flags)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
