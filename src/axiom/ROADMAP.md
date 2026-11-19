# Roadmap

These are later products. The modeling language, translators, solvers, agents, simulation, analysis, studio, persistence, and desktop shell described in the README are already in this tree.

- Live co-editing of one project by several people, with presence and a shared cursor.
- An organization SSO login (OIDC) in front of the local accounts.
- A managed pool of commercial solver licenses, so a run can burst to Gurobi or CPLEX without a local install.
- Global mixed-integer nonlinear optimization. IPOPT and SLSQP remain local solvers.
- Scenario-tree stochastic programs with non-anticipativity, as a language construct rather than a hand-written extensive form.
- Column generation and Benders decomposition as their own agents, with a cut loop the verifier can inspect.
- A diagram editor that writes AML, for people who do not want to start from text.
- Signed desktop auto-update. The installers build today; they do not phone home.
