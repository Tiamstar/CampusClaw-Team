# 可重复安全反例

cases/security-negative.json 是固定SQL/XSS/CSRF输入清单。输入只用于明确授权的本地合成课程，不对外部站点扫描；不会调用模型或发送邮件。每次运行创建并保留新课程、7个帖子及两个成员，不删除验收记录。命令使用既有账号的服务器签发JWT，不是密码登录或认证限流测试；不要将JWT写入证据。

在项目根目录构建并启动backend，确认 /health/ 为200后执行：

```powershell
docker compose build backend
docker compose up -d --no-deps backend
docker cp apitest/cases/security-negative.json campusclaw-team-backend-1:/tmp/security-negative.json
docker exec campusclaw-team-backend-1 python manage.py verify_security_negative --retain-fixtures --teacher TEACHER_EMAIL --student STUDENT_EMAIL --cases /tmp/security-negative.json
docker cp campusclaw-team-backend-1:/tmp/security-negative-evidence.json reports/security-negative-evidence.json
```

必须选择已获明确授权的两个现有账号。命令限制loopback HTTP，密钥不通过命令参数传递。后台CSRF用不存在的合成账号，正常对照仅证明令牌校验通过后返回登录失败页面，不会登录或修改凭据。无令牌/错误令牌/不可信Origin为403；匿名和仅Cookie携带JWT的API写入为401；明确Bearer头为201。SQL在有普通数据的论坛搜索中先返回空，再加入同样字符串的帖子后仅匹配该帖子；%和_作为字面值，不作为全量通配符。

HTTP通过不等于XSS渲染通过。另用浏览器打开输出中的课程→答疑论坛→「安全反例：脚本与公式（保留记录）」，核对正常公式、代码文本、无可执行script/事件属性/javascript链接、body没有data-security-probe标记。不要点击危险链接或手动执行输入。记录角色、课程/帖子ID和DOM事实，截图保存在仓库外。完整自动回归由 python scripts/check.py 执行。

本轮记录见 ../reports/security-negative-evidence.json 与 ../reports/security-negative.md。成员独立复验和更多编码变体仍待完成。
