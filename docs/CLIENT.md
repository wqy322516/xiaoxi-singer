# 桌面客户端

一个能双击打开的聊天窗口：下载 → 打开 → 说一句需求 → 看它一步步做 → 拿成品。
客户端本身很薄（Tkinter + 标准库 `urllib`，约 400 行），真正干活的是本地引擎
`xiaoxi_singer.localapp`（HTTP，默认 `127.0.0.1:8765`）。

```
┌──────────────┐   POST /chat      ┌────────────────────┐   工具调用    ┌──────────────┐
│  client.exe  │ ────────────────► │ localapp (Python)  │ ────────────► │ RVC + 后期   │
│  对话窗口     │ ◄──────────────── │  agent loop        │ ◄──────────── │ 混音 / 分析  │
└──────────────┘   GET /chat/{id}  └────────────────────┘               └──────────────┘
```

## 1. 打开

- **发布版**：`XiaoxiSinger.exe`（约 10 MB，无控制台窗口）。双击即可，第一次启动会读
  `%APPDATA%\xiaoxi-singer\client.json`；没有就连默认值。
- **源码版**：

  ```bash
  python client/desktop.py
  # 想让它自己跑一句话： python client/desktop.py --demo "把 xxx.wav 转成你的音色"
  ```

窗口左上角会显示 `引擎在线 · <模型文件名>`。若显示「引擎未连接」，客户端会拿配置里的
Python 去拉本地引擎；60 秒还连不上就说明解释器或依赖不对（见第 3 节）。

## 2. 用

1. 直接在输入框写任务，例如
   - `把 C:\a\vocal.wav 转成你的音色，存到桌面`
   - `把 vocal.wav 和 inst.wav 混成一首歌，响度对齐原曲`
   - `分析这段干声，告诉我适合的变调`
2. 也可以点「＋ 人声干声」「＋ 伴奏」选文件，路径会自动附在任务后面。
3. `Ctrl+Enter` 发送。中间会实时显示工具调用（`🔧 probe_audio [7.5s] {...}`），
   最后给出中文结论；有音频产物时会出现「打开成品文件夹」按钮。

没有写死的固定流程：先分析还是先转换、要不要变调、protect 取多少，都由模型看着中间结果决定。
换一句话说，**同一句需求换一种说法，它走的路可能不同，但目标是同一个**。

## 3. 设置

右上角「设置」可改：

| 字段 | 说明 |
| --- | --- |
| 引擎地址 | 默认 `http://127.0.0.1:8765`；也可以指向另一台机器的引擎 |
| Python 解释器 | 装了 `xiaoxi-singer` 的那个解释器（虚拟环境的 `python.exe`） |
| 项目目录 | 引擎进程的工作目录（源码运行时填仓库根目录） |
| LLM 接口 / 模型名 / API Key | 任何 OpenAI 兼容端点；默认 DeepSeek |
| 输出目录 | 生成文件的默认去处（模型也会参考它） |

保存后会写回 `%APPDATA%\xiaoxi-singer\client.json`（明文，只在本机）。

## 4. 自己打包

```powershell
python -m venv .buildvenv
.\.buildvenv\Scripts\pip install pyinstaller
.\client\build_client.ps1            # 产物：dist\XiaoxiSinger.exe
```

`build_client.ps1` 只打包 `client/desktop.py`（纯标准库 + tkinter），所以 exe 很小；
引擎仍由本机的 Python 环境提供，升级引擎不需要重新打包客户端。

## 5. 排错

| 现象 | 处理 |
| --- | --- |
| 引擎一直「未连接」 | 「设置」里的 Python 路径要指向装了本包的解释器；先在终端跑 `python -m xiaoxi_singer.localapp` 看能不能起来 |
| 发送后立刻报 401/403 | LLM Key 无效或额度用完 |
| 显示 `CUDA out of memory` | 显存被别的程序占了（TTS、浏览器硬件加速）；关掉再试，或把 RVC 指到 CPU |
| 中文乱码 | 用发布版 exe；源码运行时确保终端是 UTF-8（`chcp 65001`） |
