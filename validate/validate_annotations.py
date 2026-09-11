"""验证标注质量的脚本：基础检索 -> 语义切分 -> 人物词提取 -> 匹配 -> AI辅助"""
import yaml
import re
import json
import urllib.request
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# 描述性词汇列表
DESCRIPTIVE_WORDS = [
    # 人物类型
    '男生', '女生', '男人', '女人', '青年', '少年', '女孩', '男孩',
    '男子', '女子', '老人', '老道', '道士', '道姑', '和尚', '尼姑',
    '前辈', '后辈', '长辈', '晚辈', '师父', '徒弟', '师兄', '师弟',
    '师姐', '师妹', '掌门', '长老', '弟子', '门徒',
    'alpha', 'beta', 'omega', 'Alpha', 'Beta', 'Omega',
    # 职业身份
    '同学', '朋友', '同事', '老板', '店员', '服务员', '司机', '老师',
    '学生', '客人', '顾客', '陌生人', '路人', '医生', '护士', '警察',
    # 关系称呼
    '姐妹', '兄弟', '父子', '母子', '夫妻', '情侣', '搭档', '伙伴',
    # 群体
    '三姐妹', '双胞胎', '孪生', '众人', '大家', '人群', '队伍',
    '甲', '乙', '丙', '丁', 'A', 'B', 'C', 'O', 'a', 'b', 'c', 'o',
    # 职位称呼
    '部长', '经理', '总监', '总裁', '董事长', '社长', '会长',
    '队长', '组长', '班长', '主任', '主管', '助理', '秘书',
    '科长', '处长', '局长', '厅长', '院长', '校长',
    '太监', '宫女', '丫鬟', '嬷嬷', '官员', '国君', '首领', '管家',
]


def split_by_separators(text: str) -> list:
    """按分隔符拆分"""
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
            inner_parts = split_by_separators(inner_clean)
            parts.update(inner_parts)
            if inner_clean.endswith('者'):
                parts.add(inner_clean[:-1])
    
    # 处理"的"结构
    if '的' in original:
        de_parts = original.split('的')
        if len(de_parts) >= 2:
            if de_parts[0].strip():
                parts.add(de_parts[0].strip())
            if de_parts[-1].strip():
                parts.add(de_parts[-1].strip())
    
    # 处理描述性词汇
    for word in DESCRIPTIVE_WORDS:
        if word in original:
            parts.add(word)
            prefix = original.split(word)[0].strip()
            if prefix and len(prefix) >= 2:
                parts.add(prefix)
            if '的' in prefix:
                prefix_parts = prefix.split('的')
                for pp in prefix_parts:
                    if pp.strip() and len(pp.strip()) >= 2:
                        parts.add(pp.strip())
    
    # 处理分隔符
    separator_parts = split_by_separators(original)
    parts.update(separator_parts)
    
    # 处理后缀
    for part in list(parts):
        cleaned = re.sub(r'[等们]+\s*$', '', part).strip()
        if cleaned and cleaned != part:
            parts.add(cleaned)
    
    # 处理"者"结尾
    for part in list(parts):
        if part.endswith('者') and len(part) > 2:
            parts.add(part[:-1])
    
    # 处理形容词前缀
    adjective_words = ['神秘', '陌生', '年轻', '年老', '漂亮', '英俊', '普通']
    for word in adjective_words:
        if original.startswith(word) and len(original) > len(word):
            rest = original[len(word):].strip()
            if rest and len(rest) >= 2:
                parts.add(rest)
    
    parts = {p for p in parts if p and len(p) >= 2}
    return list(parts)


def split_sentences(text: str) -> list:
    """将文本按句子分割"""
    sentences = re.split(r'[。！？!?；;\n]', text)
    sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) >= 5]
    return sentences


def remove_dialogue_content(sentence: str) -> str:
    """删除句子中的对话内容"""
    sentence = re.sub(r'["""][^"""]*["""]', '', sentence)
    sentence = re.sub(r'「[^」]*」', '', sentence)
    sentence = re.sub(r'『[^』]*』', '', sentence)
    return sentence.strip()


def is_person_sentence(sentence: str) -> bool:
    """判断句子是否包含人物出场"""
    clean_sentence = remove_dialogue_content(sentence)
    
    for word in DESCRIPTIVE_WORDS:
        if word in clean_sentence:
            return True
    
    name_action_patterns = [
        r'[\u4e00-\u9fa5]{2,4}(?:走进|来到|出现|站在|坐在|看向|望着|看着|伸手|转身|点头|摇头|跑|走|坐|站)',
    ]
    for pattern in name_action_patterns:
        if re.search(pattern, clean_sentence):
            return True
    
    return False


def get_person_sentences(body: str) -> list:
    """获取包含人物的句子（删除对话内容）"""
    sentences = split_sentences(body)
    person_sentences = []
    
    for sentence in sentences:
        clean = remove_dialogue_content(sentence)
        if is_person_sentence(sentence) and clean and len(clean) >= 5:
            person_sentences.append(clean)
    
    return person_sentences


def extract_core_words(char_name: str) -> list:
    """提取角色名的核心词"""
    core_words = []
    
    for word in DESCRIPTIVE_WORDS:
        if word in char_name:
            core_words.append(word)
    
    return list(set(core_words))


def validate_character_in_body(char_name: str, body: str, all_characters: list) -> tuple:
    """验证角色是否在正文中（严格规则匹配）"""
    char_parts = split_character_name(char_name)
    core_words = extract_core_words(char_name)
    person_sentences = get_person_sentences(body)
    
    # 1. 全文精确匹配
    for part in char_parts:
        if len(part) >= 2 and part in body:
            return True, f"精确: {part}"
    
    # 2. 核心词在全文匹配
    for word in core_words:
        if len(word) >= 2 and word in body:
            return True, f"核心词: {word}"
    
    # 3. 在人物句子中精确匹配
    for sentence in person_sentences:
        for part in char_parts:
            if len(part) >= 2 and part in sentence:
                return True, f"句子: {part}"
        for word in core_words:
            if len(word) >= 2 and word in sentence:
                return True, f"句子核心词: {word}"
    
    return False, ""


def ai_verify_character(char_name: str, person_sentences: list, llm_base_url: str, llm_model: str, timeout: int = 60) -> bool:
    """使用 AI 判断标注角色是否对应检索到的人物"""
    if not person_sentences:
        return None
    
    char_parts = split_character_name(char_name)
    core_words = extract_core_words(char_name)
    all_parts = list(set(char_parts + core_words))
    
    system_prompt = """你是专业的文本分析助手，擅长理解中文小说的角色描述。

判断给定的角色描述是否与句子中出现的人物对应。

注意：
1. 角色可能是群体描述（如"围观群众"），句子中可能分散描述这些人
2. 角色可能是描述性称呼（如"神秘人"），句子中可能有相似描述
3. 角色可能是简称（如"部长"是"公关部长"的简称）
4. 角色可能是非人物（如"猫"、"鬼"），只要句子中有对应描述即可

只要句子中有与该角色相关的人物或描述，回答 YES。
否则回答 NO。

只回答 YES 或 NO。"""
    
    combined = " ".join(person_sentences)[:1000]
    
    user_prompt = f"""角色描述：{char_name}

可能的称呼或相关词：{'、'.join(all_parts[:8])}

包含人物的句子：
{combined}

这些句子中是否有人物符合该角色描述？
只回答 YES 或 NO。"""
    
    body_data = {
        "model": llm_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "stream": False,
        "max_tokens": 20,
    }
    
    try:
        req = urllib.request.Request(
            llm_base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body_data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        
        content = result["choices"][0]["message"]["content"].strip().upper()
        
        if "YES" in content or "是" in content:
            return True
        elif "NO" in content or "否" in content:
            return False
        else:
            return None
            
    except Exception as e:
        print(f"    [AI异常] {e}")
        return None


def validate_chapter_annotations(cleaned_dir="cleaned", use_ai=False, 
                                 llm_base_url="http://localhost:11434/v1", 
                                 llm_model="qwen2.5:3b"):
    """验证所有章节的标注质量"""
    issues = defaultdict(list)
    stats = defaultdict(int)
    character_issues = []
    
    cleaned_path = Path(cleaned_dir)
    
    for book_dir in sorted(cleaned_path.iterdir()):
        if not book_dir.is_dir():
            continue
        
        meta_path = book_dir / "_book_meta.yaml"
        if meta_path.exists():
            book_meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
            book_world = book_meta.get("world", "")
        else:
            book_world = ""
        
        for md_path in sorted(book_dir.glob("*.md")):
            stats['total_chapters'] += 1
            chapter_issue_list = []
            
            try:
                raw = md_path.read_text(encoding="utf-8")
                parts = raw.split("---", 2)
                if len(parts) < 3:
                    issues['格式错误'].append(f"{md_path}: 无法解析")
                    continue
                
                chap_meta = yaml.safe_load(parts[1])
                body = parts[2].strip()
                
                # 1. 检查必需字段
                required_fields = ['world', 'scene', 'emotion', 'plot', 'style', 'characters']
                for field in required_fields:
                    if not chap_meta.get(field):
                        issues['缺少字段'].append(f"{md_path}: 缺少 {field}")
                        chapter_issue_list.append(f"缺少{field}")
                        stats['missing_fields'] += 1
                
                # 2. 检查 world 一致性
                if book_world and chap_meta.get('world') != book_world:
                    issues['world不一致'].append(f"{md_path}: 书级={book_world}, 章节={chap_meta.get('world')}")
                    chapter_issue_list.append("world不一致")
                
                # 3. 检查 characters
                characters = chap_meta.get('characters', [])
                if characters:
                    stats['total_characters'] += len(characters)
                    
                    person_sentences = get_person_sentences(body)
                    
                    for char in characters:
                        char_name = char.get('name', '')
                        if not char_name:
                            issues['角色缺少名字'].append(f"{md_path}")
                            chapter_issue_list.append("角色缺少名字")
                            continue
                        
                        if not char.get('role'):
                            issues['角色缺少定位'].append(f"{md_path}: {char_name}")
                            chapter_issue_list.append(f"角色{char_name}缺少定位")
                        if not char.get('state'):
                            issues['角色缺少状态'].append(f"{md_path}: {char_name}")
                            chapter_issue_list.append(f"角色{char_name}缺少状态")
                        
                        found, matched = validate_character_in_body(char_name, body, characters)
                        
                        if not found and use_ai:
                            ai_found = ai_verify_character(char_name, person_sentences, llm_base_url, llm_model)
                            if ai_found is True:
                                found = True
                                matched = "AI判断存在"
                            elif ai_found is False:
                                found = False
                                matched = "AI判断不存在"
                        
                        if not found:
                            issues['角色不在正文'].append(f"{md_path}: {char_name}")
                            chapter_issue_list.append(f"{char_name}不在正文")
                            character_issues.append({
                                'file': str(md_path),
                                'character': char_name,
                                'name_parts': split_character_name(char_name),
                                'match_info': matched
                            })
                else:
                    issues['无角色'].append(f"{md_path}")
                    chapter_issue_list.append("无角色")
                
                # 4. 检查字段长度
                if len(chap_meta.get('scene', '')) > 150:
                    issues['scene过长'].append(f"{md_path}: {len(chap_meta['scene'])}字")
                    chapter_issue_list.append("scene过长")
                
                if len(chap_meta.get('plot', '')) > 100:
                    issues['plot过长'].append(f"{md_path}: {len(chap_meta['plot'])}字")
                    chapter_issue_list.append("plot过长")
                
                # 5. 检查章节长度
                if len(body) < 500:
                    issues['章节过短'].append(f"{md_path}: {len(body)}字")
                    chapter_issue_list.append("章节过短")
                    stats['short_chapters'] += 1
                
                if chapter_issue_list:
                    stats['chapters_with_issues'] += 1
                    
            except Exception as e:
                issues['解析错误'].append(f"{md_path}: {e}")
    
    return issues, stats, character_issues


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--use-ai", action="store_true", help="使用 AI 辅助判断")
    parser.add_argument("--llm-base-url", default="http://localhost:11434/v1")
    parser.add_argument("--llm-model", default="qwen2.5:3b")
    args = parser.parse_args()
    
    print("开始验证标注...")
    if args.use_ai:
        print(f"使用 AI 辅助判断（模型：{args.llm_model}）")
    
    issues, stats, character_issues = validate_chapter_annotations(
        use_ai=args.use_ai,
        llm_base_url=args.llm_base_url,
        llm_model=args.llm_model
    )
    
    output_path = Path("validation_reports")
    output_path.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = output_path / f"validation_report_{timestamp}.txt"
    
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("标注质量验证报告\n")
        if args.use_ai:
            f.write("（包含 AI 辅助判断）\n")
        f.write(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n\n")
        
        f.write("【基本统计】\n")
        f.write(f"  总章节数：{stats.get('total_chapters', 0)}\n")
        f.write(f"  总角色数：{stats.get('total_characters', 0)}\n")
        f.write(f"  缺失字段数：{stats.get('missing_fields', 0)}\n")
        f.write(f"  过短章节数：{stats.get('short_chapters', 0)}\n")
        f.write(f"  有问题的章节数：{stats.get('chapters_with_issues', 0)}\n\n")
        
        f.write("【问题统计】\n")
        total_issues = 0
        for issue_type, issue_list in issues.items():
            if issue_list:
                f.write(f"  {issue_type}: {len(issue_list)} 个问题\n")
                total_issues += len(issue_list)
        f.write(f"  总计：{total_issues} 个问题\n\n")
        
        f.write("【详细问题列表】\n")
        for issue_type, issue_list in issues.items():
            if issue_list:
                f.write(f"\n  [{issue_type}] ({len(issue_list)} 个)\n")
                for i, issue in enumerate(issue_list, 1):
                    f.write(f"    {i}. {issue}\n")
    
    print(f"\n报告已生成：{report_file}")
    print("\n" + "=" * 60)
    print("验证完成！")
    print("=" * 60)
    print(f"总章节数：{stats.get('total_chapters', 0)}")
    print(f"总角色数：{stats.get('total_characters', 0)}")
    print(f"总问题数：{total_issues}")
    print(f"角色不在正文：{len(character_issues)}")
    print(f"\n报告文件：{report_file}")


if __name__ == "__main__":
    main()