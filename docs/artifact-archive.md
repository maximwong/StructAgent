# 本机历史产物归档

适用于阶段5工作流使用的输出根目录。默认只列出运行编号、状态、可归档文件数和字节数，不删除工程文件。归档是本机存储管理，不是跨设备工程数据库同步。

```powershell
python -m examples.archive_runs
python -m examples.archive_runs --archive <工作流run_id>
python -m examples.archive_runs --restore <工作流run_id>
```

自定义项目目录时，三条命令都添加 `--output-root <原输出根目录>`。归档文件及SHA256索引位于该目录的 `archives/`。首次归档保留原文件；核对压缩包、每个成员的SHA256和来源归属后，显式清理命令可回收源产物空间：

```powershell
python -m examples.archive_runs --archive <尚未归档的工作流run_id> --compact
```

`--compact` 必须在创建该次归档时明确给出。已有归档不被覆盖，也不靠修改历史SQL终态重复归档。清理仅移除本次归档中已核验的文件；设计结果引用、SQLite数据库、CAD会话/恢复隔离日志均保留。恢复在原输出根目录执行，不调用API、计算工具或AutoCAD；已有内容不同的文件不会被覆盖。

只接受COMPLETED/FAILED/INTERRUPTED且没有未解决外部调用的工作流。工程工具目录还须有匹配project_id、tool、run_id、目录及终态的工具数据库记录；启动过外部操作的目录须有本次验证回执证明工具文档已关闭。缺失结果、未知归属、链接、越界路径、RUNNING或RECOVERY_REQUIRED一律保留，不能删除它们绕过CAD恢复保护。没有工程产物的解析失败仍保留SQL诊断。

状态查询继续返回原来的设计/执行结论，另附 `artifact_archive.path` 和 `requires_restore`。归档不使失败变成功。清理后先恢复，再使用原DWG路径。SHA256用于检测损坏与意外变更，不是数字签名；归档和本机索引应一起备份。

本阶段对新运行的真实DWG进行保留源文件的归档/恢复核验；实际删除与恢复仅在测试夹具中验证，没有清理此前阶段的基线图纸。自动按日期淘汰、配额调度及未解决故障目录的人工处置仍在Demo后规划。
