# 贡献与规约变更指南

## 开始前

先读 [项目章程](docs/project-charter.md)、[追踪矩阵](docs/requirements-traceability.md) 和关联 OpenSpec change。本仓库目前只初始化规约，没有业务运行或测试命令；接入实现时必须补充实际可执行说明。

## 一项变更的流程

1. **提出**：明确用户、场景、来源、做什么、不做什么、失败结果和证据；关联稳定 Requirement ID。
2. **评审**：双方确认范围、依赖和验收，细化草案中的待确认决策。初始文档提交不等于双方已批准。
3. **实现**：按 `tasks.md` 开发并自测，契约变化先改规约；不能由 AI 自行批准扩范围。
4. **交叉验收**：非主实现者按 [验收计划](docs/acceptance-plan.md) 在独立环境执行，并提交记录。
5. **归档**：确认全部纳入范围已通过，再把 delta 同步为 `openspec/specs/<capability>/spec.md` 并归档 change，保留证据索引。

## OpenSpec 约定

- 一个 change 包含 `proposal.md`、`design.md`、`tasks.md`、`specs/<capability>/spec.md`。
- 新增目标写在 `## ADDED Requirements` 下；修改生效规约时使用相应 `MODIFIED` / `REMOVED` delta，保留完整受影响 Requirement 和原因。
- `### Requirement: ID 名称` 至少包含一个 SHALL 条款和一个 `#### Scenario:`。
- 场景使用 `GIVEN / WHEN / THEN`；覆盖权限、失败、重试或边界，避免“体验良好”“系统智能”等不可检验描述。
- 新任务均用 `- [ ]`；只在实际完成后勾选，不把规约格式通过等同于功能通过。
- 当前没有已验收 capability，所以三批均为新增草案，不提前归档或填造通过记录。

```sh
npx --yes --package=@fission-ai/openspec@1.15.0 openspec list
npx --yes --package=@fission-ai/openspec@1.15.0 openspec validate --all --strict --no-interactive
```

需要 Node.js >= 20.19.0 和 npm；首次执行会获取固定版本工具。格式校验之外还需检查 Markdown 相对链接、追踪编号、个人信息与范围一致性。

## 提交与评审

- 建议提交格式：`docs: ...`、`feat(quiz): ...`、`fix(gradebook): ...`、`test: ...`，以实际改动为准。
- PR 使用仓库模板，注明 Requirement、验收编号、主责与验收人、运行命令和真实结果。
- 文档、代码和证据可分小提交，但同一验收必须固定到可识别提交，不能用未提交本地状态代替。
- 未执行测试明确写“未执行”；测试替身明确标注，真实模型、RAG 与 MCP 必须有单独集成证据。
- 原始设计 DOCX 仅保留本地，不随生成的规约上传公开仓库；局部修订不得静默改写其他模块的边界和计算口径。

## 数据与安全

不提交 `.env`、令牌、真实学生答卷、带身份成绩、生产日志或数据库备份。示例配置只含占位符；自制夹具使用匿名账号。引用资料和图像必须有使用权限。文件公开前核对元数据与下载链接，撤销或轮换凭据不能用删除最新文件代替。

不随意添加许可证：本批文档不替课堂底座或团队确定开源许可，接入时先核对来源并由双方确认。
