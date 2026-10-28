# 扩展 P1 课堂体验

状态：候选提议，待 P0 通过后决定启动或裁剪；优先级：P1；实现：未开始。

## Why

初步设计的 E2、E6、E7 用于提高课堂互动、阅读和通知体验，但双人组须先保证底座和 P0 完整可验收。提前记录边界，避免拓展抢占核心交付资源。

## What Changes

- E2：限时签到与补签、投票抢答、即时统计、匿名提问和出勤统计。
- E6：PDF / Office 预览、目录、阅读进度、私有笔记与引用页定位。
- E7：课程公告、站内与邮件提醒、课程日历和可撤销 iCal 订阅。

## Capabilities

### New Capabilities

- `classroom-interaction`：签到、实时活动和匿名提问。
- `preview-notes`：转换预览、学习进度和个人笔记。
- `notifications-calendar`：消息、日历、订阅与发送状态。

### Modified Capabilities

无。沿用底座授权与审计，不要求修改 P0 成绩或提醒语义。

## Impact

李非凡主责 E2，陈志康主责 E6 / E7，另一位交叉验收。验收编号为 AC-I、AC-P、AC-N 系列；未启动项必须标记未纳入，不算已完成。

## Dependencies And Non Goals

依赖已验收底座、P0 的稳定数据契约、定时任务和文件服务。实时方案在实现前从 SSE / WebSocket 选型；Office 转换规划使用隔离 LibreOffice 任务。邮件、域名和资源预算待定。不做 GPS 追踪、绝对防代签、Office 协同编辑或双向日历同步。
