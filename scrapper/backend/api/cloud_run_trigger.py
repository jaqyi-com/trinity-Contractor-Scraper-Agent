# cloud_run_trigger.py
# Cloud Run Job integration — zero manual gcloud needed.
#
# The pipeline runs as a Cloud Run JOB (full CPU for hours, reliable logs), not
# in the API service's request-throttled process. To avoid making the operator
# run any gcloud commands, the service:
#   1. ensure_pipeline_job() — on startup, reads its OWN Cloud Run service config
#      (image, env/secrets, resources, service account) and creates/updates a
#      matching Job whose command is `python -m agent.run_job`. Idempotent, so
#      every redeploy refreshes the Job to the new image automatically.
#   2. trigger_pipeline_job() — starts one execution with JOB_ID/RESUME overrides.
#
# Project/region are discovered from env or the GCP metadata server, so nothing
# needs to be configured by hand. The ONE thing that can't be self-granted is IAM:
# the service's service account needs roles/run.admin + roles/iam.serviceAccountUser
# (one-time, in the Console) — we log a clear message if a permission is missing.

import os
import copy
from datetime import timedelta

JOB_TASK_TIMEOUT_SECONDS = int(os.getenv("JOB_TASK_TIMEOUT", "21600"))  # 6h default


def _metadata(path: str) -> str:
    import requests
    r = requests.get(
        f"http://metadata.google.internal/computeMetadata/v1/{path}",
        headers={"Metadata-Flavor": "Google"},
        timeout=2,
    )
    r.raise_for_status()
    return r.text


def _project_region() -> tuple[str, str]:
    """Resolve (project, region) from env, falling back to the metadata server."""
    project = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
    region = os.getenv("GCP_REGION")
    if not project:
        project = _metadata("project/project-id")
    if not region:
        # metadata returns "projects/<num>/regions/<region>"
        region = _metadata("instance/region").rsplit("/", 1)[-1]
    return project, region


def _job_name() -> str:
    return os.getenv("CLOUD_RUN_JOB", "contractor-pipeline-job")


def ensure_pipeline_job() -> None:
    """Create or update the Cloud Run Job to mirror THIS service's container
    (same image/env/secrets/resources/SA), with the pipeline worker command.
    Best-effort: logs and returns on any error (the app still serves)."""
    svc_name = os.getenv("K_SERVICE")
    if not svc_name:
        print("ℹ️  [job-setup] not on a Cloud Run service (no K_SERVICE) — skipping job ensure")
        return
    try:
        from google.cloud import run_v2
        from google.api_core.exceptions import NotFound, PermissionDenied, Forbidden

        project, region = _project_region()
        job_id = _job_name()
        parent = f"projects/{project}/locations/{region}"

        # Read our own service to copy its container config verbatim.
        svc = run_v2.ServicesClient().get_service(
            name=f"{parent}/services/{svc_name}"
        )
        tmpl = svc.template
        src = tmpl.containers[0]

        # Copy the service's resources, but FORCE cpu_idle off: request-based CPU
        # throttling (cpu_idle=True, the Service default) is rejected for Jobs with
        # 400 "CPU idle must be set to false." Jobs always run CPU-allocated.
        resources = copy.deepcopy(src.resources)
        resources.cpu_idle = False

        container = run_v2.Container(
            image=src.image,
            command=["python"],
            args=["-m", "agent.run_job"],
            env=copy.deepcopy(list(src.env)),      # carries plain + Secret-Manager envs
            resources=resources,
        )
        task = run_v2.TaskTemplate(
            containers=[container],
            max_retries=0,                          # we resume manually; no silent retry
            timeout=timedelta(seconds=JOB_TASK_TIMEOUT_SECONDS),
            service_account=tmpl.service_account,
            vpc_access=copy.deepcopy(tmpl.vpc_access),
        )
        job = run_v2.Job(template=run_v2.ExecutionTemplate(template=task))

        jobs = run_v2.JobsClient()
        name = f"{parent}/jobs/{job_id}"
        try:
            jobs.get_job(name=name)
            job.name = name
            jobs.update_job(job=job)
            print(f"✅ [job-setup] updated Cloud Run Job '{job_id}' → image {src.image}")
        except NotFound:
            jobs.create_job(parent=parent, job=job, job_id=job_id)
            print(f"✅ [job-setup] created Cloud Run Job '{job_id}' → image {src.image}")
    except Exception as e:
        from google.api_core.exceptions import PermissionDenied, Forbidden
        if isinstance(e, (PermissionDenied, Forbidden)):
            print("⚠️  [job-setup] PERMISSION MISSING. One-time fix in the Console → IAM: "
                  "grant this service's service account the roles 'Cloud Run Admin' "
                  "(roles/run.admin) and 'Service Account User' (roles/iam.serviceAccountUser). "
                  f"Details: {e}")
        else:
            print(f"⚠️  [job-setup] could not ensure the Cloud Run Job (will retry on next "
                  f"deploy / Start): {e}")


def trigger_pipeline_job(job_id: str, resume: bool = False) -> str:
    """Start one Cloud Run Job execution for `job_id`. If the Job doesn't exist
    yet, try to create it first. Raises on unrecoverable errors."""
    from google.cloud import run_v2
    from google.api_core.exceptions import NotFound

    project, region = _project_region()
    name = f"projects/{project}/locations/{region}/jobs/{_job_name()}"

    overrides = run_v2.RunJobRequest.Overrides(
        container_overrides=[
            run_v2.RunJobRequest.Overrides.ContainerOverride(
                env=[
                    run_v2.EnvVar(name="JOB_ID", value=job_id),
                    run_v2.EnvVar(name="RESUME", value="true" if resume else "false"),
                ],
            )
        ]
    )
    req = run_v2.RunJobRequest(name=name, overrides=overrides)

    client = run_v2.JobsClient()
    try:
        client.run_job(request=req)
    except NotFound:
        # Job missing (first run before ensure succeeded) — create then retry once.
        print("ℹ️  [job-trigger] job not found, creating it now…")
        ensure_pipeline_job()
        client.run_job(request=req)
    print(f"🚀 Triggered Cloud Run Job for job_id={job_id} resume={resume}")
    return "started"
