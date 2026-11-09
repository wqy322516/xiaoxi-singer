# 原创歌曲（Original songs）

翻唱是「有现成的歌，换嗓子」；原创是「没有歌，从一句话/一张图长出一首歌」。
这条链路把两件事接起来：

```
需求（文字，可带图）
  └─> ACE-Step（text2music：人声 + 伴奏一起生成）
        └─> MDX-Net Kim_Vocal_2 分离出人声
              └─> RVC（xiaoxi_ft_e45 音色）换声
                    └─> 后期 + 混音 -> mp3 / mp4
```

最后一步决定了「这是小汐在唱」——生成的曲子只是素材，嗓子永远是**自己训练的那版模型**。

## 快速开始

```bash
# 只用 CLI
xiaoxi-singer compose "夏日傍晚骑着单车穿过老街，温柔的民谣，女声" \
    --duration 90 --out-dir runtime/demo

# 带歌词
xiaoxi-singer compose "古风、清冷、箫与古筝" --lyrics 词.txt --duration 120

# 带图（需要 VISION_* 配置）
xiaoxi-singer compose "按这张图做一首歌" --image cover.jpg
```

```python
from xiaoxi_singer.original import compose

r = compose("赛博朋克城市夜景，电子、女声、克制", duration=100)
print(r.final)      # 混音成品 mp3
print(r.prompt)     # 实际送给 ACE-Step 的提示词
```

Agent 里对应工具：`compose_song(brief, lyrics?, image?, duration?, seed?)`。

## 环境

ACE-Step 的依赖（diffusers 0.32.2 / transformers 4.50）和 RVC 用的那份会打架，所以**不进主环境**：

```bash
# 1) 依赖目录（含 acestep + diffusers + transformers）
XIAOXI_ACESTEP_LIBS=/path/to/pylibs      # 默认 <repo>/orig/pylibs

# 2) 权重目录（必须含这四个子目录）
XIAOXI_ACESTEP_MODEL=/path/to/ace-step   # 默认 <repo>/models/ace-step
#   ace_step_transformer/  music_dcae_f8c8/  music_vocoder/  umt5-base/
```

权重来自 `ACE-Step/ACE-Step-v1-3.5B`（约 6.6 GB）与 `google/umt5-base`（约 2.4 GB）。
国内拉可以用 hf-mirror，加 `-C -` 断点续传。

## 多模态：看图猜需求

`original.describe_image()` 走 OpenAI 兼容的多模态端点：

```bash
VISION_BASE_URL=https://api.siliconflow.cn/v1
VISION_API_KEY=sk-...
VISION_MODEL=Qwen/Qwen2.5-VL-72B-Instruct
```

返回 JSON：`{theme, mood, genre, instrumentation, tempo, lyrics_outline}`，
其中 `genre`/`mood` 会被拼进 ACE-Step 的提示词。

没有配置时 `compose()` **不会失败**，只是跳过图片（`image_brief` 为空），
Agent 会提醒用户用文字描述图片内容。

## 参数与取舍

| 参数 | 默认 | 说明 |
|---|---|---|
| `duration` | 90s | ACE-Step 支持到约 240s；越长越容易糊 |
| `steps` | 60 | 推理步数，降低会更快更糙 |
| `guidance` | 15.0 | 越大越贴提示词，太大发硬 |
| `seed` | 随机 | 固定 seed 可复现同一首 |

## 已知失败模式

- **生成的人声本身就很差**：ACE-Step 的中文咬字时好时坏，换声救不回发音。
  挑 seed / 改歌词结构（`[verse]` `[chorus]`）比调后期有效。
- **分轨不干净**：Kim_Vocal_2 对「人声 + 大量混响」的生成音频容易漏，
  漏了会听到两条人声（生成的原声 + 小汐）。把生成结果的 `prompt` 里加 "dry vocal" 有帮助。
- **显存**：8 GB 上 `dtype=bfloat16` 可以跑；`cpu_offload=True` 更省但慢一倍。
- **时长对不上**：分离后两条轨可能差几百毫秒，`mix_cover` 会按较短的截断。
