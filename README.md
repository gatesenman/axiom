<p align="center"><img src="frontend/src/assets/hero.png" alt="Axiom logo" width="128"></p>

<p align="center"><em>应用标识 / logo（不是产品窗口截图）</em></p>

# 公理 Axiom

**1.0.0** · 本地优先的数学建模工作室：用中文或英文描述生产计划、运输、排班等问题，智能体写成 Axiom 建模语言（AML），并行调用求解器并给出可导出报告。

## 界面截图（待补真实图）

仓库里目前只有图标和上面的装饰性 hero，**没有**真实产品窗口截图，因此不把 logo 当作界面图嵌入。预留路径（请在真实运行的工作室里截取后放入，不要用生成图）：

- `docs/screenshots/01-workbench.png` — 主工作台 / 模型列表或编辑器
- `docs/screenshots/02-solve-or-report.png` — 求解结果或导出报告

启动建议：按「从源码运行」同时打开 FastAPI `:43124` 与 Vite `:43123`，浏览器打开 http://127.0.0.1:43123 ，或 `cd frontend && npm run desktop`。请遮盖真实 API Key；演示账号不要写进新截图以外的地方。

本仓库没有 GitHub Release 安装包。

## 功能特性

- 自然语言 → AML 建模语言 → 多求解器竞赛（HiGHS、CBC、SCIP、OR-Tools、ECOS、SciPy 等，也可配置商业求解器）。
- 灵敏度、情景、蒙特卡洛分析与可导出报告；界面默认简体中文，可切换英文。
- Electron 桌面壳 + FastAPI 求解侧车（默认 `:43124`）+ SQLite；同一套网页也可单独在浏览器中打开。
- 结果可导出到 Pyomo、PuLP、CVXPY、AMPL、GAMS、LP/MPS 等格式。

## 技术栈

- 桌面：Electron + React + TypeScript + Vite + shadcn
- 后端：Python 3.11+、FastAPI、SQLAlchemy
- 求解：HiGHS / PuLP / OR-Tools / CVXPY 等（见 `backend/pyproject.toml`）

## 从源码运行

源码在仓库根目录。本仓库不包含安装包。前端（Vite `:43123`）与后端（FastAPI `:43124`）需要一并启动。

环境：Python 3.11+（开发建议 3.12）、Node.js 22+。可选系统求解器见 `backend/pyproject.toml` 与 [docs/solvers.md](docs/solvers.md)。

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

cd ../frontend
npm install
```

两个进程都要开着：

```bash
# 终端 1
cd backend
PYTHONPATH=. .venv/bin/python -m uvicorn axiom.main:app --host 127.0.0.1 --port 43124

# 终端 2
cd frontend
npm run dev
```

浏览器打开 http://127.0.0.1:43123 。第一次启动会写入演示账号 `demo` / `demo1234`。数据位于 `backend/data/`。不配置外部模型时，离线规则仍可建模。

桌面开发壳：

```bash
cd frontend
npm run desktop
```

测试：

```bash
cd backend
PYTHONPATH=. AXIOM_SKIP_EXAMPLE=1 .venv/bin/python -m pytest
cd ../frontend
npm test
```

## 文档
- [docs/architecture.md](docs/architecture.md)
- [docs/aml-spec.md](docs/aml-spec.md)
- [docs/solvers.md](docs/solvers.md)
- [docs/analysis.md](docs/analysis.md)
- [docs/agents.md](docs/agents.md)
- [docs/lifecycle.md](docs/lifecycle.md)
- [ROADMAP.md](ROADMAP.md)
- [docs/providers.md](docs/providers.md)
- [docs/studio-ux.md](docs/studio-ux.md)
- [docs/figures.md](docs/figures.md)
- [docs/algorithms.md](docs/algorithms.md)
- [docs/windows-offline.md](docs/windows-offline.md)

## 贡献

欢迎通过 Issue 和 Pull Request 参与，详见 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。参与时请遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 许可证

本仓库尚未附带 LICENSE 文件，许可证未指定。

---

## English

# Axiom

**1.0.0** · A local-first mathematical modeling studio. Describe planning, transport, scheduling, or similar problems in Chinese or English; agents write Axiom Modeling Language (AML), race open-source solvers, and export reports.

### Screenshots (reserved)

The repository currently has only icons and the decorative hero graphic above. That logo is not a product-window screenshot. Reserved paths: `docs/screenshots/01-workbench.png`, `docs/screenshots/02-solve-or-report.png`. Run the FastAPI sidecar and Vite UI, or `npm run desktop`. Mask API keys. There is no published installer.

## Features

- Natural language → AML → solver racing (HiGHS, CBC, SCIP, OR-Tools, ECOS, SciPy, and optional commercial solvers).
- Sensitivity, scenarios, Monte Carlo, and exportable reports. UI defaults to Simplified Chinese and can switch to English.
- Electron shell + FastAPI sidecar (default `:43124`) + SQLite; the same web UI can run in a browser alone.
- Export to Pyomo, PuLP, CVXPY, AMPL, GAMS, LP/MPS, and related formats.

## Tech stack

- 桌面：Electron + React + TypeScript + Vite + shadcn
- 后端：Python 3.11+、FastAPI、SQLAlchemy
- 求解：HiGHS / PuLP / OR-Tools / CVXPY 等（见 `backend/pyproject.toml`）

## Getting started

Source is at the repository root. This repository does not include installers. The frontend (Vite `:43123`) and backend (FastAPI `:43124`) must run together.

Requires Python 3.11+ (3.12 recommended) and Node.js 22+. See `backend/pyproject.toml` and [docs/solvers.md](docs/solvers.md) for optional system solvers.

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

cd ../frontend
npm install
```

Keep both processes running:

```bash
# terminal 1
cd backend
PYTHONPATH=. .venv/bin/python -m uvicorn axiom.main:app --host 127.0.0.1 --port 43124

# terminal 2
cd frontend
npm run dev
```

Open http://127.0.0.1:43123 . The first start writes the demo account `demo` / `demo1234`. Data lives in `backend/data/`. Offline rules still model problems when no external model key is configured.

Desktop dev shell:

```bash
cd frontend
npm run desktop
```

Tests:

```bash
cd backend
PYTHONPATH=. AXIOM_SKIP_EXAMPLE=1 .venv/bin/python -m pytest
cd ../frontend
npm test
```

## Documentation

- [docs/architecture.md](docs/architecture.md)
- [docs/aml-spec.md](docs/aml-spec.md)
- [docs/solvers.md](docs/solvers.md)
- [docs/analysis.md](docs/analysis.md)
- [docs/agents.md](docs/agents.md)
- [docs/lifecycle.md](docs/lifecycle.md)
- [ROADMAP.md](ROADMAP.md)
- [docs/providers.md](docs/providers.md)
- [docs/studio-ux.md](docs/studio-ux.md)
- [docs/figures.md](docs/figures.md)
- [docs/algorithms.md](docs/algorithms.md)
- [docs/windows-offline.md](docs/windows-offline.md)

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). Please report vulnerabilities privately via [SECURITY.md](SECURITY.md). This project follows [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

No LICENSE file is included in this repository; the license is unspecified.
