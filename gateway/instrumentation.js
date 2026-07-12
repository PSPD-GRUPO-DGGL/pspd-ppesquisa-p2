const { NodeSDK } = require('@opentelemetry/sdk-node');
const { getNodeAutoInstrumentations } = require('@opentelemetry/auto-instrumentations-node');
const { PrometheusExporter } = require('@opentelemetry/exporter-prometheus');

// Configura o exportador do Prometheus (exigência do professor no item 'e')
const prometheusExporter = new PrometheusExporter({
  port: 9464, // Porta padrão do Prometheus exporter
  endpoint: '/metrics',
});

const sdk = new NodeSDK({
  metricReader: prometheusExporter,
  instrumentations: [getNodeAutoInstrumentations()],
});

sdk.start();

console.log('📊 OpenTelemetry inicializado. Métricas expostas em http://localhost:9464/metrics');

// Trata o encerramento seguro
process.on('SIGTERM', () => {
  sdk.shutdown()
    .then(() => console.log('OpenTelemetry encerrado'))
    .finally(() => process.exit(0));
});