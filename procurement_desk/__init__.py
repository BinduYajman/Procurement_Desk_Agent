"""Acme procurement negotiation decision engine.

A deterministic, auditable pipeline:  parse -> extract -> normalize -> screen -> decide -> audit.
"""

__version__ = "1.0.0"

from .domain import Action, Decision, Reason, ThreadInput  # noqa: E402,F401
from .pipeline import DecisionPipeline, DecisionRecord  # noqa: E402,F401
from .playbook import Playbook  # noqa: E402,F401
