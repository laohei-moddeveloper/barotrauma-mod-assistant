# 潜渊症模组更新助手 0.1.0

并行工坊更新请求与安装、缓存复用、文件校验、失败重试和备份恢复。

从仓库 Releases 下载本版本 Windows 压缩包，解压运行 EXE。详见 [使用说明](使用说明.md)。

本版本恢复自对应历史发布源码，22 项测试及重新构建后的独立程序自检通过。恢复及二进制重建说明见 [本版本发布记录](releases/v0.1.0.md)。

开发需要 Python 3.12；测试：`python -m unittest discover -s tests -v`。构建：创建 `.build-tools` 虚拟环境，安装 `requirements-build.txt`，再运行 `build.ps1`。

不附带原版游戏文件、第三方模组、个人配置或运行日志。
