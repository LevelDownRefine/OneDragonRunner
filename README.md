# OneDragonRunner

脚本链运行器，从 OneDragon-ScriptChainer 移植，作为独立仓库维护，仅保留不含 opencv/pynput 的纯编排部分。脚本编排思路同时参考 AUTO-MAS 的多脚本统一管理设计。

## 运行

由 OneDragon-Helper 的 GUI 通过子进程调用：

```bash
python -m src.runner.launcher --chain <config_path> [--debug-index <i>]
```

--chain <config_path>：脚本链配置文件路径，.yml，相对路径以项目根为基准，例如 config/script_chain/88.yml。
--debug-index <i>：可选，仅运行第 i 条脚本及其挂靠组；省略则运行整条链。

整条链运行时，每条脚本按配置中的 block 字段决定行为：block: true 默认阻塞等待完成；block: false 后台启动并继续下一条，整链末尾统一等待所有后台脚本完成后再退出。非阻塞仅对外部脚本生效；script_type: python 在当前进程内 exec，无法后台化，始终阻塞运行。

依赖 ruamel.yaml / colorama / psutil。

## 无日志超时

阻塞外部脚本设置 `no_log_timeout_seconds > 0` 后，控制台输出与 `log_path`
文件变化任一有活动就刷新计时。两者持续静默才强制关闭受管脚本进程，并按
`no_log_max_retries` 重试；重试次数为 `0` 仍会关闭，只是不重试。

```yaml
log_path: data/apps/ok-ef/working/logs/ok-script.log
no_log_timeout_seconds: 300
no_log_max_retries: 1
```

`log_path` 相对脚本所在目录，也可填绝对路径或 `%TEMP%/` 开头的路径。
支持文件名通配符（如 `logs/*.log`），不扫描子目录；留空则只检测控制台输出。
`log_analysis_path` 是助手的运行后分析设置，runner 不使用它。

文件检测复用每秒轮询，只比较文件大小、修改时间和文件标识，不读内容、不加线程或依赖。
每次启动前建立基线；已有日志不变不算活动，新增、改写、截断及轮转均可检测。
文件暂时缺失会继续等待；访问失败会记录警告，仍按现有无日志期限判定。
计时使用单调时钟，不受系统时间调整影响。超时为 `0`、非阻塞或 Python 类型脚本不监测文件。
该检测只判断是否有日志活动，不判断内容是否有效；持续重复写日志也会刷新计时。
启动器启动的脚本仍需按原规则配置 `launcher_mode` 与实际运行的进程名。
