# estratego_maintenance_performance_report

Reporte de rendimiento por mantenimiento para Odoo 17.

## Criterios principales

- Una fila por `maintenance.request`.
- Fecha del reporte: `schedule_date` convertida desde UTC a la fecha local de `America/Lima`; en ausencia de programación se usa `request_date`.
- Estado:
  - **No presentado**: nunca enviado a facturación.
  - **Presentado**: enviado, pero sin factura cliente contabilizada.
  - **Facturado**: existe factura cliente `posted`; se prioriza la trazabilidad exacta por línea y se soportan históricos identificados mediante `legacy_invoice_move_id`.
- Venta con impuestos desde `account.move.line.price_total`.
- Venta en moneda compañía usando la tasa contable implícita de cada línea contabilizada.
- Notas de crédito vinculadas al Extra restan de la venta.
- Costo de partes desde `stock.valuation.layer`, incluyendo capas descendientes de revalorización.
- Impuestos de partes desde el factor tributario de la OC; para líneas manuales se usan impuestos de compra actuales del producto como fallback.
- Servicios: se reproduce en SQL el origen del campo calculado (no almacenado) `maintenance.service.actual_service_cost`. Se suman los apuntes analíticos de facturas proveedor y notas de crédito **contabilizadas**, asociados a la cuenta analítica del vehículo. Sin factura contabilizada, el costo real de servicio es cero. `account.analytic.line.amount` se expresa en moneda compañía, por lo que el reporte suma el costo en esa moneda. Los valores mostrados en un mantenimiento cuya moneda sea distinta pueden diferir ligeramente por redondeo/conversión, sin cambiar la fuente real del costo.
- Utilidad bruta = venta facturada en moneda compañía - costo bruto del mantenimiento.
- Conceptos adicionales: el costo analítico se conserva neto; para el reporte se aplica el factor de impuestos de compra del producto del último envío antes de sumarlo al costo bruto total.
- Para trazabilidad histórica, `legacy_invoice_move_id` se considera únicamente un guard de migración y no la llave principal. El reporte busca primero el `technical_report_number` en todas las facturas `posted` de cargos de la misma liquidación; esto permite distinguir correctamente varios informes/facturas dentro de una sola liquidación. Solo si no existe una coincidencia única recurre al `legacy_invoice_move_id`, placa/producto/cantidad/importe y, finalmente, al último cargo enviado cuando la moneda coincide. Nunca asigna el total completo de una factura compartida a cada mantenimiento.

- v17.0.1.0.4: recuperación histórica 1-a-1 por firma (liquidación/producto/cantidad/monto/moneda) y búsqueda ampliada de facturas históricas con tipo de cargo vacío/legado u origen compuesto.

- v17.0.1.2.1: corrige el Costo total para incluir impuestos de compra en los conceptos adicionales, usando el producto del último envío para preservar históricos.

- v17.0.1.2.2: utiliza fecha programada local (con fallback) y costo real de servicios (`maintenance.service.actual_service_cost`). Elimina los CTE de costos de facturas proveedor y conversión de moneda ya innecesarios para los servicios.

- v17.0.1.2.3: corrige la consulta de servicios para dejar de acceder a la columna inexistente `maintenance_service.actual_service_cost` (campo compute no almacenado). Reproduce su lógica a partir de `account_analytic_line` y resuelve dinámicamente las columnas de planes analíticos (`account_id`, `x_plan<ID>_id`). Conserva fecha programada con zona horaria y todos los cálculos restantes.
