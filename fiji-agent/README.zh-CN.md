# Fiji AI agent 环境

位置：`C:\Users\ethan\OneDrive - University of Cambridge\summer_project\fiji-agent`

- Python：3.11.16，项目内独立运行时和 `.venv`。
- PyImageJ：1.8.0；Fiji MCP server：0.2.0；FastMCP：2.14.7。
- 现有 Fiji：`C:\Users\ethan\Desktop\Fiji`。
- 现有 Java：Fiji 自带 Zulu Java 21.0.7。
- 原始 MCP 可执行文件：`.venv\Scripts\fiji-mcp-server.exe`。
- Codex 启动入口：`.venv\Scripts\python.exe start_fiji_mcp.py`。
- 默认模式：headless。

## 使用

在此文件所在目录运行：

```powershell
& '.\.venv\Scripts\python.exe' '.\test_pyimagej.py'
& '.\.venv\Scripts\python.exe' '.\test_mcp.py'
& '.\.venv\Scripts\python.exe' '.\test_codex.py'
```

无需激活环境或修改系统 PATH。普通 Python 脚本可使用：

```python
import imagej
ij = imagej.init(r'C:\Users\ethan\Desktop\Fiji', mode='headless')
try:
    print(ij.getVersion())
finally:
    ij.dispose()
```

Codex 配置候选在 `codex-fiji.snippet.toml`。必须经用户批准后才能执行
`install_codex_config.py`；该脚本会备份用户 config.toml，仅追加 fiji 段，
并校验原有配置完全保留。配置写入后用 `test_codex.py --saved` 检查。
`test_codex.py` 默认仅以进程参数预览配置，不写全局文件。

## Windows 兼容处理

`fiji_runtime.py` 经虚拟环境专用 `.pth` 文件加载，限定于此环境：

1. 固定 Fiji 自带 Java 21，避免 scyjava 默认下载其他 Java。
2. 仅在 Python 子进程内加入 Java bin；不改用户或系统 PATH。
3. 绕过 jgo Windows JAVA_HOME 路径遗漏 `.exe` 的问题。
4. 从官方仓库补齐 3 个 Java 桥接库，放在 `bridge-jars`，复用 Fiji 现有其他 JAR，
   不修改 Fiji 安装。启动无需 Maven 联网。
5. `start_fiji_mcp.py` 在主线程启动 JVM 后再启动原始 MCP 服务，修复实测首次工具调用
   在线程内启动 JVM 卡住的问题。Java 和 Python 诊断都走 stderr，保持 stdio 协议有效。
6. Java Preferences 使用内存存储；Java user.home 指向项目目录，避免读写用户全局偏好。
   偏好不会跨服务器重启保存。GUI 专用插件可能无法在 headless 中运行。

## 验证记录

- `pyimagej-test-result.json`：真实 ImageJ 启动、headless、NumPy 图像往返和宏写入像素。
- `mcp-test-result.json`：真实 MCP 握手、9 个工具、get_state 返回 READY/headless。
- `codex-preview-test-result.json`：Codex app-server 临时配置下实际发现的工具。
- `codex-saved-test-result.json`：批准写入后生成的持久配置验证结果。
- `requirements.lock.txt`：107 个 Python 包的版本锁定；依赖检查通过。

此前失败日志保留用于排查；以最终测试结果为准。没有主动删除任何现有文件。

参考：
- https://pypi.org/project/fiji-mcp-server/0.2.0/
- https://py.imagej.net/en/latest/Initialization.html
- https://developers.openai.com/codex/mcp

## 已完成的全局配置（2026-09-29）

已获得用户批准，追加写入 `C:\Users\ethan\.codex\config.toml`，原有配置校验保持不变。
备份：`C:\Users\ethan\.codex\config.toml.before-fiji-20260929-183649.bak`。
保存后的配置已通过 Codex app-server 实测，发现全部 9 个 Fiji MCP 工具。
详见 `config-install-result.json` 和 `codex-saved-test-result.json`。
当前旧聊天尚未加载新增工具；重新打开 Codex 后再使用 Fiji 工具。
