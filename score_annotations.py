"""对标注质量进行评分"""
import yaml
from pathlib import Path

def score_annotation(chap_meta: dict, body: str) -> dict:
    """对单个章节的标注进行评分"""
    scores = {}
    
    # 1. 完整性评分
    required_fields = ['world', 'scene', 'emotion', 'plot', 'style', 'characters', 'pov']
    complete_count = sum(1 for f in required_fields if chap_meta.get(f))
    scores['完整性'] = (complete_count / len(required_fields)) * 100
    
    # 2. 简洁性评分
    scene_len = len(chap_meta.get('scene', ''))
    plot_len = len(chap_meta.get('plot', ''))
    if scene_len <= 50 and plot_len <= 50:
        scores['简洁性'] = 100
    elif scene_len <= 100 and plot_len <= 100:
        scores['简洁性'] = 80
    else:
        scores['简洁性'] = 60
    
    # 3. 角色覆盖度
    characters = chap_meta.get('characters', [])
    if len(characters) >= 2:
        scores['角色数量'] = 100
    elif len(characters) == 1:
        scores['角色数量'] = 60
    else:
        scores['角色数量'] = 0
    
    # 角色信息完整性
    if characters:
        complete_chars = sum(1 for c in characters if c.get('name') and c.get('state'))
        scores['角色信息'] = (complete_chars / len(characters)) * 100
    else:
        scores['角色信息'] = 0
    
    # 4. 总体评分
    scores['总体'] = sum(scores.values()) / len(scores)
    
    return scores

def score_all(cleaned_dir="cleaned"):
    """对所有章节进行评分"""
    all_scores = []
    
    for book_dir in Path(cleaned_dir).iterdir():
        if not book_dir.is_dir():
            continue
        for md_path in book_dir.glob("*.md"):
            raw = md_path.read_text(encoding="utf-8")
            parts = raw.split("---", 2)
            if len(parts) < 3:
                continue
            chap_meta = yaml.safe_load(parts[1])
            body = parts[2].strip()
            
            scores = score_annotation(chap_meta, body)
            scores['file'] = str(md_path)
            all_scores.append(scores)
    
    # 统计
    if all_scores:
        avg_total = sum(s['总体'] for s in all_scores) / len(all_scores)
        print(f"平均总分：{avg_total:.1f}")
        
        # 找出低分章节
        low_scores = [s for s in all_scores if s['总体'] < 70]
        if low_scores:
            print(f"\n低分章节（需要重新标注）：{len(low_scores)} 个")
            for s in low_scores[:10]:
                print(f"  {s['file']}: {s['总体']:.0f}分")

if __name__ == "__main__":
    score_all()