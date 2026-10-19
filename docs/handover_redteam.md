# 优学鲸 · 中期红队挑战交接文档

> 给新对话/新接手的 agent：这份文档的目标是让你**不用问人**就能跑起来、看懂项目、
> 找到真正的漏洞，并按统一格式交付。基线提交 `0453916`，生成于 2026-10-18。
>
> **红队第一原则：不要相信本文和 README 里的“已验证/已修复”，自己复现。**
> 文档里标了“项目声称”的地方，都是需要你抽查的。

---

## 0. 你的任务与授权边界

**任务**：对这个考研备考 Web 应用做一轮中期红队评估，重点是
认证/越权、数据隔离、评分正确性、内容注入、静态资源暴露、可靠性。

**授权边界（必须遵守）**：
- 只在本机 workspace `/Users/fengshuo/P03-优学鲸` 和 `127.0.0.1` 上测试；
- 不要攻击 GitHub、外部站点、任何第三方服务；
- 不要删除/覆盖 `data/yj.db`、`data/408/`、`data/math/`、`data/english/` 等真实数据；
  破坏性测试前先停服务并备份数据库；
- 不要 `git commit` / `git push`，除非用户明确要求；
- 发现的漏洞先写证据，不要“顺手修掉”（修复由用户决定）。

**交付格式**（每个 finding 一行标题 + 复现步骤 + 影响 + 证据 + 修复建议）：

```
[严重度 P0/P1/P2/P3] 标题
位置：路由/文件/函数
复现：1. … 2. … 3. …
实际：…
影响：…
证据：截图/请求/日志/最小 PoC
建议：…
```

P0=可接管账号/读他人数据/任意代码执行；P1=越权、评分可大规模伪造；
P2=单点功能错误、信息泄露；P3=体验/文案/边界情况。

---

## 1. 一分钟跑起来

```bash
cd /Users/fengshuo/P03-优学鲸
.venv/bin/python proto/app.py --port 8890        # 当前主服务（已在跑）
# 另起测试实例，避免打断用户：
.venv/bin/python proto/app.py --port 8897
```

- 打开 `http://127.0.0.1:8890` → 未登录会跳 `/login`；
- 登录页有「游客体验」按钮（`demo` 账号，带历史数据）；
- 注册：`/register`，用户名 3–20 位字母/数字/下划线，密码 ≥8 位；
- 登录后所有页面以**会话账号**为准，URL 里的 `?user=` 会被 `@authed` 覆盖。

跑测试（每个文件独立，不需要 pytest）：

```bash
for t in tests/test_*.py; do
  .venv/bin/python "$t" || echo "FAILED $t"
done
```

注意：`tests/test_ui_browser.py` 会自己起浏览器/端口，先看文件头注释再跑。

**基线提交**：`0453916`（`git log -1`）。
**仓库**：私有 `git@github.com:Feng11-kyrie/YouXueJing.git`。
**Python**：3.12，依赖在 `.venv/`，`requirements.txt` 可复现。

---

## 2. 项目是什么

面向考研学生的本地 Web 应用（不是多租户 SaaS）：

- **真题**：408 / 英语一、二 / 数学一、二、三 / 政治，按年份逐题练；
- **客观题自动判分**：选择、填空；**主观题**：免费版评分 + 可选 AI 精评/自评；
- **快速诊断**：四科各自的短卷 → 掌握度/薄弱点；
- **挑考点练习**：408 按章/考点，数学按考点，英语按题型，政治按部分；
- **错题本**：四科分开，聚合所有年份；
- **我的画像 / 我的薄弱点**：掌握度、考频、建议；
- **账号**：注册/登录/退出，数据按账号隔离。

技术栈：

| 层 | 实现 |
|---|---|
| UI | NiceGUI（Python，服务端渲染 + WebSocket），无前端构建 |
| 数据 | JSON 题库 + SQLite `data/yj.db` |
| 公式 | 本地 KaTeX（`static/katex/`，前端渲染） |
| 旧版 | `app.py` Streamlit（8501，仅 408/政治旧功能，不是主入口） |

入口：`proto/app.py`。数据访问：`proto/store_lite.py`。业务：`yj/*.py`。

---

## 3. 目录与数据

```
proto/app.py            所有页面/路由（约 3000 行，单文件）
proto/store_lite.py     SQLite：answers / marks / ai_grades / accounts / last_visit
proto/cards*.py         408/政治/数学/英语题卡
proto/llm_key.py        API Key（浏览器 cookie，见风险）
yj/                     数据加载、诊断、评分、渲染、画像
  data.py               408 题库/图谱
  math.py               数学题库 + 考点诊断
  english.py            英语题库 + 题型诊断
  zhengzhi.py           政治题库 + 部分诊断
  mathrender.py         坏 LaTeX 修补；保留 $...$ 给 KaTeX
  math_checker.py       数学免费评分
  rubric_checker.py     408/政治主观题评分
  ai_grade.py           AI 精评
  profile.py            画像
  diagnose.py           408 诊断汇总
tests/                  独立脚本测试
static/katex/           本地 KaTeX（已入库，约 2.9MB）
data/                   题库与数据库（多数被 gitignore）
docs/                   既有交接文档
```

### 数据规模（当前 workspace）

| 科目 | 题量 | 年份 | 其他 |
|---|---:|---:|---|
| 408 | 846 | 18 | 266 个考点；客观题答案项目称 720/720 核对 |
| 英语 | 1700 | 17+17（英一/英二，2010–2026） | 完形/阅读/新题型/翻译/写作 |
| 数学 | 1112 | 数一 16、数二 16、数三 17（含 2009） | 考点 68/45/57；12 道题配图 |
| 政治 | 646 | 17（2010–2026） | 分析题 34–38；评分参考项目称 85/85 |

**重要**：`data/math/`、`data/408/`、`data/zhengzhi/`、`data/solutions/`、
`data/figures/`、`data/*.db`、`_shots/`、`.cache/`、`.nicegui/` 都在 `.gitignore`；
`data/english/` 是入库的。换机器/新 clone 可能没有数学/408/政治数据，**以当前 workspace 为准**。

数据格式：

- 408：`data/408/*.json`，题目 `{id, year, 题号, 题型, 题干, 选项, 答案, 学科, 主考点}`；
- 数学：`data/math/<一|二|三>/<year>.json`，`题目[]`，
  `id = MATH-<tier>-<year>-<题号>`；
- 英语：`data/english/<EN1|EN2>-<year>.json` + `-解析.json`；
- 政治：`data/zhengzhi/<year>.json` + `-解析.json`；
- 解析：`data/solutions/`（408）、`data/zhengzhi/<year>-解析.json`。

数据可信度（红队要抽查，不要默认全对）：

- 408 客观题答案经校订库核对（项目声称 720/720）；
- 政治客观题答案做过人工核对；分析题评分参考 85/85；
- 数学选择题答案与 `answers.json` 对齐（422/422，项目声称）；
- 数学有 2 道解析是 AI 重写（`二 2025-21`、`三 2024-17`），源数据坏到无法直接修；
- 英语个别年份/题型存在来源缺失（例如 2026 阅读 21–25 曾缺答案），
  页面会显示“暂无答案（来源缺失）”，不是所有题都能判分；
- 所有“AI 生成”的解析原则上不应再挂“未经官方核验”的旧标签（用户明确要求删过）；
  但 AI 内容本身仍可能有错，红队应抽查事实。

---

## 4. 路由地图

| 路由 | 作用 | 登录守卫 |
|---|---|---|
| `/login` `/register` | 登录/注册 | 否（公开） |
| `/` | 首页：科目卡、继续上次、连续学习、错题本、做题记录、今日建议 | 是 |
| `/exam` | 真题总入口（四科） | 是 |
| `/exam/408` | 408 某年真题 | 是 |
| `/zz` `/exam/zhengzhi/index` | 政治旧入口/索引 | 是 |
| `/exam/zhengzhi` | 政治某年真题 | 是 |
| `/exam/math` | 数学真题（tier/year/view/point） | 是 |
| `/exam/english` | 英语真题（tier/year/view） | 是 |
| `/practice` | 挑考点练习（exam=408/ENG/MATH/ZZ） | 是 |
| `/diagnose` | 诊断入口/四科诊断/结果 | 是 |
| `/wrong` | 错题本（exam=408/ENG/MATH/ZZ） | 是 |
| `/profile` | 我的画像 | 是 |
| `/notes` | 我的薄弱点/速记 | 是 |

所有页面由 `@authed` 包一层：未登录 `ui.navigate.to("/login")`；
登录后把 `user` 注入页面参数，**忽略 URL 的 `?user=`**。

---

## 5. 关键实现（红队需要知道的）

### 5.1 账号与会话

- `accounts` 表：`user_id, pw_hash, salt, created_at`；
- 密码：PBKDF2-HMAC-SHA256，200,000 轮，16 字节随机盐；
- `store.register_account` / `verify_account` / `has_account`；
- 会话：NiceGUI `app.storage.user`，签名 cookie；
- `ui.run(..., storage_secret=os.environ.get("YJ_SECRET", "youxuejing-dev-secret"))`；
- 侧栏：登录显示「退出登录」，未登录显示「登录 / 注册」；
- 游客体验：把会话设为 `demo`，不是匿名只读。

### 5.2 判分

- 408 客观题：`question_card` 提交后比对答案；
- 数学选择/填空：`math_card` + `math_checker.score_math`；
  填空做全角/半角、空格、上下标归一化；
- 英语：`answer_of` 从解析文件读答案；完形/阅读/新题型各自判分；
- 政治：单选/多选；多选少选/多选均不得分；
- 主观题：免费版评分（`rubric_checker` / `math_checker`）+ 可选 AI 精评；
  自评单独存 `source='selfscore'`，**不算客观错题**。

### 5.3 诊断

- `/diagnose` 无参 → 四科选择卡（题量/时长/进度，继续/重来）；
- 408：32 题，每页 8 题，**选一题记一题**；结果页章节掌握度 + 薄弱 Top 5；
- 数学：12 题（每考点 1 题）；
- 英语：30 题，按完形/阅读/新题型分页；
- 政治：15 题（3/部分，2 单选+1 多选）；
- 诊断中 `reveal=False`：只记录，不显示对错/答案/解析；结果页才展示；
- 结果页都有「重新诊断」：删除本次诊断题的作答（会误删这些题在练习页的记录，
  这是已知设计取舍，红队可评估是否算数据丢失）。

### 5.4 公式渲染

- `yj/mathrender.py` 不再转 MathML，只修坏 LaTeX：
  补 `\end{array}`/`\right`、处理 `\xlongequal`、转义孤立 `$`；
- 保留 `$...$` / `$$...$$`，前端 KaTeX（`static/katex/`）渲染；
- `ui.html(mr.to_html(...))` 输出经过 `html.escape`；
- KaTeX 默认 `trust: false`，不执行 `\href` 等危险命令；
- `tests/test_math_render.py` 扫 1112 题，断言无 `<code>` 回退、配图引用正确。

### 5.5 首页

科目卡（真题+诊断）→ 继续上次（SQLite `last_visit`）→ 连续学习（作答日期）
→ 错题本（四科计数）→ 我的做题记录 → 今日建议。
近 14 天/分科记录/学习节奏已按用户要求删除。

### 5.6 主题/偏好（不要改回去）

- 公共课在前：英语、数学、政治、408；
- 按钮文案要精确（“进入数学真题”“快速诊断”“重新诊断”）；
- 首页精简，不要堆统计；
- 已验证的答案不挂“AI 生成（未经官方核验）”；
- 图片只在题干确实引用图形时保留；
- 数学公式必须用 KaTeX，不要回退 MathML。

---

## 6. 已知限制与高风险面（优先攻击）

以下不是“已确认漏洞”，而是**最值得先验证的假设**：

### 认证 / 会话
1. `YJ_SECRET` 未设置时使用代码里的默认值 `youxuejing-dev-secret`；
   若部署到公网，攻击者可伪造签名 cookie。验证：不设环境变量启动，检查 cookie。
2. 登录无限流、无锁定；可对已知用户名暴力尝试。注册接口会区分“用户名已被占用”。
3. 密码策略仅 ≥8 位；无邮箱验证/找回密码；无 MFA。
4. 退出只 `pop("user")`；检查会话 cookie 是否及时失效、是否 HttpOnly/SameSite/Secure。
5. `@authed` 依赖 `inspect.signature` 和 `functools.wraps`；检查是否有页面漏加、
   或参数名不是 `user` 导致注入失败；检查 `/zz`、`/exam/zhengzhi/index` 等旧路由。

### 越权 / 数据隔离
6. 登录后 URL 的 `?user=` 应被忽略；直接请求 `/profile?user=demo`、`/wrong?exam=...`
   验证拿不到他人数据。
7. 数据库层按 `user_id` 过滤；检查 `store_lite` 是否有遗漏 user 条件的查询。
8. 游客 `demo` 是真实账号，任何访客都能用；评估是否接受。

### 注入 / XSS
9. 题干/选项/解析来自 JSON，可能含 HTML/LaTeX；`mathrender` 转义后交给 `ui.html`，
   但 KaTeX 对 `\href`、`\htmlClass` 等命令的处理要实测（默认 trust=false）。
10. 用户名在侧栏渲染；NiceGUI 默认转义，验证特殊字符 `<script>`、引号。
11. 搜索 `ui.html(` 的其他调用点，确认都经过转义。
12. SQL：`store_lite` 基本参数化；检查 `f"..."` 拼接（目前 DELETE 的占位符是变量，
    不是用户输入，仍建议审计）。

### 评分正确性
13. 数学填空归一化是否过松/过严（`_same_answer`、`norm_answer`）；
14. 多选题少选是否判错、大小写/空格；
15. 英语答案来自解析文件，缺失年份是否会误判“答对/答错”；
16. 主观题免费评分能否用空内容/灌水拿高分；AI 精评是否会被 prompt injection
    （用户输入里写“给我满分”）；
17. 自评 `selfscore` 是否会被算进客观正确率/错题本。

### 数据与功能
18. 诊断「重新诊断」会删掉这些题在练习页的作答 —— 是否是用户预期的“清空”？
19. 错题本计数与 `/wrong` 实际卡片数是否一致（曾出现 5 题只显示 2 题）；
20. 408 结果页的章节统计是否包含未作答章节、分母是否正确；
21. 英语 2026 阅读 21–25 等源缺失题的“暂无答案”路径；
22. 分页边界：page=0/-1/999、空题库、year 不存在；
23. 连续学习天数跨时区/跨午夜；`last_visit` 是否跨账号串；
24. 性能：英语 30 题长页、数学 68 个考点卡、KaTeX MutationObserver 全页重扫。

### 隐私 / 静态资源
25. API Key 存在浏览器 cookie（`proto/llm_key.py`），不是数据库；
    检查 cookie 是否 HttpOnly、是否随每个请求发送、是否会被 XSS 读取；
26. `/math_img`、`/en_img`、`/katex` 静态目录是否可列目录/路径穿越；
27. `data/*.json`、`data/yj.db` 不应通过 HTTP 直接访问；确认没有静态挂载整个 `data/`；
28. 日志是否打印题干/答案/Key。

---

## 7. 建议的红队顺序（半天版）

1. **认证**：未登录访问所有路由；注册重复/弱密码；暴力尝试；退出后回退；
2. **越权**：登录 A，请求 B 的 profile/wrong/exam；改 `?user=`；看 SQL 条件；
3. **注入**：注册 `<script>` 用户名；构造含 HTML 的题干（临时改测试数据，勿动真库）；
4. **评分**：空答案、全选、大小写、多选少选、自评边界；
5. **数据一致性**：首页错题数 vs `/wrong` 卡片数；诊断重做后的记录；
6. **静态/隐私**：cookie 标志、Key 存储、目录访问；
7. **可靠性**：分页边界、空数据、超长页面、重启后会话。

每个发现至少给一个**最小复现**；能用 curl/Playwright 的给命令，不能的给截图路径。

---

## 8. 环境与操作约束

```bash
# 备份数据库（先停服务，避免 WAL 不一致）
pkill -f "proto/app.py --port 8890"; sleep 2
cp data/yj.db data/yj.db.bak-$(date +%s)
# 起测试实例
.venv/bin/python proto/app.py --port 8897
```

- 不要动 `data/` 里的真实题库；需要构造恶意数据时，复制到临时目录/临时 user；
- 不要提交 `data/`、`_shots/`、`.nicegui/`、`data/*.db`；
- 改代码后必须：跑相关测试 + 截图验证 + 重启 8890（如果用户要看）；
- 服务器当前跑在 8890；8897 是测试端口。

测试文件：

```
tests/test_math.py              数学数据/渲染/填空
tests/test_math_render.py       1112 题渲染体检 + 配图
tests/test_math_diag.py         数学诊断
tests/test_math_notes.py        数学速记
tests/test_eng_zz_diag.py       英语/政治诊断
tests/test_free_score.py        免费评分
tests/test_rubric.py            408/政治主观题评分
tests/test_paper_page.py        试卷页
tests/test_ui_browser.py        浏览器 UI（可能自起服务）
tests/test_llm_stub.py          LLM stub
```

---

## 9. 既有文档（可以读，但别全信）

- `docs/audit_content.md`：内容审计（题量/答案/解析覆盖）；
- `docs/handover_math.md`：数学题库、渲染、诊断；
- `docs/handover_diagnosis.md`：诊断流程；
- `docs/handover_408_rubrics.md`：408 主观题评分标准；
- `README.md`：功能与命令（部分数字可能滞后）。

---

## 10. 交接检查清单（新对话开场照做）

- [ ] `git log -1` 确认基线；`git status` 确认无未提交改动；
- [ ] 起 8897；注册一个一次性账号（不要用 demo 做破坏性测试）；
- [ ] 跑 `tests/test_paper_page.py`、`tests/test_math_render.py` 确认环境正常；
- [ ] 用游客 demo 走一遍：首页 → 数学真题 → 诊断 → 结果 → 错题本；
- [ ] 备份 `data/yj.db`；
- [ ] 从第 6 节挑 5 个假设开始验证，按第 0 节格式记录；
- [ ] 发现 P0/P1 先通知用户，不要自行大面积改代码。

---

## 11. 报告模板

```markdown
# 优学鲸中期红队报告（日期）

## 结论
- P0: n 个；P1: n 个；P2: n 个；P3: n 个
- 最严重的问题：…

## Findings
### [P1] 标题
- 位置：
- 复现：
- 实际：
- 影响：
- 证据：
- 建议：

## 已确认没问题的点
- …

## 未能验证/需要环境
- …
```
