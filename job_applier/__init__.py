"""Job Applier 4.0: find internships and jobs, tailor a top-tier resume for each one, and let your own Claude Code or Codex apply."""
from . import answers, api, ats, match, render, sources, store, tailor

__version__ = '4.0.0'
__all__ = ['answers', 'api', 'ats', 'match', 'render', 'sources', 'store', 'tailor', '__version__']
