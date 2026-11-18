# 完整备份与隔离恢复

关联 DLV-002 / AC-D02；本轮由 Codex 实现和本机自测，不替代组员交叉验收或团队恢复目标冻结。

## 执行

Docker Compose 的 db 和 backend 必须正常运行。使用 Python 标准库运行；Windows、Linux均通过参数数组调用Docker，不需要宿主机安装PostgreSQL客户端或读取`.env`。

```sh
python scripts/rehearse_recovery.py --backup-dir ../.backups/recovery-new-run
```

上述无参数来源仅对应仓库默认Compose项目，脚本忽略宿主`COMPOSE_*`隐式覆盖。生产部署必须明确项目和配置合并顺序，避免备份成另一个本地库：

```sh
python scripts/rehearse_recovery.py --backup-dir ../.backups/production-new-run --project campusclaw-production --env-file .env.production --compose-file docker-compose.yml --compose-file deploy/compose.production.yml
```

使用任何自定义环境/Compose文件时必须提供`--project`，文件必须存在，参数通过数组传给Docker，不拼接shell。凭据由Compose私下读取，不作为命令行密码传递，不打印完整配置或inspect环境。显式项目可单独用于同一基础配置的另一项目。

备份前核对db/backend均为运行中的常规Compose服务、属于同一选定项目，且后端配置指向该db共享网络别名、默认5432端口及相同数据库名/角色/密码。混用项目、one-off、停止服务、外部数据库或配置不符均失败，尚未导出快照或归档媒体。本工具不支持云数据库、非默认数据库端口或跨网络连接；这类部署应采用专门恢复流程，不能因找到本地db服务而误备份。校验只读容器元数据，公开证据仅记录项目/容器身份与镜像，不记录环境值。

生产覆盖及原默认项目的实际恢复结果见 [来源选择审核](../reports/recovery-source-selection.md)。

目标必须是仓库外的新目录；脚本拒绝覆盖已有目录，也不自动挑选或覆盖已有备份。备份数据库含账号密码哈希、令牌和教学数据，媒体含附件；在具有适当访问权限的私有目录执行，不上传Git、不发送给他人。POSIX新目录为0700，Windows继承父目录ACL，执行者需确认该父目录为私人目录；脚本不配置加密或远端备份。

## 一致性与隔离

1. 定位当前Compose真实服务容器，拒绝one-off容器；源库开启REPEATABLE READ READ ONLY事务，导出快照。在同一事务计算所有public表逐行排序的SHA256摘要；`pg_dump --snapshot`使用该快照，结束后释放只读事务。不会暂停源应用、修改业务记录或触发模型与邮件。
2. 归档媒体前后核对每个文件的大小和字节哈希，遇到变动或符号链接失败。文件字段引用必须能在归档中找到。需要选择无资料修改的安静窗口；数据库MVCC与文件系统不构成跨系统原子快照，不能声称支持并发覆盖附件下的原子备份。
3. 以源PostgreSQL镜像ID创建新数据库，使用专用内部网络、无主机端口；恢复镜像不接收源服务凭据，不运行Web、worker、模型或SMTP。内部网络中临时恢复角色使用trust认证，仅限这组隔离容器，不能将该配置用于线上服务。
4. `pg_restore --exit-on-error`重建约束和数据；相同实现比较全部表内容、文件内容与引用。序列不属于MVCC快照，因此只检查恢复后下一次取号不会撞上现有最大值，不声称序列值与在线源库逐项一致。
5. 成功和失败均保留备份及`evidence.json`。成功后恢复数据库停止，探针退出，网络和卷保留供复核。脚本不调用rm/down/prune，也不删除源课程、成绩、答卷、附件或历史失败记录。私有诊断日志和逐文件清单仅放备份目录，终端只打印汇总。

命令失败返回非零；应查看该次私有诊断，不覆盖失败目录。若需要重跑，使用另一个新目录。异常中断可能留下运行中的隔离容器，应先核对证据中的准确资源名与隔离状态，不用模糊匹配批量操作。

## 证据与限制

实际执行结果见 [恢复审核](../reports/recovery-rehearsal.md) 和 [脱敏汇总](../reports/recovery-rehearsal-evidence.json)。原始数据库、媒体、逐文件清单和诊断日志均留在仓库外`.backups/full-recovery-20261116-*`，不提交。摘要允许核对是否一致，不公开答案、邮箱、令牌或文件名。

计时包括本机创建容器、恢复和摘要校验，不等于真实故障下的RTO。没有模拟源服务丢失、站点切换、异地灾备或应用恢复对外服务，也没有共同冻结RPO/RTO及保留周期；AC-D02仍需团队确认目标并独立验收。未执行存储加密、跨机器下载恢复或定期备份策略，不宣称这些已完成。
