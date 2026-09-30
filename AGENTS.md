# AGENTS.md

## 提交范围

对当前项目执行提交时，必须覆盖整个项目范围内的所有文件，包括但不限于：

- 所有文件夹及其子文件夹中的代码文件
- 根目录下的独立代码文件
- 配置文件、文档文件、资源文件等项目文件
- 新增、修改、移动或删除的文件

不要只关注"当前改动的一小部分"，也不要遗漏根目录下的独立文件。

## 分支与提交规范

项目提交统一采用"功能分支 + 逻辑分组提交 + squash 合并"方式。

> 历史教训：早期曾执行"逐文件提交"规程，导致单分钟数十个 commit 的机器化历史，
> 严重损害可读性与评审体验，自 2026-09-29 起废止。

### 核心要求

- 每个功能/修复在独立分支（`feat/xxx`、`fix/xxx`）上开发，完成后 squash 合并进 main。
- 一个 Commit 对应一个逻辑变更（一个功能、一个修复、一次重构），允许包含多个相关文件；禁止"一个文件一个 commit"的机械拆分，也禁止把无关变更混入同一 commit。
- 合并前必须保证本地门禁全绿：`ruff check .`、`mypy app`、`pytest` 全部通过。
- 提交范围必须覆盖本次逻辑变更涉及的全部文件；不要遗漏根目录独立文件。
- 如果存在 `.gitignore`，遵循其规则；不提交 `.env`、密钥、本地账号配置等敏感信息。
- 重写历史前先创建备份标签，例如 `git tag old-history-backup-<项目名> <旧HEAD>`，防止历史丢失。

### Commit Message 格式

Commit Message 必须说明本次逻辑变更的内容，格式为：

```text
type(scope): <改动主题> <具体功能或改动说明>
```

示例：

```text
feat(api): 新增会话删除接口，级联清理消息与任务记录
test(tasks): 补充 Reaper 补偿扫描的用例，覆盖死信恢复路径
chore(ci): test job 增加 postgres service 健康检查等待
```

必须说明的内容：

- 这次变更负责什么功能
- 本次提交新增了什么能力
- 修复了什么问题
- 重构或优化了什么逻辑
- 配置、文档、脚本的作用是什么

禁止使用 `update files`、`update code`、`fix bugs`、`modify files`、`save changes`、`commit all` 等模糊描述。

### 执行步骤

1. 使用 `git status` 和 `git ls-files` 核对变更清单，确认没有遗漏与混入。
2. 按逻辑变更分组暂存：`git add <相关文件...>`，`git diff --cached --stat` 核对暂存范围后提交。
3. 推送前确认本地门禁全绿；历史被重写时使用 `--force-with-lease` 强推，避免覆盖未知新提交。
4. 合并进 main 使用 squash merge，保持主干历史一条逻辑变更一行。

## 提交前检查

执行提交前，必须先确认完整范围：

1. 使用 `git status` 和 `git ls-files` 查看当前状态与完整文件清单
2. 按逻辑变更分组执行 `git add <相关文件...>`，一个暂存区对应一个 Commit
3. 使用 `git diff --cached --stat` 确认暂存范围与本次逻辑变更一致
4. 如果存在 `.gitignore`，应遵循其规则，不提交应忽略的文件
5. 不要提交敏感信息，例如 `.env`、密钥文件、本地账号配置等

## Commit Message 规范

所有 commit message 必须清晰说明每个模块、文件夹或文件的功能作用或修复内容，禁止使用模糊描述。

### 禁止使用这类描述

- `update files`
- `update code`
- `fix bugs`
- `modify files`
- `save changes`
- `commit all`

### 必须说明的内容

- 这个模块/文件负责什么功能
- 本次提交新增了什么能力
- 修复了什么问题
- 重构或优化了什么逻辑
- 配置、文档、脚本的作用是什么

## Commit Message 格式

优先使用 Conventional Commits 格式，并以"逐文件提交规范"中的单行格式为准：

```text
type(scope): <文件名> <具体功能或改动说明>
```

常用 type：

- `feat`：新增功能
- `fix`：修复问题
- `docs`：文档变更
- `style`：代码格式调整（不影响逻辑）
- `refactor`：重构
- `perf`：性能优化
- `test`：测试相关
- `chore`：构建/工具链/配置变更

## 提交流程

按"分支与提交规范"生成本次逻辑变更的 commit message 草稿，先展示变更清单和消息草稿，暂时不要 commit 和 push，等用户确认后再执行。

## 修改记录

- 2026-09-29：废止"逐文件提交规范"，改为功能分支 + 逻辑分组提交 + squash 合并；提交前检查与提交流程同步更新。
