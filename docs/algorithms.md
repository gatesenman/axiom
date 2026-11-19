# 算法目录

工作室工具栏上的算法下拉框（`data-algorithm`）和「自动」走的是同一份目录。选中具体算法时，竞赛仍然并行，但只有对应求解器带上该方法的选项；其余求解器按各自的默认设置求解。选「自动」时，保留你指定的首选求解器，并在它正好是建议方法的求解器时带上该方法选项。

接口：`GET /api/algorithms`。求解请求体可以带 `algorithm`。建议接口 `POST /api/recommend` 在原有 `solver`、`family`、`reason_zh`、`reason_en` 之外，增加 `algorithm`、`label_zh`、`label_en`。点「采用建议」会同时改首选求解器和算法。

## 目录

| id | 求解器 | 何时使用 |
| --- | --- | --- |
| `auto` | 用户首选 | 按结构选择方法，并保留多求解器竞赛 |
| `dual-simplex` | HiGHS | 连续线性规划，对偶单纯形（`simplex_strategy = 1`） |
| `primal-simplex` | HiGHS | 连续线性规划，原始单纯形（`simplex_strategy = 4`） |
| `barrier` | HiGHS | 连续线性规划，内点法（`solver = ipm`） |
| `branch-and-cut` | HiGHS | 混合整数。整数模型不会被强制成单纯形，仍走分支切割 |
| `cbc-branch-and-cut` | CBC | 另一套分支切割 |
| `scip-mip` | SCIP | 混合整数 |
| `cp-sat` | CP-SAT | 较小的整数或约束模型 |
| `slsqp` | SciPy | 连续非线性 |
| `ipopt` | IPOPT | 连续非线性内点法（本机装了才可用） |
| `weighted-sum` | HiGHS | 两个及以上线性目标。展开时已按权重合成一个目标，再跑对偶单纯形 |
| `local-search` | 局部搜索 | 0-1，或跨度不超过 8 的有界整数，且定义域乘积不超过 8192 时完全枚举。只有选中才加入竞赛 |
| `row-generation` | HiGHS | 先放入第一条约束。无界则按原顺序再加一行；有解则加入违反最严重的省略行，直到对全部行可行。若加完仍无界，退回完整模型再解一次 |

自动选择的顺序：二阶锥 → Clarabel；次数高于 2 的非线性 → SLSQP；凸二次 → OSQP，混合整数二次 → PySCIPOpt；至少两个线性目标 → 加权和；含整数或 0-1 → 分支切割（变量不超过 40 个时，建议句会提到 CP-SAT）；其余连续线性规划 → 对偶单纯形。建议句会附上当前模型能调用的全部求解器。

同一目录里还有 CLP、PDLP、Clarabel、ECOS、SCS、OSQP、CVXOPT、python-mip、PySCIPOpt、SciPy HiGHS、trust-constr、Gurobi、CPLEX、Xpress、MOSEK、COPT、Knitro、BARON、Hexaly、Bonmin 和 Couenne。选中其中一项时，竞赛仍并行，选项只交给对应的求解器。未安装的商业求解器和没有可执行文件的 Bonmin / Couenne 不会进入竞赛。

## 与标准方程的衔接

`sos1` 和 `piecewise` 在展开成标准方程之前被线性化，所以「标准方程」页和求解器看到的是同一批线性行。

```
sos1 pick: xA, xB;
```

表示至多一个变量非零。每个成员需要有限上界 `U`，线性化引入 0-1 变量 `y`，并加 `x <= U y` 与 `sum y <= 1`。下界为负时再加 `x >= L y`，使 `y = 0` 时变量回到 0。

```
piecewise cost on x: (0, 0), (10, 5), (20, 30);
```

是 SOS2 风格的凸组合：断点权 `λ >= 0`、`sum λ = 1`，自变量和函数值都是断点的加权和，相邻段用 0-1 变量限制只有一段被选中。横坐标必须严格递增，至少两个断点。函数名对应的变量若不存在会自动补上。

下标越界时，报错会写明下标、偏移、当前元素、集合名和集合长度，方便对着标准方程核对。

## 影子价格

连续线性规划的最优基上，HiGHS 的行对偶写入 `duals`，列对偶写入 `reduced_costs`。结果页的影子价格图同时画出两者：约简费用以 `rc:` 前缀标出，对应的约束名就是变量名。绝对值小于 `1e-8` 的项不画。

## 审计、隔离与频率

导入模型、套用表格、在数据页改模型、开始求解、导出报告都会写入审计日志，动作分别是 `model.import`、`data.import`、`model.edit`、`run.start`、`report.export`。

非管理员只能访问自己加入的工作区。管理员在成员检查上仍可进入工作区；隔离测试使用两个普通成员。

对话和开始求解有内存滑动窗口（大约每分钟 40 次对话、48 次求解）。超出后接口返回 429，界面用中英双语提示。语言模型调用若抛出未预料的异常，也会收成同样的双语错误，而不是一段裸的堆栈。
