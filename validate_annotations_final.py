"""针对问题角色的二次验证：只检查报告中的角色是否真的不在正文"""
import yaml
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime

def parse_problem_characters(report_file: str) -> list:
    """从验证报告中解析问题角色列表"""
    problems = []
    
    with open(report_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 匹配 "cleaned\xxx\0001.md: 角色名" 格式
    pattern = r'(cleaned[\\/].+?\.md):\s+(.+?)(?:\n|$)'
    matches = re.findall(pattern, content)
    
    # 只提取"角色不在正文"部分
    in_character_section = False
    for line in content.split('\n'):
        if '[角色不在正文]' in line:
            in_character_section = True
            continue
        if in_character_section and line.startswith('  [') and ']' in line:
            in_character_section = False
            continue
        
        if in_character_section:
            match = re.search(r'(cleaned[\\/].+?\.md):\s+(.+)$', line.strip())
            if match:
                problems.append({
                    'file': match.group(1),
                    'character': match.group(2).strip()
                })
    
    return problems

def read_chapter_body(md_path: str) -> tuple:
    """读取章节正文"""
    path = Path(md_path)
    if not path.exists():
        return None, ""
    
    raw = path.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return None, ""
    
    try:
        meta = yaml.safe_load(parts[1])
    except:
        meta = {}
    
    body = parts[2].strip()
    return meta, body

def split_by_separators(text: str) -> list:
    parts = []
    separators = ['/', '、', ',', '，', '|', ';', '；']
    for sep in separators:
        if sep in text:
            sub_parts = text.split(sep)
            parts.extend([p.strip() for p in sub_parts if p.strip()])
    return parts

def split_character_name(name: str) -> list:
    """拆分角色名称"""
    parts = set()
    original = name.strip()
    parts.add(original)
    
    # 处理括号
    bracket_match = re.search(r'[（(""]([^）)""]+)[）)""]', original)
    if bracket_match:
        inner = bracket_match.group(1).strip()
        outer = re.sub(r'[（(""][^）)""]+[）)""]', '', original).strip()
        if outer:
            parts.add(outer)
        if inner:
            inner_clean = re.sub(r'[等们]+\s*$', '', inner).strip()
            if inner_clean:
                parts.add(inner_clean)
    
    # 处理"的"
    if '的' in original:
        de_parts = original.split('的')
        if len(de_parts) >= 2:
            for dp in de_parts:
                if dp.strip() and len(dp.strip()) >= 2:
                    parts.add(dp.strip())
    
    # 处理分隔符
    separator_parts = split_by_separators(original)
    parts.update(separator_parts)
    
    parts = {p for p in parts if p and len(p) >= 2}
    return list(parts)

def extract_core_words(char_name: str) -> list:
    """提取核心词（关系称呼等）"""
    core_words = []
    
    # 关系词
    relations = ['父亲', '母亲', '爸爸', '妈妈', '父母', '爸妈', '儿子', '女儿',
                 '哥哥', '姐姐', '弟弟', '妹妹', '奶奶', '爷爷', '祖母', '祖父',
                 '丈夫', '妻子', '兄长', '姐妹', '兄弟', '室友', '同桌',
                 '手下', '下属', '跟班', '同伙', '同伴', '伙伴']
    
    for rel in relations:
        if rel in char_name:
            core_words.append(rel)
    
    # 描述词
    descriptions = ['神秘人', '路人', '围观', '陌生', '邻居', '朋友', '同学',
                    '老板', '店员', '服务员', '司机', '老师', '学生',
                    '小贩', '伙计', '小二', '摊主', '店主']
    
    for desc in descriptions:
        if desc in char_name:
            core_words.append(desc)
    
    return list(set(core_words))

def check_character_in_body(char_name: str, body: str) -> tuple:
    """检查角色是否在正文中"""
    char_parts = split_character_name(char_name)
    core_words = extract_core_words(char_name)
    all_parts = list(set(char_parts + core_words))
    
    # 1. 精确匹配
    for part in all_parts:
        if len(part) >= 2 and part in body:
            return True, f"精确: {part}"
    
    # 2. 核心词匹配
    for word in core_words:
        if len(word) >= 2 and word in body:
            return True, f"核心词: {word}"
    
    return False, ""

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default=None, help="验证报告文件路径（默认自动找最新的）")
    args = parser.parse_args()
    
    # 找到最新的报告
    if args.report:
        report_file = args.report
    else:
        reports = sorted(Path("validation_reports").glob("validation_report_*.txt"), 
                        key=lambda p: p.stat().st_mtime, reverse=True)
        if not reports:
            print("找不到验证报告，请先运行 validate_annotations.py")
            return
        report_file = str(reports[0])
    
    print(f"使用报告: {report_file}")
    
    # 解析问题角色
    problems = parse_problem_characters(report_file)
    print(f"发现 {len(problems)} 个问题角色")
    
    if not problems:
        print("没有问题角色")
        return
    
    # 二次验证
    confirmed_issues = []
    false_alarms = []
    
    print("\n开始二次验证...")
    for i, problem in enumerate(problems, 1):
        meta, body = read_chapter_body(problem['file'])
        
        if not body:
            confirmed_issues.append(problem)
            continue
        
        found, matched = check_character_in_body(problem['character'], body)
        
        if found:
            false_alarms.append({**problem, 'matched': matched})
        else:
            confirmed_issues.append(problem)
        
        if i % 100 == 0:
            print(f"  进度: {i}/{len(problems)}")
    
    # 生成报告
    output_path = Path("validation_reports")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_file = output_path / f"recheck_result_{timestamp}.txt"
    
    with open(result_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("问题角色二次验证结果\n")
        f.write(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n\n")
        
        f.write(f"原始问题数：{len(problems)}\n")
        f.write(f"确认问题（确实不在正文）：{len(confirmed_issues)}\n")
        f.write(f"误报（实际在正文中）：{len(false_alarms)}\n\n")
        
        f.write("【误报列表】（规则匹配成功，可忽略）\n")
        for i, issue in enumerate(false_alarms, 1):
            f.write(f"  {i}. {issue['file']}: {issue['character']} -> {issue.get('matched', '')}\n")
        
        f.write(f"\n【确认问题列表】（需要人工检查）\n")
        for i, issue in enumerate(confirmed_issues, 1):
            f.write(f"  {i}. {issue['file']}: {issue['character']}\n")
    
    print(f"\n结果已生成: {result_file}")
    print(f"\n确认问题: {len(confirmed_issues)}")
    print(f"误报（可忽略）: {len(false_alarms)}")

if __name__ == "__main__":
    main()