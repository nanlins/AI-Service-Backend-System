# AGENTS.md

## 提交范围

对当前项目执行提交时，必须覆盖整个项目范围内的所有文件，包括但不限于：

- 所有文件夹及其子文件夹中的代码文件
- 根目录下的独立代码文件
- 配置文件、文档文件、资源文件等项目文件
- 新增、修改、移动或删除的文件

不要只关注"当前改动的一小部分"，也不要遗漏根目录下的独立文件。

## 逐文件提交规范（通用记忆）

项目提交统一采用逐文件提交方式，禁止将所有文件合并为一个 Commit。

### 核心要求

- 每个文件独立成为一个 Commit，一个 Commit 只允许包含 1 个文件。
- 禁止使用 `git add .` 后一次性提交，必须通过多次 `git add <具体文件>` + `git commit` 循环完成。
- 提交范围必须覆盖项目全部文件：根目录独立文件、所有文件夹及其子文件夹中的代码、配置、文档、资源文件，以及新增、修改、移动、删除的文件。
- 如果存在 `.gitignore`，遵循其规则；不提交 `.env`、密钥、本地账号配置等敏感信息。
- 重写历史前先创建备份标签，例如 `git tag old-history-backup-<项目名> <旧HEAD>`，防止历史丢失。

### Commit Message 格式

每个文件的 Commit Message 必须同时包含文件名和该文件的功能说明，格式为：

```text
type(scope): <文件名> <具体功能或改动说明>
```

示例：

```text
feat(backend): main.py FastAPI 应用入口，实现聊天、流式、结构化输出、工具链路、嵌入、历史与供应商测试 API
test(tests): test_api.py 覆盖健康检查、模型列表、聊天、流式、工具链路、嵌入、历史与供应商测试接口
chore(root): requirements.txt 声明本地开发与测试依赖
```

必须说明的内容：

- 这个文件负责什么功能
- 本次提交新增了什么能力
- 修复了什么问题
- 重构或优化了什么逻辑
- 配置、文档、脚本的作用是什么

禁止使用 `update files`、`update code`、`fix bugs`、`modify files`、`save changes`、`commit all` 等模糊描述。

### 执行步骤

1. 使用 `git status` 和 `git ls-files` 核对完整文件清单，确认没有遗漏。
2. 备份旧历史：`git tag old-history-backup-<项目名> HEAD`。
3. 逐文件循环执行：`git add <具体文件>`，然后 `git commit -m "type(scope): <文件名> <功能说明>"`，直到全部文件提交完成。
4. 提交后必须校验：
   - 每个 Commit 只包含 1 个文件：`git diff-tree --root --no-commit-id --name-only -r <commit>`
   - 提交数量与项目文件数量一致：`git rev-list --count HEAD`
   - 最终文件树与提交前一致：对比 `git rev-parse HEAD:` 的树哈希
   - `git status` 干净
5. 推送前先确认远端指针；历史被重写时使用 `--force-with-lease` 强推，避免覆盖未知新提交。
6. 每次提交后由检查 Agent 自动复核，确认提交范围、Commit Message 与校验结果后再推送。

## 提交前检查

执行提交前，必须先确认完整范围：

1. 使用 `git status` 和 `git ls-files` 查看当前状态与完整文件清单
2. 逐文件执行 `git add <具体文件>`，每次只暂存 1 个文件
3. 使用 `git diff --cached --stat` 确认本次暂存区中确实只有该文件
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

按"逐文件提交规范"生成每个文件的 commit message 草稿，先展示完整文件清单和消息草稿，暂时不要 commit 和 push，等用户确认后再执行。
