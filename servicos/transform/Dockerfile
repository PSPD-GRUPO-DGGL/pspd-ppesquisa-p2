# Build a partir da raiz do repositório:
#   docker build -f servicos/transform/Dockerfile -t pspd/transform:0.1.0 .

FROM python:3.12-slim AS build

WORKDIR /build
RUN pip install --no-cache-dir grpcio-tools==1.64.1

COPY proto/ /build/proto/
RUN mkdir -p /build/out && \
    python -m grpc_tools.protoc -I/build/proto \
        --python_out=/build/out --grpc_python_out=/build/out \
        /build/proto/comum.proto /build/proto/transform.proto


FROM python:3.12-slim

RUN useradd --create-home --uid 10001 pspd

WORKDIR /app

COPY servicos/transform/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=build /build/out/*.py /app/
COPY servicos/transform/anonimizacao.py \
     servicos/transform/fhir.py \
     servicos/transform/metricas.py \
     servicos/transform/server.py \
     /app/

USER pspd

EXPOSE 50053 8000

ENV GRPC_PORT=50053 \
    METRICS_PORT=8000 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "server.py"]
