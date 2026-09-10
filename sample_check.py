"""人工抽检脚本：随机抽取章节进行标注质量检查"""
import random
import yaml
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime

def read_chapter(md_path: Path) -> tuple:
    """读取章节的 meta 和正文"""
    raw = md_path.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}, ""
    
    try:
        meta = yaml.safe_load(parts[1])
    except:
        meta = {}
    
    body = parts[2].strip()
    return meta, body

def get_all_chapters(cleaned_dir="cleaned"):
    """获取所有章节"""
    chapters = []
    cleaned_path = Path(cleaned_dir)
    
    for book_dir in sorted(cleaned_path.iterdir()):
        if not book_dir.is_dir():
            continue
        for md_path in sorted(book_dir.glob("*.md")):
            chapters.append(md_path)
    
    return chapters

def check_chapter_quality(meta: dict, body: str) -> list:
    """检查单个章节的标注质量，返回问题列表"""
    issues = []
    
    # 1. 检查必需字段
    required_fields = ['world', 'scene', 'emotion', 'plot', 'style', 'characters', 'pov']
    for field in required_fields:
        if not meta.get(field):
            issues.append(f"缺少 {field}")
    
    # 2. 检查字段长度
    if len(meta.get('scene', '')) > 100:
        issues.append(f"scene 过长 ({len(meta['scene'])}字)")
    if len(meta.get('plot', '')) > 100:
        issues.append(f"plot 过长 ({len(meta['plot'])}字)")
    
    # 3. 检查角色
    characters = meta.get('characters', [])
    if characters:
        for char in characters:
            if not char.get('name'):
                issues.append("角色缺少名字")
            if not char.get('role'):
                issues.append(f"角色 {char.get('name', '?')} 缺少定位")
            if not char.get('state'):
                issues.append(f"角色 {char.get('name', '?')} 缺少状态")
            if not char.get('speech'):
                issues.append(f"角色 {char.get('name', '?')} 缺少说话风格")
    
    # 4. 检查正文长度
    if len(body) < 500:
        issues.append(f"正文过短 ({len(body)}字)")
    
    return issues

def sample_check(sample_size=20, seed=None, output_dir="sample_check"):
    """随机抽取章节进行人工检查"""
    if seed:
        random.seed(seed)
    
    chapters = get_all_chapters()
    if not chapters:
        print("找不到章节")
        return
    
    print(f"共 {len(chapters)} 个章节")
    
    # 随机抽取
    samples = random.sample(chapters, min(sample_size, len(chapters)))
    
    # 按书分组
    book_groups = defaultdict(list)
    for md_path in samples:
        # 提取书名
        match = re.search(r'cleaned[\\/]([^\\/]+)', str(md_path))
        book_name = match.group(1) if match else "未知"
        book_groups[book_name].append(md_path)
    
    # 生成报告
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = output_path / f"sample_check_{timestamp}.txt"
    
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("人工抽检报告\n")
        f.write(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"抽取数量：{len(samples)} 章\n")
        f.write("=" * 80 + "\n\n")
        
        # 按书分组显示
        f.write(f"抽检分布：\n")
        for book, chapters_list in book_groups.items():
            f.write(f"  {book}: {len(chapters_list)} 章\n")
        f.write("\n")
        
        # 逐章详细检查
        for i, md_path in enumerate(samples, 1):
            meta, body = read_chapter(md_path)
            issues = check_chapter_quality(meta, body)
            
            f.write("\n" + "=" * 60 + "\n")
            f.write(f"样本 {i}: {md_path}\n")
            f.write("=" * 60 + "\n\n")
            
            # 标注信息
            f.write("【标注信息】\n")
            f.write(f"  World: {meta.get('world', '(空)')}\n")
            f.write(f"  Scene: {meta.get('scene', '(空)')}\n")
            f.write(f"  Emotion: {meta.get('emotion', '(空)')}\n")
            f.write(f"  Plot: {meta.get('plot', '(空)')}\n")
            f.write(f"  Style: {meta.get('style', '(空)')}\n")
            f.write(f"  POV: {meta.get('pov', '(空)')}\n")
            f.write(f"  Word Count: {meta.get('word_count', '(空)')}\n")
            
            f.write("\n【角色列表】\n")
            characters = meta.get('characters', [])
            if characters:
                for j, char in enumerate(characters, 1):
                    f.write(f"  {j}. {char.get('name', '?')} ({char.get('role', '?')})\n")
                    f.write(f"     State: {char.get('state', '(空)')}\n")
                    f.write(f"     Speech: {char.get('speech', '(空)')}\n")
                    f.write(f"     Function: {char.get('function', '(空)')}\n")
            else:
                f.write("  (无角色)\n")
            
            # 自动检查的问题
            if issues:
                f.write("\n【自动检查发现的问题】\n")
                for issue in issues:
                    f.write(f"  ⚠️ {issue}\n")
            else:
                f.write("\n【自动检查】✅ 无格式问题\n")
            
            # 正文摘要
            f.write(f"\n【正文前300字】\n")
            f.write(body[:300] + "...\n")
            
            # 人工检查清单
            f.write("\n【人工检查清单】\n")
            f.write("  □ Scene 是否准确描述章节场景？\n")
            f.write("  □ Plot 是否概括核心剧情？\n")
            f.write("  □ Characters 是否包含所有重要出场角色？\n")
            f.write("  □ 角色 State 是否符合正文表现？\n")
            f.write("  □ 角色 Speech 是否符合说话风格？\n")
            f.write("  □ Emotion 是否准确？\n")
            f.write("  □ Style 描述是否合理？\n")
            f.write("  □ POV 视角是否正确？\n")
            f.write("  □ 是否有遗漏的重要角色？\n")
            f.write("  □ 是否有不该出现的角色？\n")
            
            f.write("\n【人工评价】\n")
            f.write("  评分（1-5）：___\n")
            f.write("  备注：\n\n")
    
    print(f"\n报告已生成: {report_file}")
    print(f"\n抽检分布：")
    for book, chapters_list in book_groups.items():
        print(f"  {book}: {len(chapters_list)} 章")
    
    print(f"\n请打开报告进行人工检查：{report_file}")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="人工抽检标注质量")
    parser.add_argument("--sample-size", type=int, default=20, help="抽取数量（默认20）")
    parser.add_argument("--seed", type=int, default=None, help="随机种子（固定后每次抽同样章节）")
    parser.add_argument("--book", default=None, help="只抽检特定书籍")
    args = parser.parse_args()
    
    if args.book:
        # 只抽检特定书
        book_dir = Path("cleaned") / args.book
        if not book_dir.exists():
            print(f"找不到书籍: {args.book}")
            return
        
        chapters = sorted(book_dir.glob("*.md"))
        if args.seed:
            random.seed(args.seed)
        samples = random.sample(chapters, min(args.sample_size, len(chapters)))
        
        # 临时修改 get_all_chapters 的返回
        import types
        def get_specific_book_chapters():
            return samples
        global get_all_chapters
        get_all_chapters = get_specific_book_chapters
        
        print(f"只抽检: {args.book}")
    
    sample_check(sample_size=args.sample_size, seed=args.seed)

if __name__ == "__main__":
    main()