"""Shared primitive type aliases used across the domain layer.

Pure type-level aliases only — no runtime validation lives here. Runtime
invariants for values of these types are enforced by the domain model
constructors that use them (e.g. `Candle`, `Tick`, `Symbol`).
"""

type Price = float
type Pips = float
type Volume = float
type SymbolName = str
