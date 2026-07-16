# 低 Token 测试门禁

`scripts/test_gate.py` 统一选择和执行测试。它不会删除既有测试，也不会调用真实来源、AI、Worker 或 scheduler。

常用命令：

```bash
python scripts/test_gate.py snapshot --output /tmp/impact.json
python scripts/test_gate.py plan --snapshot /tmp/impact.json --json
python scripts/test_gate.py run --snapshot /tmp/impact.json --mode targeted
python scripts/test_gate.py run --mode full
python scripts/test_gate.py run --mode release
```

CI 使用 `--base <sha> --head <sha>` 生成同一种 impact plan。退出码为 `0`（通过）、`1`（测试失败）、`2`（快照、映射或环境配置错误）。选择器唯一映射文件是 `tests/test_impact_map.json`；未知可执行路径、依赖清单或构建配置会升级到 full。

完整命令日志和 `result.json` 位于 `.test-results/<run-id>/`，文件权限为 `0600`。stdout 成功摘要不超过 2 KiB，失败摘要不超过 8 KiB，并只包含首个失败和最多 80 行精简输出。不要把完整日志自动读入 Codex；摘要不足时只读取对应日志的必要区段。

当前为 10 个不同 CI 提交的观察期，默认完成门禁仍是 `full`。每次观察都必须满足 selector 无错误、`mapping_miss=false`、摘要与完整日志一致。达到 10 次后才能单独更新项目规则，将日常默认改为 `targeted`；PR/main、合并和发布继续永久使用 `full/release`。
