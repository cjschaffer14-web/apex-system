set -x
SA=748368520319-compute@developer.gserviceaccount.com
URI=https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/alert-maker-509913-m7/jobs/apex-cloud-auditor:run
gcloud run jobs deploy apex-cloud-auditor --source . --region us-central1 --max-retries 0 --task-timeout 10m --set-secrets=OPENAI_API_KEY=dec-openai-api-key:latest,ANTHROPIC_API_KEY=dec-anthropic-api-key:latest,GEMINI_API_KEY=dec-gemini-api-key:latest --set-env-vars=AUDIT_URL=https://dec-research-rtr25d4k5q-uc.a.run.app/ --quiet
gcloud run jobs add-iam-policy-binding apex-cloud-auditor --region us-central1 --member=serviceAccount:$SA --role=roles/run.invoker --quiet
gcloud scheduler jobs create http apex-daily-audit --location us-central1 --schedule="0 4 * * *" --time-zone="America/New_York" --uri="$URI" --http-method=POST --oauth-service-account-email=$SA --quiet
echo ALL_STEPS_FINISHED
