# Skill 自举方案（初步稿）

> 范围：只解决 **skill 自身**如何从"零"走到"出片"，不含 flint 分发与推广链路。
> 状态：初稿，待评审。落地后需要与 `AGENTS.md` 的 skill 规范对齐（文档正文英文，frontmatter 契约不变）。

---

## 1. 目标与非目标

**目标**

1. 用户只给一句话 + 一个 skill 入口（已装目录或一个 URL），agent 就能自己把服务跑起来并产出 mp4。
2. **产物路径有约定**：skill 永远知道装在哪、数据放哪、成片交到哪；不污染用户当前目录与 git 仓库。
3. **避免反复下载**：同一台机器第二次使用，除"启动服务"外不做任何网络安装动作。
4. **闭环**：首次使用引导"注册 → 领 key → 绑域名 → 校验 → 首片成功"；失败时产出可直接提交的反馈包，维护侧修复后回写 skill 判定（§12）。

**非目标**

- 不做 flint 分发、registry、遥测与推广归因。
- 不改视频生成逻辑与流水线。
- 不追求"完全无 key 可用"——key 仍由用户提供，但可以不阻塞首次体验。

---

## 2. 现状核查（均为代码实测）

| # | 事实 | 证据 | 影响 |
|---|------|------|------|
| F1 | 已有免 clone 安装渠道 | npm `free-short-video@7.2.0`，镜像 `lcy362/free-short-video:latest` | "按需下载项目"这半件事已成立，不必再设计新渠道 |
| F2 | npx 启动器把 venv 建在**包目录内** | `bin/cli.js:146` `path.join(PKG_ROOT, '.venv')` | npx 缓存位于 `~/.npm/_npx/<hash>`，被清理或换版本即整包重装 → **反复下载的根因** |
| F3 | `pip install -r requirements.txt` **每次启动都执行** | `bin/cli.js:150` 在 `if (!fs.existsSync(venvPython))` 块之外，日志却写 "first run only" | 每次启动都联网解析依赖，与 F2 叠加后尤其慢 |
| F4 | 配置目录已支持外部重定向 | `core/config.py:17-26` 支持 `AGNES_CONFIG_DIR` | 配置/密钥可以不落在 npm 缓存里 |
| F5 | 工作区可在设置里改，默认 `<项目根>/.working_dir` | `core/config.py:705-724` | 中间产物默认也在包目录内，需要首次启动后显式指向 `$AGNES_HOME/workspace` |
| F6 | skill 主文档默认让 agent `git clone` | `skills/agnes-video-usage/references/deploy.md` §0 Step 3 | 与"免克隆"目标相反；npx 只作为 §1 表格里一行 |
| F7 | npx 路线仅出现在 references | 同上 §1 Route C | agent 只读 `SKILL.md` 时看不到最优路径 |
| F8 | `SKILL.md` 依赖 17 个 references 文件 | `find skills -name '*.md' \| wc -l` | 单文件模式（agent 只抓到一个 URL）跑不通 |
| F9 | 服务是前台进程，无 `--detach` | `bin/cli.js:190` `spawn(venvPython, ['server.py'])` + stdio inherit | agent 必须自己 nohup/后台化，跨轮次易丢进程 |
| F10 | 技能 frontmatter 校验只强制 `name`/`description` | flint `server/src/core/validate.ts:39-42` | 可安全增加 `version` / `requires_service` 等自定义字段 |

结论：缺口是 **路径契约缺失 + 安装副作用（F2/F3）+ 主文档路线错误（F6/F7/F8）**，不是"没有安装能力"。

---

## 3. 路径契约（本方案的核心）

### 3.1 安装根

优先级：`$AGNES_HOME` 环境变量 > 默认 `~/.agnes-video`。**所有写入只允许发生在这个根之下**（唯一例外见 3.4）。

```
$AGNES_HOME/
├─ install.json          # 安装台账：route / 服务版本 / skill 版本 / 平台 / node+python 路径 / 时间戳
├─ lock                  # 单飞锁（O_EXCL 创建，含 pid 与过期时间）
├─ runtime/              # npm --prefix 安装的包（绕开 npx 缓存，路径稳定）
├─ venv/                 # Python 依赖（需上游 D1；当前退化方案见 §8）
├─ config/               # AGNES_CONFIG_DIR，含 api_key（0600）
├─ workspace/            # 服务工作区：分镜、片段、manifest 等中间产物
├─ outputs/<task_id>/    # 交付物：final.mp4 / 字幕 / 旁白 / 封面
├─ tasks/<task_id>.json  # 轮询快照，供下一轮 agent 续跑
├─ logs/
└─ tmp/
```

硬规则：

1. **禁止** clone 或安装到用户当前工作目录；**禁止**写 skill 自己的目录（它可能是只读 symlink）。
2. 中间产物一律留在 `workspace/`，用户可见的交付物只出现在 `outputs/` 或 3.4 指定的目录。
3. 一次性清理只需 `rm -rf $AGNES_HOME`；skill 提供 `bootstrap.py uninstall`（先确认再删）。

### 3.2 三个路径变量的语义（必须区分）

| 变量 | 语义 | 谁写 |
|------|------|------|
| `AGNES_HOME` | 安装与数据根 | skill / 用户 |
| `AGNES_VIDEO_BASE` | 服务地址，默认 `http://localhost:8765` | 用户（已有约定） |
| `AGNES_OUTPUT_DIR` | 用户指定的**交付目录**（可空） | 用户 |

交付规则：成片先落 `outputs/<task_id>/`，若 `AGNES_OUTPUT_DIR` 非空则复制一份过去；无论哪种情况，agent 汇报时必须给出**绝对路径**，并说明是"工作区副本"还是"交付副本"。

### 3.3 端口与已有实例

默认 8765，被占用时**不静默换端口**（沿用上游口径）：先探测该端口上是不是本服务（`GET /api/config` 返回 `ok:true`），是则复用；否则报冲突并让用户指定 `--port`。

### 3.4 唯一例外

`AGNES_OUTPUT_DIR` 指向用户目录时的复制动作——需在输出里显式说明目标路径，不覆盖同名文件（冲突时加 `-1` 后缀）。

---

## 4. 复用协议：如何保证"不重复下载"

### 4.1 启动状态机

```
B0  GET $AGNES_VIDEO_BASE/api/config
      ok → 直接复用（零下载、零安装），跳到 S5
B1  读 install.json
      缺失 → S1
      存在且 install.service_version >= skill.requires_service → S2
      存在但版本过低 → S3（升级，需用户同意）
B2  加锁失败（已有实例在装/在起）→ 轮询 lock 消失后重新走 B0
S1  首次安装：探测 node/python/docker → 选路线（§5）→ 安装 → 写台账 → 起服务
S2  仅 ensure：按台账路线起服务（**不执行** npm/pip）
S3  升级：按台账路线更新包，保留 config/workspace/outputs，更新台账
S4  失败：输出证据 + 下一步建议，最多重试 1 次，不长时间重试
S5  就绪：确保 workspace 指向 $AGNES_HOME/workspace（首次启动后一次 POST）
```

### 4.2 幂等与并发

- 每个动作前先判存：`runtime/` 存在且版本匹配 → 跳过 npm；`venv/bin/python` 存在且 requirements 指纹一致 → 跳过 pip。
- **requirements 指纹**：`install.json.requirements_sha256`，与包内 `requirements.txt` 对比，不一致才重装依赖（解决 F3）。
- **单飞锁**：`$AGNES_HOME/lock` 以 `O_CREAT|O_EXCL` 创建，内容 `{pid, started_at, route}`；超过 15 分钟视为僵死可抢占。第二个 agent 不重复安装，等待或复用。
- 网络失败重试上限 1 次；失败信息必须包含原始命令、退出码、镜像/源地址。

### 4.3 明确不做

- 不做后台静默升级（版本变化只在 `requires_service` 不满足时触发，且需同意）。
- 不缓存 npm tarball 之外的任何东西（不下载模型、不预拉镜像）。
- `pip` 不使用 `--upgrade`，避免每次重解析；用固定 requirements + 指纹。

---

## 5. 安装路线（默认 C）

| 路线 | 触发条件 | 落地位置 | 备注 |
|------|---------|---------|------|
| **C — npm（默认）** | 有 node ≥18 且 python ≥3.10 | `$AGNES_HOME/runtime` | `npm i --prefix "$AGNES_HOME/runtime" free-short-video@<pin>`，之后直接 `node $HOME/runtime/node_modules/free-short-video/bin/cli.js`，**不走 npx** |
| B — Docker | 有 docker 且用户不想装 Python | 命名卷 `agnes-home-config` / `agnes-home-workspace` | 与 C 互斥，台账记录 |
| A — git clone | 用户要改代码（contrib 场景） | `$AGNES_HOME/src/agnes-video-generator` | 仅此场景允许 clone，且不落 cwd |
| X — 都不满足 | 无 node/python/docker | — | 停止并给出安装指引，不"就地发明"路线 |

选 C 的理由：跨平台（`start.sh` 是 bash，Windows 直接不可用）、无需系统 ffmpeg（imageio-ffmpeg 自带）、路径可由 `--prefix` 固定。

---

## 6. SKILL.md 改造

### 6.1 单文件可跑

`SKILL.md` 的 **happy path 必须自足**：探测 → 复用/安装 → 配 key → 建任务 → 轮询 → 交付，全部内联为命令，references 只在异常分支（`401`、队列满、竖屏躺倒、manual mode 细节）才指向。

目标结构（≤160 行）：

```
§0 Bootstrap contract   （调 scripts/bootstrap.py，读它的 JSON，不自己拼安装命令）
§1 复用/启动/首次安装（三条路线的选择表，一句话一条）
§2 建任务（六种类型的参数最小集）
§3 轮询（--wait / 快照文件 / 汇报增量）
§4 交付（outputs 路径规则 + AGNES_OUTPUT_DIR）
§5 失败分支 → references/*
```

### 6.2 frontmatter

```yaml
---
name: agnes-video-usage
description: ...（保留现有触发词）
agent_created: true
version: 0.2.0              # skill 自身版本
requires_service: ">=7.2.0" # 服务最低版本，低于此值必须先升级再用
---
```

`version` / `requires_service` 属自定义字段，flint 校验只认 `name`/`description`，不会被拒。

### 6.3 description 补两句

明确"不需要预先克隆仓库，skill 会自己按需安装"，让 agent 在匹配阶段就不再要求用户先 clone。

---

## 7. 脚本契约

### 7.1 `scripts/bootstrap.py`（stdlib，跨平台）

```
bootstrap.py probe   [--json]   # 只读探测：服务/台账/环境，不写盘
bootstrap.py install [--json] [--route c|b|a] [--yes]
bootstrap.py start   [--json]   # 幂等：已在跑则直接返回地址
bootstrap.py stop    [--json]
bootstrap.py status  [--json]
bootstrap.py uninstall [--yes]
```

退出码（agent 依此分支，不靠解析文本）：

| 码 | 含义 | agent 动作 |
|----|------|-----------|
| 0 | 就绪（含"已在运行"） | 继续建任务 |
| 10 | 需要 API key | 按 §12.2 引导领 key |
| 11 | key 已配但校验失败（多为域名不匹配） | 切域名 / 重跑 detect，不重试刷接口 |
| 20 | 需要用户同意安装（体积/耗时提示） | 征求同意后 `--yes` 重试 |
| 30 | 环境不满足 | 报缺什么，停止 |
| 40 | 已安装但版本低于 `requires_service` | 征求同意后升级 |
| 41 | 生成失败且已产出反馈包 | 走 §12.3，不自动提交 |
| 50 | 端口被其他程序占用 | 报冲突，等用户指定端口 |

`--json` 输出固定字段：`{ok, code, home, base, route, service_version, skill_version, workspace, outputs, needs, hints[]}`。

### 7.2 现有脚本调整

- `agnes_task.py`：尊重 `AGNES_HOME`，任务快照写 `$AGNES_HOME/tasks/<id>.json`；新增 `resume <id>`（读快照续轮询）；下载默认落 `outputs/<id>/`。
- `verify_deploy.sh`：保留，但由 `bootstrap.py status` 调起，避免两套探测逻辑。
- key 只经 `POST /api/config` 写入 `config/`（0600），**任何脚本都不 echo key**；新增 `bootstrap.py config-key --stdin`（不回显、不写日志）。
- 新增 `scripts/report_issue.py`（放 troubleshoot，见 §12.6）：拉 `GET /api/tasks/{id}/diagnostics` → 脱敏 → 写 `$AGNES_HOME/reports/issue-<id>.md` → 打印预填 URL。

---

## 8. 需要上游配合的改动（需拍板）

| ID | 改动 | 价值 | 不做时的退化 |
|----|------|------|-------------|
| D1 | `bin/cli.js` 支持 `AGNES_HOME`：venv / config / workspace 都落 home | 消除 F2（npx 缓存失效即重装） | skill 侧用 `--prefix` 固定 runtime，接受**每次升级重装依赖** |
| D2 | venv 存在且 requirements 指纹一致时跳过 `pip install` | 消除 F3（每次启动联网） | 二次启动多几秒到几十秒网络开销，且离线不可用 |
| D3 | `--detach` + `--json`：后台启动并回传 `{pid, ready, base}` | 消除 F9，agent 不再自己 nohup | skill 用 `nohup ... &` + 轮询就绪，跨平台差（Windows 需 `start /b`） |
| D4 | `--print-paths`：打印 config/workspace 实际路径 | 让 skill 校验 F5 是否生效 | skill 用 `GET /api/config` 反查 |

建议：D1+D2 属于"重复下载"的关键，优先级最高；D3 次之；D4 可选。

---

## 9. 分阶段

| 阶段 | 内容 | 交付 |
|------|------|------|
| **P0** | 路径契约 + `bootstrap.py`（probe/install/start/uninstall）+ `SKILL.md` 单文件化 + description 补充 | 不改上游即可跑通"零到出片"，接受一次性安装成本 |
| **P1** | 上游 D1/D2/D3 + 指纹跳过 | 二次使用零安装、离线可启动 |
| **P2** | 单飞锁 + 版本策略 + `AGNES_OUTPUT_DIR` 交付 + Windows 验证 | 多 agent 并发安全、交付路径明确 |
| **P3** | 闭环：领 key 引导 + detect/校验 + `report_issue.py` + 台账记账（§12） | 首次用户不卡在 401，失败能一轮内变成可提交的 issue |
| **P4** | `agnes-video-contrib` / `troubleshoot` 复用同一 bootstrap（contrib 才走 clone） | 三个 skill 共用一套环境事实，不再各自猜 |

---

## 10. 验收用例

1. **冷启动**：`AGNES_HOME=$(mktemp -d)` → 新会话只给一句话 + skill → 产出 `outputs/<id>/final.mp4`。
2. **二次使用（关键）**：保留上一个 `AGNES_HOME`，停掉服务 → 再跑一次，断言 `install.json` 未被重写、`runtime`/`venv` 无下载动作、仅启动服务。
3. **服务在跑**：手动起服务后执行 `bootstrap.py start` → 退出码 0、耗时 < 1s、无任何安装日志。
4. **并发**：两个进程同时 `install` → 只有一个执行安装，另一个等待并最终返回 0。
5. **版本闸**：伪造 `install.json.service_version=7.0.0` 而 `requires_service=>=7.2.0` → 退出码 40 并提示升级，不静默运行。
6. **路径安全**：在用户 git 仓库内执行 → 断言仓库内未新增任何文件（`git status` 干净）。
7. **交付目录**：设 `AGNES_OUTPUT_DIR=/tmp/out` → 成片同时出现在 `outputs/` 与 `/tmp/out/`，且路径被明确汇报。

---

## 11. 「不阻塞首次体验」的具体含义

先把话说死：**没有 key 就出不了视频**。上游 `core/config.py:1282` 的域名是写死的 `com/cn/cn_bak` 映射，没有 base URL 环境变量，产品里也没有可用的 mock 上游，所以任何"无 key 演示出片"都是假体验，本方案不做。

真正能做到的是：**首次体验里只有一个阻塞点（key），它出现在最晚的时刻，且在此之前每一步都有可感知的进展。**

| 机制 | 做法 | 依据 |
|------|------|------|
| M1 安装与凭据解耦 | `bootstrap.py install` **不接收** key；装完即返回退出码 10 + `needs:["api_key"]` + 领 key 链接 | 避免"没 key 就连装都不装" |
| M2 就绪证据不依赖上游 | 装完立刻验：`GET /api/config`（返回 `source` 与掩码前缀，能判有无 key 且不泄露）+ `GET /api/voices`（13 语言音色，edge_tts 免费）+ `GET /api/voices/preview`（真能出声）+ 首页 200 | 用户看到的是"活的"，而不是一句"请给我 key" |
| M3 key 推迟到最后一刻 | 无 key 时先做完：选任务类型、写 prompt/分镜、把请求体落 `$AGNES_HOME/tasks/pending.json`；只在**第一个上游请求之前**索取 | 打断时机从"第 1 分钟"推到"马上能出片" |
| M4 廉价校验再放行 | 拿到 key 后先 `GET /api/models`（有 key 才可用，比生成便宜得多），失败即按 401/域名不匹配归因，不让用户等到任务跑一半才失败 | `web/routes/config_routes.py:470` |
| M5 已给 key 则跳过 | 环境已有 `AGNES_API_KEY` 或 config 里已有 → 直接 S5，不做 M2/M3 的演示步骤 | 老用户不被仪式感拖慢 |

另有两个**比 key 更常见的首次失败**，同样属于本方案要处理的：

- **首次安装 2–5 分钟 / 数百 MB**：必须先给体积与耗时预期并征得同意，进度可见（npm → pip → 启动三段），且只装一次（§4）。
- **首片就用长视频**：默认先用 `simple` + 最短时长验证通路，通了再上 creative/manuscript，避免第一次就等 15 分钟再失败。

明确禁止（都属于制造假体验）：mock 假视频冒充产出、无 key 时反复建任务刷 `error_logs`、静默换端口或静默降级到 Docker、无限轮询等待用户回话。

---

## 12. 闭环：领 key 与反馈

### 12.1 环路

```
注册领 key → 配 key + 自动绑域名 → 廉价校验 → 首片 → 记账（跳过后续 onboarding）
                 ↑                                        ↓
        skill 参考/判定回写  ←  人点提交  ←  预填 Issue  ←  诊断包  ←  失败
```

闭环有两条回流：**成功回流**（首片成功 → 台账标记 → 下次不再问 key）与**失败回流**（失败 → 诊断 → 可提交的 Issue → 修复后回写 skill 判定）。

### 12.2 领 key（Acquire）

站点与域名一一对应（`core/config.py:1253-1257`）：

| 域名 | API 端点 | 领 key 站点 | 备注 |
|------|---------|------------|------|
| `com`（默认） | `apihub.agnes-ai.com` | <https://platform.agnes-ai.com> | 官方文档口径，agent 默认引导这里 |
| `cn` | `api.agnes-ai.cn` | 国内站 | **需国内站专属 key** |
| `cn_bak` | `apihub.agnes-ai.cn` | — | 官方文档未提及，接受国际站 key，作为兜底 |

交 key 的三种方式，按泄露风险从低到高：

1. **推荐**：让用户自己在 `http://localhost:8765` 的配置页粘贴（key 不进 agent 上下文、不进 shell history）。
2. `bootstrap.py config-key --stdin`：从标准输入读取，不回显、不 echo、不落日志，直接 `POST /api/config`。
3. `AGNES_API_KEY` 环境变量：**仅**无人值守/CI 场景。注意 env key 不能按 key 绑定域名、会被 auto-detect 跳过（FAQ 已写明），只能靠全局域名，401 时只能整体切域名。

配完必做两步（否则就是让用户在 401 里猜）：

```bash
POST /api/config/keys/detect     # 自动探测每个 key 的域名并落盘
GET  /api/models                 # 廉价校验：无 key 直接 400，错 key 立刻失败
```

失败即退出码 11：先切域名（`com` ↔ `cn_bak`）重试一次，仍失败再判定为 key 失效，**不重试刷接口**。

### 12.3 反馈（Report）

只在"确定性故障"时提 issue，避免把噪音推给维护者：

| 类别 | 例子 | 处置 |
|------|------|------|
| 可自愈 | `video_queue_full`、`fail_to_fetch_task`、429、超时、401 域名不匹配 | 先按 troubleshoot 修复，**不提 issue** |
| 确定性故障 | 重试后仍失败、同样的 step 稳定复现、版本/环境相关崩溃 | 生成反馈包 |

反馈包内容复用前端口径（`frontend/src/utils/feedback.ts`），不另起一套：

- 标题 `[Bug] <task_type> <failed_step> failed`；
- body 上限 4000 字符（超出截断并标注），含应用版本、任务类型、失败环节、错误消息、重试次数、诊断 `error_logs`；
- **脱敏**：`$HOME` 路径替换为 `~`；过滤疑似 key（`sk-` 前缀、长度 ≥24 的连续 `[A-Za-z0-9_-]`）；诊断端点本身不返回 prompt 全文，脚本也不得自行补；
- 产出 `$AGNES_HOME/reports/issue-<task_id>.md` + 预填 URL：
  `https://github.com/lcy362/agnes-video-generator/issues/new?labels=bug&title=…&body=…`
- **由人点提交**：agent 无 GitHub 凭据，也不该代发；提交前给一条同类 issue 的搜索链接，不强制。

明确不做：把"提示词效果不好"当 bug 提交（FAQ 已写明会被关闭，属 prompting 问题）；代填 issue；在报告里出现 key。

### 12.4 回流（Learn，维护侧）

- Issue 确认的新失败模式 → 回写 `references/upstream-errors.md` 与 `SKILL.md` 失败分支（一行），commit message 引用 issue 号。
- 若判定为上游缺陷（非配置/非用法）→ 转 upstream issue，skill 只保留判定与链接（遵守 `AGENTS.md` §4，不在这里发布"修正版结论"）。
- 每次回写同步 `references/*.md` 的 source anchor 日期。

### 12.5 台账新增字段

`install.json`：

```json
{
  "key": {"source": "config", "domain": "com", "checked_at": "..."},
  "first_success": {"at": "...", "task_id": "...", "task_type": "simple"},
  "feedback": [{"task_id": "...", "path": "...", "url": "...", "at": "..."}]
}
```

`first_success` 存在即视为 onboarding 完成：后续跳过 §12.2 的引导与"首片用 simple"的策略。台账**永不**存 key 明文，只存来源与域名。

### 12.6 归属（守住 skill 边界）

- 领 key、首片、交付：`agnes-video-usage`。
- 诊断、判定、反馈包：`agnes-video-troubleshoot`（复用既有 `diagnose_task.py`，新增 `report_issue.py`）。
- `usage` 里对反馈只留**一行指针**，不复制实现——符合"索引而不复制"的仓库原则。

---

## 13. 用户 agent 侧全流程（逐步）

> 视角是**调用方 agent**（Claude Code / Cursor / TRAE 等）。每一步给出：agent 做什么、跑什么命令、拿到什么、怎么分支、对用户说什么。原则：**agent 不读文档靠猜，只读 `SKILL.md` + 调脚本读 JSON**。

### 阶段 0 — 请求理解与装载

1. 命中 `description` 里的触发词（"用 agnes 做个视频 / 起视频服务 / 任务失败了"）后加载 `SKILL.md`。
2. **只读 `SKILL.md` 正文**（≤160 行）。`references/*` 只在具体分支触发时才读，禁止整目录读入——这是上下文预算的硬约束。
3. 抽取参数，缺的用默认值并**声明假设**，不连环追问：类型（默认 simple）、比例/分辨率、时长、语言与音色、交付位置（`AGNES_OUTPUT_DIR`，可空）、是否已有服务在跑。
4. 只有"决定路线且无法推断"的才问用户（例如：要 5 秒样片还是完整长视频；成片放哪）。

### 阶段 1 — 探测（只读，零副作用）

```bash
python3 scripts/bootstrap.py probe --json
```

返回结构（agent 只依赖这几个字段）：

```json
{"ok":true,"code":0,
 "service":{"reachable":true,"base":"http://localhost:8765","version":"7.2.0"},
 "install":{"present":true,"home":"~/.agnes-video","route":"c","service_version":"7.2.0"},
 "key":{"present":true,"source":"config","domain":"com"},
 "env":{"node":"20.11","python":"3.11.6","docker":null}}
```

分支：

| 探测结果 | 下一步 |
|---------|--------|
| `service.reachable` | 直接跳阶段 4（一句话告知"检测到已在运行的服务，直接复用"） |
| `install.present` 且版本满足 | 阶段 2（只启动，**不安装**） |
| `install.present` 但版本低于 `requires_service` | 阶段 3 的升级路径（退出码 40，需同意） |
| 都没有 | 阶段 3（首次安装） |

### 阶段 2 — 启动（幂等）

```bash
python3 scripts/bootstrap.py start --json    # 0 就绪 / 10 缺 key / 50 端口冲突
```

- 已在跑则立即返回，**不重启**（用户可能正开着网页看进度）。
- 端口被非本服务占用 → 50：报冲突，等用户指定 `--port`，**不静默换端口**。
- 启动超时（>60s）→ 读 `$AGNES_HOME/logs/` 末尾 30 行再判断，不盲目重试。

### 阶段 3 — 首次安装（一次性）

1. **先征得同意**，把三件事说清：装到 `$AGNES_HOME`、约 2–5 分钟、占用数百 MB（npm 包 + Python 依赖）。用户拒绝则停，不"就地发明"别的方式。
2. 路线默认 C（npm `--prefix`）；无 Python 有 Docker → B；用户要改代码 → A（`contrib` 场景才允许 clone）。
3. 执行：

```bash
python3 scripts/bootstrap.py install --yes --json   # 长任务，分段输出进度
```

4. 安装后立即做**不依赖 key 的就绪证明**（这是"首次体验不被 key 卡死"的落地）：

```bash
curl -s $BASE/api/config | ...   # source 与掩码前缀：判断 key 有无，不泄露
curl -s $BASE/api/voices | ...   # 13 语言音色（edge_tts，无需 key）
```

5. 汇报格式固定：装在哪、做了什么验证、下一步只差什么（key）。

### 阶段 4 — key 引导（Acquire）

按 `key.present` 分叉：

- **已有** → 阶段 5 校验。
- **缺失** → 按泄露风险给三种方式，**优先推荐用户自己在 `http://localhost:8765` 配置页粘贴**；其次 `bootstrap.py config-key --stdin`；环境变量只用于无人值守（且不能按 key 绑域名）。
- 站点与 key 必须配对：`com` → `platform.agnes-ai.com`；`cn` → 国内站专属 key；`cn_bak` 兜底接受国际站 key。

配完必做：

```bash
POST /api/config/keys/detect      # 自动绑定每个 key 的域名
GET  /api/models                  # 廉价校验（无 key 400，错 key 立刻失败）
```

失败 → 退出码 11 → 依次切 `com` / `cn_bak` 各试一次 → 仍失败判为 key 失效，提示重新领取，**不刷接口**。成功 → 台账写 `{source, domain, checked_at}`（永不存 key）。

### 阶段 5 — 首片（Prove）

目的不是交付最终效果，而是"证明通路"。

1. 仅当台账无 `first_success` 时执行；默认 `simple` + `t2v` + 最短时长 + 默认分辨率。
2. `agnes_task.py create ... --json` → 立刻拿 `task_id`，**当场把 `http://localhost:8765` 给用户**让他自己看进度。
3. 轮询只报增量：`agnes_task.py status <id> --wait --interval 10 --timeout 900`；单轮等待不超过 90s，超时则本轮结束、下轮续。
4. 成功：`download` 到 `outputs/<id>/`，写 `first_success`，一句话确认"通路已打通"，转入阶段 6。
5. 失败：进阶段 7，**不重复建任务**。

### 阶段 6 — 按真实需求产出

选型规则、规模代价与能力边界见 **§14**；进度播报格式与节奏见 **§15**。本阶段只执行这几步：

1. 按 §14 判定 pipeline，并**先向用户说结论 + 预计耗时**，给一次改判机会。
2. 提交前 `GET /api/concurrency`，可能要排队 → 明说，不静默等待。
3. 长视频 10–40 分钟：按 §15.3 跨轮次推进，每轮只报增量。
4. 上传类需求（首尾帧 / 形象图 / 分镜图）见 §14.4 的两条路径，别硬编。
5. 只有用户要求"你来改分镜/旁白/字幕"时才切 manual mode，否则保持 auto。
6. 交付：`download` 到 `outputs/<task_id>/`；`AGNES_OUTPUT_DIR` 非空再复制一份；汇报绝对路径 + `ffprobe` 的时长/分辨率。

### 阶段 7 — 失败处理（Report）

1. **先分类再动作**：
   - 可自愈（`video_queue_full` / `fail_to_fetch_task` / 429 / 超时 / 401 域名不匹配）→ 修配置或等窗口，`resume` 续跑同一任务，**不新建**、**不提 issue**。
   - 确定性故障（重试后仍失败、同一步稳定复现）→ 生成反馈包。
2. 生成反馈包（`troubleshoot` 的脚本）：

```bash
python3 scripts/report_issue.py <task_id>      # 拉 diagnostics → 脱敏 → 写报告 → 打印预填 URL
```

3. 给用户三样东西：报告文件绝对路径、一键预填 URL、一句话说明"点开即可提交"。
4. 禁止：agent 代发 issue、报告里出现 key、把"提示词效果不好"当 bug。

### 阶段 8 — 中断、换会话、恢复

- 所有进度落 `$AGNES_HOME/tasks/<task_id>.json`；新会话只需 `agnes_task.py resume <task_id>`，不必重建、不必重新下载。
- 服务进程被杀：`bootstrap.py start` 幂等重启；任务状态在服务端持久化，不会因此丢进度。
- 机器重启后：先 `probe`，`install.present` 为真就只启动（这正是"避免反复下载"在用户侧的直接体现）。
- 迁移：`$AGNES_HOME` 可整体拷贝（`config/` 含密钥，迁移即携带凭据，需提示用户）。

### 用户可见的对话节奏（示例）

```
用户：帮我做一条 30 秒的创意短片，讲灯塔看守人和海燕
agent：检测到本机还没有服务，我先装一下（约 2–5 分钟，装到 ~/.agnes-video）。可以吗？
用户：可以
agent：[装完] 服务已起在 localhost:8765，音色库和界面都正常。现在只差一个免费 API key：
       打开 https://platform.agnes-ai.com 领一个，粘到 localhost:8765 的配置页就行（不用发给我）。
用户：好了
agent：[detect + 校验通过] 通了。先用 5 秒样片跑通链路，再上 30 秒的正式版。
agent：[2 分钟后] 样片好了：~/.agnes-video/outputs/<id>/final.mp4。开始正式版，预计 15–25 分钟，
       进度可以在 localhost:8765 看，我这边每有阶段变化就报一次。
```

### agent 侧硬约束（写进 SKILL.md 顶部）

1. 只读 `SKILL.md`，`references/` 按分支懒加载。
2. 一切判断读脚本 `--json` 与退出码，不解析人类可读文本。
3. 单次阻塞等待 ≤90s，长任务跨轮次推进。
4. 不 echo key、不把 key 写进任何文件、不让用户把 key 发给 agent（除非用户主动选择 stdin 方式）。
5. 不重复建任务、不重复安装、不代发 issue、不静默换端口。

---

## 14. Pipeline 选择（按需求判定，不是按型号猜）

### 14.1 判定顺序（能推断就不问）

依次回答四个问题，任一答案唯一即可定型：

| # | 问题 | 影响 |
|---|------|------|
| Q1 | 素材形态：一句话 / 一段长文 / 一首诗 / 一张人物形象图 / 只要静图 | `simple` / `manuscript` / `poetry` / `anchor` / image |
| Q2 | 是否需要**多场景连续叙事**（有分镜、有转场、有剧情推进） | 是 → `creative`（无原文）或 `manuscript`（有原文） |
| Q3 | 是否需要旁白 + 字幕 | 否 → 仍可用长视频但你应确认；长视频默认带音频/字幕步骤 |
| Q4 | 是否必须上传图片（首帧 / 尾帧 / 形象图 / 分镜图） | 是 → 见 14.4 的上传限制 |

### 14.2 判定表

| 用户说 | 类型 | 关键参数 | 典型耗时 | 误选症状 |
|--------|------|---------|---------|---------|
| "做个 5–10 秒的镜头" | `simple` t2v | `prompt` | 1–5 分钟 | 用 creative → 白等 20 分钟还多出旁白 |
| "讲个故事 / 有分镜的短片" | `creative` | `idea`、`scene_count`、`scene_durations` | 场景数 × 3–8 分钟 | 用 simple → 只有一个镜头，剧情讲不完 |
| "这段文案/文章配画面" | `manuscript` | `manuscript_text` | 段数 × 3–8 分钟 | 用 creative → 原文被"再创作"，用户要的是原文旁白 |
| "真人口播 / 数字人" | `anchor` | 形象图 + 文案 + 音频模式 | 段数 × 3–8 分钟 | 用 creative → 没有人物一致性 |
| "古诗/诗句做成视频" | `poetry` | 诗句、音色 | 句数 × 3–8 分钟 | 用 manuscript → 断句与韵脚全丢 |
| "就生成一张图" | image | `prompt`、尺寸 | < 1 分钟 | 用视频 → 白烧配额 |

判定后**先说结论再动手**："这个需求适合 creative（AI 编剧+分镜），预计 15–25 分钟；如果你只想要一个镜头，用 simple 只要几分钟。"给用户一次改判机会，比事后重跑便宜。

### 14.3 规模与代价

- 场景数上限按用户时长诉求反推：`scene_count ≈ 目标时长 ÷ 单场景时长`，单场景默认 5s；超过 8 个场景要提醒"总时长会到 40 分钟以上，且每个场景都是独立失败点"。
- 首片策略（§13 阶段 5）用 `simple` 验证通路，正式产出再按上表选型——**不要用长视频做第一次验证**。
- 中途改判：已建 creative 但用户其实只要单镜 → `stop` 旧任务 + 新建 `simple`，并说明"旧任务的已生成片段不会复用"，不硬 `resume`。

### 14.4 能力边界（选型时必须先排除）

- `anchor`（形象图）、`i2v`/`ti2vid`/`keyframes`（首尾帧）、`creative` 的自定义分镜图：**`agnes_task.py` 不支持文件上传**（脚本明确写明）。可行路径只有两条：`curl -F` 上传拿路径，或请用户在 Web UI 里传。
- `external asset mode`（v7.6，即梦协作）：产物由外部工具生成后导入，属"用户已有素材"场景，不走本方案的默认选型表；遇到时指向 `manual_mode_guide.md` 与 `POST /api/tasks/{id}/artifacts/import`。
- 需要"agent 改分镜/旁白/字幕"才切 manual mode；否则保持 auto，避免无谓暂停。

---

## 15. 进度反馈（数据源、词汇表、播报节奏）

### 15.1 可用的真实字段（全部来自 `GET /api/tasks/{id}`）

| 字段 | 含义 | 用法 |
|------|------|------|
| `status` | `pending` / `queued` / `running` / `completed` / `failed` | 任务级状态，唯一终态判据 |
| `current_step` | 当前步骤 key（如 `story`、`video_gen`） | 映射成用户语言 |
| `current_status` | `running` / `completed` / `failed` | 当前步骤状态 |
| `current_progress` | 0.0–1.0 | 阶段内百分比（跨阶段已由流水线锚点归一，如 `audio_end=0.85`） |
| `current_message` + `current_message_key` / `_params` | 人类可读消息 / 22 语言 key + 插值参数 | **优先用 key+params** 让 UI 同语言；无 key 才回退 message |
| `step_*`（如 `step_story`、`step_video_generation`） | 每个步骤的 `StepStatus` | 精确判断"哪些步骤已完成"，不靠猜 |
| `active` | 后台是否有活跃 pipeline | 区分"真在跑"与"服务重启后遗留的 pending" |
| `upstream_errors[]` | 按 status_code 聚合的上游报错 | 解释"为什么慢/为什么失败" |
| `manual_config.current_checkpoint` | 非空 = 等你改产物 | 人工介入点 |
| `created_at` / `updated_at` | 时间戳 | 算已用时长、判断是否卡住 |

步骤词汇表按类型取自 `frontend/src/steps.ts`（与 UI 完全一致，不要自造词）：

- `simple`：submit → video_gen
- `creative`：init → scene_config → image_analysis → story → character_ref → script → end_frame_prompts → end_frame_gen → video_gen → audio → subtitle → concatenate
- `manuscript`：split_text → scene_prompts → video_gen → audio → subtitle → concatenate
- `anchor`：generate_anchor → split_text → clip_prompts → clip_gen → audio → subtitle → concatenate
- `poetry`：build_scenes → video_generation → audio → subtitle → concatenation

### 15.2 三层反馈

1. **任务级**：第几步 / 共几步 + 阶段名 + 已用时长（+ 可给粗估剩余）。
2. **步骤级**：哪些步骤已完成（读 `step_*`）、当前步骤在干什么、场景级的"3/5 个片段"这类计数（来自 `current_message_params`）。
3. **证据级**：产物路径（分镜图、片段、成片）、排队状态（`GET /api/concurrency` 的 `current_weight/max_weight/queued_count`）、上游错误码计数。

### 15.3 播报节奏

- **只报增量**：步骤变化、百分比跳变（≥10%）、新消息、进入终态、出现新的 `upstream_errors` 条目。相同状态不重复。
- **单轮等待 ≤90s**，超过就本轮收尾、下一轮续（`status <id>` 或 `resume <id>`）；长任务靠跨轮次推进，不靠一个超长命令。
- **卡住要解释，不要干等**：同一 `current_step` + `current_progress` 超过 10 分钟无变化 → 查 `/api/concurrency`（是否排队）与 `upstream_errors`（是否 429/503），把原因讲出来。
- 排队时先说明："当前并发权重 3/4，前面还有 1 个任务在跑，你的任务会先排队。"
- 一句话模板：

```
[creative 7/12 分镜视频] 已用 6 分 20 秒，5 个片段完成 3 个
下一个：剩余 2 个片段 → 配音 → 字幕 → 拼接，预计还需 8–12 分钟
进度也可以在这里看：http://localhost:8765
```

- 终态播报必须带**绝对路径**与 `ffprobe` 校验结果（时长/分辨率），失败时带 `failed` 的步骤名、错误摘要与诊断入口。

### 15.4 禁止

- 轮询把整份 `state.model_dump()` 贴进对话（几十个字段，用户读不懂，还烧上下文）。
- 自己编百分比（没有数据就说"进行中，第 7/12 步"）。
- 用 `current_message` 原文覆盖 key 场景（多语言用户会看到错的语言）。
- 把"没有变化"当"卡死"直接 `stop`/重建任务——先查并发与上游错误。

---

## 16. 开放问题

1. `AGNES_HOME` 默认 `~/.agnes-video` 是否可接受？还是沿用 `~/.agnes_config` 风格（配置与数据分开）？
2. D1/D2 是否本轮就改上游（推荐），还是先按退化方案发 P0、把上游改动单独排期？
3. 首次安装是否必须显式征求同意（我倾向"必须"，并缓存同意结果到台账），还是允许静默安装 + 事后告知？
