# One image for every Lambda; each function picks its handler via CMD in the CDK stack.
FROM public.ecr.aws/lambda/python:3.12

COPY --from=ghcr.io/astral-sh/uv:0.9.21 /uv /bin/uv
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --no-hashes -o requirements.txt \
    && uv pip install --system --no-cache -r requirements.txt

COPY src/engine ${LAMBDA_TASK_ROOT}/engine
COPY static ${LAMBDA_TASK_ROOT}/static

CMD ["engine.handlers.api"]
