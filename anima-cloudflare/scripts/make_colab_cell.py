#!/usr/bin/env python3
"""產生 Colab 儲存格（金鑰從 .private/relay-keys.json 自動填入，本機完成，不外流）。

用法：python scripts/make_colab_cell.py > colab_cell.py
再把 colab_cell.py 的內容貼進 Colab 第一格。
"""
import base64
import json
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent
keys = json.loads((root / '.private/relay-keys.json').read_text(encoding='utf-8'))
agent_src = (root / 'vm/agent_diffusers.py').read_text(encoding='utf-8')
agent_b64 = base64.b64encode(agent_src.encode()).decode()

cell = f'''# Anima 生圖節點（Colab GPU）— 執行本格即上線
!pip -q install diffusers transformers accelerate safetensors huggingface_hub sentencepiece

import base64, os
AGENT_KEY = {keys['AGENT_KEY']!r}
RELAY_URL = "https://anima.s92137123.workers.dev"

# 寫出節點程式（與 repo 的 vm/agent_diffusers.py 同步）
code = base64.b64decode("{agent_b64}").decode()
open("agent_diffusers.py", "w").write(code)

os.environ["AGENT_KEY"] = AGENT_KEY
os.environ["RELAY_URL"] = RELAY_URL
# 首選模型：本地 JANKU 不在 Colab，用 HF 上對應的社群模型（可自行換）
os.environ["DEFAULT_MODEL"] = "cagliostrolab/animagine-xl-4.0"
os.environ["TURBO_LORA"] = ""   # Colab 先不鎖 turbo lora；要用再填 HF repo

import runpy
runpy.run_path("agent_diffusers.py", run_name="__main__")
'''

pathlib.Path('colab_cell.py').write_text(cell, encoding='utf-8')
print('colab_cell.py 已產生（金鑰已填，僅存在本機）')
