// Rastreamento distribuído (OpenTelemetry), só traces. Desligado por padrão;
// ligue com ENABLE_OTEL=true quando o Jaeger estiver no ar (Camada 3).
// Precisa ser o primeiro require do processo para instrumentar as libs.
if (process.env.ENABLE_OTEL !== 'true') {
  module.exports = null;
  return;
}

const { NodeSDK } = require('@opentelemetry/sdk-node');
const { getNodeAutoInstrumentations } = require('@opentelemetry/auto-instrumentations-node');
const { OTLPTraceExporter } = require('@opentelemetry/exporter-trace-otlp-http');

// Endpoint vem de OTEL_EXPORTER_OTLP_ENDPOINT; sem coletor, o export só falha em silêncio.
const sdk = new NodeSDK({
  traceExporter: new OTLPTraceExporter(),
  instrumentations: [getNodeAutoInstrumentations()],
});

sdk.start();
console.log('OpenTelemetry (traces) ativo.');

process.on('SIGTERM', () => sdk.shutdown().finally(() => process.exit(0)));

module.exports = sdk;
