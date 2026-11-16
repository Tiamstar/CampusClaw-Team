# 干净环境验收夹具

关联 BASE-001 与验收计划的夹具要求。`seed_acceptance` 仅用于另一名组员的**独立空 PostgreSQL 数据库**，不在现有真实账号教学库执行。迁移0023只新增导入回执表，不改变现有课程/成绩结构。此命令不是验收结论，也不代替真实模型、独立成员、公网或故障测试。

## 执行

先在独立工作目录按 README 生成自己的配置并构建，仅启动数据库。不要复制开发者数据库、上传卷或模型凭据。**须在完整应用首次启动前导入**：正常启动的bootstrap_tools会创建平台服务账号，届时不再是空库，命令会安全拒绝。确认新环境无任何账号与课程，之后执行：

```powershell
docker compose up -d --wait db
docker compose build backend
docker compose run --rm --no-deps backend python manage.py migrate
# 从安全输入读取合成账号密码，不写入命令行、仓库或终端输出。
$fixtureSecret = Read-Host '独立验收账号密码' -AsSecureString
$env:ACCEPTANCE_FIXTURE_PASSWORD = [System.Net.NetworkCredential]::new('', $fixtureSecret).Password
try {
    docker compose run --rm --no-deps -T -e ACCEPTANCE_FIXTURE_PASSWORD backend python manage.py seed_acceptance --allow-synthetic-fixtures
} finally {
    Remove-Item Env:ACCEPTANCE_FIXTURE_PASSWORD -ErrorAction SilentlyContinue
    $fixtureSecret.Dispose()
}
# 重复执行不再需要密码；只返回最初清单，不写业务表。
docker compose up --build -d --wait --wait-timeout 180
docker compose exec -T backend python manage.py seed_acceptance --allow-synthetic-fixtures
```

若 Compose 版本不支持只按变量名传入 `exec -e`，在独立容器中安全设置该环境变量后执行；不要把密码展开进命令参数。Linux可用 `read -rs ACCEPTANCE_FIXTURE_PASSWORD; export ACCEPTANCE_FIXTURE_PASSWORD` 输入，再用相同 `exec -e` 命令，完成后 `unset ACCEPTANCE_FIXTURE_PASSWORD`。

命令返回资源 ID、课程码与合成邮箱。T_A/T_B拥有建课资格且各管理一门课；S_A1–S_A8只属于A，S_B1只属于B。邮箱为 `t_a@acceptance.example.invalid` 等合成地址，密码为本次安全输入值；无管理员权限。导入器通过进程内已认证业务视图初始化，不经过注册邮件和密码登录，组员应自行登录验证。

## 内容和复算

- A/B成员与资料隔离；自制TXT含标明的第1/2页、四类公式分隔符和提示注入文本。TXT页码是人工逻辑页，不是PDF页码。A损坏PDF保持待索引，可由教师启动索引观察实际失败；B资料含仅B的检索词。
- K1→K2→K3经正常图谱审批建立；K4无题目和答题数据。另有未批准环候选，批准应409且正式图不变。所有候选/预索引明确为人工夹具，不是模型抽取或后台入库证明。
- 五类核心题各20分，含填空等价答案、公式和多知识点题。八名A学生均经保存→交卷→人工复核→公开；A1测验90、作业80，A2测验60、作业50，其余六人测验100、作业70，权重作业30%/测验70%，正式总评依次87.00、57.00、其余91.00。全班补齐来源才能发布完整快照，不能把缺分记零。
- 单独统计测验两题10/90分，经相同正式流程建立同快照八答卷，总分100/90/80/70/60/50/40/30；指定10分题得分10/10/10/0/10/0/0/0，正确率0.5、上下各2人区分度1。统计测验不加入总评策略；学情窗口包含它时须与核心测验分开解释。
- 练习测验保留给组员检查保存、未保存、限次1和重复/并发交卷；过期测验为草稿，发布应400。核心测验已用完限次。时间按首次导入时刻冻结，重复命令不会续期；30天后应使用另一个全新独立库复验，不能重置既有验收数据。
- 一个未答复论坛帖可供检索、草稿、教师确认和待办检查，未调用模型/未生成草稿。跨班/非法题参数与空检索词在清单中。超时、限流、断线、取消、重放、迟到事件、邮件与转换错误仍须按自动回归和验收计划另行注入；清单不会伪造失败任务。

## 幂等与失败

PostgreSQL事务级锁串行化两个导入者，所有数据库创建及回执在同一事务。第二次只读取原回执，保留验收人的改名、评分、密码修改和操作记录，甚至不会“修复”手动删除的资源。清单是初始定位记录，需用实际接口复算当前状态。没有回执却有账号或课程时拒绝；不提供覆盖/重置/清理选项。

文件存储不参与数据库事务。初次中途失败会回滚数据库，但可能保留刚写入的合成文件；应在独立环境记录故障，不清理真实教学附件。数据库迁移和导入必须在受控时间执行，避免其他进程同时注册/建课；导入锁只协调该命令，不能阻止普通API写入。

实际命令、回归、审核与隔离演练结果见 [执行记录](../reports/acceptance-fixtures.md)。
