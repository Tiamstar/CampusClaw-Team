# 本地性能基线与词法检索优化

执行者Codex；独立成员未确认最终容量/RPO/RTO目标。本报告是可重复工程测量，不代替团队冻结目标或公网验收。

## 固定环境和口径

- Docker Desktop Linux，20个可见CPU、8151900160字节内存，Docker Server28.1.1；同机PostgreSQL16/pgvector、Gunicorn2个Uvicorn worker。现有worker和监控运行；不停止审计、不绕过认证、不使用数据库结果缓存。
- 固定k6镜像`grafana/k6:1.4.1`，digest `sha256:200d24a0770ad12761569993c723fd7d48b29fc7983ff5f976bf8b8dba4c7d21`。脚本`scripts/benchmark.js`，原始报告`reports/before20-*.json`、`after20-*.json`、`afterstats20-*.json`。时间包含HTTP、JWT、服务端业务和访问审计，不包括浏览器绘制。
- 保留课程10（课程码5LDUKQ8V），实际教师/学生均已加入。查询作业11固定20个历史版本；新提交写作业12。所有虚拟客户端使用同一个授权学生账号，**不是20名学生或20个账号**，因此写入会争用同一Submission行锁。这是单账号重复提交场景，不能外推多人提交上限。
- 资料8为固定随机种子20261116的10000段合成英文词法语料，TXT与数据库片段都保留，无真实课程文本。散列`f60812cd33bf440cfc8eab1ab32142f4ba5f7b707a61d5823e2c2febe151c57d`。直接创建ready片段以隔离检索性能，**不代表真实解析/Embedding索引吞吐**；没有伪造向量或模型用量。
- 基线/优化后分别按search→query→submit串行执行，每项20VU、60秒。search/query每轮1秒思考，submit每轮5秒思考；submit每轮产生一个独立键的201，再原样重放一次，要求200且version_id一致。两次HTTP的延迟合并统计（不是单次事务的分位数），新增201数量与重放200数量分别保留。固定查询样本不会因并发提交增长。
- keyword查询`benchmarkneedle`必须仅命中一个片段。固定输入/既有GET/201与幂等回放均检查业务结果，不以HTTP200本身作为有效检索证据。读接口不调用Embedding/LLM；提交不排队批改，**不能将受理容量当作AI任务完成吞吐**。
- 脚本失败率<1%、业务断言>99%为本轮自测阈值；未事后降低阈值。最终响应时间SLO、可接受队列积压和多人容量仍待团队确认。

## 优化与迁移

基线EXPLAIN ANALYZE在10016个总片段上执行约268.45ms，原entry_id索引仍需逐行算trigram相似度。本轮仅增加`ready_chunk_text_trgm`，GIN `gin_trgm_ops`，部分条件`status='ready'`；查询、身份、课程/资料/片段ready约束、相似度阈值和排序不变。

迁移0020使用AddIndexConcurrently、atomic=False，减少建索引期间的写入阻塞；异常中断可能留下invalid index，应人工核查并通过并发DROP后重试，不静默假称成功。增加索引有磁盘/写入维护成本，不是免费加速所有查询。

主库迁移前已经pg_dump，仓库外`../.backups/before-bench-index-20261116.dump`。恢复到独立`bench_restore_20261116`，迁移通过且indisvalid=True；课程6仍存在、提交4仍5.00/revision4、报告和快照各1份、总片段10016。独立恢复库不对外暴露；主库已应用0020，随后刷新三张关联表统计信息；备份包含固定查询和语料，创建于新提交压测前。首次索引存在时规划器仍因关联表统计过旧选择entry_id索引，after20整组没有收益；保留该组而不筛除。对core_material、core_knowledgeentry和core_knowledgechunk执行ANALYZE后，规划器使用ready_chunk_text_trgm，SQL计划实际0.674ms。迁移已包含三表ANALYZE。原始SQL计划见bench-plan-before.json、bench-plan-after.json（仅建索引时未命中新索引）与bench-plan-after-analyze.json。

## 复现

先用`prepare_benchmark --teacher <现有教师邮箱> --student <现有学生邮箱> --output /private/benchmark-private.json`创建**新**保留课程。私有JSON含短期JWT，存仓库外受控路径，禁止提交、打印或放进报告。每次独立复现RUN_ID必须更换，避免把已存在的幂等重放误当新提交；一组前后对照共用固定夹具。令牌8小时失效，不改密码或开新权限。

```powershell
docker run --rm --network campusclaw-team_default -v '<仓库>/scripts:/scripts:ro' -v '<私有目录>:/private:ro' -v '<仓库>/reports:/results' -e FIXTURE=/private/benchmark-private.json -e RUN_ID=before20 -e TARGET=search -e VUS=20 -e DURATION=60s -e THINK_SECONDS=1 grafana/k6:1.4.1 run /scripts/benchmark.js
```

query同参数；submit改TARGET=submit且THINK_SECONDS=5。保留全部生成记录，不删除真实用户课程或历史提交。基线先运行，再迁移0020；仅索引组换RUN_ID=after20；索引+三表统计刷新组换RUN_ID=afterstats20，运行同样三个目标。正式数据库已有该索引时不能把它当无索引基线，应在隔离恢复库复现，避免临时移除主库索引。

## 实际结果

20VU×60秒每个目标均完成，HTTP错误率0、业务断言失败0。固定历史查询P95由61.26ms变77.04ms，不能声称有收益；提交/重放合并P95由154.75ms变134.71ms，单次差值不作容量承诺。检索P95由525.29ms变51.15ms（本轮约90.3%下降），req/s由14.23变19.34；在1秒思考的闭环脚本中该吞吐受思考时间封顶，不能当作最大容量。完整数值见bench-summary.json；后续容量阶梯结束后补表。

新增201与重复200各240次/轮，三轮合计720个新版本全部保留。固定查询作业仍20版本。纯建索引组检索P95反而542.60ms，完整保留，说明索引存在本身不证明优化生效。

这是同机单次工程对照，未证明统计置信区间：基线开头同时进行过独立恢复库的建索引验证，可能造成短时资源争用；后续未同时运行测试/构建。所有表/缓存状态和监控扫描不可能完全恒定，不能将全部HTTP差值严格归因于一个索引。数据库执行计划证据直接证明了访问路径变化；固定数据检索召回结果相同。正式容量应在独占、固定CPU/内存的验收机重复多轮。


容量探测保持同样语料、业务断言和JWT：search/query改为无思考时间，分别20/40/80VU、20秒；submit保持5秒思考，分别20/40/80VU、20秒。它们与60秒对照的负载不同，必须分表解释；短时探测不足以证明长期稳定性或最大并发。


| 运行 | 目标 | VU | 请求数 | req/s | P95 ms | 错误率 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| before20 | query | 20 | 1178 | 19.37 | 61.26 | 0.00% |
| before20 | search | 20 | 869 | 14.23 | 525.29 | 0.00% |
| before20 | submit | 20 | 480 | 7.81 | 154.75 | 0.00% |
| after20 | query | 20 | 1178 | 19.41 | 68.55 | 0.00% |
| after20 | search | 20 | 864 | 14.15 | 542.60 | 0.00% |
| after20 | submit | 20 | 480 | 7.78 | 154.67 | 0.00% |
| afterstats20 | query | 20 | 1173 | 19.30 | 77.04 | 0.00% |
| afterstats20 | search | 20 | 1160 | 19.34 | 51.15 | 0.00% |
| afterstats20 | submit | 20 | 480 | 7.80 | 134.71 | 0.00% |
| capacity20 | query | 20 | 2416 | 120.88 | 222.16 | 0.00% |
| capacity20 | search | 20 | 2825 | 141.33 | 228.66 | 0.00% |
| capacity20 | submit | 20 | 160 | 7.65 | 203.69 | 0.00% |
| capacity40 | query | 40 | 2316 | 115.12 | 460.72 | 0.00% |
| capacity40 | search | 40 | 2605 | 130.07 | 375.25 | 0.00% |
| capacity40 | submit | 40 | 320 | 14.63 | 464.97 | 0.00% |
| capacity80 | query | 80 | 2469 | 122.34 | 844.00 | 0.00% |
| capacity80 | search | 80 | 2650 | 130.01 | 743.30 | 0.00% |
| capacity80 | submit | 80 | 640 | 26.71 | 776.61 | 0.00% |

所有18项运行HTTP错误0、业务断言失败0、阈值通过。容量探测结果：search吞吐141.33→130.07→130.01req/s，query120.88→115.12→122.34req/s，二者从20VU起即表现平台，80VU主要增加排队；不能推断100VU以上性能。submit每轮新建+重放共160/320/640次HTTP，新增80/160/320条，仍受5秒思考限制，**没有找到提交饱和点**；不能把26.71HTTP req/s称为26.71份新提交/秒。

实测后核对：课程10的负载作业共1280版本，正式成绩0份、AI任务0项，固定查询仍20版本，片段10000。原提交4仍5.00/revision4，诊断报告/成绩快照各1份。索引有效，磁盘10272768字节（约9.8MiB）。一个资源瞬时采样：backend CPU33.06%、内存688.5MiB；db CPU303.35%、内存204MiB，仅为单时刻观测，不冒充完整资源曲线。所有记录保留。

脚本SHA256：`601afc11511e93b42f65e6b2740d7b39398a84eaf5aa78095e09651aae4aad79`。聚合命令`python scripts/summarize_benchmark.py`只读raw结果并重建摘要；不会筛除失败运行。原始JSON没有Authorization头或JWT。


统一检查通过：174后端、72前端测试与生产构建，7项规约严格校验通过。安全检查exit0，原7项前端中危开发依赖与包体提示保留。最终迁移在独立恢复库回退/重建成功；学生浏览器确认第1280版作答可见，截图在仓库外。单个作业保留1280版会增大原有全历史接口与页面负担，该接口的大历史分页并不在本轮固定20版查询测量内，不能据此声称任意历史长度达标。
