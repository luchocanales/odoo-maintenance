# estratego_maintenance_performance_report

Reporte de rendimiento por mantenimiento para Odoo 17.

## Criterios principales

- Una fila por `maintenance.request`.
- Estado:
  - **No presentado**: nunca enviado a facturación.
  - **Presentado**: enviado, pero sin factura cliente contabilizada.
  - **Facturado**: existe factura cliente `posted`; se prioriza la trazabilidad exacta por línea y se soportan históricos identificados mediante `legacy_invoice_move_id`.
- Venta con impuestos desde `account.move.line.price_total`.
- Venta en moneda compañía usando la tasa contable implícita de cada línea contabilizada.
- Notas de crédito vinculadas al Extra restan de la venta.
- Costo de partes desde `stock.valuation.layer`, incluyendo capas descendientes de revalorización.
- Impuestos de partes desde el factor tributario de la OC; para líneas manuales se usan impuestos de compra actuales del producto como fallback.
- Servicios provenientes de OC se valorizan desde facturas proveedor `posted`, con impuesto y porcentaje analítico del vehículo.
- Servicios manuales usan el cargo registrado, impuestos actuales del producto y conversión a moneda compañía como fallback.
- Utilidad bruta = venta facturada en moneda compañía - costo bruto del mantenimiento.
- Para trazabilidad histórica, `legacy_invoice_move_id` se considera únicamente un guard de migración y no la llave principal. El reporte busca primero el `technical_report_number` en todas las facturas `posted` de cargos de la misma liquidación; esto permite distinguir correctamente varios informes/facturas dentro de una sola liquidación. Solo si no existe una coincidencia única recurre al `legacy_invoice_move_id`, placa/producto/cantidad/importe y, finalmente, al último cargo enviado cuando la moneda coincide. Nunca asigna el total completo de una factura compartida a cada mantenimiento.
