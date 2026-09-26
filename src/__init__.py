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

    if name in (
        "safe_route",
        "OSMRouter",
        "BasicRouter",
        "RouteService",
        "build_road_graph_from_roads",
        "connect_graph_to_grid",
        "apply_risk_predictions_to_graph",
    ):
        import src.routing.router as _router

        return getattr(_router, name)

    raise AttributeError(f"module 'src' has no attribute '{name}'")


__all__ = [
    "run_pipeline",
    "PipelineResult",
    "PipelineError",
    "EmptyCellsError",
    "ForecastUnavailableError",
    "safe_route",
    "OSMRouter",
    "BasicRouter",
    "RouteService",
    "build_road_graph_from_roads",
    "connect_graph_to_grid",
    "apply_risk_predictions_to_graph",
]
