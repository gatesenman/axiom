# Windows 离线安装与重新构建

交付物是 Windows x64。安装包和便携版都带上 Python 3.12.10 embeddable、`vendor/wheelhouse` 里的 Windows 轮子，以及 GLPK 的 `glpsol.exe`。Electron 只启动相对安装目录的 `resources\python\python.exe`，不会调用系统 Python。

## 在这台 Windows 电脑上运行

1. 安装包：运行 `Axiom-Setup-1.0.0-x64.exe`，把目录改成 `E:\mydevieAPP`。
2. 或解压 `Axiom-1.0.0-win-x64.zip`，让 `Axiom.exe` 位于 `E:\mydevieAPP\Axiom.exe`。
3. 打开公理。演示账号 `demo` / `demo1234`。
4. 在「设置」里查看求解器。标成未安装的求解器不会参与竞赛。

不需要单独安装 Python、Node、HiGHS、CBC 或 GLPK。

## 求解器

| 求解器 | Windows 包 |
| --- | --- |
| HiGHS | `highspy` 轮子 |
| CBC | PuLP 自带的 `cbc.exe`，以及 python-mip 的 CBC |
| CLP、GLOP、PDLP、CP-SAT、SCIP | OR-Tools 轮子，在单独进程里调用 |
| GLPK | `solvers\glpsol.exe` 与 `glpk_4_65.dll`（winglpk 4.65） |
| PySCIPOpt | 轮子内带 SCIP |
| Clarabel、ECOS、SCS、OSQP | CVXPY 的开源求解器轮子 |
| CVXOPT | `cvxopt` 轮子 |
| SciPy | SLSQP、trust-constr，以及 `linprog` 的 HiGHS |
| IPOPT | `solvers\ipopt.exe` 与 COIN-OR 3.14.20 的 MSVC DLL（ASL 接口）。`cyipopt` 没有 Windows 轮子 |
| Bonmin、Couenne | 没有可再分发的 Windows 可执行文件。放到 PATH 或 `AXIOM_SOLVER_DIR` 后会被检测到 |
| Gurobi、CPLEX、Xpress、MOSEK、COPT、Knitro、BARON、Hexaly | 不随包分发。装好官方包和许可证后，设置页显示版本和 `licensed`；否则是 `not_installed` |

## 离线重新构建

源码包里的 `vendor/` 已包含：

- `vendor/wheelhouse/*.whl`：Windows amd64 轮子
- `vendor/windows/python`：已装好依赖的 embeddable Python
- `vendor/windows/solvers`：GLPK
- `vendor/npm-cache`：`npm ci --offline` 用的缓存
- `vendor/electron-cache/parts`：Electron 35.7.5 的 win32/linux 压缩包，按不足 100 MiB 切分。`scripts/restore-electron-cache.ps1` 会拼回缓存目录
- `vendor/electron-builder-cache`：NSIS 与 7-Zip

在一台没有网络的 Windows x64 上，需要本机已有 Node.js 22（只用于重新打包界面；运行应用不需要 Node）：

```powershell
..\scripts\restore-electron-cache.ps1
cd frontend
npm ci --offline --cache ..\vendor\npm-cache
$env:ELECTRON_CACHE = "..\vendor\electron-cache"
$env:ELECTRON_BUILDER_CACHE = "..\vendor\electron-builder-cache"
$env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
npm run dist:win
```

只重装 Python 依赖、不访问 PyPI：

```powershell
vendor\windows\python\python.exe -m pip install --no-index --find-links vendor\wheelhouse -r vendor\requirements-windows.txt
```

在 Linux 上交叉打包（需要 Wine，仅用于制作安装包，不是运行时依赖）：

```bash
scripts/build-windows-offline.sh
```

## 已知限制

在 Linux 上用 Wine 11 跑过这套 Windows Python：HiGHS、CBC、SCIP 解产品组合得到目标值 1628.5714（A 21.4286，B 25.7143），GLPK 得到 1628.573。NumPy、SciPy、OR-Tools、CVXPY、PySCIPOpt 可以导入。cyipopt 没有 Windows 轮子，Gurobi 和 CPLEX 不随包分发，设置页会把它们标成未安装。没有在一台真实的 Windows 电脑上双击安装包。
