"""生成人工审核打分 HTML 文件"""
import json
import yaml
import random
from pathlib import Path
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

def generate_html(sample_size=20, seed=42, output_file="review.html"):
    """生成审核 HTML"""
    random.seed(seed)
    
    # 获取所有章节
    chapters = []
    for book_dir in sorted(Path("cleaned").iterdir()):
        if not book_dir.is_dir():
            continue
        for md_path in sorted(book_dir.glob("*.md")):
            chapters.append(md_path)
    
    # 随机抽取
    samples = random.sample(chapters, min(sample_size, len(chapters)))
    
    # 收集数据
    data = []
    for md_path in samples:
        meta, body = read_chapter(md_path)
        data.append({
            'file': str(md_path),
            'book': md_path.parent.name,
            'chapter': md_path.stem,
            'meta': {
                'world': meta.get('world', ''),
                'scene': meta.get('scene', ''),
                'emotion': meta.get('emotion', ''),
                'plot': meta.get('plot', ''),
                'style': meta.get('style', ''),
                'pov': meta.get('pov', ''),
                'word_count': meta.get('word_count'),
                'characters': meta.get('characters', []),
            },
            'body': body,
        })
    
    # 生成 HTML
    html = generate_html_content(data)
    
    Path(output_file).write_text(html, encoding='utf-8')
    print(f"HTML 文件已生成: {output_file}")
    print(f"共 {len(data)} 个样本")
    print(f"\n打开方式：")
    print(f"  双击 {output_file}")
    print(f"  或在浏览器中打开")

def generate_html_content(data: list) -> str:
    """生成 HTML 内容"""
    
    html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>标注质量审核</title>
<style>
* {
    box-sizing: border-box;
}
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    margin: 0;
    padding: 0;
    background: #f5f5f5;
    color: #333;
    line-height: 1.6;
}
.header {
    position: sticky;
    top: 0;
    background: #fff;
    border-bottom: 1px solid #ddd;
    padding: 15px 20px;
    z-index: 100;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}
.header h1 {
    margin: 0 0 10px 0;
    font-size: 18px;
}
.header .progress {
    font-size: 14px;
    color: #666;
}
.header .stats {
    display: flex;
    gap: 20px;
    margin-top: 8px;
    font-size: 14px;
}
.header .stats span {
    padding: 4px 10px;
    border-radius: 4px;
    background: #f0f0f0;
}
.header .stats .good { background: #d4edda; color: #155724; }
.header .stats .bad { background: #f8d7da; color: #721c24; }
.header button {
    padding: 8px 16px;
    margin-right: 8px;
    border: 1px solid #ddd;
    background: #fff;
    border-radius: 4px;
    cursor: pointer;
    font-size: 14px;
}
.header button:hover {
    background: #f0f0f0;
}
.header button.primary {
    background: #0066cc;
    color: #fff;
    border-color: #0066cc;
}
.header button.primary:hover {
    background: #0052a3;
}
.container {
    max-width: 1400px;
    margin: 0 auto;
    padding: 20px;
}
.sample {
    background: #fff;
    border-radius: 8px;
    margin-bottom: 24px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    overflow: hidden;
}
.sample-header {
    padding: 12px 20px;
    background: #f8f9fa;
    border-bottom: 1px solid #eee;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.sample-header .title {
    font-weight: 600;
    color: #0066cc;
}
.sample-header .book {
    font-size: 13px;
    color: #666;
}
.sample-body {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0;
}
@media (max-width: 900px) {
    .sample-body {
        grid-template-columns: 1fr;
    }
}
.left-panel, .right-panel {
    padding: 20px;
}
.left-panel {
    border-right: 1px solid #eee;
}
.right-panel {
    background: #fafafa;
}
.section-title {
    font-size: 12px;
    text-transform: uppercase;
    color: #999;
    margin-bottom: 8px;
    font-weight: 600;
    letter-spacing: 0.5px;
}
.annotation-field {
    margin-bottom: 12px;
}
.annotation-field .label {
    font-size: 13px;
    color: #666;
    margin-bottom: 4px;
}
.annotation-field .value {
    font-size: 14px;
    color: #333;
    padding: 8px 12px;
    background: #f0f4f8;
    border-radius: 4px;
    border-left: 3px solid #0066cc;
}
.characters-list {
    margin-top: 8px;
}
.character-card {
    background: #f0f4f8;
    border-radius: 4px;
    padding: 10px 12px;
    margin-bottom: 8px;
    border-left: 3px solid #28a745;
}
.character-card .name {
    font-weight: 600;
    color: #333;
    margin-bottom: 4px;
}
.character-card .role {
    display: inline-block;
    font-size: 12px;
    padding: 2px 8px;
    background: #0066cc;
    color: #fff;
    border-radius: 10px;
    margin-left: 8px;
}
.character-card .detail {
    font-size: 13px;
    color: #555;
    margin-top: 4px;
}
.character-card .detail .key {
    color: #888;
}
.body-text {
    font-size: 14px;
    line-height: 1.8;
    color: #333;
    max-height: 500px;
    overflow-y: auto;
    padding: 12px;
    background: #fff;
    border-radius: 4px;
    border: 1px solid #eee;
    white-space: pre-wrap;
}
.scoring {
    margin-top: 20px;
    padding: 16px;
    background: #fff;
    border-radius: 8px;
    border: 1px solid #eee;
}
.scoring-title {
    font-size: 14px;
    font-weight: 600;
    margin-bottom: 12px;
    color: #333;
}
.score-row {
    display: flex;
    align-items: center;
    margin-bottom: 10px;
    gap: 10px;
}
.score-row .score-label {
    width: 120px;
    font-size: 13px;
    color: #555;
    flex-shrink: 0;
}
.score-row .stars {
    display: flex;
    gap: 4px;
}
.score-row .star {
    font-size: 22px;
    cursor: pointer;
    color: #ddd;
    transition: color 0.15s;
    user-select: none;
}
.score-row .star:hover,
.score-row .star.active {
    color: #ffc107;
}
.score-row .comment {
    flex: 1;
    padding: 6px 10px;
    border: 1px solid #ddd;
    border-radius: 4px;
    font-size: 13px;
    font-family: inherit;
}
.score-row .comment:focus {
    outline: none;
    border-color: #0066cc;
}
.footer {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    background: #fff;
    border-top: 1px solid #ddd;
    padding: 12px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    box-shadow: 0 -2px 4px rgba(0,0,0,0.05);
    z-index: 100;
}
.footer .info {
    font-size: 14px;
    color: #666;
}
.footer button {
    padding: 10px 24px;
    border: none;
    background: #0066cc;
    color: #fff;
    border-radius: 4px;
    cursor: pointer;
    font-size: 14px;
    font-weight: 500;
}
.footer button:hover {
    background: #0052a3;
}
.tag {
    display: inline-block;
    font-size: 11px;
    padding: 2px 6px;
    border-radius: 3px;
    margin-left: 6px;
}
.tag.warning {
    background: #fff3cd;
    color: #856404;
}
</style>
</head>
<body>

<div class="header">
    <h1>📝 标注质量审核</h1>
    <div class="stats">
        <span>总数: <b id="totalCount">0</b></span>
        <span class="good">已评: <b id="scoredCount">0</b></span>
        <span class="bad">未评: <b id="unscoredCount">0</b></span>
    </div>
    <div class="progress" style="margin-top: 8px;">
        <button onclick="exportData()" class="primary">💾 导出评分</button>
        <button onclick="loadData()">📂 加载评分</button>
        <button onclick="scrollToUnscored()">⬇️ 跳到未评分</button>
    </div>
</div>

<div class="container" id="container">
'''

    # 生成每个样本的 HTML
    for i, item in enumerate(data):
        meta = item['meta']
        
        html += f'''
<div class="sample" id="sample-{i}" data-index="{i}">
    <div class="sample-header">
        <div>
            <span class="title">样本 {i+1}</span>
            <span class="book">{item['book']} / {item['chapter']}</span>
        </div>
        <div>
            <span class="tag warning" id="tag-{i}" style="display:none;">已评分</span>
        </div>
    </div>
    <div class="sample-body">
        <div class="left-panel">
            <div class="section-title">📋 标注信息</div>
'''
        
        # 标注字段
        fields = [
            ('World', 'world'),
            ('Scene', 'scene'),
            ('Emotion', 'emotion'),
            ('Plot', 'plot'),
            ('Style', 'style'),
            ('POV', 'pov'),
        ]
        
        for label, key in fields:
            value = meta.get(key, '')
            if value:
                html += f'''
            <div class="annotation-field">
                <div class="label">{label}</div>
                <div class="value">{escape_html(str(value))}</div>
            </div>
'''
        
        # 角色
        characters = meta.get('characters', [])
        if characters:
            html += '''
            <div class="annotation-field">
                <div class="label">Characters</div>
                <div class="characters-list">
'''
            for char in characters:
                name = char.get('name', '')
                role = char.get('role', '')
                state = char.get('state', '')
                speech = char.get('speech', '')
                function = char.get('function', '')
                importance = char.get('importance', '')
                
                html += f'''
                    <div class="character-card">
                        <div>
                            <span class="name">{escape_html(name)}</span>
                            <span class="role">{escape_html(role)}</span>
                        </div>
'''
                if state:
                    html += f'<div class="detail"><span class="key">状态：</span>{escape_html(state)}</div>'
                if speech:
                    html += f'<div class="detail"><span class="key">说话：</span>{escape_html(speech)}</div>'
                if function:
                    html += f'<div class="detail"><span class="key">作用：</span>{escape_html(function)}</div>'
                
                html += '                    </div>\n'
            
            html += '''                </div>
            </div>
'''
        
        # 评分区域
        html += f'''
            <div class="scoring">
                <div class="scoring-title">⭐ 评分</div>
'''
        
        score_items = [
            ('scene_score', 'Scene 准确性'),
            ('plot_score', 'Plot 准确性'),
            ('character_score', '角色完整性'),
            ('emotion_score', '情感准确性'),
            ('style_score', '风格准确性'),
            ('overall_score', '总体评分'),
        ]
        
        for key, label in score_items:
            html += f'''
                <div class="score-row">
                    <div class="score-label">{label}</div>
                    <div class="stars" data-key="{key}" data-index="{i}">
'''
            for star in range(1, 6):
                html += f'<span class="star" data-value="{star}" onclick="setScore({i}, \'{key}\', {star})">★</span>'
            html += '''
                    </div>
                    <input type="text" class="comment" placeholder="备注..." 
                           data-key="comment" data-index="''' + str(i) + '''"
                           onchange="setComment(''' + str(i) + ''', this.value)">
                </div>
'''
        
        html += '''            </div>
        </div>
        <div class="right-panel">
            <div class="section-title">📖 正文原文</div>
            <div class="body-text">''' + escape_html(item['body'][:3000]) + '''</div>
        </div>
    </div>
</div>
'''
    
    # 关闭标签并添加 JavaScript
    html += '''
</div>

<div class="footer">
    <div class="info">
        <span id="footerInfo">点击星星评分，评价完点击右上角"导出评分"</span>
    </div>
    <button onclick="exportData()">💾 导出评分数据</button>
</div>

<script>
const TOTAL_SAMPLES = ''' + str(len(data)) + ''';
const STORAGE_KEY = 'annotation_review_scores';

let scores = {};

// 加载已保存的评分
function loadScores() {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
        scores = JSON.parse(saved);
        renderScores();
    }
}

// 保存评分
function saveScores() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(scores));
    updateStats();
}

// 设置分数
function setScore(index, key, value) {
    if (!scores[index]) scores[index] = {};
    
    // 点击相同星星取消
    if (scores[index][key] === value) {
        delete scores[index][key];
    } else {
        scores[index][key] = value;
    }
    
    renderScore(index, key);
    saveScores();
}

// 渲染分数
function renderScore(index, key) {
    const starsContainer = document.querySelector(`.stars[data-key="${key}"][data-index="${index}"]`);
    if (!starsContainer) return;
    
    const value = scores[index] && scores[index][key] ? scores[index][key] : 0;
    const stars = starsContainer.querySelectorAll('.star');
    
    stars.forEach((star, i) => {
        if (i < value) {
            star.classList.add('active');
        } else {
            star.classList.remove('active');
        }
    });
}

// 设置备注
function setComment(index, value) {
    if (!scores[index]) scores[index] = {};
    scores[index].comment = value;
    saveScores();
}

// 渲染所有分数
function renderScores() {
    for (const index in scores) {
        for (const key in scores[index]) {
            if (key !== 'comment') {
                renderScore(index, key);
            }
        }
        // 渲染备注
        const commentInput = document.querySelector(`.comment[data-index="${index}"]`);
        if (commentInput && scores[index].comment) {
            commentInput.value = scores[index].comment;
        }
    }
}

// 更新统计
function updateStats() {
    let scored = 0;
    let unscored = 0;
    
    for (let i = 0; i < TOTAL_SAMPLES; i++) {
        if (scores[i] && scores[i].overall_score) {
            scored++;
            document.getElementById(`tag-${i}`).style.display = 'inline-block';
        } else {
            unscored++;
            document.getElementById(`tag-${i}`).style.display = 'none';
        }
    }
    
    document.getElementById('totalCount').textContent = TOTAL_SAMPLES;
    document.getElementById('scoredCount').textContent = scored;
    document.getElementById('unscoredCount').textContent = unscored;
    document.getElementById('footerInfo').textContent = `已评 ${scored}/${TOTAL_SAMPLES}，未评 ${unscored}`;
}

// 滚动到下一个未评分
function scrollToUnscored() {
    for (let i = 0; i < TOTAL_SAMPLES; i++) {
        if (!scores[i] || !scores[i].overall_score) {
            document.getElementById(`sample-${i}`).scrollIntoView({ behavior: 'smooth', block: 'start' });
            return;
        }
    }
    alert('所有样本都已评分！');
}

// 导出数据
function exportData() {
    const result = {
        exportTime: new Date().toISOString(),
        totalSamples: TOTAL_SAMPLES,
        scoredCount: Object.keys(scores).filter(k => scores[k].overall_score).length,
        scores: scores
    };
    
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `annotation_scores_${new Date().toISOString().slice(0,10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
}

// 加载数据
function loadData() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = (e) => {
        const file = e.target.files[0];
        const reader = new FileReader();
        reader.onload = (event) => {
            try {
                const data = JSON.parse(event.target.result);
                scores = data.scores || {};
                saveScores();
                renderScores();
                updateStats();
                alert('加载成功！');
            } catch (err) {
                alert('加载失败：' + err.message);
            }
        };
        reader.readAsText(file);
    };
    input.click();
}

// 初始化
loadScores();
updateStats();
</script>

</body>
</html>
'''
    
    return html

def escape_html(text: str) -> str:
    """转义 HTML"""
    return (text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&#39;')
    )

def main():
    import argparse
    parser = argparse.ArgumentParser(description="生成审核打分 HTML")
    parser.add_argument("--sample-size", type=int, default=20, help="抽取数量")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--output", default="review.html", help="输出文件")
    parser.add_argument("--book", default=None, help="只抽检特定书籍")
    args = parser.parse_args()
    
    if args.book:
        # 只处理特定书
        book_dir = Path("cleaned") / args.book
        if not book_dir.exists():
            print(f"找不到书籍: {args.book}")
            return
        
        chapters = sorted(book_dir.glob("*.md"))
        random.seed(args.seed)
        samples = random.sample(chapters, min(args.sample_size, len(chapters)))
        
        # 直接生成
        data = []
        for md_path in samples:
            meta, body = read_chapter(md_path)
            data.append({
                'file': str(md_path),
                'book': md_path.parent.name,
                'chapter': md_path.stem,
                'meta': {
                    'world': meta.get('world', ''),
                    'scene': meta.get('scene', ''),
                    'emotion': meta.get('emotion', ''),
                    'plot': meta.get('plot', ''),
                    'style': meta.get('style', ''),
                    'pov': meta.get('pov', ''),
                    'word_count': meta.get('word_count'),
                    'characters': meta.get('characters', []),
                },
                'body': body,
            })
        
        html = generate_html_content(data)
        Path(args.output).write_text(html, encoding='utf-8')
        print(f"HTML 文件已生成: {args.output}")
    else:
        generate_html(args.sample_size, args.seed, args.output)

if __name__ == "__main__":
    main()