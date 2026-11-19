# 问题生命周期

一个「问题」是从自然语言受理走到归档的档案。工作室里的项目仍然是正在编辑的模型；`Project.status` 仍是 `draft` / `solved` 这一类求解状态，不会被生命周期阶段覆盖。每个项目最多对应一个问题。

## 阶段

主线每次只走一步：

`草稿 → 受理 → 建模 → 方程 → 求解 → 分析 → 评审 → 决策 → 归档 → 关闭`

旁路：挂起、阻塞、驳回、重开。挂起和阻塞会记下离开时的阶段，恢复时回到那一阶段。归档不能退回决策，只能重开或关闭。关闭只能重开。

指定一个主线上的目标阶段时，系统按合法的单步逐跳记录，每一步都有操作者、可选说明和时间。不能跳过机器不允许的边，例如从挂起直接进入评审。

## 角色

`viewer` 只读。`modeler` 处理草稿、受理、建模、方程、重开，以及需求、数据和模型版本。`solver` 处理求解和求解记录。`reviewer` 处理分析、评审、决策和驳回。`owner` 可以做全部变更，包括归档、关闭和永久删除。管理员视同负责人。

智能体提议下一阶段时，若问题打开了「需要人工批准」（默认打开），只生成待批准请求，不直接改阶段。人在对话里明确说「推进到求解」时，这句话本身就是批准，阶段会立刻走完。

## 档案里有什么

- 需求与验收标准。离线时按陈述里的「最大 / 不超过 / 整数」等字样给出可勾选的建议，不调用外部模型。
- 数据资产：正文、由表头推出的字段、版本号、上一版。
- 模型版本：语义化版本、AML、标准方程（矩阵式与展开式的 LaTeX）、LP / Pyomo / AMPL 导出、统一差异、唯一基线。
- 求解记录：求解器、参数、种子、耗时、状态、目标、解向量、对偶、IIS、日志。关联模型版本和数据版本。HiGHS 与 SCIP 的对比各自在子进程里求解，避免和 HiGHS 挤在同一个解释器里加载 OR-Tools。
- 分析研究：复用分析工作台的 `run_study`（局部灵敏度、试验设计、Sobol、不确定性等），挂在问题上。
- 决策备忘和变更请求。采纳变更会在合法时重开并回到建模。
- 产物：PDF、PNG、SVG、LaTeX。单份不超过 2MB。
- 活动时间线，以及工作区审计日志。

## 问题包

导出格式是 `axiom-problem-1` 的 JSON，内含问题、需求、模型、数据、求解、分析、决策、活动、产物和当前最好目标。导入会在同一工作区新建项目和问题。超过约 1.5MB 的产物正文在导出时省略。这不是求解报告那种 zip。

搜索用 SQLite `LIKE`，范围是标题、陈述、模型 AML 和求解笔记。工作区隔离、审计和原有限流仍然生效。

## 界面

左侧项目树在原有「问题 / 模型 / 标准方程 / 数据 / 运行 / 报告」之下增加生命周期节点。编辑区多一个「生命周期」页：看板、表格、保存的视图、阶段步进、版本差异、求解对比、回收站。回收站里的问题只有负责人可以永久删除。

对话里的「建成问题」会把当前陈述写入问题。像「把这个问题推进到求解并跑 HiGHS 和 SCIP 对比」这样的句子会推进阶段并记下两次求解。普通的产品组合陈述不会被当成生命周期指令。

## English

A Problem is the record that moves from intake to the archive. The studio Project remains the document being edited, and `Project.status` stays the solve status. Stages advance one legal hop at a time, with the actor, an optional comment, and a timestamp. Viewers are read-only. Owners archive, close, and permanently delete. Agent proposals wait on the human approval gate; an explicit chat command applies immediately. The share package is JSON (`axiom-problem-1`). Search is SQLite `LIKE`. Solver comparisons run in child processes.
