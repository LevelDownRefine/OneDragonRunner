"""脚本链运行器（vendored from OneDragon-ScriptChainer）。

本包是 OneDragon-ScriptChainer 子模块的本地移植，目的是让 OneDragon-Helper
摆脱对 git submodule 的依赖。仅保留「运行脚本链」所需的最小代码：

- ``script_chainer``：脚本链编排逻辑（启动子进程、监控、完成判定、重试）。
  已从原仓库去掉 gui / 配置编辑器 / 通知推送（ScriptChainerContext /
  LogNotifier / PushService）等可选模块。
- ``script_chainer/utils``：原 one_dragon 基础层（配置读写、路径、日志、进程
  工具等），已并入本仓库，不含 opencv/pynput 等游戏操控层。

``get_work_dir()`` 已重写为定位项目根目录（含 pyproject.toml 且含 src/ 的目录），
因此脚本链配置解析到 ``<项目根>/config/script_chain/``。

入口：``python -m src.runner.launcher --chain <config_path> --debug-index <i>``

其中 ``<config_path>`` 为脚本链配置文件路径（.yml），相对路径以项目根为基准
（例如 ``config/script_chain/88.yml``）。
"""
