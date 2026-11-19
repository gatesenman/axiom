<p align="center"><img src="frontend/src/assets/hero.png" alt="Axiom" width="128"></p>

# 公理 Axiom

**1.0.0** · 本地优先的数学建模工作室：用中文或英文描述生产计划、运输、排班等问题，智能体写成 Axiom 建模语言（AML），并行调用求解器并给出可导出报告。

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

源码在仓库根目录。本仓库不包含安装包。前端与后端需一并启动，具体步骤见 `README.original.md`。典型开发方式：

```bash
cd backend
# 按 pyproject.toml 创建虚拟环境并安装依赖后启动 FastAPI 侧车

cd frontend
npm install
npm run dev          # Vite
# 桌面壳：按该目录 package.json 的 electron / dist 脚本
```
## 文档

- [产品说明](README.original.md)

---

## English

# Axiom

**1.0.0** · A local-first mathematical modeling studio. Describe planning, transport, scheduling, or similar problems in Chinese or English; agents write Axiom Modeling Language (AML), race open-source solvers, and export reports.

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

Source is at the repository root. This repository does not include installers. Start the frontend and backend together; see `README.original.md` for the full flow. Typical development:

```bash
cd backend
# Create a venv from pyproject.toml and start the FastAPI sidecar

cd frontend
npm install
npm run dev          # Vite
# Desktop shell: use the electron / dist scripts in that package.json
```
## Documentation

- [产品说明](README.original.md)

