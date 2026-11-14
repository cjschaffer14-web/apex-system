FROM us-central1-docker.pkg.dev/alert-maker-509913-m7/schaffer-workspace/freqtrade-base:develop
USER root
RUN mkdir -p /apex && chown ftuser:ftuser /apex
COPY ApexCheck.py entry.py config.json /apex/
USER ftuser
ENTRYPOINT ["python3", "/apex/entry.py"]
