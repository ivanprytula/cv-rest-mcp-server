---
name: across
description: Apply ACROSS design principles when writing, reviewing, or refactoring code. Use it as the primary design lens for architecture and module-level decisions.
---

# ACROSS Design Principles

Apply these principles when writing, reviewing, or refactoring code.

## A - Abstractions and Decomposition

- Extract an interface or protocol only when consumers need different implementations.
- Give each module a defined responsibility and an explicit contract.
- Separate lifecycle management from business logic.
- Use a facade when callers would otherwise coordinate several internal steps.

## C - Composition by Default

- Prefer composition and injected collaborators over inheritance.
- Use inheritance only for intentional extension points.
- Prefer a plain function or protocol over a base class when either is sufficient.
- Extract a helper instead of creating a base class solely to share methods.

## R - Escape the Rabbit Hole

- Define the scope, success metric, and stopping point before refactoring.
- Keep changes focused on the requested behavior.
- Split very large methods, but avoid replacing one understandable function with a deep call chain.
- Iterate in short cycles: edit, test, and reassess.

## O - Optimize for Change

- Keep business-rule changes local, safe, and reversible.
- Add an adapter and registration point rather than changing shared contracts for each new integration.
- Use expand-contract for migrations and feature flags for risky behavior changes.
- Keep third-party SDK types behind project-owned interfaces.

## S - Simple As Possible

- Match the solution to today's requirements.
- Generalize after the third real occurrence, not before.
- Do not add abstractions merely for testability or hypothetical future extensions.
- Prefer a small working function over a hierarchy that adds no useful variation.

## S - Screaming Contract

- Name functions and classes with domain verbs.
- Use domain language in API endpoints and events.
- Prefer typed outcomes or specific exceptions over ambiguous booleans and generic errors.
- Make error messages describe the domain problem.
