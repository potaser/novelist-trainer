# 网络小说 LoRA 语料清洗

**单一模型 + 结构化场景/风格指令**：所有题材混在一起，每个训练样本的 user 部分带上
`[世界观]`/`[当前场景]`/`[语言风格指令]`/`[剧情骨架]`，assistant 部分是对应的正文。
模型学的不是"某个题材怎么写"，而是"看到指令后如何切换写作模式"——旁白、主角内心
OS、不同配角的说话方式都可以在指令里分别约束（穿越文"OS现代+对话古代"这种混合文风
就是靠这个解决的，不需要单独拆题材）。

## 目录结构

```
noval/
├── raw/*.txt                      # 原始下载数据，直接扔进来，不用分类
├── cleaned/<book>/
│   ├── _book_meta.yaml            # 书级：tags(原站标签，参考用)/synopsis(原站简介，参考用)/
│   │                               # world(世界观)/style_template(角色风格模板)/banned_terms
│   └── 0001.md, 0002.md, ...       # 章节级：scene(当前场景)/plot_outline(剧情骨架)/
│                                    # style_overrides(本章对 style_template 的补充或覆盖) + 正文
├── export/train.jsonl             # 最终训练集：messages 格式（兼容 LLaMA-Factory/ms-swift/
│                                    # unsloth 等主流微调框架，ChatML 模板由框架自己套）
├── cleaned/_corpus_index.jsonl     # 增量清洗用的索引：记录哪些书已经处理过(及签名)，
│                                    # 重跑 clean 时用来跳过已清洗的书，不用 --force 就不会碰它们
├── cleaned/_intra_dedup_log.txt   # 章节内重复段落删除记录
├── cleaned/_dedup_log.csv         # 整书查重丢弃记录
├── configs/
│   ├── ad_patterns.txt            # 广告行匹配规则，一行一个正则
│   └── tag_line_patterns.txt      # 正文里"标签：xxx"这类行的匹配规则（起草 world 的参考材料）
└── scripts/
    ├── cleaning.py                 # 编码修复/去广告/规范化/去重(书级+章节内)/分章
    ├── draft.py                    # 调用本地大模型起草 world/style_template/scene/plot_outline
    └── pipeline.py                 # CLI：clean / draft / flags / export
```

`_book_meta.yaml` 和每章 `.md` 的 frontmatter 里都有个 `flags` 字段（列表）：清洗时
自动检测到的可疑情况（章节数异常少、用了兜底分章规则、疑似重复段落、编码可能丢字）
会自动写进去，你自己看数据发现"这本书文笔差/机翻感重"之类，也可以直接手写进这个
列表。`python scripts/pipeline.py flags` 能把所有非空 flags 集中列出来，不用一本本翻。

## 用法

### 1. 清洗

```
python scripts/pipeline.py clean
```

对 `raw/*.txt` 做：编码自动识别转 utf-8 → 按 `ad_patterns.txt` 删广告行 → 规范化
空行/空白 → 去重（完全重复 + 近似重复，包括跟已经清洗过的老书比较） → 按"第X章"
切分（第一章之前的文案/简介/标签会被单独存成 `synopsis`，不算正文） → 检测并删除
**同一章内**大段重复粘贴的内容（真实数据里出现过，某些站点导出时会把一段内容原样/
略微改写地复制两遍）→ 写到 `cleaned/<book>/`。

**增量/大规模清洗**：`clean` 默认是增量的——`raw/` 里新加了多少本书，就只处理新加
的那些，已经清洗过的书（记录在 `cleaned/_corpus_index.jsonl` 里）会被跳过，不会
重新读取/解码/覆盖，这样才不会把你已经跑过 draft、人工审核过的内容冲掉。去重仍然
会拿新书跟"所有已清洗的老书"的签名比较，能查出跨批次的重复。所以大规模清洗的做法
就是：不断往 `raw/` 里加新书，每次都跑一遍 `python scripts/pipeline.py clean`，
它自己知道该处理哪些、该跳过哪些。想强制重新清洗某本书：要么删掉它在
`cleaned/_corpus_index.jsonl` 里的那一行 + 对应的 `cleaned/<book>/` 目录，要么整批
加 `--force` 重新处理一遍全部（会覆盖，谨慎用）。

这一步纯粹是正则/哈希运算，几百到几千本量级很快（几分钟量级）。真正慢的是下一步
的 `draft`，见下面的说明。

### 2. 起草 world / scene / plot_outline（数据标注）

```
python scripts/pipeline.py draft --scope book       # 起草缺 world 的书级 meta
python scripts/pipeline.py draft --scope chapters   # 起草缺 scene/plot_outline 的章节
python scripts/pipeline.py draft --scope all        # 两者都做
```

调用本地大模型（Ollama / vLLM 的 OpenAI 兼容 `/chat/completions` 接口，默认
`http://localhost:11434/v1`，`--llm-model` 默认 `qwen3:8b`，换成你实际拉的模型名）。

只填空字段，不会覆盖已经人工确认过的内容，可以反复重跑、增量处理新书——这意味着
标注也是"能做多少是多少"：先跑一批、人工审核修正一批，其余的随时可以再补，不用
一次性标完才能用。

**实测速度**：在你这台机器上用 `qwen3:8b`，哪怕是一句话的极简 prompt 也要 ~40 秒
（模型冷启动加载后），一整章正文的起草请求实测超过了 120 秒（已经把默认超时从
120 秒调到 300 秒）。按这个速度粗算，几千章全跑一遍 `--scope chapters` 可能要几天
——不是卡住了，就是这么慢，建议后台挂着长跑，不用干等。想加快可以考虑：
- 换一个更小的模型专门做起草这种轻量任务（比如 `ollama pull qwen3:1.7b` 之类），
  标注只是打草稿、后面还要人工审核，模型小一点、糙一点通常可以接受
- 先用 `--book` 只处理你要优先审核的书，别一次性对全部存量发起

审核工作台：打开 `cleaned/<book>/_book_meta.yaml` 和各章 `.md`，人工审核/修改起草结果：
- `world`：一句话世界观（书级，通常整本书共用一份）
- `style_template`：书级默认的角色说话风格模板（旁白/主角对话/其他有明显特征的配角群体
  + 禁用词），每章默认复用，只有某章出现新角色/新情况时才在该章的 `style_overrides`
  里补充或覆盖
- 每章的 `scene`（当前场景）、`plot_outline`（剧情骨架）
- 顺手看看 `flags` 字段，跑一遍 `python scripts/pipeline.py flags` 能集中看到所有
  自动检测出的可疑项（章节数异常少/用了兜底分章规则/疑似重复段落被删/编码可能丢字），
  也是你标"这个文件质量不行，先不用"的地方

### 3. 导出训练集

```
python scripts/pipeline.py export --out export/train.jsonl
python scripts/pipeline.py export --out export/train.jsonl --skip-flagged   # 排除带 flags 的内容
```

合并 书级 meta + 章节 frontmatter，渲染成
`[世界观]/[当前场景]/[语言风格指令]/[剧情骨架]` 的 user 提示，配上正文当 assistant
回复，写成 `{"messages": [{"role":"user",...}, {"role":"assistant",...}]}` 格式的
jsonl。`world`/`scene`/`plot_outline` 有空的章节也会导出，但命令行末尾会提示还有
多少条不完整；带 `flags` 的内容默认也会导出（只是提示一下），加 `--skip-flagged`
可以先把这些还没人工核实过的内容排除在训练集之外。

## 真实数据踩过的坑（都已经修好，记录一下供参考）

- **编码检测**：`chardet` 在低置信度时的猜测可能完全是错的（实测把一本正常的中文小说
  猜成 `koi8-u`，置信度只有 3.7%，整本解码成乱码）。现在只有置信度 ≥0.7 才采信 chardet，
  否则走 `utf-8`→`gb18030`→`big5`→`utf-16` 的固定顺序试解码。
- **去重算法**：最初用字符 4-gram + 频次加权的 simhash 做整书查重，在几十万字的长文本上
  会被高频虚词/标点"洗平"，导致两本完全不相关的书被判成 95% 相似（实测误删过一次）。
  换成了「12 字符片段集合 + MinHash 估计 Jaccard 相似度」，同样的假阳性案例上相似度
  直接变成 0。
- **章节切分**：不是所有书都用"第X章"，见过纯数字标题（"01""02"）和"☆、第1章 xxx"这种
  带装饰符号前缀的写法，都已经兼容。如果切出来发现某本书只有 1 章，大概率是遇到了新的
  标题格式，需要去 `cleaning.py` 的 `CHAPTER_RE`/`FALLBACK_CHAPTER_RE` 补规则。
- **章节内重复段落**：见"清洗"一节，个别站点导出的正文会把一整段内容复制/略微改写地
  粘贴两遍，`remove_intra_duplicate_blocks` 专门处理这个，删除记录在
  `cleaned/_intra_dedup_log.txt`，建议抽查几条确认没有误删故意重复的文学修辞。
- **路径**：`--out`/`--manifest` 这类参数如果传了带 `..` 的相对路径，会被写到 `noval`
  目录外面（真的发生过）。现在 `export` 的输出路径会先解析成绝对路径再校验必须落在
  `noval` 内，否则直接报错拒绝执行。

## 已知限制 / 后续可以做的事

- Windows 终端如果显示乱码（GBK 代码页），是控制台打印问题，不影响写出的文件内容
  （统一是 utf-8）；可以 `chcp 65001` 切一下代码页。
- `style_template`/`banned_terms` 目前完全靠 draft 起草 + 人工审核，没有做规则强制校验
  （比如没有真的检查正文里是否出现了 `banned_terms` 列表里的词）。
- 书级去重是全库 O(n²) 两两比较，几百到几千本量级没问题；如果以后语料涨到几万本以上，
  可能需要换成分桶/LSH 减少比较次数。
