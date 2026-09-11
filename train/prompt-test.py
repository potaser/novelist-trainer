from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

base_model = "Qwen/Qwen2.5-7B-Instruct"
lora_path = "./output/qwen2.5-novel-lora"

tokenizer = AutoTokenizer.from_pretrained(base_model)
model = AutoModelForCausalLM.from_pretrained(base_model)
model = PeftModel.from_pretrained(model, lora_path)

prompt = """[世界观] 现代都市，娱乐圈背景
[当前场景] 深夜办公室，两人独处
[情感基调] 暧昧、试探
[剧情要点] 顾言发现陆沉在暗中帮自己
[写作风格] 心理描写细腻，对话含蓄
[人物状态]
- 陆沉（攻）：表面冷静，内心关心
- 顾言（受）：惊讶，感动
[视角] 顾言

请写出本章正文："""

inputs = tokenizer(prompt, return_tensors="pt")
outputs = model.generate(**inputs, max_new_tokens=2000)
print(tokenizer.decode(outputs[0], skip_special_tokens=True))