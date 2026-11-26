# claude-code-reminder-hooks

和 AI 聊出一个好点子，隔天却找不到记录；说了“先讨论”，它已经改了文件；规则和记忆越写越长，自己也懒得翻。这三个小提醒，处理的就是这些日常烦恼。

不调用模型、不联网、不收费，不会自己写待办、改设置、拆文件或执行会话里的命令。需要本机已有 **Bash 和 Python 3.8+**，没有 jq 或第三方 Python 包依赖。适合 macOS / Linux 的 Claude Code；Windows 的 Git Bash / WSL 路线本包尚未实机验证。

| 提醒 | 触发时机 | 做什么 |
|---|---|---|
| 待办提醒 `idea-to-backlog-reminder.sh` | `Stop`，本轮准备收尾时 | 找到想法或待定事项，但没看到配置的待办文件成功写入时，请 AI 核对是否需要记下 |
| 讨论提醒 `discussion-drift-reminder.sh` | `Stop`，本轮准备收尾时 | 最近说的是“先讨论”，本轮却调用了改文件、联网或委派工具时，请 AI 核对授权并说明已做的动作 |
| 文件长度提醒 `filesize-reminder.sh` | `PostToolUse`，`Edit` / `Write` 成功之后 | 检查指定文件的行数、总字符数和超长行数，建议精简或拆分 |

## 怎么装

1. 把本目录放到你会长期保留的位置。三个 Bash 入口依赖同目录的 `reminders.py` 和上一层的 `config.example`，请保留整套目录。
2. 在这个目录打开终端，先跑虚构样例检查：

   ```bash
   bash tests/run.sh
   ```

   测试会临时创建一个独立 HOME 和虚构会话，临时文件也只在本包 `tests/` 中，不读写你的真实 Claude Code 配置或会话。测试输出 `PASS` 只证明这些本地样例通过。

3. 可选：复制配置后按自己的习惯修改：

   ```bash
   cp config.example config.json
   ```

   默认不需要创建配置：没有 `config.json` 时直接使用 `config.example`。第一次配置前请先核对目标待办文件，脚本不会创建它。

4. 打开 `settings.snippet.json`，把所有 `/ABSOLUTE/PATH/claude-code-reminder-hooks` 换成本包的绝对路径，保留命令里的引号。路径有空格可直接使用；路径里若有单引号，需自行做 shell 转义，或换个不含单引号的位置。
5. 先备份你自己的 Claude Code 设置，再把片段中的条目**合并**到用户级 `~/.claude/settings.json`，或仅当前项目的 `.claude/settings.local.json`。已有 `hooks` 时，把条目追加到对应的 `Stop` / `PostToolUse` 数组，保留原条目；不要用片段覆盖整个设置文件。只装想用的提醒即可，同一提醒别在两处重复登记。
6. 重开 Claude Code 会话，在 `/hooks` 里检查登记，再用你自己的无敏感内容小例子确认是否收到提醒。请先检查每条命令的绝对路径及 Python 是否可用。

本包没有自动安装步骤，不会接触你正在使用的设置。设置格式及事件说明见 [Claude Code 官方 Hooks 参考](https://code.claude.com/docs/en/hooks)；这里的设置片段按该参考核对，未在真实账号上安装验收。

## 怎么配

配置是 **JSON 数据，不作为 shell 或 Python 代码执行**。可只写要改的字段：每个小节的缺失字段沿用 `config.example`；列表整体替换，不逐项合并。不要在 JSON 里写注释。

配置优先级为：环境变量 `REMINDER_HOOKS_CONFIG` 指定的文件 → 本包 `config.json` → 本包 `config.example`。指定的配置不存在、格式不对、字段名写错或阈值非法时，本次检查跳过，stderr 给一行通用诊断，不输出原始输入。环境变量指向相对路径时按 hook 的启动目录解释，推荐绝对路径。

| 小节 / 字段 | 用法 |
|---|---|
| 每节 `enabled` | `true` 开启，`false` 关闭该提醒 |
| `idea.backlog_paths` | 接受作为待办记录的文件列表，按完整路径比较；相对路径以事件的项目 `cwd` 为基准，支持 `~`，不支持通配符 |
| `idea.user_terms` / `reply_terms` | 用户想法词、AI 待定事项词；任意一个命中就检查本轮记录 |
| `idea.skip_markers` | 回答中出现任意标记就不提醒，示例为“已记待办”“无需记待办”；建议附上记录位置或理由 |
| `discussion.discussion_terms` / `go_terms` | 表示讨论、开干的口令列表。回看最近 8 条真实用户消息，从新到旧找第一个命中；同条消息同时命中时按讨论处理 |
| `discussion.record_paths` | 讨论时允许写的记录文件列表，完整路径匹配；只代表不触发本提醒，不授予写入权限 |
| `discussion.action_tools` | 讨论时要提醒的工具名称列表，例如 `WebSearch`、`Agent` |
| `discussion.shell_action_terms` | Bash 命令中出现这些字面片段时提醒，例如 `mkdir `。不是完整 shell 解析，也不会执行命令 |
| `discussion.skip_markers` | 本轮用户明确点名要做时，AI 可在回答里用标记附上用户原话；示例为“用户已明确要求” |
| `filesize.rules` | 关注文件的规则列表。`pattern` 不含 `/` 时匹配文件名；含 `/` 时匹配相对项目 `cwd` 的路径，项目外文件使用绝对路径；采用 Python `fnmatch` 通配符，`*` 可以跨目录，默认区分大小写 |

每条文件规则都要提供以下五项。可增加、替换规则，或设空列表 `[]` 暂停文件检查：

```json
{
  "filesize": {
    "rules": [
      {
        "pattern": "notes/*.md",
        "max_lines": 180,
        "max_chars": 20000,
        "max_line_chars": 260,
        "max_long_lines": 3
      }
    ]
  }
}
```

超过阈值才提醒，等于阈值不提醒。前三个数必须是正整数，`max_long_lines` 可为 0：表示不希望出现任何超长行。默认关注 `CLAUDE.md`、`MEMORY.md`；默认待办是项目下的 `notes/tasks.md`，请按需换成自己的文件。

字符数用 Python `len(text)` 计算，中文通常一个字算一个字符，不按 UTF-8 字节算；换行也计入总字符数。组合符号或某些 emoji 可能由多个 Unicode 码点构成，因此不等于屏幕上看到的字形数。行数包含没有末尾换行的最后一行。

需要不同项目分别配置时，可以在对应项目的设置命令前指定环境变量，例如：

```bash
REMINDER_HOOKS_CONFIG='/path/to/project/reminders.json' bash '/path/to/claude-code-reminder-hooks/hooks/idea-to-backlog-reminder.sh'
```

请把示例路径换成自己的路径；每个希望使用此配置的入口都要指定。配置里不需要密钥。

## 怎么关

- 配置中把相应小节的 `enabled` 改成 `false`。
- 临时关闭全部：从设置环境变量的终端启动 Claude Code，例如 `REMINDER_HOOKS_DISABLE=all claude`。只关部分可设为 `idea`、`discussion`、`filesize`，或用英文逗号连接，例如 `idea,discussion`，不要加空格。
- 彻底停用：从自己的设置文件中移除本包的那几个登记条目，保留其他 hooks，再重开会话。无需删除任何待办或记忆文件。

## 已知局限

- **前两个提醒收尾时才检查，动作可能已经发生，不能撤销。** 文件长度提醒也发生在写完之后，不会恢复旧文件。
- Stop 提醒使用官方 JSON 字段 `decision: "block"` 和 `reason`，让 AI 继续核对或解释一轮；这是收尾反馈机制。检测到 `stop_hook_active` 就跳过，避免本包相互触发反复收尾，但不强迫 AI 最终完成记录。
- **文字标记放行不是防火墙。** 标记可以随便写，脚本不能判断授权真假。关键词也不理解语义：引述、否定句、同义词、英文或长对话都有误判、漏判。用户指令和 Claude Code 权限机制仍需各自落实。
- 待办检查只识别本轮 `Edit` / `Write` 调用与对应的非错误 `tool_result`。它不会检查待办内容是否完整、是否记错、是否后来被覆盖；通过 Bash、MCP 或外部编辑器写入的记录不自动识别，请核对后用文字标记说明。
- 讨论提醒只检查最后一条真实用户消息之后的工具调用，讨论状态回看最近 8 条。它看的是调用记录，即使调用失败也可能提醒。未列出的工具、复杂 shell 写法、委派后的下游动作都可能漏掉。
- **阈值是我们自己的经验，不是官方上限。** 超过不代表模型必然读不全，低于也不代表一定完整读取。本包不会自动归档、拆分或删减内容。
- **只适配 Claude Code 当前的事件格式。** 依据官方参考核对日期为 2026-11-26；读取 `Stop` 的 `transcript_path`、`last_assistant_message`、`stop_hook_active`，以及 `PostToolUse` 的 `tool_input.file_path` / `tool_response.filePath`。会话 JSONL 需含 `type`、`message.content`、`tool_use` / `tool_result` 等结构。格式变化需要更新，不承诺适配其他 AI 客户端。
- 本包只读事件指向的本地会话、配置和命中文件，不持久化会话或发送到网络。输入最多 1 MiB、会话最多 16 MiB、关注文件最多 4 MiB；超限或读失败会跳过并输出简短诊断，hook 退出码仍为 0。损坏的 JSONL 行跳过，可能导致该轮漏判。数据越多不等于检查越全。
- 同时命中多个长度条件时只输出一个合法 JSON，避免多段输出互相干扰。多个窗口分别检查，没有全局锁，也不协调你自己的同时写入动作；检查只是当时的一次快照。

## English

Three configurable, local Claude Code reminders: capture pending ideas, review unexpected actions during discussion, and flag growing rule or memory files. Requires Bash and Python 3.8+, with no third-party Python packages. Run `bash tests/run.sh`, customize `config.example` as `config.json`, and merge the path-adjusted settings snippet into your own settings. These are heuristic reminders after the relevant actions; they cannot undo changes or enforce authorization. MIT License, Wutuobang AI.

更多普通人使用 AI 的实践与开源资料，见 [乌托邦 AI 资料站](https://cal.wutuobangai.com)。
