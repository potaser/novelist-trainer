"""章节去重脚本：逐本书检查，用首段定位候选，再计算全文相似度"""
import hashlib
import re
from pathlib import Path
from collections import defaultdict
import yaml

def read_chapter_body(md_path: Path) -> tuple:
    """读取章节的 frontmatter 和正文"""
    raw = md_path.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return None, ""
    
    try:
        meta = yaml.safe_load(parts[1])
    except:
        meta = {}
    
    body = parts[2].strip()
    return meta, body

def split_paragraphs(text: str) -> list:
    """将正文按段落分割"""
    paragraphs = re.split(r'\n\s*\n', text)
    paragraphs = [p.strip() for p in paragraphs if p.strip() and len(p.strip()) >= 20]
    return paragraphs

def get_first_paragraph(text: str) -> str:
    """获取正文的第一个有效段落"""
    paragraphs = split_paragraphs(text)
    if paragraphs:
        return paragraphs[0]
    return text[:100] if text else ""

def normalize_text(text: str) -> str:
    """规范化文本"""
    text = re.sub(r'\s+', '', text)
    text = re.sub(r'[，。！？、；：""''（）《》【】\.,!?;:\'"()\[\]{}]', '', text)
    return text

def calculate_similarity(text1: str, text2: str) -> float:
    """计算两个文本的相似度"""
    if not text1 or not text2:
        return 0.0
    
    norm1 = normalize_text(text1)
    norm2 = normalize_text(text2)
    
    if not norm1 or not norm2:
        return 0.0
    
    def get_shingles(text: str, k: int = 12) -> set:
        if len(text) < k:
            return {text}
        return {text[i:i+k] for i in range(0, len(text) - k + 1, 3)}
    
    shingles1 = get_shingles(norm1)
    shingles2 = get_shingles(norm2)
    
    if not shingles1 or not shingles2:
        return 0.0
    
    intersection = len(shingles1 & shingles2)
    union = len(shingles1 | shingles2)
    
    return intersection / union if union > 0 else 0.0

def find_duplicates_in_book(book_dir: Path, similarity_threshold: float = 0.8) -> list:
    """在单本书中查找重复章节"""
    duplicates = []
    
    # 读取该书的所有章节
    chapters = []
    for md_path in sorted(book_dir.glob("*.md")):
        meta, body = read_chapter_body(md_path)
        if body:
            chapters.append({
                'path': md_path,
                'body': body,
                'first_para': get_first_paragraph(body),
                'first_para_norm': normalize_text(get_first_paragraph(body)),
                'char_count': len(body),
            })
    
    if len(chapters) < 2:
        return duplicates
    
    # 按首段分组，找到可能的重复候选
    para_groups = defaultdict(list)
    for chapter in chapters:
        if chapter['first_para_norm'] and len(chapter['first_para_norm']) >= 10:
            para_groups[chapter['first_para_norm']].append(chapter)
    
    # 记录已处理的配对，避免重复比较
    processed_pairs = set()
    
    # 1. 首段完全相同的章节
    for para, group in para_groups.items():
        if len(group) > 1:
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    pair_key = (str(group[i]['path']), str(group[j]['path']))
                    if pair_key in processed_pairs:
                        continue
                    processed_pairs.add(pair_key)
                    
                    # 计算全文相似度
                    similarity = calculate_similarity(group[i]['body'], group[j]['body'])
                    
                    if similarity >= similarity_threshold:
                        # 保留较长的
                        if group[i]['char_count'] >= group[j]['char_count']:
                            keep, delete = group[i], group[j]
                        else:
                            keep, delete = group[j], group[i]
                        
                        duplicates.append({
                            'file': str(delete['path']),
                            'duplicate_of': str(keep['path']),
                            'similarity': similarity,
                            'reason': f'首段相同，全文相似{similarity:.1%}'
                        })
    
    # 2. 首段部分相似的章节（使用首段搜索）
    # 对每个章节，用其首段的前30字在书中搜索
    search_cache = {}
    for chapter in chapters:
        first_para = chapter['first_para']
        if len(first_para) < 30:
            continue
        
        # 取首段前30字作为搜索关键词
        search_key = first_para[:30]
        
        # 在所有章节正文中搜索这个关键词
        for other in chapters:
            if other['path'] == chapter['path']:
                continue
            
            pair_key = tuple(sorted([str(chapter['path']), str(other['path'])]))
            if pair_key in processed_pairs:
                continue
            
            # 检查关键词是否在对方正文中
            if search_key in other['body']:
                processed_pairs.add(pair_key)
                
                # 计算全文相似度
                similarity = calculate_similarity(chapter['body'], other['body'])
                
                if similarity >= similarity_threshold:
                    if chapter['char_count'] >= other['char_count']:
                        keep, delete = chapter, other
                    else:
                        keep, delete = other, chapter
                    
                    duplicates.append({
                        'file': str(delete['path']),
                        'duplicate_of': str(keep['path']),
                        'similarity': similarity,
                        'reason': f'首段命中，全文相似{similarity:.1%}'
                    })
    
    # 去重（可能同一文件被多次标记）
    seen_files = set()
    unique_duplicates = []
    for dup in duplicates:
        if dup['file'] not in seen_files:
            seen_files.add(dup['file'])
            unique_duplicates.append(dup)
    
    return unique_duplicates

def find_all_duplicates(cleaned_dir="cleaned", similarity_threshold=0.8):
    """在所有书中查找重复章节"""
    all_duplicates = []
    
    cleaned_path = Path(cleaned_dir)
    
    book_dirs = [d for d in sorted(cleaned_path.iterdir()) if d.is_dir()]
    print(f"共 {len(book_dirs)} 本书需要检查")
    
    for i, book_dir in enumerate(book_dirs, 1):
        print(f"\n[{i}/{len(book_dirs)}] 检查: {book_dir.name}")
        
        duplicates = find_duplicates_in_book(book_dir, similarity_threshold)
        
        if duplicates:
            print(f"  发现 {len(duplicates)} 个重复章节")
            all_duplicates.extend(duplicates)
        else:
            print(f"  无重复")
    
    return all_duplicates

def delete_duplicates(duplicates, dry_run=True):
    """删除重复章节"""
    if dry_run:
        print(f"\n[预览模式] 将删除 {len(duplicates)} 个重复章节：")
        for i, dup in enumerate(duplicates, 1):
            print(f"\n  {i}. 删除: {dup['file']}")
            print(f"     重复于: {dup['duplicate_of']}")
            print(f"     相似度: {dup['similarity']:.1%}")
            print(f"     原因: {dup['reason']}")
        return 0
    
    deleted_count = 0
    for dup in duplicates:
        path = Path(dup['file'])
        try:
            path.unlink()
            print(f"✅ 已删除: {path}")
            deleted_count += 1
        except Exception as e:
            print(f"❌ 删除失败: {path} - {e}")
    
    return deleted_count

def write_report(duplicates, output_file="dedup_chapters_report.txt"):
    """生成去重报告"""
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("章节去重报告\n")
        f.write("=" * 80 + "\n\n")
        
        f.write(f"发现重复章节：{len(duplicates)} 个\n\n")
        
        # 按书分组统计
        book_stats = defaultdict(int)
        for dup in duplicates:
            match = re.search(r'cleaned[\\/]([^\\/]+)', dup['file'])
            if match:
                book_stats[match.group(1)] += 1
        
        f.write("按书统计：\n")
        for book, count in sorted(book_stats.items(), key=lambda x: x[1], reverse=True):
            f.write(f"  {book}: {count} 个重复\n")
        
        f.write("\n详细列表：\n")
        for i, dup in enumerate(duplicates, 1):
            f.write(f"\n  {i}. 删除: {dup['file']}\n")
            f.write(f"     重复于: {dup['duplicate_of']}\n")
            f.write(f"     相似度: {dup['similarity']:.1%}\n")
            f.write(f"     原因: {dup['reason']}\n")
    
    return output_file

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.8, help="相似度阈值（默认0.8）")
    parser.add_argument("--delete", action="store_true", help="实际删除（默认预览模式）")
    args = parser.parse_args()
    
    print("开始检查重复章节...")
    print(f"相似度阈值: {args.threshold}\n")
    
    # 查找重复
    duplicates = find_all_duplicates(
        cleaned_dir="cleaned",
        similarity_threshold=args.threshold
    )
    
    # 生成报告
    report_file = write_report(duplicates)
    print(f"\n报告已生成: {report_file}")
    
    # 删除（或预览）
    if args.delete:
        print(f"\n实际删除 {len(duplicates)} 个重复章节...")
        deleted = delete_duplicates(duplicates, dry_run=False)
        print(f"已删除 {deleted} 个文件")
    else:
        print(f"\n预览模式：发现 {len(duplicates)} 个重复章节")
        print("使用 --delete 参数实际删除")
        
        # 显示前10个
        for dup in duplicates[:10]:
            print(f"\n  删除: {dup['file']}")
            print(f"    重复于: {dup['duplicate_of']}")
            print(f"    相似度: {dup['similarity']:.1%}")

if __name__ == "__main__":
    main()