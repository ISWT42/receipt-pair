"""Receipt Pair: two small local models, served by Lemonade, check whether an AI agent's "done" is true
against its own log. Each model answers shown, contradicted or not shown, and must quote the exact output line
that decides it; a quote that is not in the log becomes "not shown". A pair rule combines the two answers.

Standard library only. See README.md.
"""

__version__ = "0.1.0"
