"""ffdraft — deterministic fantasy-football draft analytics.

The math layer. All ranking, valuation, and simulation lives here. The LLM
advisor (a separate concern) only ever consumes the typed objects this package
emits; it never computes a ranking itself.
"""

__version__ = "0.0.1"
