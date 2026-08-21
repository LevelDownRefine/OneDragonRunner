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

依赖 pyyaml / colorama / psutil。
