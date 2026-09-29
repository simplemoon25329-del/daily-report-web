# 生产工作日报自动填表 · Web v1.0

本项目沿用 Desktop v1.0 的两阶段 DeepSeek 识别、词典提示、逐项核对、今日与明日对齐，以及原 Word 模板和 CSV 字段。家人使用手机或电脑浏览器访问时，无需安装 Python 或 EXE。

## 本地运行

建议使用 Python 3.11。Windows PowerShell 中进入本目录后执行：

```powershell
py -3.11 -m venv ".venv"
& ".venv\Scripts\python.exe" -m pip install -r "requirements-web.txt"
$env:DEEPSEEK_API_KEY = "your_deepseek_api_key_here"
& ".venv\Scripts\python.exe" -m streamlit run "app.py"
```

将示例值替换为自己的密钥，只在服务器环境中配置。不要将真实密钥写入代码、`.env.example` 或提交到 GitHub。无需 AI 时可不配置密钥，逗号文本模式仍可使用。

本机浏览器访问 `http://localhost:8501`。同一局域网内的手机可访问 `http://服务器局域网IP:8501`；需允许服务器防火墙通过对应端口。停止服务时在运行 Streamlit 的终端按 Ctrl+C。

Linux 服务器可用 Python 3.11 创建虚拟环境、执行 `python -m pip install -r requirements-web.txt`，在服务管理器中设置 `DEEPSEEK_API_KEY` 环境变量，再运行 `python -m streamlit run app.py --server.address 0.0.0.0`。公网建议在前面配置 HTTPS 反向代理。程序只在当前 Streamlit Session 的内存中保留输入和生成内容，不建数据库、不保存历史日报；Session 结束后内容可消失。Word 与 CSV 由页面按钮直接下载。

## Streamlit Community Cloud

项目根目录的 `requirements.txt` 会读取 `requirements-web.txt`。部署时选择 Python 3.11，在应用的 Secrets 设置中加入根级条目 `DEEPSEEK_API_KEY = "实际密钥"`；程序优先读取服务器环境变量，缺失时读取 Streamlit Secrets。真实密钥须由管理员本人在平台设置页填写，不要把本地 `.streamlit/secrets.toml` 或真实密钥提交到仓库。

当前版本不包含登录或访问认证，知道网址的人理论上可以使用应用并消耗 DeepSeek API 配额。若 GitHub 仓库保持 Private，Streamlit Community Cloud 默认会将应用也设为 Private；家人免登录使用前，应由管理员在应用设置中将**应用**设为 Public，仓库仍可保持 Private。当前项目尚未完成公网部署。

Web v1.0 是独立目录；Desktop v1.0 的 EXE、打包配置和发布包不参与 Web 部署。Web 版保留无需 API 的逗号模式、人工编辑、Word 和 CSV 下载，不包含桌面启动器。
