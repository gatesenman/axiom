# Agents

Each run records a timeline. The agents are:

1. **Supervisor** opens the run.
2. **Analyst** turns the statement into AML. The offline rules cover product mix in Chinese and English, algebraic objectives, queue descriptions, and the template library. A configured OpenAI-compatible or Anthropic model is asked in parallel; its AML is used only after validation.
3. **Human** approves the reading of the problem, unless the run was started with automatic approval.
4. **Modeler and modeler-b** validate the primary model and a slack-equality alternative at the same time.
5. **Data** lists parameter values.
6. **Human** approves the model.
7. **Solver** races every installed solver that can handle the model class.
8. **Verifier** checks slacks and the alternative objective, and diagnoses infeasibility with an elastic filter when every solver is infeasible.
9. **Analyst / simulation** computes sensitivity at ±10%, three right-hand-side scenarios, and eight Monte Carlo samples. A queue statement runs a SimPy discrete-event simulation instead of the race.
10. **Report** stores the result used by Markdown, PDF, and Excel export.

Rejecting a gate ends the run. Pending gates are visible in the studio and decided with `POST /api/runs/{id}/decision`. Events can be polled or consumed as server-sent events at `/api/runs/{id}/stream`.
