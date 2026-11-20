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
- Servicios: el reporte reproduce la precedencia efectiva de `maintenance.service.actual_service_cost` después de instalar `estratego_purchase_account_provision`:
  1. **Provisión vigente** (`purchase.service.provision` con `active_key`, no anulada y asiento original `posted`): toma `maintenance.service.provision_company_cost` (costo **neto** congelado e imputado al vehículo, en moneda de compañía) y lo multiplica por el factor de impuesto **congelado** de la provisión (`purchase.service.provision.total_company_amount / net_company_amount`). Esto produce el costo **con IGV** correspondiente al vehículo sin usar tasas actuales. La factura proveedor posterior NO suma otra vez ese servicio.
  2. **Sin provisión vigente**: obtiene el costo analítico del vehículo desde facturas/notas de crédito de proveedor contabilizadas y lo multiplica por el factor **real con impuestos** de cada línea (`account.move.line.price_total / price_subtotal`); si la base de factura es cero, usa el factor de la línea de OS como respaldo. No se alteran los signos de las notas de crédito.
  3. **Sin provisión ni factura contabilizada con analítica**: costo cero.
  El campo `actual_service_cost` es calculado y NO está almacenado en PostgreSQL; por eso no se referencia como columna SQL. El costo del reporte se mantiene en moneda compañía, mientras que `actual_service_cost` en pantalla se muestra en moneda de mantenimiento.

- Utilidad bruta = venta facturada en moneda compañía - costo bruto del mantenimiento.
- Conceptos adicionales: el costo analítico se conserva neto; para el reporte se aplica el factor de impuestos de compra del producto del último envío antes de sumarlo al costo bruto total.
- Para trazabilidad histórica, `legacy_invoice_move_id` se considera únicamente un guard de migración y no la llave principal. El reporte busca primero el `technical_report_number` en todas las facturas `posted` de cargos de la misma liquidación; esto permite distinguir correctamente varios informes/facturas dentro de una sola liquidación. Solo si no existe una coincidencia única recurre al `legacy_invoice_move_id`, placa/producto/cantidad/importe y, finalmente, al último cargo enviado cuando la moneda coincide. Nunca asigna el total completo de una factura compartida a cada mantenimiento.

- v17.0.1.0.4: recuperación histórica 1-a-1 por firma (liquidación/producto/cantidad/monto/moneda) y búsqueda ampliada de facturas históricas con tipo de cargo vacío/legado u origen compuesto.

- v17.0.1.2.1: corrige el Costo total para incluir impuestos de compra en los conceptos adicionales, usando el producto del último envío para preservar históricos.

- v17.0.1.2.2: utiliza fecha programada local (con fallback) y costo real de servicios (`maintenance.service.actual_service_cost`). Elimina los CTE de costos de facturas proveedor y conversión de moneda ya innecesarios para los servicios.

- v17.0.1.2.3: corrige la consulta de servicios para dejar de acceder a la columna inexistente `maintenance_service.actual_service_cost` (campo compute no almacenado). Reproduce su lógica a partir de `account_analytic_line` y resuelve dinámicamente las columnas de planes analíticos (`account_id`, `x_plan<ID>_id`). Conserva fecha programada con zona horaria y todos los cálculos restantes.

- v17.0.1.2.4: integra los costos congelados de `estratego_purchase_account_provision` (provisión vigente → `maintenance_service.provision_company_cost`), con fallback a la analítica de facturas solo cuando no hay provisión válida. Evita doble reconocimiento si la factura se contabiliza después. Agrega dependencia explícita al módulo de provisiones. Los costos provisionados se registran netos de impuestos conforme al campo `actual_service_cost`.

- v17.0.1.2.5: el costo de servicios se presenta **con impuestos** (congruente con partes y conceptos adicionales). Para provisiones se calcula proporcionalmente con el total original congelado de la conformidad; para facturas se utiliza el factor real de la línea de factura/nota de crédito. Por ejemplo, para P00001582: S/ 50.84 netos + S/ 9.15 IGV = **S/ 59.99**. Se mantiene la precedencia provisión > factura sin duplicación.

- v17.0.1.2.6: redondea exclusivamente `maintenance_cost_company` a la unidad monetaria más próxima en la consulta del reporte (59.99 → 60; 59.49 → 59) y oculta decimales cero en el listado. No altera provisiones, facturas, impuestos ni el cálculo sin redondear de `gross_profit`. El total mostrado es un importe de presentación, por lo que puede diferir en centésimos de la resta utilizada para la utilidad bruta y los componentes detallados.
