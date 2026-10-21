# 按项目拆分的工作项（配合 `skill-bootstrap.md`）

> 配套文档：`docs/plans/skill-bootstrap.md`（方案与契约）。本文只回答"哪个仓库要改什么、先后关系、怎么验收"。
> 本轮范围：把 skill 自身做成"零前置、可自举、进度可读、失败可反馈"。**不含 flint 推广链路**。

---

## 0. 涉及项目与依赖

```
A. agnes-video-generator-skills  ← 主战场（skill 文档 + 脚本）
      ├─ 依赖 B1/B2 才能做到"二次使用零下载"（否则 P0 退化）
      └─ 引用 B5（可选，省掉掩码解析）
B. agnes-video-generator         ← 上游启动器（bin/cli.js）+ 少量接口/文档
C. flint                         ← 本轮 0 改动（仅守住"不承诺未实现能力"）
D. agnes-video-generator-seo     ← 后置（发现面：/skills 页 + llms.txt）
```

依赖顺序：**A4（契约）→ A1（bootstrap 脚本）→ A2/A3/A7（文档）→ A5/A6（脚本增强）**；B1/B2 可与 A5/A6 并行，但必须在"宣布二次使用零下载"之前合入。

---

## A. agnes-video-generator-skills（主战场）

| ID | 工作项 | 文件 | 依赖 | 验收 | 预估 |
|----|--------|------|------|------|------|
| **A4** | 落地 bootstrap 契约：目录布局、状态机、退出码、锁、版本闸 | `docs/plans/skill-bootstrap.md`（已写）+ 新增 `skills/agnes-video-usage/references/bootstrap-contract.md` | — | 人评审通过；文中每条命令可直接复制执行 | 0.5d |
| **A1** | `bootstrap.py`：`probe / install / start / stop / status / uninstall / config-key`，`--json`，退出码 0/10/11/20/30/40/50 | `skills/agnes-video-usage/scripts/bootstrap.py`（新） | A4 | 计划 §10 用例 1–6 全过；`python3 -m py_compile` 通过 | 2–3d |
| **A2** | 重写 `SKILL.md`：§0 Bootstrap contract → 单文件 happy path → 选型/进度/失败分支指针；frontmatter 加 `version`/`requires_service`；description 补"无需预克隆" | `skills/agnes-video-usage/SKILL.md` | A1 | ≤160 行；只读此文件即可完成"零到出片"；缺参数时能正确分支 | 1d |
| **A3** | 部署文档改默认路线：C（npm `--prefix`）优先、B（Docker）次之、A（clone）只给 contrib；补目录契约与"只装一次" | `skills/agnes-video-usage/references/deploy.md` | A4 | 与 `bootstrap.py` 行为一致，无"先 clone"表述 | 0.5d |
| **A7** | 新增选型与进度两份参考：判定表 + 步骤词表（对齐 `frontend/src/steps.ts`）+ 播报模板 | `references/pipeline-selection.md`、`references/progress.md` | — | 六个类型的步骤序列与上游代码一致；含误选症状表 | 1d |
| **A5** | `agnes_task.py` 增强：尊重 `AGNES_HOME`、快照落 `tasks/<id>.json`、`resume`、`download` 默认落 `outputs/<id>/`、`--json` 字段稳定 | `scripts/agnes_task.py` | A1 | 现有命令不回归；快照可跨会话续跑 | 1d |
| **A6** | `report_issue.py`：拉 `/diagnostics` → 脱敏 → 写 `reports/issue-<id>.md` → 打印预填 URL（body ≤4000） | `skills/agnes-video-troubleshoot/scripts/report_issue.py`（新） | A5 | 报告中无 key、无绝对家目录；URL 可打开且字段完整 | 1d |
| **A8** | `contrib` 微调：明确 clone 路线归它，避免与 usage 的"不克隆"冲突 | `skills/agnes-video-contrib/SKILL.md` | A3 | 两个 SKILL.md 无矛盾表述 | 0.2d |
| **A9** | 自检收口：`py_compile`、`bash -n`、实跑一遍真实出片 | 全仓库 | A1/A2/A5/A6 | `AGENTS.md` §6 自检清单全绿 | 0.5d |
| **A10** | README 安装节改写："skill 会自己按需安装，不需要先克隆服务仓库"；flint 段落保持现状 | `README.md` | A2 | 新用户按 README 能直达"一句话出片" | 0.3d |
| **A11** | `AGENTS.md` 增补 bootstrap 约定：脚本只写 `$AGNES_HOME`、key 处理红线、版本闸 | `AGENTS.md` | A4 | 后续新增 skill 能照此执行 | 0.2d |

**边界**：本仓库不含服务代码；`usage` 不修改上游仓库；`troubleshoot` 只收集证据不下结论式修复；发布不动。

---

## B. agnes-video-generator（上游）

只做"让 skill 能复用环境"的最小改动，不碰流水线。

| ID | 工作项 | 文件 | 依赖 | 验收 | 预估 |
|----|--------|------|------|------|------|
| **B1** | 启动器支持 `AGNES_HOME`：venv → `$HOME/venv`，子进程注入 `AGNES_CONFIG_DIR=$HOME/config`，首次启动后不再落在 npm 缓存 | `bin/cli.js` | — | 清空 `.npm/_npx` 后重启仍复用同一 venv；`$AGNES_HOME` 内能看到 venv/config | 0.5d |
| **B2** | 依赖只在需要时安装：把 requirements 的 sha256 写 `.venv/.agnes-req.sha256`，一致则跳过 `pip install` | `bin/cli.js` | B1 | 第二次启动无 pip 网络动作（可断网验证）；改 requirements 后自动重装 | 0.5d |
| **B3** | `--detach` + `--json`：后台启动、写 pid、就绪后回传 `{pid, base, ready}` | `bin/cli.js` | B1 | agent 可一条命令起服务并拿到机读结果；前台模式不变 | 1d |
| **B4** | （可选）`--print-paths`：打印 config/workspace/venv 实际路径 | `bin/cli.js` | B1 | 输出与 skill 台账一致 | 0.2d |
| **B5** | （可选）`GET /api/config` 增加 `has_key: bool`，免去掩码解析 | `web/routes/config_routes.py` | — | 字段向后兼容；无 key 时 false | 0.2d |
| **B6** | 文档同步：npm 路线补 `AGNES_HOME` 与"只装一次"；`agent-operations.md` Level 2 指向新的 bootstrap | `docs/public/getting-started.md`、`docs/public/agent-operations.md` | B1/B2 | 与 skill 行为一致，无过期表述 | 0.5d |
| **B7** | 回归：`./scripts/run_mock_regression.sh` + npm 路线 smoke（临时 `AGNES_HOME`） | — | B1–B3 | 回归通过；smoke 产出 mp4 | 0.5d |
| **B8** | 发版：版本号 + release notes + npm publish（**由维护者人工执行**） | `docs/public/release-notes/*`、`package.json` | B1–B7 | 发版后 skill 的 `requires_service` 才对得上 | 0.5d |

> 若 B1/B2 本轮不做：A1 用 `npm i --prefix $AGNES_HOME/runtime` 兜住安装位置，但**每次升级仍会重装依赖**——此时 A2/A10 的文案不得宣称"零下载"，只能写"只装一次，升级时会重装"。

---

## C. flint（本轮 0 改动）

| ID | 工作项 | 说明 | 验收 |
|----|--------|------|------|
| C1 | 不新增 `flint add`、不做 registry | 本轮范围外 | — |
| C2 | 守约束：skill 文档里关于 flint 的表述保持现状，不承诺未实现能力 | 只检查 `README.md`、`agent-operations.md` 的措辞 | 无"一行命令自动安装"之类未实现承诺 |

---

## D. agnes-video-generator-seo（后置，P1 发现面）

| ID | 工作项 | 文件 | 依赖 | 验收 |
|----|--------|------|------|------|
| D1 | `/skills` 落地页：三个 skill 的用途 + raw URL + 一句"何时用" | 站点页面 | A2 | 页面可达，链接指向 `raw.githubusercontent.com` |
| D2 | `llms.txt`：机器可读索引（skill 名、raw URL、适用场景、`requires_service`） | 站点根 | D1 | 陌生 agent 顺着它能走到 `SKILL.md` |
| D3 | 两处互链：`getting-started` / `faq` 加"给 agent 的一句话 + skill 地址" | 官网文档 | A2 | 链接无 404 |

---

## 建议的执行波次

| 波次 | 内容 | 可并行 | 产出 |
|------|------|--------|------|
| W0 | A4 契约定稿 | — | 可评审的契约（本文 + 方案） |
| W1 | A1 + A2 + A3 + A7 | 是 | skill 侧自举可用（接受一次性安装成本） |
| W2 | A5 + A6 + A8 + A9 | 是 | 跨会话续跑 + 反馈闭环跑通 |
| W3 | B1 + B2（+B3） | 与 W2 并行（不同仓库） | 二次使用零下载 |
| W4 | A10 + A11 + B4/B5 + B6 | 是 | 文档与台账对齐 |
| W5 | B7 + B8（+D 后置） | — | 发版；skill `requires_service` 生效 |

---

## 统一验收入口

```bash
# A（skill 仓库）
python3 -m py_compile skills/*/scripts/*.py
bash -n skills/*/scripts/*.sh
AGNES_HOME=$(mktemp -d) python3 skills/agnes-video-usage/scripts/bootstrap.py install --yes
python3 skills/agnes-video-usage/scripts/bootstrap.py status --json    # 期望 code=10（缺 key）

# 二次运行（关键：不得有安装动作）
python3 skills/agnes-video-usage/scripts/bootstrap.py start --json     # 期望 <1s 返回 0

# B（上游）
./scripts/run_mock_regression.sh
AGNES_HOME=$(mktemp -d) npx free-short-video --detach --json           # B3 之后
```

计划级的 7 条验收用例（冷启动 / 二次使用 / 服务在跑 / 并发 / 版本闸 / 路径安全 / 交付目录）见 `skill-bootstrap.md` §10。

---

## 实施状态（2026-10-21）

| 项 | 状态 |
|----|------|
| A1 `bootstrap.py`（含 `verify`） | ✅ 已实现并推送 |
| A2 `SKILL.md` 重写 | ✅ |
| A3 `deploy.md` 默认路线改 npm | ✅ |
| A4 `bootstrap-contract.md` | ✅ |
| A5 `agnes_task.py` 快照 | ✅ |
| A6 `report_issue.py` | ✅ |
| A7 `pipeline-selection.md` / `progress.md` | ✅ |
| A8 `contrib` 微调 | ✅ |
| A9 真实安装冒烟 | ⬜ 待跑（需联网下载数百 MB） |
| A10 README 安装节 | ✅ |
| A11 `AGENTS.md` bootstrap 约定 | ✅ |
| B1 `bin/cli.js` 支持 `AGNES_HOME` | ✅ |
| B2 requirements 指纹跳过 pip | ✅ |
| B3 `--detach` / `--json` | ✅ |
| B4 `--print-paths` | ✅ |
| B5 `GET /api/config` 增 `has_key` | ✅ |
| B6 文档同步（getting-started / agent-operations） | ✅ |
| B7 回归 / B8 发版 | ⬜ 回归可跑，发版需维护者执行 |

> 新增上游能力：`AGNES_WORKING_DIR`（默认工作区可重定向），由 `bin/cli.js` 在 `AGNES_HOME` 模式下注入。

---

## 明确不做

- 不改视频流水线、不改前端 UI、不加遥测。
- 不做 flint 分发、registry、推广归因。
- 不在 skill 里代发 issue、代管凭据、代做发布。
- 不支持"无 key 出片"的任何取巧实现。
