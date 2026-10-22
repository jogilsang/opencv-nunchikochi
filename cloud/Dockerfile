# Nunchikochi service — AWS Lambda arm64 (Graviton) container image.
# OWNER: cloud tab. Handler: nunchi.service.lambda_handler (Mangum over FastAPI).
#
# Base is the official AWS Lambda Python runtime for arm64 so the same OpenCV 5
# code runs on Graviton (ARCHITECTURE: analysis runs on Lambda arm64).
#
# Build (from repo root):
#   docker build --platform linux/arm64 -f cloud/Dockerfile -t nunchi-service:local .
# The actual push to ECR happens in C2 (CodeBuild remote build — see cloud/README.md,
# since cross-arch docker build on an x86/local dev box is slow/unreliable).

FROM public.ecr.aws/lambda/python:3.12-arm64

# System libs OpenCV needs at runtime (headless build still needs these shared libs).
RUN dnf install -y mesa-libGL libglvnd-glx && dnf clean all

# Dependencies first for layer caching. We install only the runtime set the service
# needs (no dev/test deps, no agent-only extras) with the exact pins from pyproject.
# NOTE: keep this list in sync with pyproject [dependency-groups].service (minus test-only
# httpx/moto, which are not needed at runtime).
COPY cloud/requirements-lambda.txt /tmp/requirements-lambda.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements-lambda.txt

# App source. ${LAMBDA_TASK_ROOT} is on sys.path; install the package layout under it.
COPY src/nunchi ${LAMBDA_TASK_ROOT}/nunchi

# Models are mounted/added in C2 (kept out of the image here to stay small and because
# model download is a separate, auditable step). NUNCHI_FORCE_STUB=1 lets the image boot
# and serve the contract before vision models are wired.
ENV NUNCHI_STATE_BACKEND=dynamo \
    NUNCHI_MODELS_DIR=/opt/models \
    PYTHONUNBUFFERED=1

# Lambda handler (Mangum adapter exported from the package __init__).
CMD ["nunchi.service.lambda_handler"]
