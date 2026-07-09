# Runs

Run packages live under `experiments/runs/<strategy-id>/<run-id>/` during local work.

Strategy-level specs and source notes live under `experiments/runs/<strategy-id>/` and are
copied into each run package so validation remains self-contained. Generated run files are
ignored by git; public-safe fixtures belong in `examples/`.
