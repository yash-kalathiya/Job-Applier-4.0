"""Job Applier 4.0 Phase 3: form filling engine with observation & submit-blocker guard."""

SCHEMA_VERSION = 'job-applier.fill-report.v1'

from .engine import fill_form, install_observation_guard, validate_answers_plan, write_bytes_atomic, write_json_atomic  # noqa: E402

__all__ = [
    'SCHEMA_VERSION',
    'fill_form',
    'install_observation_guard',
    'validate_answers_plan',
    'write_bytes_atomic',
    'write_json_atomic',
]
