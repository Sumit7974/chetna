"""Chetna application source package."""


def __getattr__(name: str):
    if name in (
        "run_pipeline",
        "PipelineResult",
        "PipelineError",
        "EmptyCellsError",
        "ForecastUnavailableError",
    ):
        import src.pipeline as _pipeline

        return getattr(_pipeline, name)
    raise AttributeError(f"module 'src' has no attribute '{name}'")


__all__ = [
    "run_pipeline",
    "PipelineResult",
    "PipelineError",
    "EmptyCellsError",
    "ForecastUnavailableError",
]
