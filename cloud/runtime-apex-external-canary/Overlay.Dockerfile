FROM us-central1-docker.pkg.dev/alert-maker-509913-m7/schaffer-workspace/runtime@sha256:0efa5ac18af8d925f604ed60c497dc7d48457d544583736d4dc505a74e047ac4
COPY --chown=root:root app.py apex_external_review.py /app/
