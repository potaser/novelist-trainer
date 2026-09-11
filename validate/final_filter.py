"""最终筛选：只留下具体人名需要检查"""
import re
from pathlib import Path
from datetime import datetime

# 真正的具体人名特征：2-4个汉字，不包含描述性词汇
DESCRIPTIVE_MARKERS = [
    '人', '者', '男', '女', '老', '少', '小', '大', '哥', '姐', '弟', '妹',
    '父', '母', '爷', '奶', '夫', '妻', '子', '儿', '女',
    '群', '众', '们', '队', '组', '团', '派', '军', '兵', '将', '官',
    '鬼', '尸', '妖', '魔', '神', '仙', '佛', '道', '僧', '尼',
    '猫', '狗', '鹰', '牛', '狼', '犬', '鼠', '萤', '鹦鹉',
    '员', '师', '生', '医', '警', '商', '贩', '匠', '工', '农',
    '主', '长', '首', '头', '领', '管', '卫', '侍', '仆', '奴', '婢',
    '修士', '弟子', '门生', '门人', '客卿', '家主', '族长',
    '摊主', '店主', '老板', '伙计', '小二', '小厮', '丫鬟',
    '观众', '网友', '粉丝', '住户', '邻居', '路人', '神秘',
    '陌生', '无名', '不明', '围观', '其他', '若干',
    '甲', '乙', '丙', '丁',
]

def is_specific_person_name(char_name: str) -> bool:
    """判断是否是具体人名（需要检查的）"""
    # 去掉括号内容
    clean = re.sub(r'[（(][^）)]*[）)]', '', char_name).strip()
    clean = re.sub(r'["""].*?["""]', '', clean).strip()
    
    if not clean:
        return False
    
    # 如果包含描述性标记，不是具体人名
    for marker in DESCRIPTIVE_MARKERS:
        if marker in clean:
            return False
    
    # 具体人名通常是2-4个汉字，或包含·的外国名
    if re.match(r'^[\u4e00-\u9fa5]{2,4}$', clean):
        return True
    
    # 外国名（包含·）
    if re.match(r'^[\u4e00-\u9fa5]{1,3}·[\u4e00-\u9fa5]{1,4}$', clean):
        return True
    
    # 英文名
    if re.match(r'^[A-Za-z]+$', clean):
        return True
    
    return False

def main():
    # 读取二次验证结果
    reports = sorted(Path("validation_reports").glob("recheck_result_*.txt"), 
                    key=lambda p: p.stat().st_mtime, reverse=True)
    
    if not reports:
        print("找不到二次验证报告")
        return
    
    report_file = reports[0]
    print(f"使用报告: {report_file}")
    
    content = report_file.read_text(encoding="utf-8")
    
    # 提取确认问题部分
    confirmed = []
    in_confirmed = False
    
    for line in content.split('\n'):
        if '【确认问题列表】' in line:
            in_confirmed = True
            continue
        if in_confirmed and line.startswith('  ') and '. cleaned' in line:
            # 提取角色名
            match = re.search(r'\.\s+(cleaned[\\/].+?\.md):\s+(.+)$', line.strip())
            if match:
                confirmed.append({
                    'file': match.group(1),
                    'character': match.group(2).strip()
                })
    
    print(f"确认问题总数: {len(confirmed)}")
    
    # 筛选具体人名
    specific_names = []
    descriptive = []
    
    for item in confirmed:
        if is_specific_person_name(item['character']):
            specific_names.append(item)
        else:
            descriptive.append(item)
    
    print(f"具体人名（需要检查）: {len(specific_names)}")
    print(f"描述性角色（可忽略）: {len(descriptive)}")
    
    # 生成最终报告
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = Path("validation_reports") / f"final_check_{timestamp}.txt"
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("最终检查列表（具体人名）\n")
        f.write(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n\n")
        
        f.write(f"具体人名总数：{len(specific_names)}\n\n")
        
        # 按角色名分组
        name_groups = defaultdict(list)
        for item in specific_names:
            name_groups[item['character']].append(item['file'])
        
        f.write("【需要检查的具体人名】\n")
        for name, files in sorted(name_groups.items()):
            f.write(f"\n  {name} ({len(files)} 次)\n")
            for file in files:
                f.write(f"    - {file}\n")
        
        f.write(f"\n\n【可忽略的描述性角色】({len(descriptive)} 个)\n")
        f.write("（这些是合理的描述性标注，不需要修改）\n")
    
    print(f"\n最终报告: {output_file}")
    
    # 打印具体人名
    print("\n需要检查的具体人名：")
    for name, files in sorted(name_groups.items()):
        print(f"  {name}: {len(files)} 次")

if __name__ == "__main__":
    from collections import defaultdict
    main()