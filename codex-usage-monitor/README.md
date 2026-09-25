# Codex Usage Monitor

Windows 11 本地桌面监控工具。它读取已登录的本地 Codex CLI App Server 的只读速率限制状态，并显示 5-hour 与 Weekly 窗口；不需要 OpenAI API Key，不上传数据。

## 安装与启动

需要 Windows 11、Python 3.10+、已安装并登录 Codex CLI/Desktop。

```powershell
cd codex-usage-monitor
python -m pip install -r requirements.txt
python main.py --status
python app.py
```

`main.py --diagnostics` 会运行只读的本机诊断。桌面版提供刷新、托盘、通知和 History 按钮。

## Usage 数据来源与可信等级

读取器仅启动本地 `codex app-server`，并调用官方文档提供的只读 `account/rateLimits/read`。它仅接受 `limitId=codex`、300 分钟与 10080 分钟的窗口，映射为 5-hour 和 Weekly。`usedPercent` 与 `resetsAt` 分别用于使用率和重置时刻。

来源显示为 **Official**，但在你通过 `Codex → Settings → Usage` 对照前仍标记为 **unverified**。无法读取或格式改变时显示 `N/A`，绝不会伪造 0%。

## Recording 与 History

首次获得真实快照后立即采样，默认每 5 分钟写入 SQLite：`data/usage_history.db`（冻结 EXE 为 `%LOCALAPPDATA%\CodexUsageMonitor\data\usage_history.db`）。GUI 刷新默认 30 秒，与历史采样间隔独立。

`config/settings.json` 保存 `recording.enabled` 和 `recording.interval_minutes`；支持 1、2、5、10、15、30、60 分钟及任意正整数自定义间隔。Unknown 字段保存为 SQL `NULL`。

History 支持时间范围、来源/状态过滤、排序、100 条分页、Used/Remaining 图表和 UTF-8 CSV 导出。表格/图表查询以只读 SQLite 连接运行，不修改原始历史。

## Statistics 与 Exemption

统计支持 Today、24 Hours、7 Days、30 Days、Custom，并计算 Usage Delta、Peak Usage、Minimum Remaining、Average Change Rate、Window Count、Sample Count。5-hour/Weekly reset 会切断 delta 计算，因此不会产生跨窗口的负用量。

Exemption 是**仅本地统计豁免**：Daily、Weekly、One-Time 和 Manual 规则仍会采集并保存 Raw History，只是统计默认不纳入。它不能绕过 Codex 限额、修改 OpenAI Usage、恢复用量或降低官方 Usage。手动 Exclude/Include Again 只维护豁免元数据，不删除样本。

## Notifications、Tray 与备份

系统托盘可打开窗口、立即刷新、暂停自动刷新、打开设置或退出。默认会对 5-hour 与 Weekly 剩余量低于 30%/10% 各通知一次，并在窗口重置后重新启用。

备份时请先退出程序，再复制 `usage_history.db` 与 `settings.json`。CSV 可从 History 导出当前过滤视图、选中样本或全部样本。

## 打包

```powershell
.\build.ps1 -Python "D:\develop\Pycharm\python\python.exe"
```

生成 `dist\CodexUsageMonitor\CodexUsageMonitor.exe` 和 `dist\CodexUsageMonitor-portable.zip`。日常使用请解压 portable ZIP，再双击其中的 `CodexUsageMonitor.exe`；不要只复制 EXE，因为 Qt DLL 与插件必须和它一起保留。程序使用 `%LOCALAPPDATA%\CodexUsageMonitor` 存放用户数据，因此替换应用文件夹不会覆盖数据库或设置。

## 排障

- **Unable to read usage**：确认 Codex CLI 可执行、已登录，或运行 `python main.py --diagnostics`。网络不可用、未安装或读取响应格式改变时会安全失败。
- **History 空白**：等待首次真实采样，检查记录开关及 SQLite 文件是否可访问。
- **Database locked/corrupt**：关闭其他占用数据库的程序；记录器会保留界面运行并在下次采样重试。损坏文件请先备份后再处理。
- **数据不一致**：以 Codex Settings → Usage 为准；本工具的 Official 数据在人工对照前仍是 unverified。
